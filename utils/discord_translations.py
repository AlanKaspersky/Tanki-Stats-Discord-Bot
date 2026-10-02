"""Discord application-command metadata translations for Tanki Stats."""

import discord
from discord import app_commands


_EN_US = {
    "Добавить аккаунт для отслеживания статистики": "Add a Tanki Online account to track stats",
    "Никнейм в Tanki Online": "Tanki Online player nickname",
    "Название аккаунта (по умолчанию равен никнейму)": "Display name (defaults to the nickname)",
    "Выбрать язык статистики в личных сообщениях": "Choose the language for stats in direct messages",
    "Язык статистических отчетов": "Language for statistics reports",
    "Русский": "Russian",
    "English (US)": "English (US)",
    "English (UK)": "English (UK)",
    "Автоматически (язык Discord)": "Automatic (Discord language)",
    "Удалить аккаунт из отслеживания": "Stop tracking an account",
    "Название аккаунта для удаления": "Name of the account to remove",
    "Посмотреть полную информацию и статистику бота": "View bot information and statistics",
    "Показать все ваши отслеживаемые аккаунты": "Show all accounts you are tracking",
    "Показать справку по командам статистики": "Show help for the statistics commands",
    "Настроить виджет в профиле Discord": "Set up a Discord profile widget",
    "Сохранить токен доступа для виджета (используйте код из ссылки)": "Save the widget access token using the code from the redirect URL",
    "Код, полученный после авторизации (часть ссылки после ?code=)": "Authorization code from the redirect URL after ?code=",
    "Обновить виджет актуальной статистикой": "Update the profile widget with current statistics",
    "Название отслеживаемого аккаунта для виджета": "Tracked account to show in the widget",
    "ID identity из Discord (если бот не смог определить его сам)": "Discord identity ID if the bot cannot detect it automatically",
}

_EN_GB_OVERRIDES = {}


class StatsTranslator(app_commands.Translator):
    async def translate(self, string, locale, context):
        if locale not in (
            discord.Locale.american_english,
            discord.Locale.british_english,
        ):
            return None
        message = string.message
        translated = _EN_US.get(message)
        if translated is None:
            return None
        return (
            _EN_GB_OVERRIDES.get(message, translated)
            if locale == discord.Locale.british_english
            else translated
        )
