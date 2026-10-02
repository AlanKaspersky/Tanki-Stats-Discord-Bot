import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from proxy.bootstrap import ProxyBootstrap
from proxy.health_check import filter_working_proxies
from proxy.models import ProxyConfig
from proxy.pool import ProxyPool
from tests.helpers import make_stats


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


class ProxyRefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(
            patch.dict(
                "os.environ",
                {
                    "PROXY_CHECK_WORKERS": "1",
                    "PROXY_CHECK_BATCH_SIZE": "4",
                    "PROXY_WORKING_TARGET": "3",
                },
            )
        )
        self.patches.enter_context(patch("proxy.bootstrap.random.shuffle"))
        self.patches.enter_context(patch("proxy.bootstrap.XrayRunner"))
        self.checker = SimpleNamespace(restart=AsyncMock(), stop=AsyncMock())
        self.patches.enter_context(
            patch("proxy.bootstrap.XrayProxyChecker", return_value=self.checker)
        )
        self.bootstrap = ProxyBootstrap(Path(self.tmp.name))
        self.bootstrap.enabled = True
        self.bootstrap._restart_xray_with_proxies = AsyncMock()
        self.candidates = [proxy(str(index)) for index in range(12)]
        self.bootstrap.parse_proxies_from_sources = AsyncMock(
            return_value=self.candidates
        )
        self.probed = []
        self.good_ids = {p.id for p in self.candidates}

        async def probe(session, current, *args, **kwargs):
            self.probed.append(current.id)
            await asyncio.sleep(0)
            return current.id in self.good_ids

        self.patches.enter_context(
            patch("proxy.health_check._check_single_proxy", side_effect=probe)
        )
        self.bootstrap.sources_path.write_text(
            "https://example.invalid/subscription\n", encoding="utf-8"
        )

    async def test_target_stops_probes_and_preserves_sources_and_progress(self):
        progress = AsyncMock()
        report = await self.bootstrap.filter_working_proxies_from_sources(
            object(), rewrite_sources=False, progress_callback=progress
        )
        self.assertEqual(
            (report.total, report.working, report.failed, report.unchecked),
            (3, 3, 0, 9),
        )
        self.assertEqual(len(self.probed), 3)
        self.assertEqual(self.checker.restart.await_count, 1)
        self.assertEqual(progress.await_args.args, (3, 12, 3, 0))
        self.assertEqual(self.bootstrap.pool.size, 3)
        self.assertEqual(
            self.bootstrap.sources_path.read_text(encoding="utf-8"),
            "https://example.invalid/subscription\n",
        )

    async def test_large_source_stops_after_target_in_first_batch(self):
        candidates = [proxy(str(index)) for index in range(10000)]
        self.good_ids = {p.id for p in candidates}
        self.bootstrap.parse_proxies_from_sources.return_value = candidates
        with patch.dict(
            "os.environ",
            {
                "PROXY_CHECK_WORKERS": "25",
                "PROXY_CHECK_BATCH_SIZE": "400",
                "PROXY_WORKING_TARGET": "50",
            },
        ):
            report = await self.bootstrap.filter_working_proxies_from_sources(
                object(), rewrite_sources=False
            )
        self.assertGreaterEqual(report.working, 50)
        self.assertLessEqual(report.total, 74)
        self.assertEqual(report.unchecked, 10000 - report.total)
        self.assertEqual(len(self.probed), report.total)
        self.assertEqual(self.checker.restart.await_count, 1)
        self.assertEqual(self.bootstrap.pool.size, report.working)

    async def test_failures_do_not_count_toward_target_and_later_batches_are_used(self):
        self.good_ids = {"0", "4", "5", "8"}
        report = await self.bootstrap.filter_working_proxies_from_sources(
            object(), rewrite_sources=False
        )
        self.assertEqual(
            (report.total, report.working, report.failed, report.unchecked),
            (6, 3, 3, 6),
        )
        self.assertEqual({p.id for p in report.working_proxies}, {"0", "4", "5"})
        self.assertEqual(set(report.failed_proxy_ids), {"1", "2", "3"})

    async def test_unreachable_target_uses_all_available_working_routes(self):
        self.good_ids = {"2"}
        report = await self.bootstrap.filter_working_proxies_from_sources(
            object(), rewrite_sources=False
        )
        self.assertEqual(
            (report.total, report.working, report.failed, report.unchecked),
            (12, 1, 11, 0),
        )
        self.assertEqual(self.bootstrap.pool.size, 1)

    async def test_zero_target_and_manual_checks_are_complete(self):
        with patch.dict("os.environ", {"PROXY_WORKING_TARGET": "0"}):
            report = await self.bootstrap.filter_working_proxies_from_sources(
                object(), rewrite_sources=False
            )
        self.assertEqual((report.total, report.unchecked), (12, 0))
        self.probed.clear()
        with patch("proxy.bootstrap.rewrite_sources_keep_working") as rewrite:
            report = await self.bootstrap.filter_working_proxies_from_sources(
                object(), rewrite_sources=True
            )
        self.assertEqual((report.total, report.unchecked), (12, 0))
        self.assertEqual(len(self.probed), 12)
        rewrite.assert_called_once_with(
            self.bootstrap.sources_path, {p.id for p in self.candidates}
        )

    async def test_partial_scan_cannot_rewrite_sources(self):
        with self.assertRaisesRegex(ValueError, "complete"):
            await self.bootstrap.filter_working_proxies_from_sources(
                object(), working_target=3, rewrite_sources=True
            )
        self.bootstrap.parse_proxies_from_sources.assert_not_awaited()
        self.checker.restart.assert_not_awaited()

    async def test_known_routes_use_fresh_subscription_data_and_removed_routes_are_not_reused(
        self,
    ):
        cached = proxy("10")
        cached.sni = "old.invalid"
        removed = proxy("removed")
        self.bootstrap._proxies = [removed, cached]
        self.bootstrap.pool = ProxyPool([removed, cached])
        self.candidates[10].sni = "fresh.invalid"
        report = await self.bootstrap.filter_working_proxies_from_sources(
            object(), rewrite_sources=False, working_target=1
        )
        self.assertEqual(self.probed, ["10"])
        self.assertEqual(report.working_proxies[0].sni, "fresh.invalid")
        self.assertEqual(cached.sni, "old.invalid")
        self.assertIsNone(self.bootstrap.pool.get_proxy_by_id("removed"))
        await self.bootstrap.filter_working_proxies_from_sources(
            object(), rewrite_sources=False, working_target=1
        )
        self.assertEqual(self.bootstrap.parse_proxies_from_sources.await_count, 2)

    async def test_bisection_stops_before_unneeded_right_half(self):
        async def restart(proxies):
            if len(proxies) > 2:
                raise RuntimeError("rejected configuration")

        self.checker.restart.side_effect = restart
        report = await self.bootstrap.filter_working_proxies_from_sources(
            object(), rewrite_sources=False, working_target=1
        )
        self.assertEqual(
            (report.total, report.working, report.failed, report.unchecked),
            (1, 1, 0, 11),
        )
        self.assertEqual(self.probed, ["0"])
        self.assertEqual(self.checker.restart.await_count, 2)

    async def test_worker_cancellation_awaits_all_inflight_probes(self):
        entered = asyncio.Event()
        active = 0

        async def probe(*args, **kwargs):
            nonlocal active
            active += 1
            if active == 3:
                entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

        with (
            patch.dict("os.environ", {"PROXY_CHECK_WORKERS": "3"}),
            patch("proxy.health_check._check_single_proxy", side_effect=probe),
        ):
            task = asyncio.create_task(
                filter_working_proxies(self.candidates, object(), working_target=1)
            )
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(active, 0)

    async def test_inflight_successes_finish_without_probing_the_remaining_list(self):
        with patch.dict("os.environ", {"PROXY_CHECK_WORKERS": "3"}):
            report = await filter_working_proxies(
                self.candidates, object(), working_target=2
            )
        self.assertGreaterEqual(report.working, 2)
        self.assertLessEqual(report.working, 4)
        self.assertEqual(report.total, report.working)
        self.assertEqual(report.unchecked, 12 - report.total)

    async def test_bisection_counts_invalid_entries_and_carries_remaining_target(self):
        self.good_ids.remove("0")

        async def restart(proxies):
            if any(p.id == "0" for p in proxies):
                raise RuntimeError("bad entry")

        self.checker.restart.side_effect = restart
        with self.assertLogs("proxy.bootstrap", level="WARNING"):
            report = await self.bootstrap.filter_working_proxies_from_sources(
                object(), rewrite_sources=False, working_target=2
            )
        self.assertEqual(
            (report.total, report.working, report.failed, report.unchecked),
            (3, 2, 1, 9),
        )
        self.assertEqual(self.probed, ["1", "2"])
        self.assertEqual(report.failed_proxy_ids, ["0"])

    async def test_interval_is_configured_per_instance_and_invalid_values_are_rejected(
        self,
    ):
        for value in ("0.5", "6", "48"):
            with patch.dict("os.environ", {"PROXY_CHECK_INTERVAL_HOURS": value}):
                stats = make_stats(self.tmp.name)
            self.assertEqual(stats.auto_proxy_check.hours, float(value))
        for value in ("0", "-1", "nan", "inf", "invalid"):
            with (
                self.subTest(value=value),
                patch.dict("os.environ", {"PROXY_CHECK_INTERVAL_HOURS": value}),
            ):
                with self.assertRaises(ValueError):
                    make_stats(self.tmp.name)
