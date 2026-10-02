import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from utils.accounts_manager import AccountsManager
from utils.storage import atomic_write_json


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = AccountsManager(self.tmp.name)

    def test_replace_failure_preserves_original_and_cleans_temporary(self):
        path = Path(self.tmp.name) / "sample.json"
        atomic_write_json(path, {"original": True})
        with patch("utils.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                atomic_write_json(path, {"original": False})
        self.assertEqual(json.loads(path.read_text()), {"original": True})
        self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])

    def test_serialization_failure_preserves_original(self):
        path = Path(self.tmp.name) / "sample.json"
        atomic_write_json(path, {"original": True})
        with self.assertRaises(TypeError):
            atomic_write_json(path, {"bad": object()})
        self.assertEqual(json.loads(path.read_text()), {"original": True})

    def test_initial_stats_written_with_subscription(self):
        self.assertTrue(
            self.manager.add_user_to_account(
                "Player",
                "url",
                1,
                "Main",
                initial_stats={"name": "Player", "score": 100},
            )
        )
        self.assertEqual(self.manager.get_account_stats("PLAYER")["score"], 100)
        self.assertEqual(len(self.manager.get_all_accounts()), 1)

    def test_duplicate_nickname_alias_and_limit(self):
        self.assertTrue(self.manager.add_user_to_account("Player", "url", 1, "Main"))
        self.assertFalse(self.manager.add_user_to_account("PLAYER", "url", 1, "Other"))
        self.assertFalse(self.manager.add_user_to_account("Other", "url", 1, "MAIN"))
        self.assertTrue(self.manager.add_user_to_account("Other", "url", 1, "Other"))
        self.assertTrue(self.manager.add_user_to_account("Third", "url", 1, "Third"))
        self.assertFalse(self.manager.add_user_to_account("Fourth", "url", 1, "Fourth"))

    def test_reserved_and_unsafe_names_do_not_modify_metadata(self):
        for nickname in ["../escape", "", "a&lang=en"]:
            self.assertFalse(
                self.manager.add_user_to_account(nickname, "url", 1, "Main")
            )
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_metadata_and_windows_device_names_are_safe_player_names(self):
        for index, nickname in enumerate(
            ["blacklist", "user_tokens", "USER_LANGUAGES", "CON", "NUL", "COM1"]
        ):
            self.assertTrue(
                self.manager.add_user_to_account(nickname, "url", index, "Main")
            )
            self.assertTrue(
                Path(self.manager._get_account_filename(nickname)).name.startswith("@")
            )
        self.assertFalse((Path(self.tmp.name) / "blacklist.json").exists())
        self.assertEqual(len(self.manager.get_all_accounts()), 6)

    def test_refresh_preserves_widget_binding(self):
        self.assertTrue(
            self.manager.save_user_tokens(
                1, "old", "refresh", account_nickname="Player"
            )
        )
        self.assertTrue(self.manager.bind_user_token(1, "Player", "identity"))
        self.assertTrue(self.manager.save_user_tokens(1, "new", "new-refresh"))
        saved = self.manager.get_user_token_simple(1)
        self.assertEqual(
            (saved["account_nickname"], saved["provider_issued_user_id"]),
            ("Player", "identity"),
        )

    def test_corrupt_tokens_are_not_overwritten(self):
        path = Path(self.tmp.name) / "user_tokens.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertLogs("utils.accounts_manager", level="ERROR"):
            self.assertFalse(self.manager.save_user_tokens(1, "token"))
        self.assertEqual(path.read_text(), "{broken")

    def test_language_preferences_compatible_with_old_and_auto_entries(self):
        self.manager.set_user_language(1, "en-GB")
        self.manager.update_detected_user_language(1, "ru")
        self.assertEqual(self.manager.get_user_language(1), "en-GB")
        self.manager.set_user_language(2, "auto", detected_locale="en-US")
        self.manager.update_detected_user_language(2, "ru")
        self.assertEqual(self.manager.get_user_language(2), "ru")
        self.assertEqual(self.manager.get_user_language_mode(2), "auto")

    def test_legacy_account_data_and_metadata_are_read_separately(self):
        account = {
            "nickname": "Player",
            "api_url": "url",
            "tracked_by": {"1": {"account_name": "Main"}},
            "last_stats": {"score": 123},
        }
        atomic_write_json(Path(self.tmp.name) / "player.json", account)
        self.manager.save_user_tokens(1, "token")
        self.manager.set_user_language(1, "en-US")
        self.assertEqual(self.manager.get_all_accounts(), [account])
        self.assertEqual(
            self.manager.get_user_accounts(1)["Main"]["nickname"], "Player"
        )
