import asyncio
from collections import Counter
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import aiohttp

from proxy.config_store import load_proxies_json, save_proxies_json
from proxy.health_check import _check_single_proxy, filter_working_proxies
from proxy.models import ProxyConfig
from proxy.vless_parser import parse_vless_uri
from proxy.xray_compat import SUPPORTED_FLOWS, valid_xray_user_id


def make_proxy(identifier="test", flow=""):
    return ProxyConfig(
        id=identifier,
        name=identifier,
        address="example.invalid",
        port=443,
        uuid="00000000-0000-4000-8000-000000000001",
        flow=flow,
        security="tls",
        local_http_port=18001,
    )


class Response:
    def __init__(self, status=200, payload=None, error=None):
        self.status = status
        self.payload = payload
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        if self.error:
            raise self.error
        return self.payload


class ProxyHealthTests(unittest.IsolatedAsyncioTestCase):
    async def probe(self, session, counts):
        return await _check_single_proxy(
            session,
            make_proxy(),
            "ExamplePlayer",
            aiohttp.ClientTimeout(total=15),
            failure_counts=counts,
        )

    async def test_success_and_rate_limit_remain_reachable(self):
        for response in (Response(payload={"responseType": "OK"}), Response(429)):
            with self.subTest(status=response.status):
                counts = Counter()
                session = SimpleNamespace(get=Mock(return_value=response))
                self.assertTrue(await self.probe(session, counts))
                self.assertEqual(counts, {})

    async def test_http_failures_retain_status(self):
        for status in (403, 404, 502):
            with self.subTest(status=status):
                counts = Counter()
                session = SimpleNamespace(get=Mock(return_value=Response(status)))
                self.assertFalse(await self.probe(session, counts))
                self.assertEqual(counts, {f"HTTP {status}": 1})

    async def test_invalid_payloads_do_not_count_as_working(self):
        for response, reason in (
            (Response(payload={"response": {}}), "unexpected JSON schema"),
            (Response(payload=[]), "unexpected JSON schema"),
            (Response(error=ValueError("private body")), "invalid JSON response"),
        ):
            with self.subTest(reason=reason):
                counts = Counter()
                session = SimpleNamespace(get=Mock(return_value=response))
                self.assertFalse(await self.probe(session, counts))
                self.assertEqual(counts, {reason: 1})

    async def test_timeout_has_a_reason_even_without_exception_text(self):
        counts = Counter()
        session = SimpleNamespace(get=Mock(side_effect=asyncio.TimeoutError()))
        self.assertFalse(await self.probe(session, counts))
        self.assertEqual(counts, {"timeout": 1})

    async def test_connection_errors_do_not_log_private_exception_text(self):
        counts = Counter()
        session = SimpleNamespace(
            get=Mock(side_effect=aiohttp.ClientConnectionError("PRIVATE_CREDENTIAL"))
        )
        with self.assertLogs("proxy.health_check", level="DEBUG") as captured:
            self.assertFalse(await self.probe(session, counts))
        self.assertEqual(counts, {"connection error": 1})
        self.assertNotIn("PRIVATE_CREDENTIAL", "\n".join(captured.output))

    async def test_batch_summary_explains_failures_and_preserves_membership(self):
        proxies = [make_proxy(str(index)) for index in range(4)]
        session = SimpleNamespace(
            get=Mock(
                side_effect=[
                    Response(404),
                    asyncio.TimeoutError(),
                    Response(429),
                    Response(payload={"responseType": "OK"}),
                ]
            )
        )
        with (
            patch.dict("os.environ", {"PROXY_CHECK_ATTEMPTS": "1"}),
            self.assertLogs("proxy.health_check", level="INFO") as captured,
        ):
            report = await filter_working_proxies(proxies, session)
        self.assertEqual((report.total, report.working, report.failed), (4, 2, 2))
        self.assertEqual({proxy.id for proxy in report.working_proxies}, {"2", "3"})
        self.assertEqual(set(report.failed_proxy_ids), {"0", "1"})
        summary = "\n".join(captured.output)
        self.assertIn("HTTP 404: 1", summary)
        self.assertIn("timeout: 1", summary)


class ProxyFlowTests(unittest.TestCase):
    def test_user_id_validation_matches_xray_forms_and_utf8_limits(self):
        for value in (
            "00000000-0000-4000-8000-000000000001",
            "00000000000040008000000000000001",
            "account-alias",
            "x" * 30,
            "т" * 15,
        ):
            with self.subTest(value=value):
                self.assertTrue(valid_xray_user_id(value))
        for value in (
            "",
            "00000000-0000-4000-8000-0000000",
            "00000000-0000-4000-8000-00000000000z",
            "x" * 31,
            "x" * 37,
            "т" * 16,
            None,
        ):
            with self.subTest(value=value):
                self.assertFalse(valid_xray_user_id(value))

    def test_parser_rejects_truncated_uuid_before_xray_start(self):
        self.assertIsNone(
            parse_vless_uri(
                "vless://00000000-0000-4000-8000-0000000@example.invalid:443?security=tls"
            )
        )

    def test_cached_truncated_uuid_does_not_discard_valid_neighbors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.json"
            bad = make_proxy("bad")
            bad.uuid = "00000000-0000-4000-8000-0000000"
            save_proxies_json(path, [bad, make_proxy("valid")])
            with self.assertLogs("proxy.config_store", level="WARNING"):
                loaded = load_proxies_json(path)
            self.assertEqual([proxy.id for proxy in loaded], ["valid"])

    def test_parser_rejects_old_flows_and_preserves_supported_flows(self):
        prefix = "vless://00000000-0000-4000-8000-000000000001@example.invalid:443?security=tls&type=tcp&flow="
        for flow in ("xtls-rprx-origin", "xtls-rprx-direct", "unknown"):
            with self.subTest(flow=flow):
                self.assertIsNone(parse_vless_uri(prefix + flow))
        for flow in SUPPORTED_FLOWS:
            with self.subTest(flow=flow):
                proxy = parse_vless_uri(prefix + flow)
                self.assertIsNotNone(proxy)
                self.assertEqual(proxy.flow, flow)

    def test_cached_old_flow_is_rejected_before_xray_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxies.json"
            save_proxies_json(
                path,
                [make_proxy("old", "xtls-rprx-origin"), make_proxy("valid")],
            )
            with self.assertLogs("proxy.config_store", level="WARNING"):
                loaded = load_proxies_json(path)
            self.assertEqual([proxy.id for proxy in loaded], ["valid"])
