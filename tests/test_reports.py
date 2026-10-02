from datetime import datetime, timezone
import json
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import make_stats, FIXTURE_PATH


class ReportRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stats = make_stats(self.tmp.name)
        self.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    async def test_differences_and_embeds_match_original_in_all_languages(self):
        current = self.fixture["current"]
        for case_name, case in self.fixture["cases"].items():
            with self.subTest(case=case_name):
                diff = self.stats.calculate_difference(current, case["previous"])
                self.assertEqual(diff, case["difference"])
                for language, expected in case["embeds"].items():
                    with patch(
                        "discord.utils.utcnow",
                        return_value=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ):
                        actual = self.stats.create_embed(
                            diff, current, language
                        ).to_dict()
                    self.assertEqual(actual, expected)

    async def test_widget_matches_original(self):
        self.assertEqual(
            self.stats._build_widget_payload(self.fixture["current"], "TestPlayer"),
            self.fixture["widget"],
        )

    async def test_views_match_original(self):
        for language, expected in self.fixture["views"].items():
            with self.subTest(language=language):
                info = self.stats._build_info_view(
                    total_accounts=3, guilds_count=2, ping="20ms", language=language
                )
                help_view = self.stats._build_stats_help_view(
                    accounts_count=1, remaining=2, language=language
                )
                accounts = {
                    "Main": {
                        "nickname": "TestPlayer",
                        "api_url": "https://example.invalid",
                        "original_name": "Main",
                    }
                }
                list_view = self.stats._build_stats_list_view(
                    123, accounts, language=language
                )
                self.assertEqual(info.to_components(), expected["info"])
                self.assertEqual(help_view.to_components(), expected["help"])
                self.assertEqual(list_view.to_components(), expected["list"])

    async def test_rank_boundaries(self):
        for score, title in self.stats.RANKS[:-1]:
            self.assertEqual(self.stats.get_rank_title(score), title)
        self.assertEqual(self.stats.get_rank_title(1600000), "Legend 1")
        self.assertEqual(self.stats.get_rank_title(1800000), "Legend 2")
