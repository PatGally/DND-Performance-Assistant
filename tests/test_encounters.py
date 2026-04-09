import pytest

import BackendAPI.server as server


pytestmark = pytest.mark.asyncio


class FakeCursor:
    def __init__(self, items):
        self._items = items

    async def to_list(self, length=None):
        return self._items


class FakeItem:
    def __init__(self, name):
        self._name = name

    def toDict(self):
        return {"name": self._name}


class FakeCreatureObj:
    def __init__(
        self,
        name,
        cid=None,
        active_status_effects=None,
        active_conditions=None,
        spells=None,
        weapons=None,
        hp=10,
        maxhp=10,
        ac=10,
    ):
        self._name = name
        self._cid = cid or name.lower().replace(" ", "-")
        self._effects = active_status_effects or []
        self._conditions = active_conditions or []
        self._spells = spells or []
        self._weapons = weapons or []
        self._hp = hp
        self._maxhp = maxhp
        self._ac = ac

    def getName(self):
        return self._name

    def getCID(self):
        return self._cid

    def getActiveStatusEffects(self):
        return self._effects

    def getActiveConditions(self):
        return self._conditions

    def getSpellLength(self):
        return len(self._spells)

    def getSpell(self, idx):
        return self._spells[idx]

    def getWeaponLength(self):
        return len(self._weapons)

    def getWeapon(self, idx):
        return self._weapons[idx]

    def getHP(self):
        return self._hp

    def getMaxHP(self):
        return self._maxhp

    def getAC(self):
        return self._ac


class FakeEncounterForRecommendation:
    def __init__(self, players=None, monsters=None):
        self._players = players or []
        self._monsters = monsters or []

    def getInitiative(self):
        return [{"name": "Fighter", "currentTurn": True, "turnType": "Player"}]

    def playerSize(self):
        return len(self._players)

    def getPlayer(self, idx):
        return self._players[idx]

    def monsterSize(self):
        return len(self._monsters)

    def getMonster(self, idx):
        return self._monsters[idx]


class FakeEncounterForNextTurn:
    def __init__(self):
        self._initiative = [
            {"name": "Fighter", "currentTurn": True, "turnType": "Player"},
            {"name": "Goblin", "currentTurn": False, "turnType": "Monster"},
        ]
        self._players = [FakeCreatureObj("Fighter")]
        self._monsters = [FakeCreatureObj("Goblin")]

    def getInitiative(self):
        return self._initiative

    def playerSize(self):
        return len(self._players)

    def getPlayer(self, idx):
        return self._players[idx]

    def monsterSize(self):
        return len(self._monsters)

    def getMonster(self, idx):
        return self._monsters[idx]

    def getResultByID(self, result_id):
        return None


class FakeEncounterModel:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="json", by_alias=True):
        return self.payload


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    server.app.dependency_overrides = {}
    yield
    server.app.dependency_overrides = {}


async def test_get_creature_position(monkeypatch, active_user):
    async def fake_get_creature(eid, cid, current_user):
        return {"stats": {"position": [[3, 4]]}}

    monkeypatch.setattr(server, "getCreature", fake_get_creature)

    result = await server.getCreaturePosition("enc-1", "player-1", active_user)

    assert result == [[3, 4]]


async def test_get_creature_actions(monkeypatch, active_user):
    fake_creature = FakeCreatureObj(
        "Fighter",
        cid="player-1",
        spells=[FakeItem("Shield")],
        weapons=[FakeItem("Longsword")],
    )

    async def fake_get_encounter(eid, current_user):
        return {"eid": eid}

    async def fake_get_creature_obj(encounter, cid):
        assert cid == "player-1"
        return fake_creature

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)
    monkeypatch.setattr(server.main, "loadEncounter", lambda enc: object())
    monkeypatch.setattr(server, "getCreatureObj", fake_get_creature_obj)
    monkeypatch.setattr(server.json, "load", lambda _: [])

    result = await server.getCreatureActions("enc-1", "player-1", active_user)

    assert result == [{"name": "Shield"}, {"name": "Longsword"}]


async def test_get_creature(monkeypatch, active_user):
    encounter = {
        "players": [
            {
                "stats": {
                    "cid": "player-1",
                    "name": "Fighter",
                    "characterClass": "Fighter",
                    "level": 5,
                },
                "weapons": [],
                "spells": [],
            }
        ],
        "monsters": [],
    }

    async def fake_get_encounter(eid, current_user):
        return encounter

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)

    result = await server.getCreature("enc-1", "player-1", active_user)

    assert result["stats"]["cid"] == "player-1"
    assert result["stats"]["name"] == "Fighter"


async def test_add_to_encounter(monkeypatch, active_user):
    encounter = {"players": [], "monsters": []}
    creature = {"stats": {"cid": "player-1", "name": "Fighter"}}

    async def fake_get_encounter(eid, current_user):
        return encounter

    async def fake_save_encounter(obj):
        return None

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)
    monkeypatch.setattr(server, "requireOwnedPlayer", lambda cid, user: None)
    monkeypatch.setattr(server.main, "loadEncounter", lambda enc: enc)
    monkeypatch.setattr(server.main, "saveEncounter", fake_save_encounter)

    result = await server.addtoEncounter("enc-1", creature, active_user)

    assert result == {"verification": "true"}
    assert encounter["players"][0]["stats"]["cid"] == "player-1"


