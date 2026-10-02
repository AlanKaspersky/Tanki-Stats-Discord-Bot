import asyncio
import unittest
from unittest.mock import patch

from proxy.pool import ProxyPoolExhausted
from utils.stats_collector import collect_daily_stats_parallel


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        p = patch(
            "utils.stats_collector.daily_stats_settings", return_value=(1, 0, 0, 3)
        )
        p.start()
        self.addCleanup(p.stop)

    async def test_unexpected_error_does_not_hang_or_skip_remaining_accounts(self):
        async def process(account):
            if account["nickname"] == "broken":
                raise ValueError("bad response")
            return True, None, {"score": 1}

        accounts = [{"nickname": "broken"}, {"nickname": "ok"}]
        with self.assertLogs("utils.stats_collector", level="ERROR"):
            processed, failed, exhausted, _ = await asyncio.wait_for(
                collect_daily_stats_parallel(accounts, process), 1
            )
        self.assertEqual(processed, 1)
        self.assertEqual(failed, [accounts[0]])
        self.assertFalse(exhausted)

    async def test_retries_then_succeeds(self):
        attempts = 0

        async def process(account):
            nonlocal attempts
            attempts += 1
            return (True, None, {}) if attempts == 3 else (False, "HTTP 429", None)

        with self.assertLogs("utils.stats_collector", level="WARNING"):
            processed, failed, _, _ = await collect_daily_stats_parallel(
                [{"nickname": "a"}], process
            )
        self.assertEqual((processed, failed, attempts), (1, [], 3))

    async def test_retry_callback_failure_isolated(self):
        async def process(account):
            return False, "timeout", None

        async def wait(reason):
            raise RuntimeError("retry callback failed")

        accounts = [{"nickname": "a"}, {"nickname": "b"}]
        with self.assertLogs("utils.stats_collector", level="ERROR"):
            processed, failed, _, _ = await asyncio.wait_for(
                collect_daily_stats_parallel(accounts, process, wait_before_retry=wait),
                1,
            )
        self.assertEqual(processed, 0)
        self.assertEqual(failed, accounts)

    async def test_exhausted_pool_preserves_all_pending_accounts(self):
        async def process(account):
            raise ProxyPoolExhausted()

        accounts = [{"nickname": "a"}, {"nickname": "b"}]
        with self.assertLogs("utils.stats_collector", level="WARNING"):
            processed, failed, exhausted, _ = await collect_daily_stats_parallel(
                accounts, process
            )
        self.assertEqual((processed, failed, exhausted), (0, accounts, True))

    async def test_cancellation_stops_workers(self):
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def process(account):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        task = asyncio.create_task(
            collect_daily_stats_parallel([{"nickname": "a"}], process)
        )
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stopped.is_set())

    async def test_retry_limit_is_enforced(self):
        attempts = 0

        async def process(account):
            nonlocal attempts
            attempts += 1
            return False, "timeout", None

        with self.assertLogs("utils.stats_collector", level="WARNING"):
            result = await collect_daily_stats_parallel([{"nickname": "a"}], process)
        self.assertEqual(attempts, 3)
        self.assertEqual(len(result[1]), 1)
