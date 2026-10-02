import discord
from discord import app_commands
import aiohttp
import logging
import asyncio
from datetime import datetime
from typing import Optional
import os
from urllib.parse import urlencode


logger = logging.getLogger(__name__)


class WidgetMixin:
    def _build_widget_payload(self, stats: dict, nickname: str) -> dict:
        """
        Формирует JSON для отправки в Discord API на основе статистики.
        Соответствует структуре wighet.json.
        """
        kills = stats.get("kills", 0)
        deaths = stats.get("deaths", 1)
        kd = round(kills / deaths, 2) if deaths > 0 else 0.0

        score = stats.get("score", 0)
        score_next = stats.get("scoreNext", 0)
        score_display = f"{score:,} / {score_next:,}".replace(",", " ")

        rank_display = self.get_rank_title(score)

        total_time = 0
        for mode in stats.get("modesPlayed", []):
            total_time += mode.get("timePlayed", 0)

        turrets = stats.get("turretsPlayed", [])
        best_turret = (
            max(turrets, key=lambda x: x.get("scoreEarned", 0))
            if turrets
            else {"name": "N/A"}
        )
        hulls = stats.get("hullsPlayed", [])
        best_hull = (
            max(hulls, key=lambda x: x.get("scoreEarned", 0))
            if hulls
            else {"name": "N/A"}
        )

        dynamic = [
            {"type": 1, "name": "nickname", "value": nickname},
            {"type": 1, "name": "rank", "value": rank_display},
            {"type": 1, "name": "score / scoreNext", "value": score_display},
            {"type": 2, "name": "playTime", "value": total_time},
            {
                "type": 1,
                "name": "game",
                "value": "<@$1129504740301086812>",
            },
            {"type": 1, "name": "kills", "value": f"{kills:,}".replace(",", " ")},
            {"type": 1, "name": "deaths", "value": f"{deaths:,}".replace(",", " ")},
            {"type": 1, "name": "kills/deaths", "value": f"{kd:.2f}".replace(".", ",")},
            {"type": 1, "name": "BestTurret", "value": best_turret.get("name", "N/A")},
            {"type": 1, "name": "BestHull", "value": best_hull.get("name", "N/A")},
        ]

        return {"username": nickname, "data": {"dynamic": dynamic}}

    async def _update_widget_for_user(self, user_id: int, stats: dict, nickname: str):
        """Обновляет виджет для конкретного пользователя (без ответа в чат)."""
        token_data = self.accounts_manager.get_user_token_simple(user_id)
        if not token_data:
            return
        bound_nickname = token_data.get("account_nickname")
        if not bound_nickname or bound_nickname.casefold() != nickname.casefold():
            return
        provider_user_id = token_data.get("provider_issued_user_id")
        if not provider_user_id:
            logger.info(
                "Автообновление виджета пропущено для %s: identity ID не привязан",
                user_id,
            )
            return

        refresh_token = token_data.get("refresh_token")
        expires_at_str = token_data.get("expires_at")

        try:
            expires_at = (
                datetime.fromisoformat(expires_at_str)
                if expires_at_str
                else datetime.now()
            )
        except (ValueError, TypeError):
            expires_at = datetime.now()

        if datetime.now() >= expires_at:
            if not refresh_token:
                self.accounts_manager.remove_user_token(user_id)
                logger.info(f"Токен для {user_id} удалён (истёк, нет refresh_token)")
                return
            logger.info(f"Токен для {user_id} истёк, обновляем через refresh_token")
            new_token = await self._refresh_access_token(user_id, refresh_token)
            if not new_token:
                logger.warning(
                    "Не удалось обновить токен для %s; OAuth-привязка сохранена",
                    user_id,
                )
                return

        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            logger.error("BOT_TOKEN не установлен: нельзя обновить профиль Discord")
            return

        payload = self._build_widget_payload(stats, nickname)
        app_id = self.bot.user.id
        from urllib.parse import quote

        url = f"https://discord.com/api/v10/applications/{app_id}/users/{user_id}/identities/{quote(str(provider_user_id), safe='')}/profile"

        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://discord.com, 1.0.0)",
        }

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.patch(url, json=payload, headers=headers) as resp:
                    if resp.status == 401:
                        error_text = await resp.text()
                        logger.error(
                            "Discord rejected widget write for %s: HTTP 401 - %s",
                            user_id,
                            error_text[:500],
                        )
                    elif not 200 <= resp.status < 300:
                        error_text = await resp.text()
                        logger.warning(
                            "Ошибка обновления виджета для %s (%s): HTTP %s - %s",
                            user_id,
                            nickname,
                            resp.status,
                            error_text[:500],
                        )
        except Exception as e:
            logger.error(f"Ошибка фонового обновления виджета для {user_id}: {e}")

    async def _refresh_access_token(
        self, user_id: int, refresh_token: str
    ) -> Optional[str]:
        async with self._token_locks.setdefault(user_id, asyncio.Lock()):
            current = self.accounts_manager.get_user_token_simple(user_id)
            if current:
                try:
                    if datetime.fromisoformat(current["expires_at"]) > datetime.now():
                        return current.get("access_token")
                except (ValueError, TypeError, KeyError):
                    pass
                refresh_token = current.get("refresh_token") or refresh_token
            return await self._refresh_access_token_unlocked(user_id, refresh_token)

    async def _refresh_access_token_unlocked(
        self, user_id: int, refresh_token: str
    ) -> Optional[str]:
        """
        Обновляет access_token через refresh_token.
        Возвращает новый access_token или None, если не удалось.
        """
        client_id = str(self.bot.application_id or self.bot.user.id)
        client_secret = os.getenv("DISCORD_CLIENT_SECRET")
        if not client_secret:
            logger.error("DISCORD_CLIENT_SECRET не установлен в переменных окружения")
            return None

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.post(
                    "https://discord.com/api/oauth2/token", data=data, headers=headers
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"Ошибка обновления токена для {user_id}: {resp.status} - {error_text}"
                        )
                        return None
                    token_data = await resp.json()
                    new_access = token_data.get("access_token")
                    new_refresh = token_data.get("refresh_token", refresh_token)
                    expires_in = token_data.get("expires_in", 3600)
                    if new_access:
                        saved = self.accounts_manager.save_user_tokens(
                            user_id, new_access, new_refresh, expires_in
                        )
                        if not saved:
                            return None
                        logger.info(f"Токен для {user_id} обновлён")
                        return new_access
                    return None
        except Exception as e:
            logger.error(
                f"Ошибка при обновлении токена для {user_id}: {e}", exc_info=True
            )
            return None

    @app_commands.command(
        name="widget_setup", description="Настроить виджет в профиле Discord"
    )
    async def widget_setup(self, interaction: discord.Interaction):
        language = self._language_for_interaction(interaction)
        client_id = str(self.bot.application_id or self.bot.user.id)
        redirect_uri = "https://discord.com"

        auth_url = "https://discord.com/oauth2/authorize?" + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": "openid sdk.social_layer",
                "prompt": "consent",
            }
        )

        button = discord.ui.Button(
            label="Authorize app"
            if self._is_english(language)
            else "Авторизовать приложение",
            style=discord.ButtonStyle.link,
            url=auth_url,
        )
        view = discord.ui.View()
        view.add_item(button)

        await interaction.response.send_message(
            self._text(
                language,
                "### 🔑 Авторизация для виджета\n1. Нажмите кнопку ниже, чтобы авторизовать приложение.\n2. Redirect URI `https://discord.com` должен быть добавлен в OAuth2 приложения в Developer Portal.\n3. После авторизации вы будете перенаправлены на discord.com.\n4. Скопируйте из адресной строки браузера **всё, что идёт после `?code=`** (до первого `&`, если есть).\n5. Отправьте этот код сюда командой `/widget_token <код>`.\n\n-# Код действителен всего несколько минут.",
                "### 🔑 Widget authorization\n1. Click the button below to authorize the app.\n2. `https://discord.com` must be registered as an OAuth2 redirect URI in the Developer Portal.\n3. After authorization, Discord will redirect you to discord.com.\n4. Copy everything after `?code=` in the address bar, up to the first `&` if present.\n5. Submit the code with `/widget_token <code>`.\n\n-# The code expires in a few minutes.",
            ),
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="widget_token",
        description="Сохранить токен доступа для виджета (используйте код из ссылки)",
    )
    @app_commands.describe(
        code="Код, полученный после авторизации (часть ссылки после ?code=)"
    )
    async def widget_token(self, interaction: discord.Interaction, code: str):
        """Обменивает код на access_token и refresh_token и сохраняет их."""
        language = self._language_for_interaction(interaction)
        if len(code) < 10:
            await interaction.response.send_message(
                self._text(
                    language,
                    "❌ Похоже, вы ввели неверный код. Он должен быть длинной строкой.\nУбедитесь, что скопировали именно часть после `?code=`.",
                    "❌ That code looks invalid. Make sure you copied the full value after `?code=`.",
                ),
                ephemeral=True,
            )
            return

        client_id = str(self.bot.application_id or self.bot.user.id)
        redirect_uri = "https://discord.com"
        client_secret = os.getenv("DISCORD_CLIENT_SECRET")
        if not client_secret:
            await interaction.response.send_message(
                self._text(
                    language,
                    "❌ Ошибка конфигурации: не найден CLIENT_SECRET. Сообщите администратору.",
                    "❌ Configuration error: CLIENT_SECRET is missing. Please contact the bot administrator.",
                ),
                ephemeral=True,
            )
            return

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.post(
                    "https://discord.com/api/oauth2/token", data=data, headers=headers
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        await interaction.followup.send(
                            self._text(
                                language,
                                f"❌ Ошибка обмена кода на токены (HTTP {resp.status}):\n```{error_text[:500]}```",
                                f"❌ Could not exchange the code for tokens (HTTP {resp.status}):\n```{error_text[:500]}```",
                            ),
                            ephemeral=True,
                        )
                        return
                    token_data = await resp.json()
        except Exception as e:
            logger.error(f"Ошибка в widget_token: {e}", exc_info=True)
            await interaction.followup.send(
                self._text(
                    language,
                    f"❌ Внутренняя ошибка при обмене кода: {str(e)[:100]}",
                    f"❌ Internal error while exchanging the code: {str(e)[:100]}",
                ),
                ephemeral=True,
            )
            return

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        logger.info(
            "Discord OAuth granted scopes: %s", token_data.get("scope", "<missing>")
        )

        if not access_token:
            await interaction.followup.send(
                self._text(
                    language,
                    "❌ Не удалось получить access_token. Ответ Discord: ",
                    "❌ Discord did not return an access token. Response: ",
                )
                + str(token_data),
                ephemeral=True,
            )
            return

        success = self.accounts_manager.save_user_tokens(
            interaction.user.id, access_token, refresh_token, expires_in
        )
        if success:
            await interaction.followup.send(
                self._text(
                    language,
                    "✅ Токены сохранены. Выполните `/widget_refresh`, чтобы выбрать аккаунт и привязать его к виджету.",
                    "✅ Tokens saved. Run `/widget_refresh` to choose an account and link it to the widget.",
                ),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                self._text(
                    language,
                    "❌ Не удалось сохранить токены. Попробуйте позже.",
                    "❌ Could not save the tokens. Please try again later.",
                ),
                ephemeral=True,
            )

    @app_commands.command(
        name="widget_refresh", description="Обновить виджет актуальной статистикой"
    )
    @app_commands.describe(
        account_name="Название отслеживаемого аккаунта для виджета",
        provider_user_id="ID identity из Discord (если бот не смог определить его сам)",
    )
    async def widget_refresh(
        self,
        interaction: discord.Interaction,
        account_name: str = None,
        provider_user_id: str = None,
    ):
        """Обновляет виджет в профиле пользователя."""
        user_id = interaction.user.id
        await interaction.response.defer(ephemeral=True)
        language = self._language_for_interaction(interaction)

        token_data = self.accounts_manager.get_user_token_simple(user_id)
        if not token_data:
            await interaction.followup.send(
                self._text(
                    language,
                    "❌ Токены не найдены. Выполните `/widget_setup` и сохраните код командой `/widget_token`.",
                    "❌ No tokens found. Run `/widget_setup`, then save the code with `/widget_token`.",
                ),
                ephemeral=True,
            )
            return

        refresh_token = token_data.get("refresh_token")
        expires_at_str = token_data.get("expires_at")

        try:
            expires_at = (
                datetime.fromisoformat(expires_at_str)
                if expires_at_str
                else datetime.now()
            )
        except (ValueError, TypeError):
            expires_at = datetime.now()

        if datetime.now() >= expires_at:
            if not refresh_token:
                self.accounts_manager.remove_user_token(user_id)
                await interaction.followup.send(
                    self._text(
                        language,
                        "❌ Токен истёк, а refresh_token отсутствует. Выполните `/widget_setup` заново.",
                        "❌ The token expired and no refresh token is available. Run `/widget_setup` again.",
                    ),
                    ephemeral=True,
                )
                return

            logger.info(f"Токен для {user_id} истёк, обновляем через refresh_token")
            new_token = await self._refresh_access_token(user_id, refresh_token)
            if not new_token:
                await interaction.followup.send(
                    self._text(
                        language,
                        "❌ Не удалось обновить токен. Возможно, refresh_token устарел. Выполните `/widget_setup` заново.",
                        "❌ Could not refresh the token. It may have expired; run `/widget_setup` again.",
                    ),
                    ephemeral=True,
                )
                return

        accounts = self.accounts_manager.get_user_accounts(user_id)
        if not accounts:
            await interaction.followup.send(
                self._text(
                    language,
                    "❌ У вас нет отслеживаемых аккаунтов. Добавьте аккаунт через `/add`.",
                    "❌ You are not tracking any accounts. Add one with `/add`.",
                ),
                ephemeral=True,
            )
            return

        bound_nickname = token_data.get("account_nickname")
        if account_name:
            selected = next(
                (
                    (name, data)
                    for name, data in accounts.items()
                    if name.casefold() == account_name.casefold()
                    or data.get("original_name", "").casefold()
                    == account_name.casefold()
                ),
                None,
            )
        elif bound_nickname:
            selected = next(
                (
                    (name, data)
                    for name, data in accounts.items()
                    if data["nickname"].casefold() == bound_nickname.casefold()
                ),
                None,
            )
        elif len(accounts) == 1:
            selected = next(iter(accounts.items()))
        else:
            selected = None
        if selected is None:
            names = ", ".join(
                data.get("original_name", name) for name, data in accounts.items()
            )
            await interaction.followup.send(
                self._text(
                    language,
                    f"Укажите аккаунт: `/widget_refresh account_name:<название>`. Доступны: {names}",
                    f"Choose an account with `/widget_refresh account_name:<name>`. Available: {names}",
                ),
                ephemeral=True,
            )
            return
        account_name, account_data = selected
        nickname = account_data["nickname"]

        stats = self.accounts_manager.get_account_stats(nickname)
        if not stats:
            await interaction.followup.send(
                self._text(
                    language,
                    f"❌ Нет сохранённой статистики для аккаунта **{account_name}**. Подождите до ежедневного обновления.",
                    f"❌ No saved stats for **{account_name}** yet. Wait for the next daily update.",
                ),
                ephemeral=True,
            )
            return

        provider_user_id = (
            provider_user_id or token_data.get("provider_issued_user_id") or ""
        ).strip()
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            await interaction.followup.send(
                self._text(
                    language,
                    "❌ На сервере не настроен BOT_TOKEN.",
                    "❌ BOT_TOKEN is not configured on the server.",
                ),
                ephemeral=True,
            )
            return
        app_id = self.bot.user.id
        identities_url = f"https://discord.com/api/v10/users/{user_id}/application-identities/{app_id}"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://discord.com, 1.0.0)",
        }
        if not provider_user_id:
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as session:
                    async with session.get(identities_url, headers=headers) as resp:
                        if resp.status == 200:
                            body = await resp.json()
                            identities = body.get("identities", [])
                            ids = list(
                                dict.fromkeys(
                                    str(item.get("provider_issued_user_id", "")).strip()
                                    for item in identities
                                    if item.get("provider_issued_user_id") is not None
                                )
                            )
                            ids = [value for value in ids if value]
                            if len(ids) == 1:
                                provider_user_id = ids[0]
                            elif len(ids) > 1:
                                shown = "\n".join(f"• `{value}`" for value in ids[:15])
                                await interaction.followup.send(
                                    self._text(
                                        language,
                                        "У приложения найдено несколько Discord identity. Повторите команду и передайте нужный ID в `provider_user_id`.\n",
                                        "Multiple Discord identities were found. Run the command again and pass the right ID as `provider_user_id`.\n",
                                    )
                                    + shown,
                                    ephemeral=True,
                                )
                                return
                        elif resp.status in (401, 403):
                            error_text = await resp.text()
                            logger.info(
                                "Cannot enumerate identities for %s: HTTP %s %s",
                                user_id,
                                resp.status,
                                error_text[:300],
                            )
                        else:
                            error_text = await resp.text()
                            logger.warning(
                                "Identity lookup failed for %s: HTTP %s %s",
                                user_id,
                                resp.status,
                                error_text[:300],
                            )
            except Exception as e:
                logger.warning("Identity lookup failed for %s: %s", user_id, e)

        if not provider_user_id:
            await interaction.followup.send(
                self._text(
                    language,
                    "Не удалось автоматически определить `provider_issued_user_id`. Введите ID identity из ответа Discord или попросите администратора получить список identities. Это отдельный ID, не никнейм Tanki; значение `0` использовать нельзя, если Discord не вернул именно его.",
                    "Could not detect `provider_issued_user_id` automatically. Enter the ID returned by Discord or ask an administrator to retrieve the identity list. This is not your Tanki nickname; do not use `0` unless Discord returned it.",
                ),
                ephemeral=True,
            )
            return

        payload = self._build_widget_payload(stats, nickname)

        from urllib.parse import quote

        url = f"https://discord.com/api/v10/applications/{app_id}/users/{user_id}/identities/{quote(provider_user_id, safe='')}/profile"

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.patch(url, json=payload, headers=headers) as resp:
                    if 200 <= resp.status < 300:
                        if not self.accounts_manager.bind_user_token(
                            user_id, nickname, provider_user_id
                        ):
                            await interaction.followup.send(
                                self._text(
                                    language,
                                    "Виджет обновлён, но сохранить привязку не удалось. Повторите `/widget_refresh`.",
                                    "The widget was updated, but the binding could not be saved. Run `/widget_refresh` again.",
                                ),
                                ephemeral=True,
                            )
                            return
                        await interaction.followup.send(
                            self._text(
                                language,
                                f"✅ Виджет для аккаунта **{account_name}** обновлён и привязан к identity `{provider_user_id}`. Дальше он будет обновляться автоматически.",
                                f"✅ Widget updated for **{account_name}** and linked to identity `{provider_user_id}`. It will now update automatically.",
                            ),
                            ephemeral=True,
                        )
                    elif resp.status == 401:
                        error_text = await resp.text()
                        logger.error(
                            "Discord rejected widget write for %s: HTTP 401 - %s",
                            user_id,
                            error_text[:500],
                        )
                        await interaction.followup.send(
                            self._text(
                                language,
                                "❌ Discord отклонил авторизацию приложения. OAuth-привязку не удалял; проверьте BOT_TOKEN и настройки виджета приложения.",
                                "❌ Discord rejected the app authorization. The OAuth link was kept; check BOT_TOKEN and the app's widget settings.",
                            ),
                            ephemeral=True,
                        )
                    else:
                        error_text = await resp.text()
                        await interaction.followup.send(
                            self._text(
                                language,
                                f"❌ Ошибка обновления виджета (HTTP {resp.status}):\n```{error_text[:500]}```",
                                f"❌ Widget update failed (HTTP {resp.status}):\n```{error_text[:500]}```",
                            ),
                            ephemeral=True,
                        )
        except Exception as e:
            logger.error(f"Ошибка в widget_refresh: {e}", exc_info=True)
            await interaction.followup.send(
                self._text(
                    language,
                    f"❌ Внутренняя ошибка: {str(e)[:100]}",
                    f"❌ Internal error: {str(e)[:100]}",
                ),
                ephemeral=True,
            )
