from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from proxy.bootstrap import ProxyBootstrap
from proxy.config_store import save_proxies_json
from proxy.health_check import ProxyFilterReport
from proxy.models import ProxyConfig
from proxy.pool import ProxyPool


def proxy(identifier):
    return ProxyConfig(
        identifier,
        identifier,
        "example.invalid",
        443,
        "example-user",
        security="tls",
        local_http_port=18001,
    )


class ProxyStartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bootstrap = ProxyBootstrap(Path(self.tmp.name))
        self.bootstrap.enabled = True
        self.bootstrap.refresh_on_start = True
        self.bootstrap.parse_proxies_from_sources = AsyncMock(
            side_effect=AssertionError("startup must not download candidates")
        )

    async def test_start_uses_cache_without_downloading_or_overwriting_it(self):
        save_proxies_json(self.bootstrap.proxies_json_path, [proxy("cached")])
        original = self.bootstrap.proxies_json_path.read_bytes()
        runner = SimpleNamespace(start_async=AsyncMock())
        with patch("proxy.bootstrap.XrayRunner", return_value=runner):
            await self.bootstrap.start(object())
        self.assertEqual(self.bootstrap.pool.size, 1)
        runner.start_async.assert_awaited_once()
        self.bootstrap.parse_proxies_from_sources.assert_not_awaited()
        self.assertEqual(self.bootstrap.proxies_json_path.read_bytes(), original)

    async def test_missing_cache_does_not_delay_start_or_save_candidates(self):
        with patch("proxy.bootstrap.XrayRunner") as runner:
            await self.bootstrap.start(object())
        self.assertIsNone(self.bootstrap.pool)
        self.assertFalse(self.bootstrap.proxies_json_path.exists())
        self.assertFalse(self.bootstrap.xray_config_path.exists())
        self.bootstrap.parse_proxies_from_sources.assert_not_awaited()
        runner.assert_not_called()

    async def test_70813_entry_cache_is_skipped_without_overwriting_it(self):
        original = b'{"proxies": [], "migration": "preserve"}'
        self.bootstrap.proxies_json_path.write_bytes(original)
        self.bootstrap.base_port = 18001
        with (
            patch(
                "proxy.bootstrap.load_proxies_json",
                return_value=[proxy("candidate")] * 70813,
            ),
            patch("proxy.bootstrap.XrayRunner") as runner,
        ):
            with self.assertLogs("proxy.bootstrap", level="WARNING"):
                await self.bootstrap.start(object())
        self.assertIsNone(self.bootstrap.pool)
        self.assertEqual(self.bootstrap._proxies, [])
        self.assertEqual(self.bootstrap.proxies_json_path.read_bytes(), original)
        runner.assert_not_called()
        self.bootstrap.parse_proxies_from_sources.assert_not_awaited()

    async def test_background_refresh_creates_pool_after_cacheless_start(self):
        await self.bootstrap.start(object())
        candidate = proxy("checked")
        self.bootstrap.parse_proxies_from_sources = AsyncMock(return_value=[candidate])
        self.bootstrap._health_check_proxies_resilient = AsyncMock(
            return_value=ProxyFilterReport(1, 1, 0, [candidate], [])
        )
        self.bootstrap._restart_xray_with_proxies = AsyncMock()
        with patch("proxy.bootstrap.XrayRunner"):
            await self.bootstrap.refresh_proxies(object())
        self.assertEqual(self.bootstrap.pool.size, 1)
        self.assertIsNotNone(self.bootstrap.pool.get_proxy_by_id("checked"))
        self.assertTrue(self.bootstrap.proxies_json_path.exists())

    async def test_failed_refresh_keeps_cache_and_serving_pool(self):
        cached = proxy("cached")
        save_proxies_json(self.bootstrap.proxies_json_path, [cached])
        original = self.bootstrap.proxies_json_path.read_bytes()
        self.bootstrap._proxies = [cached]
        self.bootstrap.pool = ProxyPool([cached])
        serving = self.bootstrap.pool
        self.bootstrap.parse_proxies_from_sources = AsyncMock(
            return_value=[proxy("bad")]
        )
        self.bootstrap._health_check_proxies_resilient = AsyncMock(
            return_value=ProxyFilterReport(1, 0, 1, [], ["bad"])
        )
        with (
            patch("proxy.bootstrap.XrayRunner"),
            self.assertLogs("proxy.bootstrap", level="ERROR"),
        ):
            with self.assertRaises(RuntimeError):
                await self.bootstrap.refresh_proxies(object())
        self.assertIs(self.bootstrap.pool, serving)
        self.assertEqual(self.bootstrap.proxies_json_path.read_bytes(), original)
