import asyncio
import base64
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from proxy.bootstrap import ProxyBootstrap
from proxy.checker import XrayProxyChecker
from proxy.config_store import load_proxies_json, save_proxies_json
from proxy.health_check import filter_working_proxies, profile_api_timeout
from proxy.subscription import fetch_all_subscriptions
from proxy.subscription_import import import_subscription
from proxy.vless_parser import parse_vless_uri
from proxy.xray_config import build_xray_config
from tests.test_proxy_health import Response, make_proxy


PREFIX = "vless://example-user@example.invalid:443?security=tls"
KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


def imported(document):
    failures, counts = Counter(), Counter()
    return list(import_subscription(json.dumps(document), failures, counts)), failures


def outbound():
    return {
        "tag": "example",
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": "example.invalid",
                    "port": 443,
                    "users": [{"id": "example-user", "encryption": "none"}],
                }
            ]
        },
        "streamSettings": {
            "network": "ws",
            "security": "tls",
            "tlsSettings": {
                "serverName": "tls.example",
                "fingerprint": "chrome",
                "alpn": ["http/1.1"],
            },
            "wsSettings": {"path": "/socket", "headers": {"Host": "cdn.example"}},
        },
    }


class ProxyImportTests(unittest.IsolatedAsyncioTestCase):
    def test_same_endpoint_different_connection_parameters_are_not_duplicates(self):
        variants = [
            PREFIX + suffix
            for suffix in (
                "&sni=one.example",
                "&sni=two.example",
                "&type=ws&path=/a&host=cdn.example",
                "&type=ws&path=/b&host=cdn.example",
                "&type=grpc&serviceName=first",
                "&type=grpc&serviceName=second",
                "&fp=firefox",
                "&flow=xtls-rprx-vision",
                "&alpn=h2",
                "&encryption=mlkem768x25519plus.native.1rtt." + KEY,
            )
        ]
        ids = [parse_vless_uri(uri).id for uri in variants]
        self.assertEqual(len(set(ids)), len(variants))
        reality = f"vless://example-user@example.invalid:443?security=reality&pbk={KEY}"
        first = parse_vless_uri(reality + "&sid=01")
        second = parse_vless_uri(reality + "&sid=02")
        self.assertNotEqual(first.id, second.id)

    def test_names_query_order_and_local_ports_do_not_affect_identity(self):
        first = parse_vless_uri(PREFIX + "&type=ws&path=%2Fa#first", 18001)
        second = parse_vless_uri(
            "vless://example-user@EXAMPLE.invalid:443?path=%2Fa&type=websocket&security=tls#second",
            19001,
        )
        self.assertEqual(first.id, second.id)

    def test_uri_retains_transport_security_and_encryption_settings(self):
        config = parse_vless_uri(
            PREFIX
            + "&type=ws&path=%2Fsocket&host=cdn.example&sni=tls.example&alpn=http%2F1.1&allowInsecure=1"
        )
        built = build_xray_config([config])["outbounds"][0]
        self.assertEqual(
            built["streamSettings"]["wsSettings"],
            {"host": "cdn.example", "path": "/socket"},
        )
        tls = built["streamSettings"]["tlsSettings"]
        self.assertEqual(tls["serverName"], "tls.example")
        self.assertEqual(tls["alpn"], ["http/1.1"])
        self.assertTrue(tls["allowInsecure"])
        for suffix, key, expected in (
            (
                "&type=grpc&serviceName=svc&authority=grpc.example&mode=multi",
                "grpcSettings",
                {"serviceName": "svc", "authority": "grpc.example", "multiMode": True},
            ),
            (
                "&type=httpupgrade&path=%2Fu&host=h.example",
                "httpupgradeSettings",
                {"path": "/u", "host": "h.example"},
            ),
            (
                "&type=xhttp&path=%2Fx&mode=stream-one",
                "xhttpSettings",
                {"path": "/x", "host": "", "mode": "stream-one"},
            ),
        ):
            proxy = parse_vless_uri(PREFIX + suffix)
            self.assertEqual(
                build_xray_config([proxy])["outbounds"][0]["streamSettings"][key],
                expected,
            )

    def test_realities_allow_empty_short_id_and_preserve_spider_x(self):
        proxy = parse_vless_uri(
            f"vless://example-user@example.invalid:443?security=reality&pbk={KEY}&sid=&spx=%2Fnews"
        )
        self.assertIsNotNone(proxy)
        settings = build_xray_config([proxy])["outbounds"][0]["streamSettings"][
            "realitySettings"
        ]
        self.assertEqual(settings["shortId"], "")
        self.assertEqual(settings["spiderX"], "/news")
        self.assertIsNone(
            parse_vless_uri(
                f"vless://example-user@example.invalid:443?security=reality&pbk={KEY}&sid=xyz"
            )
        )

    def test_uri_percent_user_html_query_and_none_security(self):
        proxy = parse_vless_uri(
            "vless://custom%20user@127.0.0.1:443?type=ws&amp;path=%2Fa"
        )
        self.assertEqual(proxy.uuid, "custom user")
        self.assertEqual(proxy.security, "none")
        self.assertEqual(proxy.stream_settings["wsSettings"]["path"], "/a")
        self.assertIsNone(
            parse_vless_uri("vless://user@example.invalid:0?security=tls")
        )
        self.assertIsNone(parse_vless_uri(PREFIX + "&type=unsupported"))

    def test_json_profiles_arrays_and_uri_arrays_import(self):
        node = outbound()
        for document in (
            {"outbounds": [node]},
            [{"outbounds": [node]}],
            node,
            {"configs": [node]},
        ):
            proxies, failures = imported(document)
            self.assertEqual(len(proxies), 1)
            self.assertEqual(failures, {})
        proxies, failures = imported([PREFIX, PREFIX + "&type=grpc&serviceName=svc"])
        self.assertEqual(len(proxies), 2)
        self.assertEqual(failures, {})

    def test_json_settings_survive_cache_roundtrip_and_build_without_mutation(self):
        node = outbound()
        node["mux"] = {"enabled": True, "concurrency": 4}
        node["streamSettings"]["sockopt"] = {"tcpKeepAliveIdle": 30}
        original = deepcopy(node)
        proxies, failures = imported(node)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.json"
            save_proxies_json(path, proxies)
            loaded = load_proxies_json(path)
        built = build_xray_config(loaded)["outbounds"][0]
        self.assertEqual(node, original)
        self.assertEqual(built["mux"], node["mux"])
        self.assertEqual(built["streamSettings"]["sockopt"], {"tcpKeepAliveIdle": 30})
        self.assertEqual(built["streamSettings"]["wsSettings"]["host"], "cdn.example")
        self.assertEqual(loaded[0].connection_id(), proxies[0].id)

    def test_equivalent_json_and_uri_have_same_identity(self):
        proxies, _ = imported(outbound())
        uri = parse_vless_uri(
            PREFIX
            + "&type=ws&path=%2Fsocket&host=cdn.example&sni=tls.example&alpn=http%2F1.1"
        )
        self.assertEqual(proxies[0].id, uri.id)

    def test_invalid_or_dependent_json_neighbor_does_not_drop_valid_nodes(self):
        chained = outbound()
        chained["proxySettings"] = {"tag": "another"}
        proxies, failures = imported(
            [
                {"outbounds": None},
                chained,
                {"protocol": "vless", "settings": {}},
                outbound(),
            ]
        )
        self.assertEqual(len(proxies), 1)
        self.assertEqual(sum(failures.values()), 3)

    def test_json_multiple_servers_and_users_are_imported_separately(self):
        node = outbound()
        node["settings"]["vnext"][0]["users"].append(
            {"id": "another-user", "encryption": "none"}
        )
        second = deepcopy(node["settings"]["vnext"][0])
        second["address"] = "other.invalid"
        node["settings"]["vnext"].append(second)
        proxies, failures = imported(node)
        self.assertEqual(len({proxy.id for proxy in proxies}), 4)
        self.assertEqual(failures, {})

    def test_malformed_server_inside_json_keeps_valid_neighbor(self):
        node = outbound()
        node["settings"]["vnext"].insert(0, None)
        bad = deepcopy(node["settings"]["vnext"][1])
        bad["address"] = None
        node["settings"]["vnext"].insert(1, bad)
        proxies, failures = imported(node)
        self.assertEqual(len(proxies), 1)
        self.assertEqual(sum(failures.values()), 2)

    def test_invalid_reality_key_is_rejected_without_exposing_it(self):
        counts = Counter()
        with self.assertLogs("proxy.vless_parser", level="DEBUG") as logs:
            config = parse_vless_uri(
                "vless://example-user@example.invalid:443?security=reality&pbk=PRIVATE_KEY",
                failure_counts=counts,
            )
        self.assertIsNone(config)
        self.assertEqual(counts, {"invalid REALITY publicKey": 1})
        self.assertNotIn("PRIVATE_KEY", "\n".join(logs.output))

    def test_bootstrap_logs_real_duplicate_count_and_keeps_connection_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = ProxyBootstrap(Path(directory))
            bootstrap.max_proxies = 0
            with self.assertLogs("proxy.bootstrap", level="INFO") as logs:
                proxies = bootstrap._parse_source_content(
                    [PREFIX, PREFIX + "#other", PREFIX + "&sni=another"],
                    [json.dumps(outbound())],
                )
        self.assertEqual(len(proxies), 3)
        self.assertIn("1 duplicates, 0 rejected", "\n".join(logs.output))

    def test_health_timeout_phases_are_bounded_and_invalid_values_rejected(self):
        with patch.dict(
            "os.environ",
            {
                "PROXY_CHECK_TIMEOUT": "3",
                "PROXY_CHECK_CONNECT_TIMEOUT": "10",
                "PROXY_CHECK_READ_TIMEOUT": "15",
            },
        ):
            timeout = profile_api_timeout()
            self.assertEqual(
                (timeout.total, timeout.connect, timeout.sock_read), (3, 3, 3)
            )
            for value in ("0", "-1", "nan", "inf"):
                with patch.dict("os.environ", {"PROXY_CHECK_TIMEOUT": value}):
                    with self.assertRaises(ValueError):
                        profile_api_timeout()

    async def test_transient_failure_retries_without_double_counting_proxy(self):
        session = SimpleNamespace(
            get=Mock(
                side_effect=[
                    asyncio.TimeoutError(),
                    Response(payload={"responseType": "OK"}),
                ]
            )
        )
        with patch.dict("os.environ", {"PROXY_CHECK_ATTEMPTS": "2"}):
            report = await filter_working_proxies([make_proxy()], session)
        self.assertEqual((report.total, report.working, report.failed), (1, 1, 0))
        self.assertEqual(session.get.call_count, 2)

    async def test_http_failure_does_not_retry_and_timeouts_stop_at_limit(self):
        for side_effect, expected_calls in (
            ([Response(403)], 1),
            ([asyncio.TimeoutError(), asyncio.TimeoutError()], 2),
        ):
            session = SimpleNamespace(get=Mock(side_effect=side_effect))
            with patch.dict("os.environ", {"PROXY_CHECK_ATTEMPTS": "2"}):
                report = await filter_working_proxies([make_proxy()], session)
            self.assertEqual((report.total, report.failed), (1, 1))
            self.assertEqual(session.get.call_count, expected_calls)

    async def test_timed_out_subscription_does_not_abort_next_download(self):
        session = SimpleNamespace(
            get=Mock(side_effect=[asyncio.TimeoutError(), Response(payload={})])
        )
        body = json.dumps(outbound())
        response = Response()
        response.raise_for_status = Mock()

        async def text():
            return body

        response.text = text
        session.get.side_effect = [asyncio.TimeoutError(), response]
        with self.assertLogs("proxy.subscription", level="ERROR"):
            result = await fetch_all_subscriptions(
                ["https://one.invalid", "https://two.invalid"], session
            )
        self.assertEqual(result, [body])

    async def test_base64_json_subscription_is_imported(self):
        from proxy.subscription import decode_subscription_body

        body = base64.b64encode(json.dumps(outbound()).encode()).decode()
        failures, counts = Counter(), Counter()
        proxies = list(
            import_subscription(decode_subscription_body(body), failures, counts)
        )
        self.assertEqual(len(proxies), 1)
        self.assertEqual(failures, {})

    async def test_checker_waits_for_actual_listening_port(self):
        async def accept(reader, writer):
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(accept, "127.0.0.1", 0)
        with tempfile.TemporaryDirectory() as directory:
            checker = XrayProxyChecker(Path("unused"), Path(directory), set())
            candidate = make_proxy()
            candidate.local_http_port = server.sockets[0].getsockname()[1]
            try:
                await checker._wait_for_ports([candidate])
            finally:
                await checker.stop()
                server.close()
                await server.wait_closed()

    async def test_checker_readiness_timeout_is_bounded(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        candidate = make_proxy()
        candidate.local_http_port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        with tempfile.TemporaryDirectory() as directory:
            checker = XrayProxyChecker(Path("unused"), Path(directory), set())
            try:
                with patch.dict("os.environ", {"PROXY_CHECK_START_TIMEOUT": "0.05"}):
                    with self.assertRaises(asyncio.TimeoutError):
                        await checker._wait_for_ports([candidate])
            finally:
                await checker.stop()
