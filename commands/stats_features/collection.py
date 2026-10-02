import discord
from discord.ext import tasks
import aiohttp
import logging
import asyncio
from datetime import time
from typing import Optional, List
from utils.tanki_client import fetch_tanki_stats as fetch_tanki_stats_via_proxy
from utils.stats_collector import collect_daily_stats_parallel, daily_stats_settings
import os


logger = logging.getLogger(__name__)


class CollectionMixin:
    def _proxy_pool(self):
        if self.proxy_bootstrap and self.proxy_bootstrap.pool:
            return self.proxy_bootstrap.pool
        return None

    def _log_dry_run_stats(self, nickname: str, stats: dict) -> None:
        logger.info(
            "🧪 [dry-run] ✅ %s: score=%s kills=%s deaths=%s crystals=%s golds=%s",
            nickname,
            stats.get("score", "?"),
            stats.get("kills", "?"),
            stats.get("deaths", "?"),
            stats.get("earnedCrystals", "?"),
            stats.get("caughtGolds", "?"),
        )

    async def _wait_before_account_retry(self, failure_reason: Optional[str]) -> None:
        pool = self._proxy_pool()
        _, _, retry_delay, _ = daily_stats_settings()
        if pool is not None:
            max_wait = float(os.getenv("DAILY_STATS_RETRY_MAX_WAIT", "65"))
            if (
                "cooldown" in (failure_reason or "").lower()
                or pool.cooldown_count == pool.size
            ):
                await pool.wait_until_available(max_wait=max_wait)
            elif pool.cooldown_count > pool.size * 0.8:
                await pool.wait_until_available(max_wait=min(max_wait, 30.0))
        await asyncio.sleep(retry_delay)

    async def _process_daily_account(
        self,
        account: dict,
        *,
        dry_run: bool = False,
    ) -> tuple[bool, Optional[str], Optional[dict]]:
        nickname = account.get("nickname", "Unknown")
        session = self.proxy_session or aiohttp.ClientSession()
        close_session = self.proxy_session is None

        try:
            stats, failure_reason = await fetch_tanki_stats_via_proxy(
                session,
                account["api_url"],
                self._proxy_pool(),
            )
            if not stats:
                return False, failure_reason or "неизвестная ошибка", None

            if dry_run:
                return True, None, stats

            logger.info("✅ Получена статистика для %s", nickname)
            delivered = await self._deliver_account_stats(account, stats)
            if not delivered:
                return False, None, None
            return True, None, stats
        finally:
            if close_session:
                await session.close()
            pool = self._proxy_pool()
            if pool is not None:
                await pool.cleanup_task_binding()

    async def _run_daily_collection(
        self, *, dry_run: bool = False
    ) -> tuple[int, int, List[dict]]:
        async with self._collection_lock:
            return await self._collect_accounts(dry_run=dry_run)

    async def _collect_accounts(
        self, *, dry_run: bool = False
    ) -> tuple[int, int, List[dict]]:
        log_prefix = "🧪 [dry-run] " if dry_run else ""
        logger.info("%sЗапуск проверки статистики", log_prefix.rstrip())

        accounts = self.accounts_manager.get_all_accounts()
        logger.info(
            "%s📊 Найдено аккаунтов для проверки: %d", log_prefix, len(accounts)
        )

        if not accounts:
            logger.info("%sНет аккаунтов для проверки", log_prefix)
            return 0, 0, []

        pending_accounts = list(accounts)
        total_processed = 0
        failed_accounts: List[dict] = []
        recoveries = 0
        max_recoveries = max(0, int(os.getenv("DAILY_STATS_MAX_RECOVERIES", "2")))

        while pending_accounts:

            async def process_one(account: dict, *, _dry_run: bool = dry_run):
                return await self._process_daily_account(account, dry_run=_dry_run)

            async with self._pool_recovery_lock:
                (
                    processed,
                    failed_accounts,
                    pool_exhausted,
                    elapsed,
                ) = await collect_daily_stats_parallel(
                    pending_accounts,
                    process_one,
                    dry_run=dry_run,
                    wait_before_retry=self._wait_before_account_retry,
                    log_dry_run_stats=self._log_dry_run_stats,
                )
            total_processed += processed
            logger.info(
                "%sРаунд сбора: %.2fs, обработано %d, ошибок %d",
                log_prefix,
                elapsed,
                processed,
                len(failed_accounts),
            )

            if not pool_exhausted or not failed_accounts:
                break

            if dry_run:
                break

            if recoveries >= max_recoveries:
                logger.error(
                    "Достигнут лимит восстановления прокси (%d)", max_recoveries
                )
                break
            recoveries += 1

            recovered = await self._recover_proxy_pool(
                f"Все прокси в cooldown во время ежедневного сбора ({len(failed_accounts)} аккаунтов)."
            )
            if not recovered:
                break

            pending_accounts = list(failed_accounts)
            failed_accounts = []
            logger.info(
                "Повторный сбор после восстановления прокси: %d аккаунтов",
                len(pending_accounts),
            )

        errors = len(failed_accounts)

        if failed_accounts and not dry_run:
            for failed_account in failed_accounts:
                nickname = failed_account.get("nickname", "Unknown")
                await self.notify_users_of_failure(failed_account, nickname)
        elif failed_accounts and dry_run:
            for failed_account in failed_accounts:
                nickname = failed_account.get("nickname", "Unknown")
                logger.error(
                    "%s❌ %s: проверка не удалась (не повторяемая ошибка)",
                    log_prefix,
                    nickname,
                )

        logger.info(
            "%s🏁 Проверка завершена. Обработано: %d, Ошибок: %d",
            log_prefix,
            total_processed,
            errors,
        )
        if failed_accounts and not dry_run:
            logger.info(
                "⚠️ Уведомления отправлены для %d недоступных аккаунтов",
                len(failed_accounts),
            )

        return total_processed, errors, failed_accounts

    @tasks.loop(time=time(hour=2, minute=0, second=0))
    async def daily_stats(self):
        """Проверяет все аккаунты и отправляет статистику всем пользователям"""
        logger.info("🚀 Запуск ежедневной проверки статистики")

        try:
            await self._run_daily_collection(dry_run=False)
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в daily_stats: {e}", exc_info=True)

    @daily_stats.before_loop
    async def before_daily_stats(self):
        """Ожидает готовности бота перед запуском задачи"""
        await self.bot.wait_until_ready()
        logger.info("Бот готов, ежедневная задача начнется в 2:00 UTC")

    async def fetch_tanki_stats(self, api_url: str):
        stats, _ = await self._fetch_tanki_stats_result(api_url)
        return stats

    async def _fetch_tanki_stats_result(self, api_url: str):
        """Получает актуальную статистику с API TankiOnline с авторотацией прокси."""
        session = self.proxy_session or aiohttp.ClientSession()
        close_session = self.proxy_session is None
        try:
            async with self._pool_recovery_lock:
                return await fetch_tanki_stats_via_proxy(
                    session,
                    api_url,
                    self._proxy_pool(),
                )
        finally:
            pool = self._proxy_pool()
            if pool is not None:
                await pool.cleanup_task_binding()
            if close_session:
                await session.close()

    def load_previous_stats(self, user_id, account_name):
        """Загружает предыдущую статистику для конкретного аккаунта (для совместимости с v1)"""
        user_accounts = self.accounts_manager.get_user_accounts(int(user_id))
        for acc_name, acc_data in user_accounts.items():
            if acc_name == account_name:
                nickname = acc_data.get("nickname")
                if nickname:
                    return self.accounts_manager.get_account_stats(nickname)
        return None

    def save_current_stats(self, user_id, account_name, stats):
        """Сохраняет текущую статистику для конкретного аккаунта (для совместимости с v1)"""
        user_accounts = self.accounts_manager.get_user_accounts(int(user_id))
        for acc_name, acc_data in user_accounts.items():
            if acc_name == account_name:
                nickname = acc_data.get("nickname")
                if nickname:
                    return self.accounts_manager.update_account_stats(nickname, stats)
        return False

    async def update_single_account(
        self, user_id, account_name, account_data, ctx=None
    ):
        """Обновляет статистику для одного аккаунта"""
        try:
            current_stats = await self.fetch_tanki_stats(account_data["api_url"])
            if not current_stats:
                if ctx:
                    await ctx.send(
                        f"❌ Не удалось получить статистику для {account_name}"
                    )
                return

            account = self.accounts_manager.load_account(account_data["nickname"])
            if not account or not await self._deliver_account_stats(
                account, current_stats, recipients=[user_id]
            ):
                if ctx:
                    await ctx.send(
                        f"❌ Не удалось сохранить статистику для {account_name}"
                    )
                return
            pending = self.accounts_manager.get_pending_reports(account["nickname"])
            if any(str(user_id) in report["pending_users"] for report in pending):
                if ctx:
                    await ctx.send(
                        f"📨 Отчёт для **{account_name}** сохранён в очереди доставки"
                    )
                return

            if ctx:
                await ctx.send(f"✅ Статистика для **{account_name}** отправлена в ЛС")

        except discord.Forbidden:
            if ctx:
                await ctx.send(
                    "❌ Не могу отправить сообщение в ЛС. Проверьте настройки приватности!"
                )
        except Exception as e:
            if ctx:
                await ctx.send(f"❌ Ошибка для {account_name}: {e}")

    async def notify_users_of_failure(self, account: dict, nickname: str):
        """Отправляет пользователям уведомление о невозможности получить статистику"""
        tracked_by = account.get("tracked_by", {})

        if not tracked_by:
            return

        sent_count = 0
        for user_id_str, user_data in tracked_by.items():
            try:
                user = await self.bot.fetch_user(int(user_id_str))
                if user:
                    language = self.accounts_manager.get_user_language(int(user_id_str))
                    if self._is_english(language):
                        embed = discord.Embed(
                            title=":warning: Stats temporarily unavailable",
                            description=f"Could not retrieve stats for **{nickname}** after several attempts.",
                            color=0xFF0000,
                            timestamp=discord.utils.utcnow(),
                        )
                        embed.add_field(
                            name=":question: What happened?",
                            value="- Tanki Online API is temporarily unavailable\n"
                            "- Too many requests (429, 502, or 404)\n"
                            "- Connection problems with Tanki Ratings",
                            inline=False,
                        )
                        embed.add_field(
                            name=":bar_chart: When will stats be available?",
                            value="We will try again tomorrow around the Tanki Online server restart. Today's progress is not lost and will be included in the next update.",
                            inline=False,
                        )
                        embed.set_footer(
                            text="❤️‍🩹 Sorry for the inconvenience. — Kaspersky"
                        )
                    else:
                        embed = discord.Embed(
                            title=":warning: Временная недоступность статистики",
                            description=f"Не удалось получить статистику для аккаунта **{nickname}** после нескольких попыток.",
                            color=0xFF0000,
                            timestamp=discord.utils.utcnow(),
                        )
                        embed.add_field(
                            name=":question: Что произошло?",
                            value="- API Tanki Online временно недоступен\n"
                            "- Слишком много запросов (ошибка 429, 502, 404)\n"
                            "- Проблемы с соединением с сайтом Tanki Ratings",
                            inline=False,
                        )
                        embed.add_field(
                            name=":bar_chart: Когда будет статистика?",
                            value="Попробуем завтра также в момент рестарта серверов Танков Онлайн. Не переживайте, статистика за сегодня не будет потеряна — она накопится к завтрашнему дню!",
                            inline=False,
                        )
                        embed.set_footer(
                            text="❤️‍🩹 Приносим извинения за временные неудобства. С уважением, Kaspersky!"
                        )
                    await user.send(embed=embed)
                    sent_count += 1
                    logger.debug(
                        f"✅ Уведомление об ошибке отправлено пользователю {user_id_str}"
                    )
            except Exception as e:
                logger.error(
                    f"❌ Ошибка отправки уведомления пользователю {user_id_str}: {e}"
                )

        logger.info(f"📤 Отправлено {sent_count} уведомлений об ошибке для {nickname}")
