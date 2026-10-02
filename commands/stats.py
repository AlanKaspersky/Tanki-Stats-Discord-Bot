"""Discord extension entry point; features live in stats_features."""

import asyncio
import logging
from pathlib import Path

import aiohttp
from discord.ext import commands

from proxy.bootstrap import ProxyBootstrap
from utils.accounts_manager import AccountsManager
from .stats_features.accounts import AccountCommandsMixin
from .stats_features.admin import AdminCommandsMixin
from .stats_features.collection import CollectionMixin
from .stats_features.delivery import DeliveryMixin
from .stats_features.localization import LocalizationMixin
from .stats_features.proxy_tasks import ProxyTasksMixin
from .stats_features.reports import ReportsMixin
from .stats_features.views import ViewCommandsMixin
from .stats_features.widget import WidgetMixin

logger = logging.getLogger(__name__)


class Stats(
    AccountCommandsMixin,
    AdminCommandsMixin,
    CollectionMixin,
    DeliveryMixin,
    LocalizationMixin,
    ProxyTasksMixin,
    ReportsMixin,
    ViewCommandsMixin,
    WidgetMixin,
    commands.Cog,
):
    def __init__(self, bot):
        self.bot = bot
        self.base_dir = Path(__file__).resolve().parent.parent
        self.accounts_manager = AccountsManager(str(self.base_dir / "accounts"))
        self.proxy_bootstrap = None
        self.proxy_session = None
        self._pool_recovery_lock = asyncio.Lock()
        self._collection_lock = asyncio.Lock()
        self._account_locks = {}
        self._registration_lock = asyncio.Lock()
        self._token_locks = {}

    def _account_lock(self, nickname):
        return self._account_locks.setdefault(nickname.casefold(), asyncio.Lock())

    async def cog_load(self):
        self.proxy_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self.proxy_bootstrap = ProxyBootstrap(self.base_dir)
        try:
            await self.proxy_bootstrap.start(self.proxy_session)
        except asyncio.CancelledError:
            await self.cog_unload()
            raise
        except Exception:
            logger.exception(
                "Ошибка запуска прокси; фоновые задачи попробуют восстановить пул"
            )
            await self.proxy_bootstrap.stop()
        self.daily_stats.start()
        self.auto_proxy_check.start()
        self.retry_pending_reports.start()
        logger.info("Stats загружен; ежедневный сбор в 02:00 UTC (05:00 МСК)")

    async def cog_unload(self):
        loops = (self.daily_stats, self.auto_proxy_check, self.retry_pending_reports)
        running = [loop.get_task() for loop in loops if loop.get_task() is not None]
        for loop in loops:
            loop.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        try:
            if self.proxy_bootstrap:
                await self.proxy_bootstrap.stop()
        finally:
            if self.proxy_session:
                await self.proxy_session.close()
        logger.info("Stats: фоновые задачи, сессия и прокси остановлены")


async def setup(bot):
    if bot.tree.translator is None:
        from utils.discord_translations import StatsTranslator

        await bot.tree.set_translator(StatsTranslator())
    await bot.add_cog(Stats(bot))
