import discord
from discord.ext import commands
import logging


logger = logging.getLogger(__name__)


class LocalizationMixin:
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Keep automatic language preferences aligned with Discord's user locale."""
        if not getattr(interaction, "user", None):
            return
        locale = self._language_from_locale(getattr(interaction, "locale", None))
        self.accounts_manager.update_detected_user_language(interaction.user.id, locale)

    def _language_for_interaction(self, interaction: discord.Interaction) -> str:
        if self.accounts_manager.get_user_language_mode(interaction.user.id) == "auto":
            return self._language_from_locale(getattr(interaction, "locale", None))
        return self.accounts_manager.get_user_language(interaction.user.id)

    @staticmethod
    def _is_english(language: str) -> bool:
        return str(language).lower().startswith("en")

    @staticmethod
    def _text(language: str, russian: str, english: str, british: str = None) -> str:
        if str(language).lower() == "en-gb" and british is not None:
            return british
        return english if str(language).lower().startswith("en") else russian

    @staticmethod
    def _language_from_locale(locale) -> str:
        """Normalize Discord's interaction locale to a supported locale."""
        locale_value = getattr(locale, "value", locale)
        normalized = str(locale_value or "").lower().replace("_", "-")
        if normalized.startswith("en-gb"):
            return "en-GB"
        if normalized.startswith("en"):
            return "en-US"
        return "ru"

    @staticmethod
    def _localized_item_name(name: str, language: str) -> str:
        if not str(language).lower().startswith("en"):
            return name
        translations = {
            "Викинг": "Viking",
            "Крусейдер": "Crusader",
            "Паладин": "Paladin",
            "Васп": "Wasp",
            "Хорнет": "Hornet",
            "Хантер": "Hunter",
            "Мамонт": "Mammoth",
            "Арес": "Ares",
            "Диктатор": "Dictator",
            "Титан": "Titan",
            "Хоппер": "Hopper",
            "Джаггернаут": "Juggernaut",
            "Смоки": "Smoky",
            "Рикошет": "Ricochet",
            "Гром": "Thunder",
            "Рельса": "Railgun",
            "Изида": "Isida",
            "Магнум": "Magnum",
            "Твинс": "Twins",
            "Страйкер": "Striker",
            "Гаусс": "Gauss",
            "Вулкан": "Vulcan",
            "Шафт": "Shaft",
            "Молот": "Hammer",
            "Огнемёт": "Firebird",
            "Скорпион": "Scorpion",
            "Фриз": "Freeze",
            "Тесла": "Tesla",
            "Цунами": "Tsunami",
            "Терминатор": "Terminator",
            "Кризис": "Crisis",
            "Брут": "Brutus",
            "Диверсант": "Saboteur",
            "Ловкач": "Dodger",
            "Механик": "Mechanic",
            "Бустер": "Booster",
            "Защитник": "Defender",
            "Гиперион": "Hyperion",
            "Оракул": "Oracle",
            "Кризис ХТ": "Crisis XT",
            "Гиперион ХТ": "Hyperion XT",
            "Сокол": "Falcon",
            "Дельфин": "Dolphin",
            "Лев": "Lion",
            "Гризли": "Grizzly",
            "Грифон": "Griffin",
            "Сова": "Owl",
            "Касатка": "Orca",
            "Гриф": "Vulture",
            "Паук": "Spider",
            "Акула": "Shark",
            "Броненосец": "Armadillo",
            "Волк": "Wolf",
            "Лис": "Fox",
            "Барсук": "Badger",
            "Оцелот": "Ocelot",
            "Ласка": "Weasel",
            "Пантера": "Panther",
            "Орёл": "Eagle",
            "Ворон": "Raven",
            "Спектр B": "Spectrum B",
            "Спектр A": "Spectrum A",
            "Спектр M": "Spectrum M",
            "Спектр C": "Spectrum C",
            "Спектр Демон": "Spectrum Demon",
            "Спектр Лорд": "Spectrum Lord",
            "Мина": "Mine",
            "Повышенный урон": "Boosted Damage",
            "Повышенная защита": "Boosted Armor",
            "Ускорение": "Speed Boost",
            "Ядерная энергия": "Nuclear Energy",
            "Золотой ящик": "Gold Box",
            "Ремкомплект": "Repair Kit",
            "Бомба": "Bomb",
            "Царь": "Tsar",
            "Снежок": "Snowball",
            "Мортира": "Mortar",
            "Салют": "Sakyut",
            "Тыква": "Pumpkin",
            "Медик": "Medic",
            "Дым": "Smoke",
            "Телепорт": "Teleport",
        }
        translated = translations.get(name, name)
        if language == "en-GB" and translated == "Armor Boost":
            return "Armour Boost"
        return translated
