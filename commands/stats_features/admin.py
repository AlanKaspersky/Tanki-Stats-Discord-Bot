import discord
from discord.ext import commands
import aiohttp
import logging
import asyncio


from .constants import ADMIN_IDS

logger = logging.getLogger(__name__)


class AdminCommandsMixin:
    @commands.command(name="proxycheck", hidden=True)
    async def proxycheck_admin(self, ctx):
        """Проверяет прокси из sources, оставляет только рабочие."""
        if ctx.author.id not in ADMIN_IDS:
            await ctx.send("❌ Неизвестная команда")
            return

        if not self.proxy_bootstrap or not self.proxy_bootstrap.enabled:
            await ctx.send("❌ Прокси-система не запущена")
            return

        status_msg = await ctx.send(
            "🔄 Проверка прокси: загрузка sources и запуск xray..."
        )
        last_edit_at = 0.0

        async def progress(checked: int, total: int, working: int, failed: int) -> None:
            nonlocal last_edit_at
            now = asyncio.get_running_loop().time()
            if checked < total and now - last_edit_at < 3:
                return
            last_edit_at = now
            try:
                await status_msg.edit(
                    content=(
                        f"🔄 Проверка прокси: **{checked}/{total}** | "
                        f"✅ {working} | ❌ {failed}"
                    )
                )
            except discord.HTTPException:
                pass

        session = self.proxy_session
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        try:
            report = await self.proxy_bootstrap.filter_working_proxies_from_sources(
                session,
                progress_callback=progress,
                rewrite_sources=True,
                replacement_lock=self._pool_recovery_lock,
            )
            await status_msg.edit(
                content=(
                    f"✅ Проверка завершена: **{report.working}/{report.total}** рабочих, "
                    f"**{report.failed}** отсеяно.\n"
                    f"Обновлены `{self.proxy_bootstrap.proxies_json_path.name}` и "
                    f"`{self.proxy_bootstrap.sources_path.name}`."
                )
            )
        except Exception as e:
            logger.error("Ошибка proxycheck: %s", e, exc_info=True)
            await status_msg.edit(content=f"❌ Ошибка проверки прокси: {str(e)[:500]}")
        finally:
            if close_session:
                await session.close()

    @commands.command(name="statscheck", hidden=True)
    async def stats_check_dry_run(self, ctx):
        """Dry-run всех аккаунтов: как ежедневный сбор, но только логи (без DM и без записи в JSON)."""
        if ctx.author.id not in ADMIN_IDS:
            await ctx.send("❌ Неизвестная команда")
            return

        await ctx.send(
            "🧪 Запущена тестовая проверка аккаунтов "
            "(только логи, без сохранения и без уведомлений пользователям)…"
        )

        try:
            processed, errors, failed = await self._run_daily_collection(dry_run=True)
            failed_names = ", ".join(acc.get("nickname", "?") for acc in failed[:5])
            suffix = f" Не удалось: {failed_names}" if failed_names else ""
            if len(failed) > 5:
                suffix += f" (+{len(failed) - 5})"
            await ctx.send(
                f"🧪 Тестовая проверка завершена: ✅ **{processed}** | ❌ **{errors}**. "
                f"Подробности в логах.{suffix}"
            )
        except Exception as e:
            logger.error("Ошибка statscheck: %s", e, exc_info=True)
            await ctx.send(f"❌ Ошибка: {str(e)[:100]}")

    @commands.command(name="stats_force", hidden=True)
    async def force_stats_admin(self, ctx, nickname: str):
        async with self._collection_lock:
            await self._force_stats(ctx, nickname)

    async def _force_stats(self, ctx, nickname: str):
        """Принудительный сбор статистики для аккаунта"""

        if ctx.author.id not in ADMIN_IDS:
            await ctx.send("❌ Неизвестная команда")
            return

        await ctx.send(f"🔄 Сбор статистики для **{nickname}**...")

        try:
            all_accounts = self.accounts_manager.get_all_accounts()
            target_account = None

            for acc in all_accounts:
                if acc.get("nickname", "").lower() == nickname.lower():
                    target_account = acc
                    break

            if not target_account:
                await ctx.send(f"❌ Аккаунт **{nickname}** не найден в базе!")
                return

            api_url = target_account.get("api_url")
            if not api_url:
                await ctx.send(f"❌ Нет API URL для **{nickname}**")
                return

            current_stats = await self.fetch_tanki_stats(api_url)

            if not current_stats:
                await ctx.send(f"❌ Не удалось получить статистику для **{nickname}**")
                return

            success = await self._deliver_account_stats(target_account, current_stats)
            if not success:
                await ctx.send(f"❌ Не удалось сохранить статистику для **{nickname}**")
                return
            pending = sum(
                len(report["pending_users"])
                for report in self.accounts_manager.get_pending_reports(nickname)
            )
            await ctx.send(
                f"✅ Статистика для **{nickname}** обновлена.\n"
                f"📨 Неотправленных сообщений в очереди: **{pending}** (повтор каждые 5 минут)."
            )

        except Exception as e:
            logger.error(f"Ошибка в force_stats_admin: {e}", exc_info=True)
            await ctx.send(f"❌ Ошибка: {str(e)[:100]}")

    @commands.command(name="blacklist_add", aliases=["bl_add", "ban"], hidden=True)
    async def blacklist_add_prefix(self, ctx, user_id_str: str):
        """Добавить пользователя в черный список по ID (Только для админов)"""
        if ctx.author.id not in ADMIN_IDS:
            return

        try:
            target_id = int(user_id_str)
        except ValueError:
            await ctx.send(
                "❌ Неверный формат ID. Пример: `!blacklist_add 570644931841097728`"
            )
            return

        success = self.accounts_manager.add_to_blacklist(target_id)
        if success:
            await ctx.send(
                f"✅ Пользователь с ID `{target_id}` добавлен в черный список. Бот больше не будет реагировать на его сообщения и команды."
            )
        else:
            await ctx.send(
                f"ℹ️ Пользователь с ID `{target_id}` уже находится в черном списке."
            )

    @commands.command(name="blacklist_remove", aliases=["bl_rm", "unban"], hidden=True)
    async def blacklist_remove_prefix(self, ctx, user_id_str: str):
        """Удалить пользователя из черного списка по ID (Только для админов)"""
        if ctx.author.id not in ADMIN_IDS:
            return

        try:
            target_id = int(user_id_str)
        except ValueError:
            await ctx.send(
                "❌ Неверный формат ID. Пример: `!blacklist_remove 570644931841097728`"
            )
            return

        success = self.accounts_manager.remove_from_blacklist(target_id)
        if success:
            await ctx.send(
                f"✅ Пользователь с ID `{target_id}` успешно удален из черного списка."
            )
        else:
            await ctx.send(
                f"❌ Пользователь с ID `{target_id}` не найден в черном списке."
            )

    @commands.command(name="stats_force_all", hidden=True)
    async def force_all_stats_admin(self, ctx):
        """Принудительно проверить все аккаунты и разослать статистику подписчикам."""
        if ctx.author.id not in ADMIN_IDS:
            await ctx.send("❌ Неизвестная команда")
            return

        await ctx.send(
            "🔄 Запущена принудительная проверка всех аккаунтов и рассылка статистики…"
        )
        try:
            processed, errors, failed = await self._run_daily_collection(dry_run=False)
            failed_names = ", ".join(acc.get("nickname", "?") for acc in failed[:10])
            suffix = (
                f"\n❌ Не удалось проверить: {failed_names}" if failed_names else ""
            )
            if len(failed) > 10:
                suffix += f" и ещё {len(failed) - 10}"
            await ctx.send(
                f"✅ Принудительная проверка завершена. Успешно: **{processed}**; "
                f"ошибок: **{errors}**.{suffix}"
            )
        except Exception as e:
            logger.error("Ошибка stats_force_all: %s", e, exc_info=True)
            await ctx.send(f"❌ Ошибка принудительной проверки: {str(e)[:200]}")