async def test_get_map_link(monkeypatch, active_user):
    async def fake_get_encounter(eid, current_user):
        return {
            "mapData": {
                "map": {
                    "image": {
                        "mapLink": "https://example.com/map.png"
                    }
                }
            }
        }

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)

    result = await server.getMapLink("enc-1", active_user)

    assert result == "https://example.com/map.png"


async def test_get_encounter(monkeypatch, active_user):
    async def fake_get_by_eid(eid):
        return {"eid": eid, "name": "Cave Battle"}

    monkeypatch.setattr(server, "get_encounter_by_eid", fake_get_by_eid)

    result = await server.getEncounter("enc-1", active_user)

    assert result["eid"] == "enc-1"
    assert result["name"] == "Cave Battle"


async def test_action_recommendation(monkeypatch, active_user):
    fake_player = FakeCreatureObj("Fighter", cid="player-1")
    fake_encounter = FakeEncounterForRecommendation(players=[fake_player])

    async def fake_get_encounter(eid, current_user):
        return {"eid": eid}

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)
    monkeypatch.setattr(server.main, "loadEncounter", lambda enc: fake_encounter)
    monkeypatch.setattr(server.main, "setActiveInitiative", lambda enc: enc.getInitiative())
    monkeypatch.setattr(
        server.main,
        "playerTurn",
        lambda player, initiative: [{"name": "Attack", "overallRank": 1}],
    )

    result = await server.actionRecommendation("enc-1", "player-1", active_user)

    assert result == [{"name": "Attack", "overallRank": 1}]


async def test_get_next_turn(monkeypatch, active_user):
    fake_encounter = FakeEncounterForNextTurn()

    async def fake_get_encounter(eid, current_user):
        return {"eid": eid}

    async def fake_save_encounter(enc):
        return None

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)
    monkeypatch.setattr(server.main, "loadEncounter", lambda enc: fake_encounter)
    monkeypatch.setattr(server.main, "saveEncounter", fake_save_encounter)
    monkeypatch.setattr(server.main, "setActiveInitiative", lambda enc: enc.getInitiative())
    monkeypatch.setattr(server.main, "ensureList", lambda x: x if isinstance(x, list) else [x])
    monkeypatch.setattr(server.main, "endSpellEffect", lambda *args, **kwargs: None)

    result = await server.getNextTurn("enc-1", active_user)

    assert result == []
    assert fake_encounter.getInitiative()[0]["currentTurn"] is False
    assert fake_encounter.getInitiative()[1]["currentTurn"] is True


async def test_get_current_turn(monkeypatch, active_user):
    async def fake_get_encounter(eid, current_user):
        return {
            "initiative": [
                {"name": "Goblin", "currentTurn": False},
                {"name": "Fighter", "currentTurn": True},
            ]
        }

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)

    result = await server.getTurn("enc-1", active_user)

    assert result == "Fighter"


async def test_get_initiative(monkeypatch, active_user):
    fake_init = [
        {
            "name": "Fighter",
            "currentTurn": True,
            "turnType": "Player",
            "Statblock": FakeCreatureObj(
                "Fighter",
                cid="player-1",
                hp=35,
                maxhp=42,
                ac=17,
            ),
        }
    ]

    async def fake_get_encounter(eid, current_user):
        return {"eid": eid}

    monkeypatch.setattr(server, "getEncounter", fake_get_encounter)
    monkeypatch.setattr(server.main, "loadEncounter", lambda enc: object())
    monkeypatch.setattr(server.main, "setActiveInitiative", lambda enc: fake_init)

    result = await server.getSimulationInitiative("enc-1", active_user)

    assert result == [
        {
            "name": "Fighter",
            "currentTurn": True,
            "turnType": "Player",
            "hp": 35,
            "maxhp": 42,
            "ac": 17,
            "cid": "player-1",
        }
    ]


async def test_post_encounter(monkeypatch, active_user):
    payload = {
        "eid": "enc-1",
        "name": "Cave Battle",
        "players": [],
        "monsters": [],
        "date": "2026-03-27",
    }
    encounter_model = FakeEncounterModel(payload)

    saved = {}

    async def fake_upsert(encounter_json):
        saved["encounter"] = encounter_json

    async def fake_add_encounter_to_user(username, eid):
        saved["username"] = username
        saved["eid"] = eid

    monkeypatch.setattr(server, "upsert_encounter_dict", fake_upsert)
    monkeypatch.setattr(server, "addEncounterToUser", fake_add_encounter_to_user)

    result = await server.postEncounter(encounter_model, active_user)

    assert result == {"verification": "true"}
    assert saved["encounter"]["eid"] == "enc-1"
    assert saved["username"] == "charles"
    assert saved["eid"] == "enc-1"