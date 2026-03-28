import json
import pytest

import BackendAPI.server as server


pytestmark = pytest.mark.asyncio


class FakeCursor:
    def __init__(self, items):
        self._items = items

    async def to_list(self, length=None):
        return self._items


class FakePlayerModel:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="json", by_alias=True):
        return self.payload


class FakePlayerObj:
    def getClass(self):
        return "fighter"


async def test_dashboard_encounters(monkeypatch, active_user):
    async def fake_find_encounters(username):
        return FakeCursor([
            {
                "name": "Encounter A",
                "date": "2026-03-27",
                "eid": "enc-1",
                "completed": False,
            }
        ])

    monkeypatch.setattr(server, "find_encounters_by_username", fake_find_encounters)

    result = await server.getEncounterPacket(active_user)

    assert result == [
        {
            "name": "Encounter A",
            "date": "2026-03-27",
            "eid": "enc-1",
            "completed": False,
        }
    ]


async def test_dashboard_packet(monkeypatch, active_user):
    async def fake_get_encounter(eid, current_user):
        return {
            "players": [
                {
                    "stats": {
                        "name": "Fighter",
                        "level": 5,
                        "characterClass": "Fighter",
                    }
                }
            ],
            "monsters": [
                {
                    "name": "Goblin",
                    "cr": "1/4",
                    "size": "Small",
                    "creatureType": "Humanoid",
                }
            ],
        }

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)

    result = await server.getEncounterMiniData("enc-1", active_user)

    assert result == {
        "players": [
            {"name": "Fighter", "level": 5, "characterClass": "Fighter"}
        ],
        "monsters": [
            {"name": "Goblin", "cr": "1/4", "size": "Small", "type": "Humanoid"}
        ],
    }


async def test_dashboard_monsters(tmp_path, monkeypatch):
    data_dir = tmp_path / "CoreEngine" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "monster_list.json").write_text(
        json.dumps([{"name": "Goblin"}]),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = server.getMonsters()

    assert result == [{"name": "Goblin"}]


async def test_dashboard_players(monkeypatch, active_user):
    async def fake_find_players(username):
        return FakeCursor([
            {"stats": {"cid": "player-1", "name": "Fighter"}}
        ])

    monkeypatch.setattr(server, "find_players_by_username", fake_find_players)

    result = await server.getPlayers(active_user)

    assert result == [{"stats": {"cid": "player-1", "name": "Fighter"}}]


async def test_dashboard_weapons(tmp_path, monkeypatch):
    data_dir = tmp_path / "CoreEngine" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "weapons_list.json").write_text(
        json.dumps([{"name": "Longsword"}]),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = server.getWeapons()

    assert result == [{"name": "Longsword"}]


async def test_dashboard_available_spells(tmp_path, monkeypatch):
    data_dir = tmp_path / "CoreEngine" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "spell_list.json").write_text(
        json.dumps([
            {"name": "Magic Missile", "level": 1, "classes": ["Wizard", "Sorcerer"]},
            {"name": "Fireball", "level": 3, "classes": ["Wizard", "Sorcerer"]},
            {"name": "Cure Wounds", "level": 1, "classes": ["Cleric", "Bard"]},
        ]),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = server.getSpells("wizard", 6)

    assert result == [
        {"name": "Magic Missile", "level": 1, "classes": ["Wizard", "Sorcerer"]},
        {"name": "Fireball", "level": 3, "classes": ["Wizard", "Sorcerer"]},
    ]


async def test_dashboard_post_player(monkeypatch, active_user):
    payload = {
        "stats": {
            "cid": "player-1",
            "name": "Fighter",
            "characterClass": "Fighter",
        },
        "weapons": [{"name": "Longsword"}],
        "spells": [],
    }
    player_model = FakePlayerModel(payload)

    captured = {}

    monkeypatch.setattr(server.main, "getPlayerStats", lambda p: FakePlayerObj())
    monkeypatch.setattr(server.main, "getSavedWeapons", lambda player, weapons: None)
    monkeypatch.setattr(server.main, "getSavedSpells", lambda player, spells: None)

    async def fake_save_player(player_obj):
        captured["saved"] = True

    async def fake_add_player_to_user(username, cid):
        captured["username"] = username
        captured["cid"] = cid

    monkeypatch.setattr(server.main, "savePlayer", fake_save_player)
    monkeypatch.setattr(server, "addPlayerToUser", fake_add_player_to_user)

    result = await server.postPlayerToPlayerList(player_model, active_user)

    assert result == {"verification": "true"}
    assert captured["saved"] is True
    assert captured["username"] == "charles"
    assert captured["cid"] == "player-1"