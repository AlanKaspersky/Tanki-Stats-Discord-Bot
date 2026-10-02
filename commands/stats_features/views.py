import discord
from discord import app_commands, ui
import logging
from datetime import datetime
from typing import List
import os


logger = logging.getLogger(__name__)


class ViewCommandsMixin:
    def _build_info_view(
        self,
        total_accounts: int,
        guilds_count: int,
        ping: str,
        with_thumbnail: bool = False,
        language: str = "ru",
    ) -> ui.LayoutView:
        """Строит структуру компонентов v2 для команды info в объектном стиле"""

        intro_text = (
            "## ⚙️ Tanki Stats\n"
            "**Tanki Stats** is an asynchronous analytics tracker for Tanki Online. It collects game statistics, turns API data into clear reports, and helps players and clans follow their progress in Discord."
            if self._is_english(language)
            else "## ⚙️ Tanki Stats\n"
            "**Tanki Stats** — это асинхронный аналитический трекер для Танков Онлайн, который автоматизирует сбор игровой статистики, преобразует сухие данные API в красивые профили и позволяет кланам или друзьям в реальном времени мониторить свой игровой прогресс прямо в Discord."
        )

        container_children: List[ui.Item] = []

        if with_thumbnail:
            container_children.append(
                ui.Section(
                    ui.TextDisplay(intro_text),
                    accessory=ui.Thumbnail("attachment://rounded-in-photoretrica.png"),
                )
            )
        else:
            container_children.append(ui.TextDisplay(intro_text))

        main_info_text = (
            "### 📌 About\n"
            "- **Developers:** <@570644931841097728> and <@589024114791153676>\n"
            "- **Language:** `Python 3.11.2`\n"
            "  - **Infrastructure:** `VLESS-Tunneling` `Xray-Multi-Routing`\n"
            "  - **Libraries:** `discord.py` `aiohttp` `pytz` `python-dotenv`\n"
            "- **Version:** `3.1.7.91837`\n"
            "- **Created:** November 25, 2025"
            if self._is_english(language)
            else "### 📌 Основная информация\n"
            "- **Разработчики:** <@570644931841097728> и <@589024114791153676>\n"
            "- **Язык программирования:** `Python 3.11.2`\n"
            "  - **Инфраструктура:** `VLESS-Tunneling` `Xray-Multi-Routing`\n"
            "  - **Используется:** `asyncio`  `json`  `pathlib (Path)`  `subprocess`  `urllib.parse (urlparse, parse_qs)`  `hashlib`  `base64`  `logging`\n"
            "- **Библиотеки:** `discord.py 2.7.1`  `aiohttp 3.8.0`  `pytz 2023.1`  `python-dotenv 1.0.0`\n"
            "- **Версия:** `3.1.7.91837`\n"
            "- **Дата создания:** 25 ноября 2025 г."
        )

        stats_text = (
            "### 📊 Bot statistics\n"
            f"- **Tracked accounts:** `{total_accounts}`\n"
            f"- **Servers:** `{guilds_count}`\n"
            f"- **Ping:** `{ping}`"
            if self._is_english(language)
            else "### 📊 Статистика бота\n"
            f"- **Количество аккаунтов:** `{total_accounts}`\n"
            f"- **Количество серверов:** `{guilds_count}`\n"
            f"- **Пинг:** `{ping}`"
        )

        container_children.extend(
            [
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(main_info_text),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(stats_text),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(
                    "### 🔗 Useful links"
                    if self._is_english(language)
                    else "### 🔗 Полезные ссылки"
                ),
            ]
        )

        container_children.extend(
            [
                ui.Section(
                    ui.TextDisplay(
                        "Terms of Service"
                        if self._is_english(language)
                        else "Условия использования (на английском)"
                    ),
                    accessory=ui.Button(
                        label="Terms of Service",
                        url="https://sites.google.com/view/tankistats-terms-of-service",
                    ),
                ),
                ui.Separator(spacing=discord.SeparatorSpacing.small),
                ui.Section(
                    ui.TextDisplay(
                        "Privacy Policy"
                        if self._is_english(language)
                        else "Политика конфиденциальности (на английском)"
                    ),
                    accessory=ui.Button(
                        label="Privacy Policy",
                        url="https://sites.google.com/view/tankistats-ptivacy-policy",
                    ),
                ),
                ui.Separator(spacing=discord.SeparatorSpacing.small),
                ui.Section(
                    ui.TextDisplay(
                        "Visit our Telegram project for more detailed Tanki Online account information."
                        if self._is_english(language)
                        else "Не забудьте посетить наш второй проект в Telegram, где вы можете получить расширенную информацию о своем аккаунте Танков Онлайн"
                    ),
                    accessory=ui.Button(
                        label="Tanki Ratings", url="https://t.me/tankirating_bot"
                    ),
                ),
            ]
        )

        footer_text = (
            "-# <:135:1518725252971106364> Kaspersky x Tenobyte, 2026 © All rights reserved."
            if self._is_english(language)
            else "-# <:135:1518725252971106364> Kaspersky x Tenobyte, 2026 © Все права защищены."
        )
        container_children.append(ui.TextDisplay(footer_text))

        view = ui.LayoutView(timeout=None)
        view.add_item(ui.Container(*container_children, accent_color=16448250))
        return view

    @app_commands.command(
        name="info", description="Посмотреть полную информацию и статистику бота"
    )
    async def info_command(self, interaction: discord.Interaction):
        """Показывает полную информацию и живую статистику бота"""
        await interaction.response.defer(ephemeral=True)
        logger.info(f"Команда info: пользователь {interaction.user.id}")

        try:
            ping = f"{round(interaction.client.latency * 1000)}ms"
            guilds_count = len(interaction.client.guilds)

            total_accounts = 0
            accounts_dir = self.accounts_manager.accounts_dir

            if os.path.exists(accounts_dir) and os.path.isdir(accounts_dir):
                for filename in os.listdir(accounts_dir):
                    if filename.endswith(".json") and filename not in {
                        "blacklist.json",
                        "user_tokens.json",
                        "user_languages.json",
                    }:
                        total_accounts += 1
            else:
                logger.warning(f"⚠️ Папка '{accounts_dir}' не найдена!")
                total_accounts = 0

            base_dir = self.base_dir
            icon_path = base_dir / "rounded-in-photoretrica.png"
            with_thumbnail = icon_path.exists()

            view = self._build_info_view(
                total_accounts=total_accounts,
                guilds_count=guilds_count,
                ping=ping,
                with_thumbnail=with_thumbnail,
                language=self._language_for_interaction(interaction),
            )

            if with_thumbnail:
                file = discord.File(
                    str(icon_path), filename="rounded-in-photoretrica.png"
                )
                await interaction.followup.send(view=view, file=file, ephemeral=True)
            else:
                logger.warning(
                    "Иконка info не найдена по пути: %s, отправка без картинки",
                    icon_path,
                )
                await interaction.followup.send(view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Ошибка в команде info: {e}", exc_info=True)
            await interaction.followup.send(
                self._text(
                    self._language_for_interaction(interaction),
                    "❌ Произошла ошибка при генерации карточки информации.",
                    "❌ Could not generate the information card.",
                ),
                ephemeral=True,
            )

    def _build_stats_list_view(
        self,
        interaction_user_id: int,
        accounts: dict,
        with_thumbnail: bool = False,
        language: str = "ru",
    ) -> ui.LayoutView:
        max_accounts = self.accounts_manager.max_accounts_per_user

        intro_text = (
            "## 📊 Your accounts\n"
            f"These are the accounts linked to you. You can track up to **{max_accounts}** accounts."
            if self._is_english(language)
            else "## 📊 Ваши аккаунты\n"
            f"Здесь вы можете просмотреть все свои привязанные аккаунты. Не забывайте, что максимальное количество привязок составляет **{max_accounts}** штуки!"
        )

        container_children: List[ui.Item] = [ui.TextDisplay(intro_text)]

        months_ru = {
            1: "января",
            2: "февраля",
            3: "марта",
            4: "апреля",
            5: "мая",
            6: "июня",
            7: "июля",
            8: "августа",
            9: "сентября",
            10: "октября",
            11: "ноября",
            12: "декабря",
        }
        months_en = {
            1: "January",
            2: "February",
            3: "March",
            4: "April",
            5: "May",
            6: "June",
            7: "July",
            8: "August",
            9: "September",
            10: "October",
            11: "November",
            12: "December",
        }

        for account_name, account_data in accounts.items():
            if not account_data or "nickname" not in account_data:
                continue

            nickname = account_data["nickname"]

            full_raw_data = self.accounts_manager.load_account(nickname)
            raw_date = None

            if full_raw_data:
                tracked_by = full_raw_data.get("tracked_by", {})
                user_info = tracked_by.get(str(interaction_user_id))
                if user_info:
                    raw_date = user_info.get("added_at")

                if not raw_date:
                    raw_date = full_raw_data.get("created_at")

            formatted_date = (
                "Not specified" if self._is_english(language) else "Не указана"
            )

            if raw_date:
                try:
                    dt = datetime.fromisoformat(raw_date)
                    formatted_date = (
                        f"{months_en[dt.month]} {dt.day}, {dt.year}"
                        if self._is_english(language)
                        else f"{dt.day} {months_ru[dt.month]} {dt.year} г."
                    )
                except Exception:
                    formatted_date = str(raw_date)[:10]

            account_text = (
                f"### ℹ️ {account_name}\n"
                f"- **Nickname:** {nickname}\n"
                f"- **Delivery:** Direct messages\n"
                f"- **Linked:** {formatted_date}"
                if self._is_english(language)
                else f"### ℹ️ {account_name}\n"
                f"- **Никнейм:** {nickname}\n"
                f"- **Метод отправки:** Личные сообщения\n"
                f"- **Дата привязки:** {formatted_date}"
            )

            container_children.append(
                ui.Separator(spacing=discord.SeparatorSpacing.large)
            )

            if with_thumbnail:
                container_children.append(
                    ui.Section(
                        ui.TextDisplay(account_text),
                        accessory=ui.Thumbnail("attachment://account_icon.png"),
                    )
                )
            else:
                container_children.append(ui.TextDisplay(account_text))

        view = ui.LayoutView(timeout=None)
        view.add_item(ui.Container(*container_children, accent_color=0xFFFFFF))
        return view

    @app_commands.command(
        name="list", description="Показать все ваши отслеживаемые аккаунты"
    )
    async def stats_list(self, interaction: discord.Interaction):
        """Показывает все ваши отслеживаемые аккаунты"""
        await interaction.response.defer(ephemeral=True)
        logger.info(f"Команда stats_list: пользователь {interaction.user.id}")

        try:
            accounts = self.accounts_manager.get_user_accounts(interaction.user.id)

            if not accounts:
                logger.info(f"У пользователя {interaction.user.id} нет аккаунтов")
                await interaction.followup.send(
                    self._text(
                        self._language_for_interaction(interaction),
                        "У вас нет отслеживаемых аккаунтов",
                        "You are not tracking any accounts.",
                    ),
                    ephemeral=True,
                )
                return

            logger.info(
                f"Отображение {len(accounts)} аккаунтов для пользователя {interaction.user.id}"
            )

            base_dir = self.base_dir
            icon_path = base_dir / "account_icon.png"
            with_thumbnail = icon_path.exists()

            view = self._build_stats_list_view(
                interaction.user.id,
                accounts,
                with_thumbnail=with_thumbnail,
                language=self._language_for_interaction(interaction),
            )

            if with_thumbnail:
                file = discord.File(icon_path, filename="account_icon.png")
                await interaction.followup.send(view=view, file=file, ephemeral=True)
            else:
                await interaction.followup.send(view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Ошибка в команде stats_list: {e}", exc_info=True)
            await interaction.followup.send(
                self._text(
                    self._language_for_interaction(interaction),
                    "❌ Произошла ошибка при получении списка аккаунтов.",
                    "❌ Could not load your account list.",
                ),
                ephemeral=True,
            )

    def _build_stats_help_view(
        self,
        accounts_count: int,
        remaining: int,
        *,
        with_thumbnail: bool = False,
        language: str = "ru",
    ) -> ui.LayoutView:
        max_accounts = self.accounts_manager.max_accounts_per_user

        intro = (
            "## ℹ️ Statistics command help\n"
            "For help, contact <@570644931841097728>. This bot was created with <@589024114791153676>."
            if self._is_english(language)
            else "## ℹ️ Справка по командам статистики\n"
            "Если у вас остались какие-нибудь вопросы или возникли проблемы, вы можете обратиться за консультацией к <@570644931841097728>. Бот также был создан совместно с <@589024114791153676>."
        )
        commands_one = (
            "### ✅ </add:1515660487637864490>\n"
            "Add an account to track. Enter the player's nickname; matching is case-insensitive. You can optionally set a custom `account_name`.\n"
            if self._is_english(language)
            else "### ✅ </add:1515660487637864490>\n"
            "Добавление аккаунта для отслеживания статистики. В атрибут `nickname` вы должны ввести любой желаемый никнейм (регистр не имеет значения), а в `account_name` по желанию можно ввести кастомное название вашей привязки.\n"
        )
        commands_two = (
            "### 📛 </remove:1515660487637864491>\n"
            "Remove an account by its nickname or custom account name. Matching is case-insensitive.\n\n"
            if self._is_english(language)
            else "### 📛 </remove:1515660487637864491>\n"
            "При удалении аккаунта вы должны ввести либо никнейм (регистр не имеет значения), либо кастомное название привязки.\n\n"
        )
        commands_three = (
            "### 📋 </list:1515660487637864492>\nView the accounts you are tracking.\n"
            if self._is_english(language)
            else "### 📋 </list:1515660487637864492>\n"
            "Здесь вы можете просмотреть список ваших привязанных аккаунтов.\n"
        )
        commands_four = (
            "### 📜 </info:1519048336362045482>\nView information and live statistics for the bot.\n"
            if self._is_english(language)
            else "### 📜 </info:1519048336362045482>\n"
            "Здесь предоставлена вся доступная информация о боте.\n"
        )
        commands_five = (
            "### 🆘 </help:1515660487637864493>\nShow this help page."
            if self._is_english(language)
            else "### 🆘 </help:1515660487637864493>\n"
            "Здесь вы можете просмотреть всю информацию о боте."
        )
        limits = (
            "### 🔒 Tracking limits\n\n"
            f"- Maximum linked accounts: **{max_accounts}**\n"
            f"- You are using: **{accounts_count}/{max_accounts}**\n"
            f"- Slots remaining: **{remaining}**"
            if self._is_english(language)
            else "### 🔒 Ограничения по статистике\n\n"
            f"- У вас максимум может быть **{max_accounts}** привязанных аккаунтов.\n"
            f"- У вас: **{accounts_count}/{max_accounts}**\n"
            f"- Осталось слотов: **{remaining}**"
        )
        notes = (
            "### 📝 Notes\n\n"
            "- Removing an account only removes it from your list. If others track it, the bot keeps it in its database.\n"
            "- Stats are sent daily around 02:00 UTC (05:00 Moscow time), during the Tanki Online server restart.\n\n"
            "- Use `/language` to choose Russian, English (US), English (UK), or automatic Discord language detection.\n\n"
            if self._is_english(language)
            else "### 📝 Примечания\n\n"
            "- Удаление аккаунта удаляет его только из вашего списка. Если его отслеживают другие пользователи, то он останется в базе данных бота.\n"
            "- Статистика отправляется ежедневно в момент рестарта серверов Танков Онлайн в 5:00 по Московскому времени (2:00 UTC).\n\n"
            "- Используйте `/language`, чтобы выбрать русский, English (US), English (UK) или автоматическое определение языка Discord.\n\n"
        )
        footer = (
            "-# <:135:1518725252971106364> © Kaspersky x Tenobyte, 2026. All rights reserved."
            if self._is_english(language)
            else "-# <:135:1518725252971106364> © Kaspersky x Tenobyte, 2026. Все права защищены."
        )

        container_children: List[ui.Item] = []
        if with_thumbnail:
            container_children.append(
                ui.Section(
                    ui.TextDisplay(intro),
                    accessory=ui.Thumbnail("attachment://rounded-in-photoretrica.png"),
                )
            )
        else:
            container_children.append(ui.TextDisplay(intro))

        container_children.extend(
            [
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(commands_one),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(commands_two),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(commands_three),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(commands_four),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(commands_five),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(limits),
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                ui.TextDisplay(notes),
                ui.TextDisplay(footer),
            ]
        )

        view = ui.LayoutView(timeout=None)
        view.add_item(ui.Container(*container_children, accent_color=0xFFFFFF))
        return view

    @app_commands.command(
        name="help", description="Показать справку по командам статистики"
    )
    async def stats_help(self, interaction: discord.Interaction):
        """Показывает справку по командам статистики"""
        await interaction.response.defer(ephemeral=True)
        logger.info(f"Команда stats_help: пользователь {interaction.user.id}")

        try:
            accounts = self.accounts_manager.get_user_accounts(interaction.user.id)
            accounts_count = len(accounts) if accounts else 0
            remaining = max(
                0, self.accounts_manager.max_accounts_per_user - accounts_count
            )

            base_dir = self.base_dir
            icon_path = base_dir / "rounded-in-photoretrica.png"
            with_thumbnail = icon_path.exists()

            view = self._build_stats_help_view(
                accounts_count,
                remaining,
                with_thumbnail=with_thumbnail,
                language=self._language_for_interaction(interaction),
            )

            if with_thumbnail:
                file = discord.File(
                    str(icon_path), filename="rounded-in-photoretrica.png"
                )
                await interaction.followup.send(view=view, file=file, ephemeral=True)
            else:
                logger.warning(
                    "Иконка не найдена по пути: %s, отправка без вложения", icon_path
                )
                await interaction.followup.send(view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Ошибка в команде stats_help: {e}", exc_info=True)
            await interaction.followup.send(
                self._text(
                    self._language_for_interaction(interaction),
                    f"❌ Ошибка: {str(e)[:100]}",
                    f"❌ Error: {str(e)[:100]}",
                ),
                ephemeral=True,
            )
