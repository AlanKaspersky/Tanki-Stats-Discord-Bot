from discord.ext import tasks
import aiohttp
import logging
import math
import os


from .constants import ADMIN_IDS

logger = logging.getLogger(__name__)


def proxy_check_interval_hours() -> float:
    interval = float(os.getenv("PROXY_CHECK_INTERVAL_HOURS", "6"))
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("PROXY_CHECK_INTERVAL_HOURS must be a positive finite number")
    return interval


class ProxyTasksMixin:
    @tasks.loop(hours=6.0)
    async def auto_proxy_check(self):
        """Обновляет рабочий пул из свежих ответов подписок."""
        interval = self.auto_proxy_check.hours
        logger.info(
            "⏳ Запуск автоматической проверки прокси (интервал %g ч)...", interval
        )
        await self.bot.wait_until_ready()
        if self.proxy_bootstrap is not None and not self.proxy_bootstrap.enabled:
            return

        try:
            if not self.proxy_bootstrap:
                from proxy.bootstrap import ProxyBootstrap

                self.proxy_bootstrap = ProxyBootstrap(base_dir=self.base_dir)

            logger.info(
                "📡 Запускаю фильтрацию и проверку связи с API для всех прокси..."
            )
            async with aiohttp.ClientSession() as session:
                report = await self.proxy_bootstrap.filter_working_proxies_from_sources(
                    session=session,
                    rewrite_sources=False,
                    replacement_lock=self._pool_recovery_lock,
                )

            total_working = report.working if report else 0
            msg = (
                f"🔄 **Автоматическое обновление прокси (каждые {interval:g} ч):**\n"
                f"✅ Найдено рабочих прокси: **{total_working}**.\n"
                f"Проверено: **{report.total}**, ошибок: **{report.failed}**, "
                f"не проверено: **{report.unchecked}**."
            )
            logger.info(
                f"✅ Авто-проверка завершена. Реально живых прокси: {total_working}"
            )

            if total_working < 2:
                logger.error("❌ Критически мало живых прокси после полной проверки!")
                await self._send_admin_notification(
                    f"🚨 **Критическая ситуация:** После полной проверки найдено всего прокси: **{total_working}**! Проверь файлы подписок."
                )
            else:
                await self._send_admin_notification(msg)

        except Exception as e:
            logger.error(
                f"❌ Ошибка в автоматическом таске auto_proxy_check: {e}", exc_info=True
            )
            try:
                await self._send_admin_notification(
                    f"❌ **Ошибка авто-проверки прокси:** {str(e)[:100]}"
                )
            except Exception:
                pass

    async def _send_admin_notification(self, text: str):
        """Вспомогательный метод для отправки уведомлений администраторам бота"""
        for admin_id in ADMIN_IDS:
            try:
                user = await self.bot.fetch_user(admin_id)
                if user:
                    await user.send(text)
            except Exception as e:
                logger.error(
                    f"Не удалось отправить пуш-уведомление админу {admin_id}: {e}"
                )

    async def _notify_admins_proxy_recovery(self, reason: str) -> None:
        text = (
            "⚠️ **Прокси-пул исчерпан**\n\n"
            f"{reason}\n\n"
            "Запускаю внеплановую проверку прокси (`!proxycheck`)…"
        )
        for admin_id in ADMIN_IDS:
            try:
                admin = await self.bot.fetch_user(admin_id)
                if admin:
                    await admin.send(text)
            except Exception as e:
                logger.error("Не удалось уведомить админа %s: %s", admin_id, e)

    async def _recover_proxy_pool(self, reason: str) -> bool:
        if (
            not self.proxy_bootstrap
            or not self.proxy_bootstrap.enabled
            or self.proxy_session is None
        ):
            return False

        await self._notify_admins_proxy_recovery(reason)
        try:
            report = await self.proxy_bootstrap.filter_working_proxies_from_sources(
                self.proxy_session,
                rewrite_sources=False,
                replacement_lock=self._pool_recovery_lock,
            )
            logger.info(
                "Emergency proxy check completed: %d/%d working",
                report.working,
                report.total,
            )
            return report.working > 0
        except Exception as e:
            logger.error("Emergency proxy check failed: %s", e, exc_info=True)
            return False
