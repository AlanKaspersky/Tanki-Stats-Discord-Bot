import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from proxy.bootstrap import ProxyBootstrap
from proxy.checker import XrayProxyChecker
from proxy.health_check import ProxyFilterReport
from proxy.models import ProxyConfig
from proxy.pool import ProxyPool
from proxy.xray_runner import XrayRunner
from tests.helpers import make_interaction, make_stats


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
        binary = patch("proxy.bootstrap.XrayRunner")
        binary.start().resolve_binary.return_value = Path("unused")
        self.addCleanup(binary.stop)

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
        self.bootstrap._restart_xray_with_proxies.assert_not_awaited()

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

    async def test_cancelled_scan_stops_only_checker(self):
        entered = asyncio.Event()
        pool = self.bootstrap.pool
        self.bootstrap.parse_proxies_from_sources = AsyncMock(
            return_value=[make_proxy("new")]
        )
        checker = Mock(stop=AsyncMock())

        async def scan(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        self.bootstrap._health_check_proxies_resilient = scan
        with patch("proxy.bootstrap.XrayProxyChecker", return_value=checker):
            task = asyncio.create_task(
                self.bootstrap.filter_working_proxies_from_sources(object())
            )
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        checker.stop.assert_awaited_once()
        self.assertIs(self.bootstrap.pool, pool)
        self.bootstrap._restart_xray_with_proxies.assert_not_awaited()

    async def test_cancelled_publication_restores_pool_before_unlocking(self):
        candidate = make_proxy("new")
        pool = self.bootstrap.pool
        self.bootstrap.parse_proxies_from_sources = AsyncMock(return_value=[candidate])
        self.bootstrap._health_check_proxies_resilient = AsyncMock(
            return_value=ProxyFilterReport(1, 1, 0, [candidate], [])
        )
        self.bootstrap._restart_xray_with_proxies.side_effect = [
            asyncio.CancelledError(),
            None,
        ]
        lock = asyncio.Lock()
        with self.assertRaises(asyncio.CancelledError):
            with self.assertLogs("proxy.bootstrap", level="ERROR"):
                await self.bootstrap.filter_working_proxies_from_sources(
                    object(), replacement_lock=lock
                )
        self.assertIs(self.bootstrap.pool, pool)
        self.assertFalse(lock.locked())
        self.assertEqual(self.bootstrap._restart_xray_with_proxies.await_count, 2)

    async def test_add_and_daily_collection_complete_during_scan(self):
        stats = make_stats(self.tmp.name)
        stats.proxy_bootstrap = self.bootstrap
        stats.proxy_session = object()
        entered, finish = asyncio.Event(), asyncio.Event()
        self.bootstrap.parse_proxies_from_sources = AsyncMock(
            return_value=[make_proxy("new")]
        )

        async def scan(proxies, session, **kwargs):
            entered.set()
            await finish.wait()
            return ProxyFilterReport(1, 1, 0, proxies, [])

        self.bootstrap._health_check_proxies_resilient = scan
        check = asyncio.create_task(stats.auto_proxy_check.coro(stats))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertFalse(stats._pool_recovery_lock.locked())
            interaction = make_interaction()

            async def fetch(session, url, pool):
                self.assertIs(pool, self.bootstrap.pool)
                self.assertIsNotNone(pool.get_proxy_by_id("old"))
                return {"name": "Player", "score": 123}, None

            with patch(
                "commands.stats_features.collection.fetch_tanki_stats_via_proxy",
                side_effect=fetch,
            ):
                await asyncio.wait_for(
                    stats.stats_add.callback(stats, interaction, "Player", "Main"), 1
                )
                result = await asyncio.wait_for(
                    stats._run_daily_collection(dry_run=True), 1
                )
                delivered = await asyncio.wait_for(stats._run_daily_collection(), 1)
            self.assertEqual(result, (1, 0, []))
            self.assertEqual(delivered, (1, 0, []))
            stats.bot.fetch_user.assert_awaited()
            self.assertEqual(
                stats.accounts_manager.get_account_stats("Player")["score"], 123
            )
            self.bootstrap._restart_xray_with_proxies.assert_not_awaited()
            finish.set()
            await asyncio.wait_for(check, 1)
            self.bootstrap._restart_xray_with_proxies.assert_awaited_once()
        finally:
            check.cancel()
            await asyncio.gather(check, return_exceptions=True)

    async def test_publication_waits_for_inflight_profile_request(self):
        stats = make_stats(self.tmp.name)
        stats.proxy_bootstrap = self.bootstrap
        stats.proxy_session = object()
        entered, release = asyncio.Event(), asyncio.Event()
        candidate = make_proxy("new")
        self.bootstrap.parse_proxies_from_sources = AsyncMock(return_value=[candidate])
        self.bootstrap._health_check_proxies_resilient = AsyncMock(
            return_value=ProxyFilterReport(1, 1, 0, [candidate], [])
        )

        async def fetch(*args):
            entered.set()
            await release.wait()
            return {"score": 1}, None

        with patch(
            "commands.stats_features.collection.fetch_tanki_stats_via_proxy",
            side_effect=fetch,
        ):
            request = asyncio.create_task(stats._fetch_tanki_stats_result("url"))
            await asyncio.wait_for(entered.wait(), 1)
            check = asyncio.create_task(
                self.bootstrap.filter_working_proxies_from_sources(
                    object(),
                    rewrite_sources=False,
                    replacement_lock=stats._pool_recovery_lock,
                )
            )
            try:
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertFalse(check.done())
                self.bootstrap._restart_xray_with_proxies.assert_not_awaited()
                release.set()
                await asyncio.wait_for(asyncio.gather(request, check), 1)
                self.assertIsNotNone(self.bootstrap.pool.get_proxy_by_id("new"))
            finally:
                request.cancel()
                check.cancel()
                await asyncio.gather(request, check, return_exceptions=True)

    async def test_shutdown_cancels_scan_and_stops_both_runtimes(self):
        entered = asyncio.Event()
        self.bootstrap.parse_proxies_from_sources = AsyncMock(
            return_value=[make_proxy("new")]
        )

        async def scan(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        self.bootstrap._health_check_proxies_resilient = scan
        serving = Mock(stop_async=AsyncMock())
        checker = Mock(stop=AsyncMock())
        self.bootstrap._runner = serving
        with patch("proxy.bootstrap.XrayProxyChecker", return_value=checker):
            check = asyncio.create_task(
                self.bootstrap.filter_working_proxies_from_sources(object())
            )
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.wait_for(self.bootstrap.stop(), 1)
            self.assertTrue(check.cancelled())
        checker.stop.assert_awaited_once()
        serving.stop_async.assert_awaited_once()
        self.assertIsNone(self.bootstrap.pool)

    async def test_checker_ports_and_config_are_independent(self):
        checker = XrayProxyChecker(Path("unused"), Path(self.tmp.name), {18001})
        checker.runner = Mock(start_async=AsyncMock(), stop_async=AsyncMock())
        candidates = [make_proxy("a"), make_proxy("b")]
        try:
            with patch.dict("os.environ", {"PROXY_CHECK_XRAY_WARMUP": "0"}):
                await checker.restart(candidates)
            ports = {p.local_http_port for p in candidates}
            self.assertEqual(len(ports), 2)
            self.assertNotIn(18001, ports)
            self.assertNotEqual(checker.config_path, self.bootstrap.xray_config_path)
            self.assertTrue(checker.config_path.exists())
            self.assertEqual(self.previous.local_http_port, 18001)
        finally:
            await checker.stop()
        self.assertFalse(checker.config_path.parent.exists())

    async def test_simultaneous_checks_are_serialized_and_do_not_mutate_inputs(self):
        entered, release = asyncio.Event(), asyncio.Event()
        candidate = make_proxy("new")
        self.bootstrap.parse_proxies_from_sources = AsyncMock(return_value=[candidate])
        calls = 0

        async def scan(proxies, session, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            proxies[0].local_http_port = 54321
            return ProxyFilterReport(1, 1, 0, proxies, [])

        self.bootstrap._health_check_proxies_resilient = scan
        checks = [
            asyncio.create_task(
                self.bootstrap.filter_working_proxies_from_sources(
                    object(), rewrite_sources=False
                )
            )
        ]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            checks.append(
                asyncio.create_task(
                    self.bootstrap.filter_working_proxies_from_sources(
                        object(), rewrite_sources=False
                    )
                )
            )
            await asyncio.sleep(0)
            self.assertEqual(calls, 1)
            release.set()
            reports = await asyncio.wait_for(asyncio.gather(*checks), 1)
            self.assertEqual(calls, 2)
            self.assertEqual(candidate.local_http_port, 18001)
            self.assertEqual(self.previous.local_http_port, 18001)
            self.assertEqual(
                self.bootstrap._proxies[0].local_http_port, self.bootstrap.base_port
            )
            self.assertEqual(reports[0].working_proxies[0].local_http_port, 54321)
        finally:
            for task in checks:
                task.cancel()
            await asyncio.gather(*checks, return_exceptions=True)

    async def test_manual_and_emergency_checks_do_not_hold_serving_lock(self):
        stats = make_stats(self.tmp.name)
        stats.proxy_bootstrap = self.bootstrap
        stats.proxy_session = object()
        stats._notify_admins_proxy_recovery = AsyncMock()
        report = ProxyFilterReport(1, 1, 0, [make_proxy("new")], [])

        async def scan(*args, replacement_lock, **kwargs):
            self.assertIs(replacement_lock, stats._pool_recovery_lock)
            self.assertFalse(replacement_lock.locked())
            return report

        self.bootstrap.filter_working_proxies_from_sources = AsyncMock(side_effect=scan)
        ctx = Mock(author=Mock(id=570644931841097728), send=AsyncMock())
        await stats.proxycheck_admin.callback(stats, ctx)
        self.assertTrue(await stats._recover_proxy_pool("test"))
        self.assertEqual(
            self.bootstrap.filter_working_proxies_from_sources.await_count, 2
        )

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
