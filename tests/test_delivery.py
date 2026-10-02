import asyncio
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from tests.helpers import make_stats


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stats = make_stats(self.tmp.name)
        manager = self.stats.accounts_manager
        manager.add_user_to_account(
            "Player", "url", 1, "Main", initial_stats={"score": 100, "kills": 10}
        )
        manager.add_user_to_account("Player", "url", 2, "Main")
        self.users = {
            1: SimpleNamespace(send=AsyncMock()),
            2: SimpleNamespace(send=AsyncMock()),
        }
        self.stats.bot.fetch_user.side_effect = lambda uid: self.users[uid]

    def account(self):
        return self.stats.accounts_manager.load_account("Player")

    async def test_partial_delivery_retries_only_failed_recipient_after_restart(self):
        self.users[2].send.side_effect = RuntimeError("Discord unavailable")
        with self.assertLogs("commands.stats_features.delivery", level="ERROR"):
            self.assertTrue(
                await self.stats._deliver_account_stats(
                    self.account(), {"score": 150, "kills": 13}
                )
            )
        self.assertEqual(self.account()["last_stats"]["score"], 150)
        self.assertEqual(self.account()["pending_reports"][0]["pending_users"], ["2"])
        self.assertEqual(
            self.account()["pending_reports"][0]["diff_stats"]["score"], 50
        )
        restarted = make_stats(self.tmp.name)
        restarted.bot.fetch_user.side_effect = lambda uid: self.users[uid]
        self.users[2].send.side_effect = None
        await restarted.retry_pending_reports()
        self.assertEqual(self.users[1].send.await_count, 1)
        self.assertEqual(self.users[2].send.await_count, 2)
        self.assertEqual(self.account()["pending_reports"], [])
        self.assertIn(
            "+3", self.users[2].send.call_args.kwargs["embed"].fields[0].value
        )

    async def test_all_failed_messages_are_kept_and_report_order_preserved(self):
        for user in self.users.values():
            user.send.side_effect = RuntimeError("outage")
        with self.assertLogs("commands.stats_features.delivery", level="ERROR"):
            await self.stats._deliver_account_stats(
                self.account(), {"score": 150, "kills": 13}
            )
            await self.stats._deliver_account_stats(
                self.account(), {"score": 180, "kills": 18}
            )
        reports = self.account()["pending_reports"]
        self.assertEqual([r["diff_stats"]["score"] for r in reports], [50, 30])
        for user in self.users.values():
            user.send.side_effect = None
            user.send.reset_mock()
        await self.stats.retry_pending_reports()
        for user in self.users.values():
            calls = user.send.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertIn("+3", calls[0].kwargs["embed"].fields[0].value)
            self.assertIn("+5", calls[1].kwargs["embed"].fields[0].value)
        self.assertEqual(self.account()["pending_reports"], [])

    async def test_failed_save_does_not_send_or_advance_baseline(self):
        with patch("utils.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertLogs("utils.accounts_manager", level="ERROR"):
                self.assertFalse(
                    await self.stats._deliver_account_stats(
                        self.account(), {"score": 150}
                    )
                )
        self.assertEqual(self.account()["last_stats"]["score"], 100)
        self.assertNotIn("pending_reports", self.account())
        self.stats.bot.fetch_user.assert_not_awaited()

    async def test_cancellation_after_commit_leaves_deliverable_report(self):
        committed = asyncio.Event()

        async def widget(*args):
            committed.set()
            await asyncio.Event().wait()

        self.stats._update_widget_for_user.side_effect = widget
        task = asyncio.create_task(
            self.stats._deliver_account_stats(self.account(), {"score": 150})
        )
        await asyncio.wait_for(committed.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.account()["last_stats"]["score"], 150)
        self.assertEqual(
            self.account()["pending_reports"][0]["pending_users"], ["1", "2"]
        )
        await self.stats.retry_pending_reports()
        self.assertEqual(self.account()["pending_reports"], [])

    async def test_unsubscribed_recipient_is_not_sent_old_reports(self):
        self.users[2].send.side_effect = RuntimeError("outage")
        with self.assertLogs("commands.stats_features.delivery", level="ERROR"):
            await self.stats._deliver_account_stats(self.account(), {"score": 150})
        self.stats.accounts_manager.remove_user_from_account("Player", 2)
        await self.stats.retry_pending_reports()
        self.assertEqual(self.users[2].send.await_count, 1)
        self.assertEqual(self.account()["pending_reports"], [])

    async def test_concurrent_delivery_serializes_baseline_updates(self):
        await asyncio.gather(
            self.stats._deliver_account_stats(self.account(), {"score": 150}),
            self.stats._deliver_account_stats(self.account(), {"score": 180}),
        )
        self.assertEqual(self.account()["last_stats"]["score"], 180)
        self.assertEqual(self.users[1].send.await_count, 2)
        self.assertEqual(self.account()["pending_reports"], [])
