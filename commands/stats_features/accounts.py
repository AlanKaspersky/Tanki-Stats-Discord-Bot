import discord
from discord import app_commands
import logging
from urllib.parse import urlencode


logger = logging.getLogger(__name__)


class AccountCommandsMixin:
    @app_commands.command(
        name="add", description="Добавить аккаунт для отслеживания статистики"
    )
    @app_commands.describe(
        nickname="Никнейм в Tanki Online",
        account_name="Название аккаунта (по умолчанию равен никнейму)",
    )
    async def stats_add(
        self, interaction: discord.Interaction, nickname: str, account_name: str = None
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self._registration_lock:
            await self._add_account(interaction, nickname, account_name)

    async def _add_account(
        self, interaction: discord.Interaction, nickname: str, account_name: str = None
    ):
        if account_name is None:
            account_name = nickname

        detected_language = self._language_from_locale(
            getattr(interaction, "locale", None)
        )
        self.accounts_manager.set_user_language(
            interaction.user.id,
            "auto",
            detected_locale=detected_language,
            only_if_missing=True,
        )
        language = self._language_for_interaction(interaction)

        try:
            # 1. Проверяем лимит аккаунтов у конкретного пользователя
            can_add, current_count, remaining = (
                self.accounts_manager.can_add_more_accounts(interaction.user.id)
            )
            if not can_add:
                await interaction.followup.send(
                    self._text(
                        language,
                        f"❌ Лимит достигнут! У вас уже добавлено {current_count} аккаунтов.",
                        f"❌ Account limit reached. You are tracking {current_count} accounts.",
                    ),
                    ephemeral=True,
                )
                return

            # 2. Проверяем, не привязал ли ЭТОТ ЖЕ пользователь этот аккаунт ранее
            user_accounts = self.accounts_manager.get_user_accounts(
                interaction.user.id, case_insensitive=True
            )
            if any(
                data["nickname"].casefold() == nickname.casefold()
                for data in user_accounts.values()
            ):
                await interaction.followup.send(
                    self._text(
                        language,
                        f"❌ Вы уже отслеживаете аккаунт **{nickname}**!",
                        f"❌ You are already tracking **{nickname}**.",
                    ),
                    ephemeral=True,
                )
                return

            if not nickname or any(not (c.isalnum() or c in "_-") for c in nickname):
                await interaction.followup.send(
                    self._text(
                        language, "❌ Некорректный никнейм.", "❌ Invalid nickname."
                    ),
                    ephemeral=True,
                )
                return
            if not account_name.strip() or account_name.casefold() in user_accounts:
                await interaction.followup.send(
                    self._text(
                        language,
                        "❌ Выберите уникальное название аккаунта.",
                        "❌ Choose a unique account name.",
                    ),
                    ephemeral=True,
                )
                return

            # 3. Проверка ЛС для новичков
            if not self.accounts_manager.has_verified_dm(interaction.user.id):
                try:
                    test_embed = discord.Embed(
                        title=self._text(language, "✅ Проверка ЛС", "✅ DM check"),
                        description=self._text(
                            language,
                            "Бот сможет присылать вам статистику.",
                            "The bot can send your statistics by DM.",
                        ),
                    )
                    await interaction.user.send(embed=test_embed)
                except discord.Forbidden:
                    await interaction.followup.send(
                        self._text(
                            language,
                            "❌ Откройте ЛС в настройках приватности, чтобы бот мог отправлять отчеты!",
                            "❌ Enable direct messages in your privacy settings so the bot can send reports.",
                        ),
                        ephemeral=True,
                    )
                    return

            api_url = "https://ratings.tankionline.com/api/eu/profile/?" + urlencode(
                {"user": nickname, "lang": "ru"}
            )

            # === НАЧАЛО НОВОЙ ЛОГИКИ ===
            # Проверяем, отслеживает ли КТО-ТО ЕЩЕ этот аккаунт в боте
            existing_file = self.accounts_manager.find_existing_account_file(nickname)

            if existing_file:
                # Аккаунт уже есть в базе! Просто привязываем юзера к нему
                success = self.accounts_manager.add_user_to_account(
                    nickname, api_url, interaction.user.id, account_name
                )
                if success:
                    user_count = self.accounts_manager.get_account_users_count(nickname)
                    await interaction.followup.send(
                        self._text(
                            language,
                            f"✅ Аккаунт **{account_name}** успешно добавлен к вашему списку!\nℹ️ Этот аккаунт уже отслеживается ботом. Ваша статистика зафиксирована относительно общей точки отсчета бота (всего трекеров: **{user_count}**).",
                            f"✅ **{account_name}** was added to your list.\nℹ️ This account is already tracked. Your stats use the bot's shared baseline (**{user_count}** trackers).",
                        ),
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        self._text(
                            language,
                            "❌ Ошибка при привязке к существующему аккаунту.",
                            "❌ Could not link the existing account.",
                        ),
                        ephemeral=True,
                    )
                return
            # === КОНЕЦ НОВОЙ ЛОГИКИ ===

            # Если файла нет — этот аккаунт добавляется впервые в истории бота.
            # Только в этом случае мы дергаем API и ставим "точку отсчета".
            logger.info(
                f"Первое добавление аккаунта {nickname}. Скачиваем стартовую статистику..."
            )
            current_stats, failure_reason = await self._fetch_tanki_stats_result(
                api_url
            )

            if not current_stats:
                if (
                    failure_reason == "API HTTP 404"
                    or failure_reason == "player not found"
                ):
                    await interaction.followup.send(
                        self._text(
                            language,
                            f"❌ Игрок **{nickname}** не найден.",
                            f"❌ Player **{nickname}** was not found.",
                        ),
                        ephemeral=True,
                    )
                    return
                await interaction.followup.send(
                    self._text(
                        language,
                        "❌ Не удалось получить данные от серверов ТО. Попробуйте позже.",
                        "❌ Could not retrieve stats from Tanki Online. Please try again later.",
                    ),
                    ephemeral=True,
                )
                return

            # Создаем файл и записываем первого пользователя
            success = self.accounts_manager.add_user_to_account(
                nickname,
                api_url,
                interaction.user.id,
                account_name,
                initial_stats=current_stats,
            )

            if success:
                await interaction.followup.send(
                    self._text(
                        language,
                        f"✅ Аккаунт **{account_name}** успешно зарегистрирован в системе и добавлен к вам!",
                        f"✅ **{account_name}** was registered and added to your list.",
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    self._text(
                        language,
                        "❌ Ошибка при создании базы данных аккаунта.",
                        "❌ Could not create the account record.",
                    ),
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"Ошибка в stats_add: {e}", exc_info=True)
            await interaction.followup.send(
                self._text(
                    language,
                    f"❌ Внутренняя ошибка: {str(e)[:100]}",
                    f"❌ Internal error: {str(e)[:100]}",
                ),
                ephemeral=True,
            )

    @app_commands.command(
        name="language", description="Выбрать язык статистики в личных сообщениях"
    )
    @app_commands.describe(language="Язык статистических отчетов")
    @app_commands.choices(
        language=[
            app_commands.Choice(name=app_commands.locale_str("Русский"), value="ru"),
            app_commands.Choice(
                name=app_commands.locale_str("English (US)"), value="en-US"
            ),
            app_commands.Choice(
                name=app_commands.locale_str("English (UK)"), value="en-GB"
            ),
            app_commands.Choice(
                name=app_commands.locale_str("Автоматически (язык Discord)"),
                value="auto",
            ),
        ]
    )
    async def stats_language(
        self, interaction: discord.Interaction, language: app_commands.Choice[str]
    ):
        """Set the language used for future statistical reports."""
        detected = self._language_from_locale(getattr(interaction, "locale", None))
        if not self.accounts_manager.set_user_language(
            interaction.user.id, language.value, detected_locale=detected
        ):
            await interaction.response.send_message(
                self._text(
                    language.value,
                    "Не удалось сохранить язык. Попробуйте ещё раз.",
                    "Could not save the language preference. Please try again.",
                ),
                ephemeral=True,
            )
            return
        selected_name = {
            "ru": "Русский",
            "en-US": "English (US)",
            "en-GB": "English (UK)",
            "auto": f"Автоматически ({detected})",
        }[language.value]
        response_language = detected if language.value == "auto" else language.value
        if self._is_english(response_language):
            selected_name = {
                "ru": "Russian",
                "en-US": "English (US)",
                "en-GB": "English (UK)",
                "auto": f"Automatic ({detected})",
            }[language.value]
            message = f"Statistics language set to **{selected_name}**."
        else:
            message = f"Язык статистики установлен: **{selected_name}**."
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="remove", description="Удалить аккаунт из отслеживания")
    @app_commands.describe(account_name="Название аккаунта для удаления")
    async def stats_remove(self, interaction: discord.Interaction, account_name: str):
        """Удаляет аккаунт из отслеживания"""
        await interaction.response.defer(ephemeral=True)
        language = self._language_for_interaction(interaction)

        try:
            # 🔧 Получаем аккаунты с регистронезависимым доступом
            user_accounts = self.accounts_manager.get_user_accounts(
                interaction.user.id,
                case_insensitive=True,  # ← регистронезависимо!
            )

            if not user_accounts:
                await interaction.followup.send(
                    self._text(
                        language,
                        "У вас нет отслеживаемых аккаунтов",
                        "You are not tracking any accounts.",
                    ),
                    ephemeral=True,
                )
                return

            # 🔧 Ищем аккаунт по названию (регистронезависимо)
            target_nickname = None
            original_account_name = None

            # Приводим введенное имя к нижнему регистру для сравнения
            search_name = account_name.lower()

            for acc_name_lower, acc_data in user_accounts.items():
                if acc_name_lower == search_name:
                    target_nickname = acc_data["nickname"]
                    original_account_name = acc_data.get("original_name", account_name)
                    logger.info(
                        f"Найден аккаунт: {acc_name_lower} -> {target_nickname}"
                    )
                    break

            if not target_nickname:
                # 🔧 Показываем варианты, если имя не найдено (регистронезависимый поиск)
                similar_names = []
                for acc_name_lower, acc_data in user_accounts.items():
                    if search_name in acc_name_lower or acc_name_lower in search_name:
                        similar_names.append(
                            acc_data.get("original_name", acc_name_lower)
                        )

                if similar_names:
                    await interaction.followup.send(
                        self._text(
                            language,
                            f"Аккаунт **{account_name}** не найден!\nВозможно вы имели в виду:\n"
                            + "\n".join([f"• **{name}**" for name in similar_names]),
                            f"Account **{account_name}** was not found.\nDid you mean:\n"
                            + "\n".join([f"• **{name}**" for name in similar_names]),
                        ),
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        self._text(
                            language,
                            f"Аккаунт **{account_name}** не найден\nИспользуйте `/stats_list` чтобы увидеть ваши аккаунты",
                            f"Account **{account_name}** was not found. Use `/list` to view your accounts.",
                        ),
                        ephemeral=True,
                    )
                return

            # 🔧 Удаляем пользователя из аккаунта
            success = self.accounts_manager.remove_user_from_account(
                target_nickname, interaction.user.id
            )

            if success:
                await interaction.followup.send(
                    self._text(
                        language,
                        f"Аккаунт **{original_account_name}** удален",
                        f"Account **{original_account_name}** removed.",
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    self._text(
                        language,
                        "Ошибка при удалении аккаунта",
                        "Could not remove the account.",
                    ),
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"Ошибка в команде stats_remove: {e}", exc_info=True)
            await interaction.followup.send(
                self._text(
                    language, f"Ошибка: {str(e)[:100]}", f"Error: {str(e)[:100]}"
                ),
                ephemeral=True,
            )
