from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from commands.stats import Stats
from utils.accounts_manager import AccountsManager


def make_stats(accounts_dir):
    bot = SimpleNamespace(
        fetch_user=AsyncMock(),
        wait_until_ready=AsyncMock(),
        application_id=123,
        user=SimpleNamespace(id=123),
    )
    stats = Stats(bot)
    stats.accounts_manager = AccountsManager(str(accounts_dir))
    stats._update_widget_for_user = AsyncMock()
    return stats


def make_interaction(user_id=1):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, send=AsyncMock()),
        locale="ru",
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reports.json"
