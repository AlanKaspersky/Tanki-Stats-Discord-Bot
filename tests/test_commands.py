import asyncio
import importlib
import logging
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from commands.stats import Stats
from tests.helpers import make_stats, make_interaction


class CommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stats = make_stats(self.tmp.name)

    async def test_all_command_signatures_preserved(self):
        slash = {
            c.name: [p.name for p in c.parameters] for c in Stats.__cog_app_commands__
        }
        self.assertEqual(
            slash,
            {
                "add": ["nickname", "account_name"],
                "remove": ["account_name"],
                "language": ["language"],
                "list": [],
                "help": [],
                "info": [],
                "widget_setup": [],
                "widget_token": ["code"],
                "widget_refresh": ["account_name", "provider_user_id"],
            },
        )
        self.assertEqual(
            {c.name for c in Stats.__cog_commands__},
            {
                "proxycheck",
                "statscheck",
                "stats_force",
                "blacklist_add",
                "blacklist_remove",
                "stats_force_all",
            },
        )
        self.assertEqual(
            Stats.__cog_listeners__, [("on_interaction", "on_interaction")]
        )

    async def test_widget_oauth_uses_current_application_after_token_change(self):
        from urllib.parse import parse_qs, urlsplit

        self.stats.bot.application_id = 987654321
        interaction = make_interaction()
        await self.stats.widget_setup.callback(self.stats, interaction)
        view = interaction.response.send_message.call_args.kwargs["view"]
        query = parse_qs(urlsplit(view.children[0].url).query)
        self.assertEqual(query["client_id"], ["987654321"])

    async def test_add_uses_one_fetch_and_stores_initial_baseline(self):
        self.stats._fetch_tanki_stats_result = AsyncMock(
            return_value=({"name": "Player", "score": 123}, None)
        )
        interaction = make_interaction()
        await self.stats.stats_add.callback(self.stats, interaction, "Player", "Main")
        interaction.response.defer.assert_awaited_once()
        self.stats._fetch_tanki_stats_result.assert_awaited_once()
        self.assertEqual(
            self.stats.accounts_manager.get_account_stats("Player")["score"], 123
        )
        self.assertEqual(len(self.stats.accounts_manager.get_all_accounts()), 1)

    async def test_concurrent_add_respects_three_account_limit(self):
        async def fetch(url):
            await asyncio.sleep(0)
            return {"score": 1}, None

        self.stats._fetch_tanki_stats_result = AsyncMock(side_effect=fetch)
        await asyncio.gather(
            *[
                self.stats.stats_add.callback(
                    self.stats, make_interaction(), f"Player{i}", f"Account{i}"
                )
                for i in range(4)
            ]
        )
        self.assertEqual(len(self.stats.accounts_manager.get_user_accounts(1)), 3)
        self.assertEqual(self.stats._fetch_tanki_stats_result.await_count, 3)

    async def test_existing_account_keeps_shared_baseline_and_skips_fetch(self):
        manager = self.stats.accounts_manager
        manager.add_user_to_account(
            "Player", "url", 2, "Main", initial_stats={"score": 123}
        )
        self.stats._fetch_tanki_stats_result = AsyncMock()
        await self.stats.stats_add.callback(
            self.stats, make_interaction(1), "PLAYER", "Other"
        )
        self.stats._fetch_tanki_stats_result.assert_not_awaited()
        self.assertEqual(manager.get_account_stats("Player")["score"], 123)
        self.assertEqual(len(manager.load_account("Player")["tracked_by"]), 2)

    async def test_429_does_not_claim_player_is_missing(self):
        self.stats._fetch_tanki_stats_result = AsyncMock(
            return_value=(None, "HTTP 429")
        )
        interaction = make_interaction()
        await self.stats.stats_add.callback(self.stats, interaction, "Player")
        message = interaction.followup.send.call_args.args[0]
        self.assertIn("Попробуйте позже", message)
        self.assertEqual(self.stats.accounts_manager.get_all_accounts(), [])

    async def test_load_unload_reload_registers_once_and_stops_every_loop(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        with patch.dict("os.environ", {"XRAY_ENABLED": "false"}):
            async with bot:
                await bot.load_extension("commands.stats")
                old = bot.get_cog("Stats")
                self.assertEqual(len(bot.tree.get_commands()), 9)
                session = old.proxy_session
                await bot.reload_extension("commands.stats")
                self.assertTrue(session.closed)
                for loop in [
                    old.daily_stats,
                    old.auto_proxy_check,
                    old.retry_pending_reports,
                ]:
                    self.assertTrue(loop.get_task().done())
                self.assertEqual(len(bot.tree.get_commands()), 9)
                current = bot.get_cog("Stats")
                await bot.unload_extension("commands.stats")
                self.assertTrue(current.proxy_session.closed)
                self.assertEqual(bot.tree.get_commands(), [])

    async def test_slash_blacklist_check_is_actually_bound_to_tree(self):
        with (
            patch("dotenv.load_dotenv"),
            patch("logging.basicConfig"),
            patch(
                "logging.handlers.RotatingFileHandler",
                return_value=logging.NullHandler(),
            ),
        ):
            main = importlib.import_module("bot")
        with patch.object(main, "accounts_manager", self.stats.accounts_manager):
            self.stats.accounts_manager.add_to_blacklist(1)
            denied = make_interaction(1)
            self.assertFalse(await main.bot.tree.interaction_check(denied))
            denied.response.send_message.assert_awaited_once()
            self.assertTrue(await main.bot.tree.interaction_check(make_interaction(2)))
        await main.bot.close()

    async def test_failed_start_allows_background_proxy_recovery(self):
        failed = Mock(
            start=AsyncMock(side_effect=RuntimeError("invalid cache")), stop=AsyncMock()
        )
        replacement = Mock(stop=AsyncMock())
        loops = (
            self.stats.daily_stats,
            self.stats.auto_proxy_check,
            self.stats.retry_pending_reports,
        )
        with patch("commands.stats.ProxyBootstrap", side_effect=[failed, replacement]):
            with (
                patch.object(loops[0], "start"),
                patch.object(loops[1], "start"),
                patch.object(loops[2], "start"),
            ):
                try:
                    with self.assertLogs("commands.stats", level="ERROR"):
                        await self.stats.cog_load()
                    self.assertIs(self.stats.proxy_bootstrap, replacement)
                    failed.stop.assert_awaited_once()
                finally:
                    await self.stats.cog_unload()
        replacement.stop.assert_awaited_once()

    async def test_dry_run_does_not_save_or_send(self):
        self.stats.accounts_manager.add_user_to_account(
            "Player", "url", 1, "Main", initial_stats={"score": 1}
        )
        original = self.stats.accounts_manager.load_account("Player")
        self.stats.proxy_session = SimpleNamespace()
        with patch(
            "commands.stats_features.collection.fetch_tanki_stats_via_proxy",
            AsyncMock(return_value=({"score": 2}, None)),
        ):
            processed, errors, failed = await self.stats._run_daily_collection(
                dry_run=True
            )
        self.assertEqual((processed, errors, failed), (1, 0, []))
        self.assertEqual(self.stats.accounts_manager.load_account("Player"), original)
        self.stats.bot.fetch_user.assert_not_awaited()

    async def test_proxy_recovery_rounds_are_bounded(self):
        self.stats.accounts_manager.add_user_to_account("Player", "url", 1, "Main")
        self.stats._process_daily_account = AsyncMock(
            return_value=(False, "proxy pool exhausted", None)
        )
        self.stats._recover_proxy_pool = AsyncMock(return_value=True)
        self.stats.notify_users_of_failure = AsyncMock()
        with patch.dict("os.environ", {"DAILY_STATS_MAX_RECOVERIES": "2"}):
            with self.assertLogs(level="WARNING"):
                result = await asyncio.wait_for(self.stats._run_daily_collection(), 1)
        self.assertEqual(result[1], 1)
        self.assertEqual(self.stats._recover_proxy_pool.await_count, 2)

    async def test_temporary_oauth_failure_keeps_binding(self):
        manager = self.stats.accounts_manager
        manager.save_user_tokens(
            1, "old", "refresh", expires_in=-1, account_nickname="Player"
        )
        manager.bind_user_token(1, "Player", "identity")
        original = manager.get_user_token_simple(1)
        self.stats._update_widget_for_user = Stats._update_widget_for_user.__get__(
            self.stats
        )
        self.stats._refresh_access_token = AsyncMock(return_value=None)
        with self.assertLogs("commands.stats_features.widget", level="WARNING"):
            await self.stats._update_widget_for_user(1, {"score": 1}, "Player")
        self.assertEqual(manager.get_user_token_simple(1), original)
