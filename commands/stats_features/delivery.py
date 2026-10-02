"""Persist reports before sending, retry only recipients who have not received them."""

from datetime import datetime, timezone
import logging
from uuid import uuid4

import discord
from discord.ext import tasks

logger = logging.getLogger(__name__)


class DeliveryMixin:
    async def _deliver_account_stats(
        self, account: dict, stats: dict, *, recipients=None
    ) -> bool:
        nickname = account["nickname"]
        async with self._account_lock(nickname):
            current_account = self.accounts_manager.load_account(nickname)
            if current_account is None:
                return False
            tracked_by = current_account.get("tracked_by", {})
            pending_users = (
                list(tracked_by)
                if recipients is None
                else [str(uid) for uid in recipients if str(uid) in tracked_by]
            )
            diff_stats = self.calculate_difference(
                stats, current_account.get("last_stats")
            )
            report = (
                {
                    "id": uuid4().hex,
                    "nickname": nickname,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "stats": stats,
                    "diff_stats": diff_stats,
                    "pending_users": pending_users,
                }
                if pending_users
                else None
            )
            if not self.accounts_manager.update_account_stats(
                nickname, stats, pending_report=report
            ):
                return False
            for user_id in pending_users:
                try:
                    await self._update_widget_for_user(int(user_id), stats, nickname)
                except Exception:
                    logger.exception("Не удалось обновить виджет для %s", user_id)
            await self._flush_account_reports(nickname)
            return True

    async def _flush_account_reports(self, nickname: str) -> int:
        """Called with the account lock held. Do not resend acknowledged recipients."""
        sent = 0
        blocked_users = set()
        for report in self.accounts_manager.get_pending_reports(nickname):
            for user_id in list(report["pending_users"]):
                if user_id in blocked_users:
                    continue
                account = self.accounts_manager.load_account(nickname)
                if account is None:
                    return sent
                if user_id not in account.get("tracked_by", {}):
                    if not self.accounts_manager.acknowledge_report(
                        nickname, report["id"], user_id
                    ):
                        blocked_users.add(user_id)
                    continue
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    language = self.accounts_manager.get_user_language(int(user_id))
                    embed = self.create_embed(
                        report["diff_stats"], report["stats"], language=language
                    )
                    embed.timestamp = datetime.fromisoformat(report["created_at"])
                    embed.title = (
                        f"📊 Statistics: {report['nickname']}"
                        if self._is_english(language)
                        else f"📊 Статистика {report['nickname']}"
                    )
                    await user.send(embed=embed)
                except discord.Forbidden:
                    logger.warning("Пользователь %s закрыл ЛС; отчёт сохранён", user_id)
                    blocked_users.add(user_id)
                except Exception:
                    logger.exception(
                        "Отчёт для %s сохранён для повторной отправки", user_id
                    )
                    blocked_users.add(user_id)
                else:
                    sent += 1
                    if not self.accounts_manager.acknowledge_report(
                        nickname, report["id"], user_id
                    ):
                        logger.error(
                            "Отчёт отправлен, но подтверждение для %s не сохранено",
                            user_id,
                        )
                        blocked_users.add(user_id)
        return sent

    @tasks.loop(minutes=5)
    async def retry_pending_reports(self):
        for account in self.accounts_manager.get_all_accounts():
            nickname = account["nickname"]
            if not account.get("pending_reports"):
                continue
            try:
                async with self._account_lock(nickname):
                    await self._flush_account_reports(nickname)
            except Exception:
                logger.exception("Ошибка повторной доставки %s", nickname)

    @retry_pending_reports.before_loop
    async def before_retry_pending_reports(self):
        await self.bot.wait_until_ready()
