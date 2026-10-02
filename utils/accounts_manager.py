from __future__ import annotations
import json
import os
import logging
from utils.storage import atomic_write_json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

RESERVED_FILENAMES = {
    "blacklist",
    "user_tokens",
    "user_languages",
    "con",
    "prn",
    "aux",
    "nul",
} | {f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)}


class AccountsManager:
    """Менеджер аккаунтов с файловой системой"""

    def __init__(self, accounts_dir: str = "accounts", max_accounts_per_user: int = 3):
        self.accounts_dir = accounts_dir
        self.max_accounts_per_user = max_accounts_per_user
        self._ensure_accounts_dir()
        logger.info(
            f"AccountsManager инициализирован, лимит: {max_accounts_per_user} аккаунтов на пользователя"
        )

    def get_user_accounts_count(self, user_id: int) -> int:
        """Возвращает количество аккаунтов пользователя"""
        user_accounts = self.get_user_accounts(user_id)
        return len(user_accounts)

    def can_add_more_accounts(self, user_id: int) -> Tuple[bool, int, int]:
        """Проверяет может ли пользователь добавить еще аккаунты"""
        current_count = self.get_user_accounts_count(user_id)
        can_add = current_count < self.max_accounts_per_user
        remaining = max(0, self.max_accounts_per_user - current_count)
        return can_add, current_count, remaining

    def _ensure_accounts_dir(self):
        """Создает папку accounts если её нет"""
        if not os.path.exists(self.accounts_dir):
            os.makedirs(self.accounts_dir)
            logger.info(f"Создана папка {self.accounts_dir}")

    def _get_account_filename(self, nickname: str) -> str:
        """Генерирует безопасное имя файла для аккаунта, ВСЕГДА в нижнем регистре"""
        safe_nickname = "".join(
            c for c in nickname if c.isalnum() or c in ("_", "-")
        ).strip()
        if not safe_nickname:
            safe_nickname = "unknown"
        safe_nickname = safe_nickname.lower()
        if safe_nickname in RESERVED_FILENAMES:
            safe_nickname = "@" + safe_nickname
        return os.path.join(self.accounts_dir, f"{safe_nickname}.json")

    def account_exists(self, nickname: str) -> bool:
        """Проверяет существует ли файл аккаунта"""
        filename = self._get_account_filename(nickname)
        return os.path.exists(filename)

    def load_account(self, nickname: str) -> Optional[Dict]:
        """Загружает данные аккаунта из файла"""
        filename = self._get_account_filename(nickname)

        if not os.path.exists(filename):
            logger.debug(f"Файл аккаунта не найден: {filename}")
            return None

        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(f"Аккаунт загружен: {nickname}")
            return data
        except Exception as e:
            logger.error(f"Ошибка загрузки аккаунта {nickname}: {e}")
            return None

    def save_account(self, nickname: str, account_data: Dict) -> bool:
        """Сохраняет данные аккаунта в файл"""
        filename = self._get_account_filename(nickname)

        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)

            atomic_write_json(filename, account_data)

            logger.debug(f"Аккаунт сохранен: {nickname}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения аккаунта {nickname}: {e}")
            return False

    def add_user_to_account(
        self,
        nickname: str,
        api_url: str,
        user_id: int,
        account_name: str,
        *,
        initial_stats: Optional[Dict] = None,
    ) -> bool:
        """
        Добавляет пользователя к аккаунту.
        Имя файла на диске всегда будет строго в нижнем регистре.
        """
        try:
            if not nickname or any(not (c.isalnum() or c in "_-") for c in nickname):
                return False
            user_accounts = self.get_user_accounts(user_id, case_insensitive=True)
            if (
                not account_name.strip()
                or account_name.casefold() in user_accounts
                or any(
                    acc["nickname"].casefold() == nickname.casefold()
                    for acc in user_accounts.values()
                )
                or len(user_accounts) >= self.max_accounts_per_user
            ):
                return False
            file_path = self._get_account_filename(nickname)

            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(
                    f"Аккаунт {nickname.lower()} уже отслеживается. Добавляем пользователя {user_id} в существующий файл."
                )
            else:
                data = {
                    "nickname": nickname,
                    "api_url": api_url,
                    "tracked_by": {},
                    "current_stats": {},
                    "last_updated": None,
                }
                logger.info(
                    f"Создаем новый файл аккаунта для {nickname.lower()} по пути {file_path}."
                )
                if initial_stats is not None:
                    data["last_stats"] = self._prepare_stats(initial_stats)
                    data["nickname"] = initial_stats.get("name", nickname)
                    data["last_updated"] = datetime.now().isoformat()

            data["tracked_by"][str(user_id)] = {
                "account_name": account_name,
                "added_at": datetime.now().isoformat(),
            }

            atomic_write_json(file_path, data)

            return True
        except Exception as e:
            logger.error(f"Ошибка в add_user_to_account для {nickname}: {e}")
            return False

    def remove_user_from_account(self, nickname: str, user_id: int) -> bool:
        """Удаляет пользователя из отслеживающих аккаунт"""
        try:
            account = self.load_account(nickname)
            if not account:
                logger.warning(f"Аккаунт не найден при удалении: {nickname}")
                return False

            user_id_str = str(user_id)

            if user_id_str not in account.get("tracked_by", {}):
                logger.warning(
                    f"Пользователь {user_id} не отслеживает аккаунт {nickname}"
                )
                return False

            del account["tracked_by"][user_id_str]
            logger.info(f"Пользователь {user_id} удален из аккаунта {nickname}")

            if not account["tracked_by"]:
                filename = self._get_account_filename(nickname)
                os.remove(filename)
                logger.info(f"Аккаунт {nickname} удален (нет отслеживающих)")
                return True
            else:
                success = self.save_account(nickname, account)
                if success:
                    logger.info(
                        f"Аккаунт {nickname} обновлен, осталось пользователей: {len(account['tracked_by'])}"
                    )
                return success

        except Exception as e:
            logger.error(f"Ошибка удаления пользователя из аккаунта {nickname}: {e}")
            return False

    def get_user_accounts(
        self, user_id: int, case_insensitive: bool = False
    ) -> Dict[str, Dict]:
        """Возвращает все аккаунты пользователя"""
        user_accounts = {}
        user_id_str = str(user_id)

        if not os.path.exists(self.accounts_dir):
            logger.debug(f"Папка {self.accounts_dir} не существует")
            return user_accounts

        try:
            for filename in os.listdir(self.accounts_dir):
                if filename.endswith(".json"):
                    if filename in (
                        "blacklist.json",
                        "user_tokens.json",
                        "user_languages.json",
                    ):
                        continue
                    try:
                        filepath = os.path.join(self.accounts_dir, filename)
                        with open(filepath, "r", encoding="utf-8") as f:
                            account = json.load(f)

                        if user_id_str in account.get("tracked_by", {}):
                            user_info = account["tracked_by"][user_id_str]
                            account_name = user_info["account_name"]

                            if case_insensitive:
                                account_name = account_name.casefold()

                            user_accounts[account_name] = {
                                "nickname": account.get("nickname", "Unknown"),
                                "api_url": account.get("api_url", ""),
                                "original_name": user_info["account_name"],
                            }

                    except Exception as e:
                        logger.error(f"Ошибка чтения файла {filename}: {e}")
                        continue

            logger.debug(
                f"Найдено аккаунтов для пользователя {user_id}: {len(user_accounts)}"
            )
            return user_accounts

        except Exception as e:
            logger.error(f"Ошибка получения аккаунтов пользователя {user_id}: {e}")
            return {}

    def _merge_items_by_name(
        self, items_list: List[Dict], sum_fields: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Объединяет элементы по названию, суммируя выбранные поля и сохраняя максимальный grade.
        Это уменьшает размер файлов, убирая дубликаты с разными grade.
        """
        if not isinstance(items_list, list):
            return []

        if sum_fields is None:
            sum_fields = ["scoreEarned", "timePlayed"]

        aggregated = {}
        for item in items_list:
            if not isinstance(item, dict):
                continue

            name = item.get("name")
            if not name:
                continue

            if name not in aggregated:
                aggregated[name] = item.copy()
                for field in sum_fields:
                    aggregated[name][field] = 0

            for field in sum_fields:
                aggregated[name][field] = aggregated[name].get(field, 0) + item.get(
                    field, 0
                )

            grade = item.get("grade")
            if grade is not None:
                current_grade = aggregated[name].get("grade", -999)
                aggregated[name]["grade"] = max(current_grade, grade)

        return list(aggregated.values())

    def _prepare_stats(self, stats: Dict) -> Dict:
        filtered = stats.copy()
        filtered.pop("paintsPlayed", None)
        for key in ("hullsPlayed", "turretsPlayed", "resistanceModules"):
            if isinstance(filtered.get(key), list):
                filtered[key] = self._merge_items_by_name(filtered[key])
        return filtered

    def update_account_stats(
        self, nickname: str, stats: Dict, *, pending_report: Optional[Dict] = None
    ) -> bool:
        """
        Обновляет статистику аккаунта.
        Файл сохраняется строго в нижнем регистре, а красивое имя из корня API пишется внутрь JSON.
        """
        try:
            account = self.load_account(nickname)
            if not account:
                logger.error(f"Аккаунт не найден для обновления статистики: {nickname}")
                return False

            official_nickname = stats.get("name", account.get("nickname", nickname))

            filtered_stats = self._prepare_stats(stats)

            account["nickname"] = official_nickname
            account["last_stats"] = filtered_stats
            account["last_updated"] = datetime.now().isoformat()
            if pending_report is not None:
                account.setdefault("pending_reports", []).append(pending_report)

            success = self.save_account(nickname, account)
            if success:
                logger.debug(
                    f"Статистика успешно обновлена для файла: {nickname.lower()} (Внутри записан как: {official_nickname})"
                )

            return success

        except Exception as e:
            logger.error(f"Ошибка обновления статистики аккаунта {nickname}: {e}")
            return False

    def find_existing_account_file(self, nickname: str) -> Optional[str]:
        """
        Ищет, существует ли уже JSON-файл для такого никнейма.
        Возвращает имя файла в нижнем регистре или None.
        """
        file_path = self._get_account_filename(nickname)
        if os.path.exists(file_path):
            return os.path.basename(file_path)
        return None

    def get_pending_reports(self, nickname: str) -> List[Dict]:
        account = self.load_account(nickname)
        return account.get("pending_reports", []) if account else []

    def acknowledge_report(self, nickname: str, report_id: str, user_id: str) -> bool:
        """Remove only a delivered recipient, preserving other reports and users."""
        account = self.load_account(nickname)
        if not account:
            return False
        reports = account.get("pending_reports", [])
        for report in reports:
            if report["id"] == report_id:
                report["pending_users"] = [
                    uid for uid in report["pending_users"] if uid != str(user_id)
                ]
                break
        account["pending_reports"] = [
            report for report in reports if report["pending_users"]
        ]
        return self.save_account(nickname, account)

    def get_account_stats(self, nickname: str) -> Optional[Dict]:
        """Возвращает последнюю сохраненную статистику аккаунта"""
        account = self.load_account(nickname)
        if account:
            return account.get("last_stats")
        return None

    def get_all_accounts(self) -> List[Dict]:
        """Возвращает все аккаунты для ежедневной проверки"""
        accounts = []

        if not os.path.exists(self.accounts_dir):
            logger.warning(f"Папка {self.accounts_dir} не существует")
            return accounts

        try:
            files = os.listdir(self.accounts_dir)
            logger.info(f"📁 Файлов в папке accounts: {len(files)}")

            for filename in files:
                logger.info(f"  📄 Файл: {filename}")
                if filename.endswith(".json"):
                    if filename in (
                        "blacklist.json",
                        "user_tokens.json",
                        "user_languages.json",
                    ):
                        continue
                    try:
                        filepath = os.path.join(self.accounts_dir, filename)
                        logger.info(f"    📖 Чтение файла: {filename}")

                        with open(filepath, "r", encoding="utf-8") as f:
                            account = json.load(f)

                        tracked_by = account.get("tracked_by", {})
                        logger.info(
                            f"    👥 Пользователей в {filename}: {len(tracked_by)}"
                        )

                        if tracked_by:
                            accounts.append(account)
                            logger.info(
                                f"    ✅ Аккаунт {account.get('nickname')} добавлен в список проверки"
                            )
                        else:
                            logger.info(
                                f"    ⚠️ Аккаунт {account.get('nickname')} пропущен (нет пользователей)"
                            )

                    except Exception as e:
                        logger.error(f"    ❌ Ошибка чтения файла {filename}: {e}")
                        continue

            logger.info(f"📊 Всего аккаунтов для проверки: {len(accounts)}")
            return accounts

        except Exception as e:
            logger.error(f"❌ Ошибка получения всех аккаунтов: {e}")
            return []

    def get_account_users_count(self, nickname: str) -> int:
        """Возвращает количество пользователей, отслеживающих аккаунт"""
        account = self.load_account(nickname)
        if account:
            return len(account.get("tracked_by", {}))

    def has_verified_dm(self, user_id: int) -> bool:
        """Проверяет проходил ли пользователь проверку ЛС"""
        return len(self.get_user_accounts(user_id)) > 0

    def mark_dm_verified(self, user_id: int):
        """Отмечает что пользователь прошел проверку ЛС"""
        pass
        return 0

    def _get_blacklist_path(self) -> str:
        """Возвращает путь к файлу черного списка."""
        return os.path.join(self.accounts_dir, "blacklist.json")

    def is_blacklisted(self, user_id: int) -> bool:
        """Проверяет, находится ли пользователь в черном списке."""
        path = self._get_blacklist_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                blacklist = json.load(f)
                return user_id in blacklist
        except Exception as e:
            logger.error(f"Ошибка чтения блеклиста: {e}")
            return False

    def add_to_blacklist(self, user_id: int) -> bool:
        """Добавляет пользователя в черный список."""
        path = self._get_blacklist_path()
        blacklist = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    blacklist = json.load(f)
            except Exception:
                logger.exception("Повреждён файл блеклиста; запись отменена")
                return False

        if user_id not in blacklist:
            blacklist.append(user_id)
            try:
                atomic_write_json(path, blacklist)
                return True
            except Exception as e:
                logger.error(f"Ошибка записи в блеклист: {e}")
                return False
        return False

    def remove_from_blacklist(self, user_id: int) -> bool:
        """Удаляет пользователя из черного списка."""
        path = self._get_blacklist_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                blacklist = json.load(f)
            if user_id in blacklist:
                blacklist.remove(user_id)
                atomic_write_json(path, blacklist)
                return True
        except Exception as e:
            logger.error(f"Ошибка удаления из блеклиста: {e}")
            return False
        return False

    def _get_tokens_path(self) -> str:
        """Возвращает путь к файлу с токенами пользователей."""
        return os.path.join(self.accounts_dir, "user_tokens.json")

    def _get_user_languages_path(self) -> str:
        return os.path.join(self.accounts_dir, "user_languages.json")

    def get_user_language(self, user_id: int) -> str:
        """Return the saved or last detected locale; existing users default to Russian."""
        path = self._get_user_languages_path()
        if not os.path.exists(path):
            return "ru"
        try:
            with open(path, "r", encoding="utf-8") as f:
                languages = json.load(f)
            value = languages.get(str(user_id), "ru")
            if isinstance(value, dict):
                value = value.get("locale", "ru")
            if value == "en":
                return "en-US"
            return value if value in ("ru", "en-US", "en-GB") else "ru"
        except Exception as e:
            logger.error("Ошибка чтения языковых настроек: %s", e)
            return "ru"

    def get_user_language_mode(self, user_id: int) -> str:
        path = self._get_user_languages_path()
        if not os.path.exists(path):
            return "auto"
        try:
            with open(path, "r", encoding="utf-8") as f:
                languages = json.load(f)
            if str(user_id) not in languages:
                return "auto"
            entry = languages[str(user_id)]
            return entry.get("mode", "manual") if isinstance(entry, dict) else "manual"
        except Exception:
            return "manual"

    def set_user_language(
        self,
        user_id: int,
        language: str,
        *,
        detected_locale: str = "ru",
        only_if_missing: bool = False,
    ) -> bool:
        """Save a manual language or automatic locale-detection preference."""
        if language not in ("ru", "en-US", "en-GB", "auto"):
            return False
        path = self._get_user_languages_path()
        try:
            languages = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    languages = json.load(f)
            user_key = str(user_id)
            if only_if_missing and user_key in languages:
                return True
            if language == "auto":
                locale = (
                    detected_locale
                    if detected_locale in ("ru", "en-US", "en-GB")
                    else "ru"
                )
                languages[user_key] = {"mode": "auto", "locale": locale}
            else:
                languages[user_key] = language
            atomic_write_json(path, languages)
            return True
        except Exception as e:
            logger.error("Ошибка сохранения языковой настройки для %s: %s", user_id, e)
            return False

    def update_detected_user_language(self, user_id: int, locale: str) -> None:
        """Refresh the stored locale only for users who selected automatic mode."""
        if (
            locale not in ("ru", "en-US", "en-GB")
            or self.get_user_language_mode(user_id) != "auto"
        ):
            return
        path = self._get_user_languages_path()
        try:
            languages = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    languages = json.load(f)
            user_key = str(user_id)
            entry = languages.get(user_key)
            if entry is None:
                languages[user_key] = {"mode": "auto", "locale": locale}
            elif isinstance(entry, dict) and entry.get("mode") == "auto":
                entry["locale"] = locale
            else:
                return
            atomic_write_json(path, languages)
        except Exception as e:
            logger.error("Ошибка обновления языка Discord для %s: %s", user_id, e)

    def save_user_tokens(
        self,
        user_id: int,
        access_token: str,
        refresh_token: str = None,
        expires_in: int = 3600,
        account_nickname: str = None,
    ) -> bool:
        """Сохраняет access_token, refresh_token и время истечения."""
        path = self._get_tokens_path()
        tokens = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tokens = json.load(f)
            except Exception:
                logger.exception("Повреждён файл токенов; запись отменена")
                return False
        user_id_str = str(user_id)
        user_tokens = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": (datetime.now() + timedelta(seconds=expires_in)).isoformat(),
        }
        bound_nickname = account_nickname or tokens.get(user_id_str, {}).get(
            "account_nickname"
        )
        if bound_nickname:
            user_tokens["account_nickname"] = bound_nickname
        provider_user_id = tokens.get(user_id_str, {}).get("provider_issued_user_id")
        if provider_user_id:
            user_tokens["provider_issued_user_id"] = provider_user_id
        tokens[user_id_str] = user_tokens
        try:
            atomic_write_json(path, tokens)
            logger.info(
                f"Токены для {user_id} сохранены до {tokens[user_id_str]['expires_at']}"
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения токенов для {user_id}: {e}", exc_info=True)
            return False

    def get_user_token_simple(self, user_id: int) -> Optional[Dict]:
        """Возвращает словарь с access_token, refresh_token и expires_at для пользователя."""
        path = self._get_tokens_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                all_tokens = json.load(f)
            return all_tokens.get(str(user_id))
        except Exception as e:
            logger.error(f"Ошибка чтения токенов: {e}")
            return None

    def bind_user_token(
        self, user_id: int, account_nickname: str, provider_user_id: str
    ) -> bool:
        """Bind the user's OAuth token to a game account and Discord identity."""
        path = self._get_tokens_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                tokens = json.load(f)
            user_tokens = tokens.get(str(user_id))
            if not user_tokens:
                return False
            user_tokens["account_nickname"] = account_nickname
            user_tokens["provider_issued_user_id"] = str(provider_user_id)
            atomic_write_json(path, tokens)
            return True
        except Exception as e:
            logger.error("Ошибка привязки виджета для %s: %s", user_id, e)
            return False

    def remove_user_token(self, user_id: int) -> bool:
        """Удаляет все токены пользователя."""
        path = self._get_tokens_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                tokens = json.load(f)
            if str(user_id) in tokens:
                del tokens[str(user_id)]
                atomic_write_json(path, tokens)
                logger.info(f"Токены для {user_id} удалены")
                return True
        except Exception as e:
            logger.error(f"Ошибка удаления токенов для {user_id}: {e}")
        return False
