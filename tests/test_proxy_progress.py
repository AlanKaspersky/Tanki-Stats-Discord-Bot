import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from commands.stats_features.constants import ADMIN_IDS
from proxy.bootstrap import ProxyBootstrap
from proxy.health_check import ProxyFilterReport
from proxy.subscription import fetch_all_subscriptions
from tests.helpers import make_stats
from tests.test_proxy_startup import proxy


class ProxyProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bootstrap = ProxyBootstrap(Path(self.tmp.name))
        self.bootstrap.enabled = True

    async def test_queued_check_shows_waiting_before_acquiring_lock(self):
        waiting = asyncio.Event()
        stages = []

        async def stage(text):
            stages.append(text)
            waiting.set()

        self.bootstrap._filter_working_proxies_from_sources = AsyncMock()
        await self.bootstrap._check_lock.acquire()
        task = asyncio.create_task(
            self.bootstrap.filter_working_proxies_from_sources(
                object(), stage_callback=stage
            )
        )
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            self.assertIn("Ожидание", stages[0])
            self.bootstrap._filter_working_proxies_from_sources.assert_not_awaited()
        finally:
            self.bootstrap._check_lock.release()
            await task

    async def test_counter_appears_before_xray_and_switching_stage_after_probes(self):
        events = []
        candidate = proxy("good")
        self.bootstrap.parse_proxies_from_sources = AsyncMock(return_value=[candidate])
        self.bootstrap._restart_xray_with_proxies = AsyncMock()

        async def stage(text):
            events.append(text)

        async def progress(*counts):
            events.append(counts)

        async def check(*args, **kwargs):
            self.assertIn((0, 1, 0, 0), events)
            events.append("probed")
            return ProxyFilterReport(1, 1, 0, [candidate], [])

        self.bootstrap._health_check_proxies_resilient = check
        with patch("proxy.bootstrap.XrayRunner"):
            await self.bootstrap.filter_working_proxies_from_sources(
                object(),
                rewrite_sources=False,
                progress_callback=progress,
                stage_callback=stage,
            )
        self.assertIn("Загрузка", events[0])
        self.assertIn("переключение", events[-1])
        self.assertLess(events.index("probed"), len(events) - 1)

    async def test_subscription_stages_do_not_expose_urls(self):
        stage = AsyncMock()
        with patch("proxy.subscription.fetch_subscription", AsyncMock(return_value="")):
            await fetch_all_subscriptions(
                ["https://example.invalid/SECRET", "https://example.invalid/TOKEN"],
                object(),
                stage_callback=stage,
            )
        self.assertEqual(
            [call.args[0] for call in stage.await_args_list],
            ["Загрузка подписки 1/2...", "Загрузка подписки 2/2..."],
        )

    async def test_large_source_parsing_does_not_block_event_loop(self):
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def parse(*args):
            loop.call_soon_threadsafe(entered.set)
            release.wait(2)
            return []

        self.bootstrap._parse_source_content = parse
        with patch("proxy.bootstrap.load_sources_file", return_value=([], [])):
            task = asyncio.create_task(self.bootstrap.parse_proxies_from_sources())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                self.assertFalse(task.done())
                await asyncio.sleep(0)
            finally:
                release.set()
                await task

    async def test_command_edits_same_message_for_stages_progress_and_completion(self):
        stats = make_stats(self.tmp.name)
        message = SimpleNamespace(edit=AsyncMock())
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=next(iter(ADMIN_IDS))),
            send=AsyncMock(return_value=message),
        )

        async def check(session, **kwargs):
            await kwargs["stage_callback"]("Ожидание очереди...")
            await kwargs["stage_callback"]("Загрузка подписки 1/18...")
            await kwargs["progress_callback"](0, 100, 0, 0)
            return ProxyFilterReport(100, 5, 95, [], [])

        stats.proxy_bootstrap = SimpleNamespace(
            enabled=True,
            filter_working_proxies_from_sources=check,
            proxies_json_path=Path("proxies.json"),
            sources_path=Path("sources.txt"),
        )
        stats.proxy_session = object()
        await stats.proxycheck_admin.callback(stats, ctx)
        contents = [call.kwargs["content"] for call in message.edit.await_args_list]
        self.assertIn("Ожидание", contents[0])
        self.assertIn("1/18", contents[1])
        self.assertIn("0/100", contents[2])
        self.assertIn("Проверка завершена", contents[3])
        ctx.send.assert_awaited_once()
