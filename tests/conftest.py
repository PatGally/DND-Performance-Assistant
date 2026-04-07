from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture
def active_user():
    return SimpleNamespace(
        username="charles",
        disabled=False,
        encounter_ids=["enc-1"],
        player_ids=["player-1"],
    )