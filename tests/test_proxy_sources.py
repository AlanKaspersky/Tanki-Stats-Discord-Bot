import base64
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from proxy.bootstrap import ProxyBootstrap
from proxy.subscription import decode_subscription_body, fetch_all_subscriptions
from proxy.vless_parser import has_masked_authority, parse_vless_uri


VALID = "vless://example-user@example.invalid:443?security=tls"


class ProxySourceTests(unittest.IsolatedAsyncioTestCase):
    def test_masked_entries_are_rejected_without_logging_credentials(self):
        counts = Counter()
        with self.assertLogs("proxy.vless_parser", level="DEBUG") as logs:
            for authority in (
                "[emailprotected]",
                "[email protected]",
                "[email\u00a0protected]",
                "%5Bemailprotected%5D",
                "[email&#160;protected]",
            ):
                self.assertIsNone(
                    parse_vless_uri(
                        f"vless://{authority}:443?security=tls&pbk=PRIVATE_KEY",
                        failure_counts=counts,
                    )
                )
        self.assertEqual(counts, {"masked user ID/address (email protection)": 5})
        self.assertNotIn("PRIVATE_KEY", "\n".join(logs.output))
        self.assertFalse(any("WARNING" in line for line in logs.output))

    def test_ipv6_and_masked_names_remain_valid(self):
        for uri in (
            "vless://example-user@[::1]:443?security=tls",
            VALID + "#%5Bemailprotected%5D",
            VALID + "&label=[emailprotected]",
        ):
            self.assertFalse(has_masked_authority(uri))
            self.assertIsNotNone(parse_vless_uri(uri))

    def test_other_syntax_errors_do_not_echo_original_uri(self):
        with self.assertLogs("proxy.vless_parser", level="DEBUG") as logs:
            self.assertIsNone(
                parse_vless_uri(
                    "vless://PRIVATE_ID@example.invalid:PRIVATE_PORT?security=tls&token=PRIVATE_TOKEN"
                )
            )
        text = "\n".join(logs.output)
        for value in ("PRIVATE_ID", "PRIVATE_PORT", "PRIVATE_TOKEN"):
            self.assertNotIn(value, text)

    def test_plain_and_base64_subscriptions_keep_their_content(self):
        plain = "# subscription\n" + VALID + "\n" + VALID + "#Example"
        encoded = base64.b64encode(plain.encode()).decode().rstrip("=")
        wrapped = "\n".join(
            encoded[index : index + 20] for index in range(0, len(encoded), 20)
        )
        self.assertEqual(decode_subscription_body(plain), plain)
        self.assertEqual(decode_subscription_body(encoded), plain)
        self.assertEqual(decode_subscription_body(wrapped), plain)
        bad_utf8 = base64.b64encode(b"\xffvless://bad").decode()
        self.assertEqual(decode_subscription_body(bad_utf8), bad_utf8)

    async def test_parser_emits_one_summary_for_many_bad_entries_and_keeps_valid_neighbor(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = ProxyBootstrap(Path(directory))
            bootstrap.sources_path.write_text(
                "\n".join(
                    ["vless://[emailprotected]:443?security=tls"] * 100 + [VALID]
                ),
                encoding="utf-8",
            )
            with (
                patch.dict("os.environ", {"MAX_PROXIES": "0"}),
                self.assertLogs("proxy.bootstrap", level="WARNING") as logs,
            ):
                bootstrap.max_proxies = 0
                parsed = await bootstrap.parse_proxies_from_sources(object())
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0].uuid, "example-user")
            self.assertEqual(len(logs.output), 1)
            self.assertIn("email protection): 100", logs.output[0])

    async def test_source_summary_identifies_source_without_printing_private_url(self):
        body = (
            VALID
            + "\nvless://[emailprotected]:443?security=tls\n"
            + VALID
            + "#[emailprotected]"
        )
        with (
            patch(
                "proxy.subscription.fetch_subscription", AsyncMock(return_value=body)
            ),
            self.assertLogs("proxy.subscription", level="WARNING") as logs,
        ):
            result = await fetch_all_subscriptions(
                ["https://example.invalid/PRIVATE_PATH?token=PRIVATE_TOKEN"], object()
            )
        self.assertEqual(result, [body])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Subscription #1 (example.invalid) contains 1", logs.output[0])
        self.assertNotIn("PRIVATE", logs.output[0])
