import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

from proxy.bootstrap import ProxyBootstrap
from proxy.health_check import ProxyFilterReport
from proxy.models import ProxyConfig
from proxy.pool import ProxyPool
from proxy.xray_runner import XrayRunner


def make_proxy(identifier):
    return ProxyConfig(
        id=identifier,
        name=identifier,
        address="example.invalid",
        port=443,
        uuid="test",
        local_http_port=18001,
    )


class ProxyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bootstrap = ProxyBootstrap(Path(self.tmp.name))
        self.bootstrap.enabled = True
        self.previous = make_proxy("old")
        self.bootstrap._proxies = [self.previous]
        self.bootstrap.pool = ProxyPool([self.previous])
        self.bootstrap._restart_xray_with_proxies = AsyncMock()

    async def test_failed_check_restores_previous_pool(self):
        self.bootstrap.parse_proxies_from_sources = AsyncMock(
            return_value=[make_proxy("new")]
        )
        self.bootstrap._health_check_proxies_resilient = AsyncMock(
            return_value=ProxyFilterReport(1, 0, 1, [], ["new"])
        )
        with self.assertLogs("proxy.bootstrap", level="ERROR"):
            with self.assertRaises(RuntimeError):
                await self.bootstrap.filter_working_proxies_from_sources(
                    object(), rewrite_sources=False
                )
        self.assertIsNotNone(self.bootstrap.pool.get_proxy_by_id("old"))
        self.bootstrap._restart_xray_with_proxies.assert_awaited_once()

    async def test_final_restart_failure_does_not_publish_candidate_pool(self):
        candidate = make_proxy("new")
        self.bootstrap.parse_proxies_from_sources = AsyncMock(return_value=[candidate])
        self.bootstrap._health_check_proxies_resilient = AsyncMock(
            return_value=ProxyFilterReport(1, 1, 0, [candidate], [])
        )
        self.bootstrap._restart_xray_with_proxies.side_effect = [
            RuntimeError("restart failed"),
            None,
        ]
        with self.assertLogs("proxy.bootstrap", level="ERROR"):
            with self.assertRaises(RuntimeError):
                await self.bootstrap.filter_working_proxies_from_sources(
                    object(), rewrite_sources=False
                )
        self.assertIsNone(self.bootstrap.pool.get_proxy_by_id("new"))
        self.assertIsNotNone(self.bootstrap.pool.get_proxy_by_id("old"))

    async def test_cancelled_check_stops_xray(self):
        self.bootstrap._filter_working_proxies_from_sources = AsyncMock(
            side_effect=asyncio.CancelledError()
        )
        self.bootstrap.stop = AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            await self.bootstrap.filter_working_proxies_from_sources(object())
        self.bootstrap.stop.assert_awaited_once()

    async def test_cancelled_start_waits_for_executor_before_cleanup(self):
        runner = XrayRunner(Path("unused"), Path("unused"))
        started = threading.Event()
        release = threading.Event()
        events = []

        def start():
            started.set()
            release.wait(timeout=1)
            events.append("started")

        def stop():
            events.append("stopped")

        with (
            patch.object(runner, "_start_sync", start),
            patch.object(runner, "stop", stop),
        ):
            task = asyncio.create_task(runner.start_async())
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(events, ["started", "stopped"])

    async def test_windows_prefers_windows_binary_and_preserves_linux_binary(self):
        base = Path(self.tmp.name)
        (base / "xray").write_bytes(b"\x7fELFtest")
        (base / "xray.exe").write_bytes(b"MZtest")
        with patch("proxy.xray_runner.platform.system", return_value="Windows"):
            self.assertEqual(
                XrayRunner.resolve_binary(base), (base / "xray.exe").resolve()
            )
        self.assertEqual((base / "xray").read_bytes(), b"\x7fELFtest")

    async def test_linux_binary_on_windows_has_clear_error_before_process_start(self):
        base = Path(self.tmp.name)
        (base / "xray").write_bytes(b"\x7fELFtest")
        with patch("proxy.xray_runner.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(OSError, "Linux ELF binary"):
                XrayRunner.resolve_binary(base)

    async def test_explicit_relative_binary_path_is_relative_to_project(self):
        base = Path(self.tmp.name)
        (base / "custom.exe").write_bytes(b"MZtest")
        with patch("proxy.xray_runner.platform.system", return_value="Windows"):
            self.assertEqual(
                XrayRunner.resolve_binary(base, "custom.exe"),
                (base / "custom.exe").resolve(),
            )
