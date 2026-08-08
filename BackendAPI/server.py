import copy
import json
import logging
import math
import os
from typing import Union, List, Any
import uuid
from fastapi.middleware.cors import CORSMiddleware
from logs.loggingConfig import setupLogging
from BackendAPI.models import Monster, Player, Encounter, ActionRequest
from BackendAPI.models.DNDClasses import Barbarian, Bard, Cleric, Druid, Fighter, Paladin, Sorcerer
from pymongo.errors import PyMongoError
from dotenv import load_dotenv
import httpx
from ml.inference import get_predictor
from ml.main_hooks import build_scored_training_record_inputs
from ml.training_hooks import persist_labeled_action_record
from ml.training_service import maybe_train_after_action_uses
from fastapi.responses import StreamingResponse
import main
from fastapi import FastAPI, Request, Depends, HTTPException, status, Response
from fastapi.params import Cookie
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import time
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from pathlib import Path

from .models.AffectedCreatures import AffectedCreaturesRequest
from .models.PreTurnRequest import PreTurnRequest
from .models.UserAuth import (TokenData, UserCreate,
                             UserInDB, UserPublic, ChangePasswordRequest, SetDisabledRequest, GoogleAuthRequest)
from db.db_access import init_indexes, get_user_by_username, get_encounter_by_eid, \
    upsert_encounter_dict, find_encounters_by_username, find_players_by_username, upsert_user_dict, addEncounterToUser, \
    addPlayerToUser, deleteEncounterByEid, deletePlayerByCid, getUserByGoogleSub
from pathlib import Path

setupLogging()
logger = logging.getLogger("backend")
load_dotenv(".env")

BASE_DIR = Path(__file__).resolve().parent.parent
status_path = BASE_DIR / "CoreEngine" / "data" / "status_effect_list.json"
condition_path = BASE_DIR / "CoreEngine" / "data" / "condition_list.json"

env = os.getenv("ENV", "development")
if env == "production":
    load_dotenv(".env.production", override=True)
else:
    load_dotenv(".env.development", override=True)

#USER VALIDATION
ACCESS_SECRET_KEY = os.getenv("ACCESS_SECRET_KEY")
REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 30))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = os.getenv("REFRESH_COOKIE_PATH")
REFRESH_STORE_PATH = Path("CoreEngine/data/refresh_store.json")
ORIGINS = [origin for origin in [os.getenv("ORIGIN1"), os.getenv("ORIGIN2")] if origin]
app = FastAPI()
pwdContext = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2Scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], #DELETE, PUT, etc
    allow_headers=["*"], #Specific requests from specific sources.
)

handlers = {
    "statArray": main.handle_stat_array,
    "saveProfs": main.handle_save_profs,
    "damResists": main.handle_dam_resistances,
    "damImmunes": main.handle_dam_immunes,
    "damVulns": main.handle_dam_vulns,
    "conImmunes": main.handle_con_immunes,
    "activeConditions": main.handle_active_conditions,
    "activeStatusEffects": main.handle_active_status_effects,
    "hp": main.handle_hp,
    "position": main.handle_position,
    "ac": main.handle_ac,
    "lResists": main.handle_l_resists,
    "spellSlots": main.handle_spell_slots,
    "charges": main.handle_charges
}

@app.middleware("http")
async def logRequests(request: Request, callNext):
    startTime = time.time()
    logger.info("Incoming request: %s %s", request.method, request.url.path)
    response = await callNext(request)
    duration = time.time() - startTime
    logger.info(
        "Completed request: %s %s Status=%s Duration=%.4fs",request.method,request.url.path,response.status_code,duration)

    return response
AnyPlayer = Union[Fighter, Barbarian, Bard, Cleric, Druid, Paladin, Sorcerer]
async def getCurrentUser(token : str = Depends(oauth2Scheme)):
    credentialsException = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate" : "Bearer"})
    try:
        payload = jwt.decode(token, ACCESS_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise credentialsException
        username: str | None = payload.get("sub")
        if username is None:
            raise credentialsException
        tokenData = TokenData(username=username)
    except JWTError:
        raise credentialsException
    user = await getUser(username=tokenData.username)
    if user is None:
        raise credentialsException
    return user
async def getCurrentActiveUser(currentUser : UserInDB = Depends(getCurrentUser)):
    if currentUser.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return currentUser
def requireOwnedEncounter(eid: str, currentUser: UserInDB) -> None:
    if eid not in currentUser.encounter_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found"
        )
async def getCreatureObj(encounter, cid):
    creatures = []
    players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
    monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
    creatures.extend(players)
    creatures.extend(monsters)
    for creature in creatures:
        if creature.getCID() == cid:
            return creature
def requireOwnedPlayer(pid: str, currentUser: UserInDB) -> None:
    if pid not in currentUser.player_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )
def isPlayer(creature):
    if isinstance(creature, dict):
        if creature.get("stats", {}):
            return True
        else:
            return False
    else:
        try:
            caster = creature.isCaster()
            return False
        except:
            return True


async def _request_json_object(request: Request) -> dict:
    """Return the original JSON body when FastAPI model parsing dropped extras."""
    try:
        payload = await request.json()
    except (json.JSONDecodeError, RuntimeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _model_json_payload(value) -> dict:
    if isinstance(value, dict):
        return copy.deepcopy(value)

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json", by_alias=True)
        return payload if isinstance(payload, dict) else {}

    return {}


def _persisted_monster_by_cid(encounter_data: dict, cid: str) -> dict | None:
    wanted_cid = str(cid).strip().lower()
    if not wanted_cid or not isinstance(encounter_data, dict):
        return None

    for monster in encounter_data.get("monsters", []):
        if not isinstance(monster, dict):
            continue
        monster_cid = monster.get("cid")
        if monster_cid in (None, "") and isinstance(monster.get("stats"), dict):
            monster_cid = monster["stats"].get("cid")
        if str(monster_cid or "").strip().lower() == wanted_cid:
            return monster

    return None


def _restore_persisted_multiattack(monster_obj, encounter_data: dict, cid: str) -> None:
    persisted = _persisted_monster_by_cid(encounter_data, cid)
    if persisted is None:
        return

    raw_multiattack = persisted.get(
        "multiattack",
        persisted.get("multiAttack", {}),
    )
    main.setMonsterMultiattack(monster_obj, raw_multiattack)


def _merge_raw_monster_multiattacks(
    validated_encounter: dict,
    raw_encounter: dict,
) -> None:
    """Preserve Monster.multiattack even when the Pydantic model omits extras."""
    validated_monsters = validated_encounter.get("monsters", [])
    raw_monsters = raw_encounter.get("monsters", [])
    if not isinstance(validated_monsters, list) or not isinstance(raw_monsters, list):
        return

    raw_by_cid = {}
    for raw_monster in raw_monsters:
        if not isinstance(raw_monster, dict):
            continue
        raw_cid = str(raw_monster.get("cid", "")).strip().lower()
        if raw_cid:
            raw_by_cid[raw_cid] = raw_monster

    for index, monster in enumerate(validated_monsters):
        if not isinstance(monster, dict):
            continue

        cid = str(monster.get("cid", "")).strip().lower()
        raw_monster = raw_by_cid.get(cid) if cid else None
        if raw_monster is None and index < len(raw_monsters):
            indexed_candidate = raw_monsters[index]
            raw_monster = indexed_candidate if isinstance(indexed_candidate, dict) else None
        if raw_monster is None:
            continue

        raw_multiattack = raw_monster.get(
            "multiattack",
            raw_monster.get("multiAttack", {}),
        )
        normalized = main.normalizeMonsterMultiattack(raw_multiattack)
        if normalized:
            monster["multiattack"] = normalized

@app.on_event("startup")
async def startup_event():
    await init_indexes()


@app.get("/drive-image/{file_id}")
async def get_drive_image(file_id: str):
    url = f"https://drive.google.com/uc?export=view&id={file_id}"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url)

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch image")

        content_type = response.headers.get("content-type", "image/jpeg")

        return StreamingResponse(
            iter([response.content]),
            media_type=content_type
        )

@app.get("/encounter/{eid}/creature/{cid}/position")
async def getCreaturePosition(eid : str, cid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    creature = await getCreature(eid, cid, currentUser)
    if isinstance(creature.get("stats", {}), dict):
        return creature.get("stats").get("position", [0, 0])
    return creature.get("position", [0, 0])
@app.get("/encounter/{eid}/creature/{cid}/actions")
async def getCreatureActions(eid : str, cid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounter_data = await getEncounter(eid, currentUser)
    encounter = main.loadEncounter(encounter_data)
    if encounter is None:
        return []
    creature = await getCreatureObj(encounter, cid)
    if isPlayer(creature):
        actions = []
        spells = [creature.getSpell(i).toDict() for i in range(creature.getSpellLength())]
        weapons = [creature.getWeapon(i).toDict() for i in range(creature.getWeaponLength())]
        actions.extend(spells)
        actions.extend(weapons)
    else:
        # The persisted stat block is authoritative. This also covers
        # CoreEngine Monster versions that do not serialize multiattack.
        _restore_persisted_multiattack(creature, encounter_data, cid)

        actions = [creature.getAction(i).toDict() for i in range(creature.getActionLength())]
        multiattack_action = main.buildMonsterMultiattackActionPayload(creature)
        if multiattack_action is not None:
            actions.insert(0, multiattack_action)
        if creature.isCaster():
            for i in range(creature.getSpellLength()):
                spell = creature.getSpell(i)
                if isinstance(spell, dict) and "spellData" in spell:
                    actions.append(spell["spellData"].toDict())
                else:
                    actions.append(spell)
    with open("CoreEngine/data/basic_actions.json", "r") as brf:
        basics = json.load(brf)
        actions.extend(basics)
    return actions
@app.get("/encounter/{eid}/creature/{cid}", response_model=Union[AnyPlayer, Monster])
async def getCreature(eid : str, cid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    enc = await getEncounter(eid, currentUser)
    creatures = enc.get("players", []) + enc.get("monsters", [])
    cids = []
    for creature in creatures:
        if isPlayer(creature):
            foundcid = creature.get("stats", {}).get("cid", "")
        else:
            foundcid = creature.get("cid", "")
        cids.append(foundcid)
    try:
        creatureIdx = cids.index(cid)
    except:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player not found"
        )
    return creatures[creatureIdx]
@app.post("/encounter/{eid}/creature")
async def addtoEncounter(eid : str, request: Request, creature : Union[AnyPlayer, Player, Monster], currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounter = await getEncounter(eid, currentUser)
    raw_creature = await _request_json_object(request)
    creature_payload = _model_json_payload(creature)

    if isPlayer(creature_payload):
        requireOwnedPlayer(creature_payload["stats"]["cid"], currentUser)
        encounter.get("players", []).append(creature_payload)
        pass
    else:
        normalized_multiattack = main.normalizeMonsterMultiattack(
            raw_creature.get("multiattack", raw_creature.get("multiAttack", {}))
        )
        if normalized_multiattack:
            creature_payload["multiattack"] = normalized_multiattack
        encounter.get("monsters", []).append(creature_payload)
    try:
        await main.saveEncounter(main.loadEncounter(encounter))
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Failed to save Encounter: {err}")
    return {"verification" : "true"}
@app.get("/encounter/{eid}/state/maplink")
async def getMapLink(eid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    enc = await getEncounter(eid, currentUser)
    mapLink = None
    mapData = enc.get("mapData")
    if mapData:
        mapLink = mapData.get("map", {}).get("image", {}).get("mapLink", {})
    return mapLink

@app.get("/encounter/{eid}/state")
async def getEncounter(eid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    requireOwnedEncounter(eid, currentUser)
    try:
        encounter = await get_encounter_by_eid(eid)
        encounter.pop("_id", None)
        return encounter
    except:
        raise HTTPException(status_code=404, detail="Encounter not found")

@app.get("/encounter/{eid}/recommendation/{cid}")
async def actionRecommendation(eid: str, cid: str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounter_data = await getEncounter(eid, currentUser)
    encounter = main.loadEncounter(encounter_data)
    initiative = main.setActiveInitiative(encounter)

    players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
    playercids = [player.getCID().lower() for player in players]

    if cid.lower() in playercids:
        player = players[playercids.index(cid.lower())]
        rankings = main.playerTurn(player, initiative, encounter_id=eid)
        return rankings
    else:
        monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
        monstercids = [monster.getCID().lower() for monster in monsters]
        if cid.lower() in monstercids:
            monster = monsters[monstercids.index(cid.lower())]

            # Restore immediately before analysis so monsterTurn can synthesize
            # and rank the aggregate option on every CoreEngine version.
            _restore_persisted_multiattack(monster, encounter_data, cid)

            rankings = main.monsterTurn(monster, initiative, encounter_id=eid)
            return rankings
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Creature not found"
            )

@app.delete("/encounter/{eid}")
async def deleteEncounter(eid: str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    userDeleted, encounterDeleted = await deleteEncounterByEid(eid, currentUser.username)

    if not encounterDeleted:
        raise HTTPException(status_code=404, detail="Encounter not found.")

    return {
        "message": "Encounter deleted successfully",
        "eid": eid,
        "removedFromUser": userDeleted
    }

@app.delete("/dashboard/players/{cid}")
async def deletePlayer(cid: str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    userDeleted, playerDeleted = await deletePlayerByCid(cid, currentUser.username)

    if not playerDeleted:
        raise HTTPException(status_code=404, detail="Player not found.")

    return {
        "message": "Player deleted successfully",
        "cid" : cid,
        "removedFromUser": userDeleted
    }

@app.delete("/encounter/{eid}/creature/{cid}/pre-effect/{resultID}")
async def endPreEffect(
    eid: str,
    cid: str,
    resultID: str,
    currentUser: UserInDB = Depends(getCurrentActiveUser)
):
    """
    End a lingering pre-turn result early.

    This keeps the existing frontend route while routing cleanup through the
    same result-based function used by the generic effect-result endpoint.
    """
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creatureObj = await getCreatureObj(encounter, cid)

    if creatureObj is None:
        raise HTTPException(status_code=404, detail="Creature not found.")

    removed = main.endTimedResultForCreature(resultID, creatureObj, encounter)
    concentration_ended = main.reconcileConcentrationForResult(
        resultID, encounter
    )
    await main.saveEncounter(encounter)

    return {
        "verification": "true",
        "removed": removed,
        "concentrationEnded": concentration_ended,
        "resultID": resultID,
    }


@app.delete("/encounter/{eid}/creature/{cid}/effect-result/{resultID}")
async def endCreatureEffectResult(
    eid: str,
    cid: str,
    resultID: str,
    currentUser: UserInDB = Depends(getCurrentActiveUser)
):
    """Remove every active effect created by one action result for one creature."""
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creatureObj = await getCreatureObj(encounter, cid)

    if creatureObj is None:
        raise HTTPException(status_code=404, detail="Creature not found.")

    removed = main.endTimedResultForCreature(resultID, creatureObj, encounter)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail="No active effect or timer was found for this result."
        )

    concentration_ended = main.reconcileConcentrationForResult(
        resultID, encounter
    )
    await main.saveEncounter(encounter)

    return {
        "verification": "true",
        "removed": True,
        "concentrationEnded": concentration_ended,
        "resultID": resultID,
    }


@app.delete("/encounter/{eid}/creature/{cid}/condition/{conditionName}")
async def removeCreatureCondition(
    eid: str,
    cid: str,
    conditionName: str,
    currentUser: UserInDB = Depends(getCurrentActiveUser)
):
    """Remove only the named condition while leaving sibling result effects active."""
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creatureObj = await getCreatureObj(encounter, cid)

    if creatureObj is None:
        raise HTTPException(status_code=404, detail="Creature not found.")

    def _condition_is_active() -> bool:
        for condition in creatureObj.getActiveConditions() or []:
            if isinstance(condition, str):
                active_name = condition
            elif isinstance(condition, dict):
                active_name = condition.get("cond", condition.get("name", ""))
            else:
                continue

            if str(active_name).lower() == conditionName.lower():
                return True

        return False

    if not _condition_is_active():
        raise HTTPException(
            status_code=404,
            detail=f"Condition '{conditionName}' is not active."
        )

    linked_result_ids = []
    for condition in creatureObj.getActiveConditions() or []:
        if not isinstance(condition, dict):
            continue
        active_name = condition.get("cond", condition.get("name", ""))
        if str(active_name).lower() != conditionName.lower():
            continue
        linked_result_ids.extend(
            main.ensureList(
                condition.get("resultID", condition.get("resultid", []))
            )
        )

    main.removeCondition(conditionName, creatureObj)
    if _condition_is_active():
        raise HTTPException(
            status_code=400,
            detail=f"Condition '{conditionName}' cannot be removed."
        )

    main.pruneCreatureTurnCounts(creatureObj, encounter)
    concentration_ended = False
    for result_id in linked_result_ids:
        concentration_ended = (
            main.reconcileConcentrationForResult(result_id, encounter)
            or concentration_ended
        )
    await main.saveEncounter(encounter)

    return {
        "verification": "true",
        "removed": True,
        "concentrationEnded": concentration_ended,
        "effectType": "condition",
        "effectName": conditionName,
    }


@app.delete("/encounter/{eid}/creature/{cid}/status-effect/{effectName}")
async def removeCreatureStatusEffect(
    eid: str,
    cid: str,
    effectName: str,
    currentUser: UserInDB = Depends(getCurrentActiveUser)
):
    """Remove only the named status effect while leaving sibling effects active."""
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creatureObj = await getCreatureObj(encounter, cid)

    if creatureObj is None:
        raise HTTPException(status_code=404, detail="Creature not found.")

    def _status_is_active() -> bool:
        return any(
            isinstance(effect, dict)
            and str(effect.get("name", "")).lower() == effectName.lower()
            for effect in creatureObj.getActiveStatusEffects() or []
        )

    if not _status_is_active():
        raise HTTPException(
            status_code=404,
            detail=f"Status effect '{effectName}' is not active."
        )

    active_effect = next(
        (
            effect
            for effect in creatureObj.getActiveStatusEffects() or []
            if isinstance(effect, dict)
            and str(effect.get("name", "")).lower() == effectName.lower()
        ),
        None,
    )
    active_effect_data = (active_effect or {}).get("effect", {})
    if not isinstance(active_effect_data, dict):
        active_effect_data = {}
    linked_result_ids = main.ensureList(
        active_effect_data.get("resultID", [])
    )
    concentration_ended = False

    if effectName.strip().lower() == "concentration":
        concentration = _active_concentration(creatureObj)
        concentration_result_id = _concentration_result_id(concentration)

        concentration_ended = main.endConcentrationForResult(
            concentration_result_id, encounter
        )
        if not concentration_ended:
            main.endConcentration(
                creatureObj,
                concentration or {},
                main.setActiveInitiative(encounter),
                _safe_concentration_mapdata(encounter.getMapData()),
            )
            concentration_ended = True
    else:
        main.removeStatusEffect(effectName, creatureObj)
        for result_id in linked_result_ids:
            concentration_ended = (
                main.reconcileConcentrationForResult(result_id, encounter)
                or concentration_ended
            )
    if _status_is_active():
        raise HTTPException(
            status_code=400,
            detail=f"Status effect '{effectName}' could not be removed."
        )

    main.pruneCreatureTurnCounts(creatureObj, encounter)
    await main.saveEncounter(encounter)

    return {
        "verification": "true",
        "removed": True,
        "concentrationEnded": concentration_ended,
        "effectType": "status-effect",
        "effectName": effectName,
    }

def unpackEntry(entry, activeInitiative):
    """Resolve an action request using either creature CIDs or names.

    The frontend normally submits CIDs, while some older callers still submit
    creature names. Supporting both prevents valid ruleset requests from
    failing with an internal 404 after the FastAPI route has already matched.
    """
    actor_key = str(entry.get("actor", "")).strip().lower()
    action_name = str(entry.get("action", "")).strip()
    targets = entry.get("targets", []) or []
    target_keys = {
        str(target).strip().lower()
        for target in targets
        if target not in (None, "")
    }

    actorObj = None
    selectedTargets = []
    isSpell = False

    for creature in activeInitiative:
        if not isinstance(creature, dict):
            continue

        statblock = creature.get("Statblock")
        if statblock is None:
            continue

        creature_cid = str(
            creature.get("cid", statblock.getCID())
        ).strip().lower()
        creature_name = str(
            creature.get("name", statblock.getName())
        ).strip().lower()

        if actor_key in {creature_cid, creature_name}:
            actorObj = statblock

        statblock_cid = str(statblock.getCID()).strip().lower()
        statblock_name = str(statblock.getName()).strip().lower()
        if target_keys.intersection({statblock_cid, statblock_name}):
            selectedTargets.append(statblock)

    if actorObj is None:
        raise HTTPException(
            status_code=404,
            detail=f"Actor '{entry.get('actor')}' was not found in initiative.",
        )

    action = actorObj.getSpellByName(action_name)
    if action:
        isSpell = True
    elif isPlayer(actorObj):
        action = None
        for index in range(actorObj.getWeaponLength()):
            weapon = actorObj.getWeapon(index)
            if weapon.getName().strip().lower() == action_name.lower():
                action = weapon
                break
    else:
        action = actorObj.getActionByName(action_name)

    if not action:
        normalized_action_name = action_name.lower()
        if normalized_action_name in {"dodge", "shove", "grapple"}:
            basic_actions = getBasicActions()
            if normalized_action_name == "grapple":
                action = main.translateBasicAction(actorObj, basic_actions[0])
            elif normalized_action_name == "shove":
                action = main.translateBasicAction(actorObj, basic_actions[1])
            else:
                action = main.translateBasicAction(actorObj, basic_actions[2])
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Action '{action_name}' was not found for {actorObj.getName()}.",
            )

    if isinstance(action, dict) and "spellData" in action:
        action = action["spellData"]

    return actorObj, action, targets, isSpell, selectedTargets
def _persist_lingering_aoe_token(encounter, token: dict | None) -> None:
        def _get_map_data(encounter):
            if hasattr(encounter, "getMapData"):
                return encounter.getMapData()
            return getattr(encounter, "_Encounter__mapData", None)

        def _set_map_data(encounter, map_data):
            if hasattr(encounter, "setMapData"):
                encounter.setMapData(map_data)
            else:
                setattr(encounter, "_Encounter__mapData", map_data)

        if not token or token.get("timing") != "lingering":
            return

        map_data = _get_map_data(encounter)
        if map_data is None:
            return

        layers = map_data.setdefault("layers", {})
        aoe_tokens = layers.setdefault("aoeTokens", [])

        aoe_tokens = [
            existing
            for existing in aoe_tokens
            if existing.get("resultID") != token.get("resultID")
        ]

        aoe_tokens.append(token)

        layers["aoeTokens"] = aoe_tokens
        map_data["layers"] = layers
        _set_map_data(encounter, map_data)
def _get_actor_and_turn_entry(actor_key: str, active_initiative, encounter_initiative):
    """Return the actor object and persisted turn entry by CID or name."""
    normalized_actor_key = str(actor_key).strip().lower()
    actor_obj = None

    for creature in active_initiative:
        if not isinstance(creature, dict):
            continue

        statblock = creature.get("Statblock")
        if statblock is None:
            continue

        creature_cid = str(
            creature.get("cid", statblock.getCID())
        ).strip().lower()
        creature_name = str(
            creature.get("name", statblock.getName())
        ).strip().lower()

        if normalized_actor_key in {creature_cid, creature_name}:
            actor_obj = statblock
            break

    if actor_obj is None:
        raise HTTPException(
            status_code=404,
            detail=f"Actor '{actor_key}' was not found.",
        )

    actor_cid = str(actor_obj.getCID()).strip().lower()
    actor_name = str(actor_obj.getName()).strip().lower()
    turn_entry = None

    for creature in encounter_initiative:
        if not isinstance(creature, dict):
            continue

        initiative_cid = str(creature.get("cid", "")).strip().lower()
        initiative_name = str(creature.get("name", "")).strip().lower()

        if actor_cid == initiative_cid or actor_name == initiative_name:
            turn_entry = creature
            break

    if turn_entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Actor '{actor_obj.getName()}' was not found in initiative.",
        )

    return actor_obj, turn_entry

def _consume_action_cost(turn_entry: dict, action_cost: str) -> None:
    normalized_cost = str(action_cost).strip().lower()
    if normalized_cost == "action":
        if turn_entry.get("actionResource"):
            turn_entry["actionResource"] -= 1
            return
        raise HTTPException(status_code=500, detail="Insufficient action resources")

    if normalized_cost == "bonus action":
        if turn_entry.get("bonusActionResource"):
            turn_entry["bonusActionResource"] -= 1
            return
        if turn_entry.get("actionResource"):
            turn_entry["actionResource"] -= 1
            return
        raise HTTPException(status_code=500, detail="Insufficient action resources")

    raise HTTPException(status_code=500, detail="Invalid Action cost")


def _active_concentration(creature_obj):
    getter = getattr(creature_obj, "getActiveStatusEffect", None)
    if not callable(getter):
        return None
    return getter("concentration") or getter("Concentration")


def _safe_concentration_mapdata(mapdata):
    if not isinstance(mapdata, dict):
        return {"layers": {"aoeTokens": []}}
    mapdata.setdefault("layers", {}).setdefault("aoeTokens", [])
    return mapdata


def _concentration_result_id(concentration) -> str | None:
    if not isinstance(concentration, dict):
        return None
    effect = concentration.get("effect")
    if not isinstance(effect, dict):
        return None
    result_id = effect.get("resultID")
    if result_id in (None, ""):
        return None
    return str(result_id)


def _pending_concentration_checks_after_damage(
    *,
    selected_targets,
    action_entry: dict,
    concentrating_before: dict[str, str | None],
):
    """Build authoritative concentration checks after damage is applied.

    ``main.executeAction`` normalizes the action's damage arrays to the damage
    actually taken, including hit/save handling and damage resistance,
    vulnerability, and immunity.  The frontend therefore never supplies the DC.
    """
    base_damage = (action_entry.get("outcome") or {}).get("diceResults", []) or []
    extra_damage = (action_entry.get("extraOutcome") or {}).get("extraDiceResults", []) or []
    checks = []

    for index, target in enumerate(selected_targets):
        cid = str(target.getCID())
        if cid not in concentrating_before:
            continue

        try:
            applied_base = float(base_damage[index]) if index < len(base_damage) else 0.0
        except (TypeError, ValueError):
            applied_base = 0.0
        try:
            applied_extra = float(extra_damage[index]) if index < len(extra_damage) else 0.0
        except (TypeError, ValueError):
            applied_extra = 0.0

        applied_damage = max(0.0, applied_base + applied_extra)
        if applied_damage <= 0:
            continue

        dc = max(10, math.floor(applied_damage / 2))
        result_id = str(action_entry.get("resultID"))
        checks.append({
            "checkID": str(uuid.uuid4()),
            "cid": cid,
            "name": target.getName(),
            "damage": int(applied_damage) if applied_damage.is_integer() else applied_damage,
            "dc": dc,
            "required": True,
            "resolved": False,
            "cancelled": False,
            "resultID": result_id,
            "concentrationResultID": concentrating_before[cid],
            "sourceAction": action_entry.get("action"),
            "targetIndex": index,
        })

    return checks


def _iter_concentration_checks(encounter):
    for result_index in range(encounter.resultSize()):
        result = encounter.getResultByIdx(result_index)
        if not isinstance(result, dict):
            continue
        checks = result.get("concentrationChecks", [])
        if not isinstance(checks, list):
            continue
        for check in checks:
            if isinstance(check, dict):
                yield result, check


def _same_optional_result_id(left, right) -> bool:
    if left in (None, "") or right in (None, ""):
        return left in (None, "") and right in (None, "")
    return str(left) == str(right)


def _cancel_remaining_concentration_checks(
    encounter,
    *,
    cid: str,
    concentration_result_id,
    exclude_check_id: str,
):
    cancelled = []
    for _, check in _iter_concentration_checks(encounter):
        if str(check.get("checkID", "")) == exclude_check_id:
            continue
        if str(check.get("cid", "")) != cid:
            continue
        if not _same_optional_result_id(
            check.get("concentrationResultID"),
            concentration_result_id,
        ):
            continue
        if check.get("resolved") or check.get("cancelled"):
            continue

        check["resolved"] = True
        check["cancelled"] = True
        check["required"] = False
        check["reason"] = "Concentration already ended after an earlier failed save."
        cancelled.append(str(check.get("checkID", "")))

    return cancelled

def _expanded_multiattack_names(multiattack: dict) -> list[str]:
    return main.expandMonsterMultiattack(multiattack)


@app.post("/encounter/{eid}/simulate/ruleset")
async def rulesetSimulate(
    eid: str,
    request: Request,
    entry: ActionRequest,
    currentUser: UserInDB = Depends(getCurrentActiveUser),
):
    def _persist_lingering_aoe_token(encounter_obj, aoe_token: dict | None) -> None:
        def _get_map_data(current_encounter):
            if hasattr(current_encounter, "getMapData"):
                return current_encounter.getMapData()
            return getattr(current_encounter, "_Encounter__mapData", None)

        def _set_map_data(current_encounter, map_data):
            if hasattr(current_encounter, "setMapData"):
                current_encounter.setMapData(map_data)
            else:
                setattr(current_encounter, "_Encounter__mapData", map_data)

        if not aoe_token or aoe_token.get("timing") != "lingering":
            return

        map_data = _get_map_data(encounter_obj)
        if map_data is None:
            return

        layers = map_data.setdefault("layers", {})
        aoe_tokens = layers.setdefault("aoeTokens", [])
        aoe_tokens = [
            existing
            for existing in aoe_tokens
            if existing.get("resultID") != aoe_token.get("resultID")
        ]
        aoe_tokens.append(aoe_token)

        layers["aoeTokens"] = aoe_tokens
        map_data["layers"] = layers
        _set_map_data(encounter_obj, map_data)

    def _sum_numeric(values) -> float:
        total = 0.0
        for value in values or []:
            try:
                total += float(value)
            except (TypeError, ValueError):
                continue
        return total

    def _resource_snapshot(prefix: str, turn_entry: dict) -> dict:
        return {
            f"action_resource_{prefix}": float(
                turn_entry.get("actionResource", 0) or 0
            ),
            f"bonus_action_resource_{prefix}": float(
                turn_entry.get("bonusActionResource", 0) or 0
            ),
            f"movement_resource_{prefix}": float(
                turn_entry.get("movementResource", 0) or 0
            ),
        }

    def _is_actor_concentrating(creature_obj) -> float:
        return 1.0 if _active_concentration(creature_obj) else 0.0

    def _team_hp_context(encounter_obj, actor_obj) -> dict:
        actor_cid = actor_obj.getCID()
        player_cids = {
            encounter_obj.getPlayer(index).getCID()
            for index in range(encounter_obj.playerSize())
        }
        actor_is_player = actor_cid in player_cids

        friendly_hp = 0.0
        friendly_max = 0.0
        enemy_hp = 0.0
        enemy_max = 0.0

        for index in range(encounter_obj.playerSize()):
            creature = encounter_obj.getPlayer(index)
            hp = float(creature.getHP())
            max_hp = float(creature.getMaxHP())
            if actor_is_player:
                friendly_hp += hp
                friendly_max += max_hp
            else:
                enemy_hp += hp
                enemy_max += max_hp

        for index in range(encounter_obj.monsterSize()):
            creature = encounter_obj.getMonster(index)
            hp = float(creature.getHP())
            max_hp = float(creature.getMaxHP())
            if actor_is_player:
                enemy_hp += hp
                enemy_max += max_hp
            else:
                friendly_hp += hp
                friendly_max += max_hp

        return {
            "friendly_team_hp_pct": (
                friendly_hp / friendly_max if friendly_max > 0 else 0.0
            ),
            "enemy_team_hp_pct": (
                enemy_hp / enemy_max if enemy_max > 0 else 0.0
            ),
        }

    def _target_side_counts(encounter_obj, actor_obj, target_list) -> dict:
        actor_cid = actor_obj.getCID()
        player_cids = {
            encounter_obj.getPlayer(index).getCID()
            for index in range(encounter_obj.playerSize())
        }
        actor_is_player = actor_cid in player_cids

        enemy_hits = 0.0
        ally_hits = 0.0
        self_hits = 0.0

        for target in target_list or []:
            target_cid = target.getCID() if hasattr(target, "getCID") else None
            if target_cid == actor_cid:
                self_hits += 1.0
            elif (target_cid in player_cids) == actor_is_player:
                ally_hits += 1.0
            else:
                enemy_hits += 1.0

        return {
            "enemy_targets_hit": enemy_hits,
            "ally_targets_hit": ally_hits,
            "self_targets_hit": self_hits,
        }

    async def _persist_ml_result(
        *,
        encounter_obj,
        actor_obj,
        action_obj,
        selected_targets,
        action_entry: dict,
        resources_before: dict,
        resources_after: dict,
        team_hp_before: dict,
        actor_concentrating_before: float,
        action_is_spell: bool,
        aoe_token: dict | None,
    ) -> bool:
        """Persist one resolved action as one labeled residual-model record."""
        try:
            outcome_results = (
                (action_entry.get("outcome") or {}).get("rollResults", []) or []
            )
            hit_targets = [
                target
                for index, target in enumerate(selected_targets)
                if index < len(outcome_results)
                and str(outcome_results[index]).lower() in ("y", "crit")
            ]

            side_counts = _target_side_counts(
                encounter_obj,
                actor_obj,
                hit_targets,
            )
            targets_hit_count = float(len(hit_targets))
            damage_total = _sum_numeric(
                (action_entry.get("outcome") or {}).get("diceResults", [])
            )
            extra_damage_total = _sum_numeric(
                (action_entry.get("extraOutcome") or {}).get(
                    "extraDiceResults", []
                )
            )

            spell_slot_level_spent = 0.0
            if action_is_spell:
                get_level = getattr(action_obj, "getLvl", None)
                if callable(get_level):
                    action_level = float(get_level() or 0)
                    if action_level > 0:
                        spell_slot_level_spent = action_level

            turn_context = {
                **resources_before,
                **resources_after,
                **team_hp_before,
                **side_counts,
                "actor_concentrating_before": actor_concentrating_before,
                "spell_slot_level_spent": spell_slot_level_spent,
                "num_targets_selected": float(len(selected_targets)),
                "num_targets_hit": targets_hit_count,
                "targets_hit_count": targets_hit_count,
                "damage_total": damage_total,
                "extra_damage_total": extra_damage_total,
                "conditions_applied_count": float(
                    len(action_entry.get("conditions", []) or [])
                ),
                "status_effects_applied_count": float(
                    len(action_entry.get("statusEffects", []) or [])
                ),
            }

            frontend_base_weight = action_entry.get("baseWeight")
            if frontend_base_weight is None:
                frontend_base_weight = action_entry.get("base_weight")
            if frontend_base_weight is None:
                frontend_base_weight = action_entry.get("actionBaseWeight")

            scored_inputs = build_scored_training_record_inputs(
                actor=actor_obj,
                action_obj=action_obj,
                targets=selected_targets,
                encounter_id=eid,
                prob=float(action_entry.get("actionProb", 0.0) or 0.0),
                expected_damage=float(
                    action_entry.get("actionEDam", 0.0) or 0.0
                ),
                impact=float(action_entry.get("actionImpact", 0.0) or 0.0),
                aoe_token=aoe_token,
                action_result=action_entry,
                turn_context=turn_context,
                base_weight=frontend_base_weight,
            )

            await persist_labeled_action_record(
                action=action_obj,
                actor=actor_obj,
                targets=selected_targets,
                encounter_id=eid,
                user_id=currentUser.username,
                base_weight=scored_inputs["base_weight"],
                predicted_weight=scored_inputs["predicted_weight"],
                heuristic_components=scored_inputs["heuristic_components"],
                outcome_snapshot=scored_inputs["outcome_snapshot"],
                context=scored_inputs["context"],
                action_result=action_entry,
                target_snapshot=scored_inputs["target_snapshot"],
                aoe_snapshot=scored_inputs["aoe_snapshot"],
                turn_context_snapshot=scored_inputs["turn_context_snapshot"],
            )
            return True

        except Exception as exc:
            action_name = action_entry.get("action", "unknown action")
            logger.exception(
                "ML post-action persistence failed for %s: %s",
                action_name,
                exc,
            )
            return False

    async def _maybe_retrain_after_persist(persisted_any: bool) -> None:
        if not persisted_any:
            return

        try:
            retrain_result = await maybe_train_after_action_uses(
                min_labeled_uses_per_action=100,
                delete_used_records=True,
            )
            if retrain_result.get("trained"):
                get_predictor.cache_clear()
        except Exception as exc:
            logger.exception("ML post-action training hook failed: %s", exc)

    encounter_data = await getEncounter(eid, currentUser)
    encounter = main.loadEncounter(encounter_data)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found.")

    mapdata = encounter.getMapData()
    active_initiative = main.setActiveInitiative(encounter)
    encounter_initiative = encounter.getInitiative()

    # ActionRequest in older deployments does not declare `multiattack`, so
    # Pydantic legitimately omits it from model_dump. Merge only that normalized
    # extension from the original request body after the normal model validates.
    raw_entry = await _request_json_object(request)
    token_model = entry.token
    entry = entry.model_dump(mode="json", by_alias=True)
    raw_multiattack = raw_entry.get("multiattack")
    if isinstance(raw_multiattack, dict):
        entry["multiattack"] = raw_multiattack
    movement_recommendation = entry.get("movementRecc", [])

    token = token_model.model_dump(mode="json") if token_model else None
    if token:
        token["anchor"] = {
            "x": token["anchor"][0],
            "y": token["anchor"][1],
        }

    requested_multiattack = entry.get("multiattack")
    if isinstance(requested_multiattack, dict):
        actor_obj, actor_turn_entry = _get_actor_and_turn_entry(
            entry["actor"],
            active_initiative,
            encounter_initiative,
        )

        if isPlayer(actor_obj):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Player Extra Attack is not implemented by the monster "
                    "multiattack route."
                ),
            )

        _restore_persisted_multiattack(
            actor_obj,
            encounter_data,
            actor_obj.getCID(),
        )
        configured_multiattack = main.getMonsterMultiattack(actor_obj)
        if not configured_multiattack:
            raise HTTPException(
                status_code=404,
                detail="Monster has no configured multiattack.",
            )

        expected_names = _expanded_multiattack_names(configured_multiattack)
        submitted_attacks = requested_multiattack.get("attacks", [])
        if not isinstance(submitted_attacks, list):
            raise HTTPException(
                status_code=422,
                detail="multiattack.attacks must be a list.",
            )
        if len(submitted_attacks) != len(expected_names):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Multiattack requires exactly {len(expected_names)} "
                    "child attacks."
                ),
            )

        submitted_names = [
            str(attack.get("action", "")).strip().lower()
            for attack in submitted_attacks
            if isinstance(attack, dict)
        ]
        normalized_expected_names = [
            name.strip().lower() for name in expected_names
        ]
        if submitted_names != normalized_expected_names:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Submitted multiattack actions do not match the "
                    "configured split/order."
                ),
            )

        resources_before = _resource_snapshot("before", actor_turn_entry)
        team_hp_before = _team_hp_context(encounter, actor_obj)
        actor_concentrating_before = _is_actor_concentrating(actor_obj)

        # A configured multiattack consumes one action. Its child attacks do not
        # consume additional action resources.
        _consume_action_cost(actor_turn_entry, "action")
        resources_after = _resource_snapshot("after", actor_turn_entry)

        parent_result_id = str(entry.get("resultID"))
        executed_children = []
        ml_child_results = []
        concentration_resolutions = []
        aggregate_targets = []
        aggregate_rolls = []
        aggregate_damage = []
        aggregate_extra_rolls = []
        aggregate_extra_damage = []

        sequence_metadata = requested_multiattack.get("sequence", [])

        for index, submitted_attack in enumerate(submitted_attacks):
            if not isinstance(submitted_attack, dict):
                raise HTTPException(
                    status_code=422,
                    detail="Each multiattack child must be an object.",
                )

            metadata = (
                sequence_metadata[index]
                if isinstance(sequence_metadata, list)
                and index < len(sequence_metadata)
                and isinstance(sequence_metadata[index], dict)
                else {}
            )

            child_entry = {
                "resultID": str(
                    submitted_attack.get("resultID")
                    or f"{parent_result_id}:multiattack:{index + 1}"
                ),
                "parentResultID": parent_result_id,
                "multiattackChild": True,
                "hidden": True,
                "multiattackIndex": index,
                "actor": entry["actor"],
                "action": expected_names[index],
                "actionType": "MonAction",
                "actionProb": submitted_attack.get(
                    "actionProb", metadata.get("prob", 0.0)
                ),
                "actionEDam": submitted_attack.get(
                    "actionEDam", metadata.get("eDam", 0.0)
                ),
                "actionImpact": submitted_attack.get(
                    "actionImpact", metadata.get("impact", 0.0)
                ),
                "baseWeight": submitted_attack.get(
                    "baseWeight", metadata.get("baseWeight")
                ),
                "base_weight": submitted_attack.get(
                    "base_weight", metadata.get("base_weight")
                ),
                "actionBaseWeight": submitted_attack.get(
                    "actionBaseWeight", metadata.get("actionBaseWeight")
                ),
                "targets": submitted_attack.get("targets", []),
                "conditions": submitted_attack.get("conditions", []),
                "statusEffects": submitted_attack.get("statusEffects", []),
                "outcome": submitted_attack.get(
                    "outcome",
                    {"rollResults": [], "diceResults": []},
                ),
                "extraOutcome": submitted_attack.get(
                    "extraOutcome",
                    {"extraRollResults": [], "extraDiceResults": []},
                ),
                "concentrationChecks": [],
                "timestamp": entry.get("timestamp"),
                "recommended": entry.get("recommended", False),
            }

            _, child_action, _, child_is_spell, child_targets = unpackEntry(
                child_entry,
                active_initiative,
            )
            if child_is_spell:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Monster multiattack currently supports monster "
                        "actions only."
                    ),
                )
            if not child_action:
                raise HTTPException(
                    status_code=404,
                    detail=f"Multiattack child action not found: {expected_names[index]}",
                )

            concentrating_targets_before = {
                str(target.getCID()): _concentration_result_id(
                    _active_concentration(target)
                )
                for target in child_targets
                if _active_concentration(target)
            }

            main.executeAction(
                actor_obj,
                child_action,
                child_targets,
                child_entry,
                active_initiative,
                mapdata,
            )

            child_concentration_checks = (
                _pending_concentration_checks_after_damage(
                    selected_targets=child_targets,
                    action_entry=child_entry,
                    concentrating_before=concentrating_targets_before,
                )
            )
            child_entry["concentrationChecks"] = child_concentration_checks
            concentration_resolutions.extend(child_concentration_checks)

            # Child results remain addressable for timed effects, save-ends,
            # concentration cleanup, and resultID-based effect removal. They
            # remain hidden so the parent is the only visible action result.
            main.logActionResult(encounter, child_entry)
            executed_children.append(child_entry)
            ml_child_results.append(
                {
                    "action": child_action,
                    "targets": child_targets,
                    "entry": child_entry,
                }
            )

            for target_cid in child_entry.get("targets", []):
                if target_cid not in aggregate_targets:
                    aggregate_targets.append(target_cid)
            aggregate_rolls.extend(
                (child_entry.get("outcome") or {}).get("rollResults", []) or []
            )
            aggregate_damage.extend(
                (child_entry.get("outcome") or {}).get("diceResults", []) or []
            )
            aggregate_extra_rolls.extend(
                (child_entry.get("extraOutcome") or {}).get(
                    "extraRollResults", []
                )
                or []
            )
            aggregate_extra_damage.extend(
                (child_entry.get("extraOutcome") or {}).get(
                    "extraDiceResults", []
                )
                or []
            )

        entry["action"] = configured_multiattack["name"]
        entry["actionType"] = "Multiattack"
        entry["targets"] = aggregate_targets
        entry["outcome"] = {
            "rollResults": aggregate_rolls,
            "diceResults": aggregate_damage,
        }
        entry["extraOutcome"] = {
            "extraRollResults": aggregate_extra_rolls,
            "extraDiceResults": aggregate_extra_damage,
        }
        entry["multiattack"] = {
            **configured_multiattack,
            "sequence": sequence_metadata,
            "attacks": executed_children,
        }
        entry["concentrationChecks"] = concentration_resolutions
        entry["resourceContext"] = {
            **resources_before,
            **resources_after,
        }

        # Persist every resolved child as a real MonAction use. This matches
        # the model's per-action-family/per-action-name training design and
        # avoids creating a duplicate aggregate damage label for the parent.
        persisted_any_ml_record = False
        for ml_child in ml_child_results:
            persisted_child = await _persist_ml_result(
                encounter_obj=encounter,
                actor_obj=actor_obj,
                action_obj=ml_child["action"],
                selected_targets=ml_child["targets"],
                action_entry=ml_child["entry"],
                resources_before=resources_before,
                resources_after=resources_after,
                team_hp_before=team_hp_before,
                actor_concentrating_before=actor_concentrating_before,
                action_is_spell=False,
                aoe_token=None,
            )
            persisted_any_ml_record = (
                persisted_any_ml_record or persisted_child
            )

        # Check the training threshold once after all child labels are stored.
        await _maybe_retrain_after_persist(persisted_any_ml_record)

        main.logActionResult(encounter, entry)
        await main.saveEncounter(encounter)

        return {
            "ok": True,
            "multiattack": True,
            "resultID": parent_result_id,
            "childResultIDs": [
                child["resultID"] for child in executed_children
            ],
            "concentrationChecks": concentration_resolutions,
        }

    actor_obj, action, _, is_spell, selected_targets = unpackEntry(
        entry,
        active_initiative,
    )
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")

    actor_cid = actor_obj.getCID()
    actor_obj, actor_turn_entry = _get_actor_and_turn_entry(
        actor_cid,
        active_initiative,
        encounter_initiative,
    )

    resources_before = _resource_snapshot("before", actor_turn_entry)
    team_hp_before = _team_hp_context(encounter, actor_obj)
    actor_concentrating_before = _is_actor_concentrating(actor_obj)
    concentrating_targets_before = {
        str(target.getCID()): _concentration_result_id(
            _active_concentration(target)
        )
        for target in selected_targets
        if _active_concentration(target)
    }

    if is_spell:
        level = action.getLvl()
        if actor_obj.getName().lower() != "lair action":
            if isPlayer(actor_obj) or actor_obj.hasSpellSlots():
                if level > 0:
                    insufficient_spell_slot = True
                    for slot_index in range(level, 9):
                        current_slots = int(
                            actor_obj.getSpellSlot(slot_index) or 0
                        )
                        if current_slots > 0:
                            actor_obj.setSpellSlots(
                                slot_index,
                                current_slots - 1,
                            )
                            insufficient_spell_slot = False
                            break
                    if insufficient_spell_slot:
                        raise HTTPException(
                            status_code=409,
                            detail="Insufficient spell slot",
                        )
            elif not isPlayer(actor_obj) and level > 0:
                insufficient_charges = False
                found = False
                for spell_index in range(actor_obj.getSpellLength()):
                    spell = actor_obj.getSpell(spell_index)
                    if spell["name"].lower() != action.getName().lower():
                        continue

                    found = True
                    charges = spell.get("charges", 0)
                    if str(charges).lower() != "at will":
                        charges = int(charges)
                        if charges > 0:
                            charges -= 1
                        else:
                            insufficient_charges = True
                        spell["charges"] = str(charges)

                if not found:
                    raise HTTPException(
                        status_code=404,
                        detail="Action not found.",
                    )
                if insufficient_charges:
                    raise HTTPException(
                        status_code=409,
                        detail="Insufficient charges",
                    )

    _consume_action_cost(actor_turn_entry, action.getActionCost())
    resources_after = _resource_snapshot("after", actor_turn_entry)

    if movement_recommendation:
        try:
            sharedMovementErrorContext(
                encounter,
                actor_obj,
                movement_recommendation,
            )
            actor_obj.setPosition(movement_recommendation)
        except HTTPException as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc

    main.executeAction(
        actor_obj,
        action,
        selected_targets,
        entry,
        active_initiative,
        mapdata,
    )

    concentration_resolutions = _pending_concentration_checks_after_damage(
        selected_targets=selected_targets,
        action_entry=entry,
        concentrating_before=concentrating_targets_before,
    )
    entry["concentrationChecks"] = concentration_resolutions

    persisted_ml_record = await _persist_ml_result(
        encounter_obj=encounter,
        actor_obj=actor_obj,
        action_obj=action,
        selected_targets=selected_targets,
        action_entry=entry,
        resources_before=resources_before,
        resources_after=resources_after,
        team_hp_before=team_hp_before,
        actor_concentrating_before=actor_concentrating_before,
        action_is_spell=is_spell,
        aoe_token=token,
    )
    await _maybe_retrain_after_persist(persisted_ml_record)

    _persist_lingering_aoe_token(encounter, token)
    concentration_ended = main.reconcileConcentrationForResult(
        entry.get("resultID"), encounter
    )
    if concentration_ended:
        entry["turnCounts"] = {}
        entry["expiredCreatures"] = {}
        entry["turnCount"] = 0
    main.logActionResult(encounter, entry)
    await main.saveEncounter(encounter)

    return {
        "ok": True,
        "concentrationEnded": concentration_ended,
        "concentrationChecks": concentration_resolutions,
    }

@app.post("/encounter/{eid}/simulate/concentration")
async def concentrationSimulate(
    eid: str,
    payload: dict[str, Any],
    currentUser: UserInDB = Depends(getCurrentActiveUser),
):
    """Resolve one pending concentration save using a backend-calculated DC."""
    check_id = str(payload.get("checkID", "")).strip()
    if not check_id:
        raise HTTPException(status_code=422, detail="checkID is required.")

    try:
        roll = float(payload.get("roll"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="roll must be numeric.")

    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    active_initiative = main.setActiveInitiative(encounter)
    mapdata = _safe_concentration_mapdata(encounter.getMapData())

    pending_check = None
    for _, check in _iter_concentration_checks(encounter):
        if str(check.get("checkID", "")) == check_id:
            pending_check = check
            break

    if pending_check is None:
        raise HTTPException(status_code=404, detail="Concentration check not found.")
    if pending_check.get("resolved") or pending_check.get("cancelled"):
        raise HTTPException(status_code=409, detail="Concentration check is already resolved.")

    cid = str(pending_check.get("cid", ""))
    creature = await getCreatureObj(encounter, cid)
    if creature is None:
        raise HTTPException(status_code=404, detail="Concentrating creature not found.")

    concentration = _active_concentration(creature)
    expected_concentration_result_id = pending_check.get("concentrationResultID")
    current_concentration_result_id = _concentration_result_id(concentration)

    if not concentration or not _same_optional_result_id(
        current_concentration_result_id,
        expected_concentration_result_id,
    ):
        pending_check.update({
            "resolved": True,
            "cancelled": True,
            "required": False,
            "roll": roll,
            "reason": "The original concentration effect is no longer active.",
        })
        await main.saveEncounter(encounter)
        return {"ok": True, "check": pending_check, "cancelledCheckIDs": []}

    dc = int(pending_check.get("dc", 10))
    succeeded = roll >= dc
    cancelled_check_ids = []

    if not succeeded:
        concentration_result_id = (
            current_concentration_result_id
            or expected_concentration_result_id
        )
        if not main.endConcentrationForResult(concentration_result_id, encounter):
            main.endConcentration(
                creature,
                concentration,
                active_initiative,
                mapdata,
            )
        cancelled_check_ids = _cancel_remaining_concentration_checks(
            encounter,
            cid=cid,
            concentration_result_id=expected_concentration_result_id,
            exclude_check_id=check_id,
        )

    pending_check.update({
        "roll": roll,
        "resolved": True,
        "cancelled": False,
        "required": True,
        "succeeded": succeeded,
        "concentrationEnded": not succeeded,
    })

    await main.saveEncounter(encounter)
    return {
        "ok": True,
        "check": pending_check,
        "cancelledCheckIDs": cancelled_check_ids,
    }


@app.get("/aoe/template-masks")
def get_aoe_template_masks(
    shape: str,
    sizeCells: int,
    lineWidthCells: int = 1,
):
    masks = main.getOrientedTemplateMasks(
        shapeKind=shape,
        sizeCells=sizeCells,
        lineWidthCells=lineWidthCells,
    )

    return {
        "shape": shape,
        "sizeCells": sizeCells,
        "lineWidthCells": lineWidthCells,
        "masks": [
            {
                "orientation": orientation,
                "offsets": [[dx, dy] for dx, dy in mask],
            }
            for orientation, mask in masks
        ],
    }

@app.post("/encounter/{eid}/simulate/manual")
async def manualSimulate(eid : str, affectedCreatures : AffectedCreaturesRequest, currentUser : UserInDB = Depends(getCurrentActiveUser)):
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creature_dict = affectedCreatures.model_dump(mode="json", by_alias=True, exclude_none=True)
    for creature in creature_dict["affectedCreatures"]:
        cid = creature.get("cid", "")
        creatureObj = await getCreatureObj (encounter, cid)
        for field, value in creature.items():
            handler = handlers.get(field)
            if field == "lResists" and not hasattr(creatureObj, "setlResists"):
                continue
            if handler:
                handler(creatureObj, value)
    try:
        await main.saveEncounter(encounter)
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Failed to save Encounter: {err}")

    return {"verification" : "true"}

@app.post("/encounter/{eid}/simulate/preturn")
async def preTurnSimulate(
    eid: str,
    entry: PreTurnRequest,
    currentUser: UserInDB = Depends(getCurrentActiveUser)
):
    def _normalize_token_anchor_for_map(anchor):
        if isinstance(anchor, dict):
            return {
                "x": int(anchor.get("x", 0)),
                "y": int(anchor.get("y", 0)),
            }

        if isinstance(anchor, list) and len(anchor) == 2:
            return {
                "x": int(anchor[0]),
                "y": int(anchor[1]),
            }

        return {"x": 0, "y": 0}

    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    mapdata = encounter.getMapData()
    activeInitiative = main.setActiveInitiative(encounter)

    token_model = entry.token
    entry = entry.model_dump(mode="json", by_alias=True)

    token = token_model.model_dump(mode="json") if token_model else None
    if token:
        token["anchor"] = _normalize_token_anchor_for_map(token.get("anchor"))
        token["timing"] = str(token.get("timing", "")).strip().lower()

    actorObj, action, targets, isSpell, selectedTargets = unpackEntry(entry, activeInitiative)

    concentrating_targets_before = {
        str(target.getCID()): _concentration_result_id(_active_concentration(target))
        for target in selectedTargets
        if _active_concentration(target)
    }

    main.executeAction(actorObj, action, selectedTargets, entry, activeInitiative, mapdata)

    concentration_checks = _pending_concentration_checks_after_damage(
        selected_targets=selectedTargets,
        action_entry=entry,
        concentrating_before=concentrating_targets_before,
    )

    result_id = entry.get("resultID")
    source_result = encounter.getResultByID(result_id) if result_id not in (None, -1, "-1") else None
    if isinstance(source_result, dict) and concentration_checks:
        source_result.setdefault("concentrationChecks", []).extend(concentration_checks)

    saved_out = (
        str(entry.get("preTurnMeta", "")).lower() == "lingsave"
        and bool(entry.get("outcome", {}).get("rollResults"))
        and str(entry["outcome"]["rollResults"][0]).lower() == "y"
    )
    removed_from_targets = []

    if result_id not in (None, -1, "-1"):
        for target in selectedTargets:
            target_obj = target["Statblock"] if isinstance(target, dict) else target
            if saved_out:
                if main.endTimedResultForCreature(result_id, target_obj, encounter):
                    removed_from_targets.append(str(target_obj.getCID()))
            else:
                main.finalizeTimedResult(result_id, target_obj, encounter)

    _persist_lingering_aoe_token(encounter, token)
    concentration_ended = (
        main.reconcileConcentrationForResult(result_id, encounter)
        if result_id not in (None, -1, "-1")
        else False
    )

    await main.saveEncounter(encounter)

    return {
        "savedOut": saved_out,
        "removedEffects": bool(removed_from_targets),
        "removedFromTargets": removed_from_targets,
        "concentrationEnded": concentration_ended,
        "concentrationChecks": concentration_checks,
    }

def _normalizeMovementPositions(value):
    """Normalize one coordinate or a creature footprint to ``[[x, y], ...]``."""
    if value is None:
        return []

    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, (int, float)) for item in value)
    ):
        return [[int(value[0]), int(value[1])]]

    if not isinstance(value, (list, tuple)):
        return []

    normalized = []
    for position in value:
        if (
            isinstance(position, (list, tuple))
            and len(position) == 2
            and all(isinstance(item, (int, float)) for item in position)
        ):
            normalized.append([int(position[0]), int(position[1])])

    return normalized


def _getMovementMapBounds(encounter):
    """Read canonical or legacy map-bound keys and reject unusable maps."""
    map_data = encounter.getMapData() or {}
    cell_bounds = map_data.get("grid", {}).get("cellBounds", {})

    cols = int(cell_bounds.get("cols", cell_bounds.get("col", 0)) or 0)
    rows = int(cell_bounds.get("rows", cell_bounds.get("row", 0)) or 0)

    if cols <= 0 or rows <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Encounter map bounds are missing or invalid. Expected positive "
                "grid.cellBounds.cols and grid.cellBounds.rows values."
            ),
        )

    return rows, cols

def sharedMovementErrorContext(encounter, creature, newPos, ruleset=False, newAnchorDistance=0):
    size = creature.getSize()
    bad = False
    message = ""
    if size == "medium" and len(newPos) != 1:
        bad = True
        message = f"Incorrect position sizing!"
    elif size == "large" and len(newPos) != 4:
        bad = True
        message = f"Incorrect position sizing!"
    elif size == "huge" and len(newPos) != 9:
        bad = True
        message = f"Incorrect position sizing!"
    elif size == "gargantuan" and len(newPos) != 16:
        bad = True
        message = f"Incorrect position sizing!"

    players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
    monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
    allPositions = [player.getPosition() for player in players]
    allPositions.extend([monster.getPosition() for monster in monsters])
    currentPos = creature.getPosition()
    allPositions.remove(currentPos)
    max_X = encounter.getMapData()["grid"]["cellBounds"]["cols"]
    max_Y = encounter.getMapData()["grid"]["cellBounds"]["rows"]

    for pos2D in allPositions:
        for pos in newPos:
            if max_X in pos or max_Y in pos:
                bad = True
                message = f"Out of Bounds!"
            if ruleset:
                if pos in pos2D and currentPos not in pos2D:
                    bad = True
                    message = f"Position collision detected"

    if ruleset:
        if (creature.getMovementMax() // 5) - newAnchorDistance < 0:
            bad = True
            message = f"Insufficient movement"

    if bad:
        raise HTTPException(status_code=500, detail=message)
def sharedTokenContext(encounter, creature, newPos):
    tokens = encounter.getMapData()["layers"]["aoeTokens"]
    token = {}
    for t in tokens:
        for pos in newPos:
            if pos in t["positioning"]:
                token = t
                break
    if token:
        tokenCID = token["cid"]

        concEffect = {}
        players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
        monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
        for player in players:
            if player.getCID() == tokenCID:
                concEffect = player.getActiveStatusEffect("concentration")
                break
        if not concEffect:
            for monster in monsters:
                if monster.getCID() == tokenCID:
                    concEffect = monster.getActiveStatusEffect("concentration")
                    break
        if not concEffect:
            raise HTTPException(status_code=500, detail="Error with concentration effect")
        #Moved into lingering token -> gain the lingering effect associated with that token.
        if concEffect:
            main.addStatusEffect(
                {
                    "name": "lingeffect",
                    "effect": {
                        "action": [concEffect["effect"]["action"]],
                        "resultID": [token["resultID"]],
                        "actor": [str(tokenCID)],
                    },
                },
                creature,
                token["resultID"],
            )
    else:
        #Moved out of a lingering token -> remove lingeffect associated with that token.
        if creature.getActiveStatusEffect("lingeffect"):
            tokenIDs = [t["resultID"] for t in tokens]
            lingEff = creature.getActiveStatusEffect("lingeffect")
            for ridx, rid in enumerate(lingEff["effect"]["resultID"]):
                if rid in tokenIDs:
                    if len(lingEff["effect"]["resultID"]) == 1:
                        creature.removeStatusEffect("lingeffect")
                        break
                    else:
                        del lingEff["effect"]["resultID"][ridx]
                        del lingEff["effect"]["action"][ridx]
                        actors = lingEff["effect"].get("actor")
                        if isinstance(actors, list) and ridx < len(actors):
                            del actors[ridx]
                        break

@app.post("/encounter/{eid}/creature/{cid}/simulate/manual-movement")
async def movementSimulateMANUAL(
    eid: str,
    cid: str,
    newPos: List[List[int]],
    currentUser: UserInDB = Depends(getCurrentActiveUser),
):
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creature = await getCreatureObj(encounter, cid)
    initEntry = main.findInitiativeEntryByCID(creature, encounter.getInitiative())

    try:
        sharedMovementErrorContext(encounter, creature, newPos)
    except HTTPException as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)

    creature.setPosition(newPos)
    initEntry["movementResource"] = creature.getMovementMax()
    initEntry["startingAnchor"] = newPos

    sharedTokenContext(encounter, creature, newPos)

    await main.saveEncounter(encounter)

@app.post("/encounter/{eid}/creature/{cid}/simulate/movement")
async def movementSimulate(eid : str, cid : str, newPos : List[List[int]], currentUser : UserInDB = Depends(getCurrentActiveUser)):
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creature = await getCreatureObj(encounter, cid)
    initEntry = main.findInitiativeEntryByCID(creature, encounter.getInitiative())
    players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
    monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
    #Currently considering players+monsters as collisions, since difficult terrain isnt implemented yet.
    blockingPositions = [
        other.getPosition()
        for other in players + monsters
        if other.getCID() != creature.getCID()
    ]
    cellBounds = encounter.getMapData()["grid"]["cellBounds"]
    newAnchorDistance = main.shortest_movement_distance_tiles(
        initEntry["startingAnchor"],
        newPos,
        blockingPositions,
        creature.getMovementMax() // 5,
        cellBounds["cols"],
        cellBounds["rows"]
    )

    try:
        sharedMovementErrorContext(encounter, creature, newPos,
                                   True, newAnchorDistance)
    except HTTPException as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)

    creature.setPosition(newPos)

    initEntry["movementResource"] = creature.getMovementMax() - (newAnchorDistance * 5)

    sharedTokenContext(encounter, creature, newPos)

    await main.saveEncounter(encounter)

@app.get("/uuid")
def getUUID():
    myUuidObject = uuid.uuid4()
    myUuidString = str(myUuidObject)
    return myUuidString

@app.get("/basic-actions")
def getBasicActions():
    with open("CoreEngine/data/basic_actions.json", "r") as brf:
        basicActions = json.load(brf)
        return basicActions
@app.get("/status-effects")
def getStatusEffects():
    with open(status_path, "r") as srf:
        statusEffects = json.load(srf)
        return statusEffects
@app.get("/conditions")
def getConditions():
    with open(condition_path, "r") as crf:
        conditions = json.load(crf)
        return conditions

@app.get("/encounter/{eid}/initiative/nextturn")
async def getNextTurn(eid: str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    def normalize_conditions(raw_conditions):
        normalized = set()

        for cond in raw_conditions or []:
            if isinstance(cond, str):
                normalized.add(cond.lower())
            elif isinstance(cond, dict):
                if "cond" in cond and isinstance(cond["cond"], str):
                    normalized.add(cond["cond"].lower())
                elif "name" in cond and isinstance(cond["name"], str):
                    normalized.add(cond["name"].lower())

        return normalized
    def get_pre_turn_effects(current_creature, encounter_obj):
        pre_effects = []

        if current_creature is None:
            return pre_effects

        # Repair duplicate sources produced by older executions before the
        # frontend queue is built. This also keeps action/result/actor arrays
        # aligned for each lingering source.
        main.dedupeCreatureLingeringEffects(current_creature)

        for effect in current_creature.getActiveStatusEffects() or []:
            effect_name = str(effect.get("name", "")).lower()
            if effect_name not in {"lingsave", "lingeffect"}:
                continue

            pre_effects.append(copy.deepcopy(effect))

            effect_data = effect.get("effect", {})
            if not isinstance(effect_data, dict):
                continue

            result_ids = main.ensureList(effect_data.get("resultID", []))
            stored_actors = main.ensureList(effect_data.get("actor", []))
            resolved_actors = []

            for index, result_id in enumerate(result_ids):
                actor = (
                    stored_actors[index]
                    if index < len(stored_actors)
                    else stored_actors[0] if stored_actors else ""
                )

                if not actor:
                    source_result = encounter_obj.getResultByID(result_id)
                    if isinstance(source_result, dict):
                        actor = source_result.get("actor", "")

                resolved_actors.append(str(actor or ""))

            if result_ids:
                effect_data["actor"] = resolved_actors

        # Snapshot first, then advance. The response remains available to the
        # frontend even when a timed effect expires as this turn begins.
        main.advanceTimedEffects(current_creature, encounter_obj)

        return pre_effects
    def get_creature_from_turn(turn_obj, encounter_obj):
        turn_cid = str(turn_obj.get("cid", ""))
        turn_type = turn_obj.get("turnType", "")

        if turn_type == "lairAction":
            return "LAIR_ACTION"

        if not turn_cid:
            return None

        if turn_type == "Player":
            return encounter_obj.getPlayerByCID(turn_cid)

        elif turn_type == "Monster":
            return encounter_obj.getMonsterByCID(turn_cid)

        return None

    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    initiative = encounter.getInitiative()

    if not initiative:
        raise HTTPException(status_code=400, detail="Encounter has no initiative entries")

    blocked_conditions = {
        "downed",
        "stabilized",
        "dead",
        "incapacitated",
        "paralyzed",
        "petrified",
        "stunned",
        "unconscious",
        "out of combat",
    }

    current_index = next(
        (i for i, turn in enumerate(initiative) if turn.get("currentTurn")),
        -1
    )

    preE = []
    found_turn = False

    for _ in range(len(initiative)):
        next_index = (current_index + 1) % len(initiative)

        for turn in initiative:
            turn["currentTurn"] = False

        initiative[next_index]["currentTurn"] = True
        initiative[next_index]["actionResource"] = 1
        initiative[next_index]["bonusActionResource"] = 1

        current_turn = initiative[next_index]

        current_creature = get_creature_from_turn(current_turn, encounter)
        if current_creature is None:
            logger.warning(f"Could not resolve creature for initiative entry: {current_turn}")
            current_index = next_index
            continue

        if current_creature == "LAIR_ACTION":
            found_turn = True
            break

        if not isinstance(current_creature, str):
            initiative[next_index]["movementResource"] = current_creature.getMovementMax()
            initiative[next_index]["startingAnchor"] = current_creature.getPosition()

            active_conditions = normalize_conditions(current_creature.getActiveConditions())
            preE = get_pre_turn_effects(current_creature, encounter)

            if blocked_conditions & active_conditions:
                if preE:
                    found_turn = True
                    break

                current_index = next_index
                continue

        found_turn = True
        break

    if not found_turn:
        logger.warning("No valid next turn found after checking the full initiative order.")

    try:
        await main.saveEncounter(encounter)
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Failed to save Encounter: {err}")

    return preE
@app.get("/encounter/{eid}/initiative/currentturn")
async def getTurn(eid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounter = await getEncounter(eid, currentUser)
    initiative = encounter.get("initiative", [])
    for turn in initiative:
        if turn["currentTurn"]:
            return turn["cid"]
    return {"error" : "no turns in initiative!"}
@app.get("/encounter/{eid}/initiative")
async def getSimulationInitiative(eid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    def setActiveInitiativeWLair(encounter):
        import copy
        initiative = copy.deepcopy(encounter.getInitiative())

        for i, creature in enumerate(initiative):
            # Add creature statblock to their associated turn
            # SHALLOW COPY OF MONSTER/PLAYER OBJECTS - Changes to creature["Statblock"] affect associated object in encounter
            creatureObj = main.getCreatureFromInitiativeEntry(encounter, creature)
            if creatureObj:
                creature["Statblock"] = creatureObj
        return initiative
    enc = main.loadEncounter(await getEncounter(eid, currentUser))
    init = setActiveInitiativeWLair(enc)
    for i, creature in enumerate(init):
        if creature.get("turnType") == "lairAction":
            continue
        init[i]["hp"] = creature["Statblock"].getHP()
        init[i]["maxhp"] = creature["Statblock"].getMaxHP()
        init[i]["ac"] = creature["Statblock"].getAC()
        init[i]["cid"] = creature["Statblock"].getCID()
        del init[i]["Statblock"]
    return init

@app.post("/encounter")
async def postEncounter(request: Request, encounter : Encounter, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    raw_encounter = await _request_json_object(request)
    encounterJSON = encounter.model_dump(mode="json", by_alias=True)
    _merge_raw_monster_multiattacks(encounterJSON, raw_encounter)
    for i, player in enumerate(encounterJSON["players"]):
        if player["stats"]["characterClass"].lower() != "sorcerer" and "metamagics" in player:
            del encounterJSON["players"][i]["metamagics"]
            del encounterJSON["players"][i]["chosenMetaMagics"]
            del encounterJSON["players"][i]["sorceryPoints"]
    try:
        await upsert_encounter_dict(encounterJSON)
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Failed to save Encounter: {err}")
    await addEncounterToUser(currentUser.username, encounterJSON["eid"])
    return dict(verification="true")
@app.get("/dashboard/encounters")
async def getEncounterPacket(currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounterList = await find_encounters_by_username(currentUser.username)
    encounters = await encounterList.to_list(length=None)
    return [{"name": enc.get("name"),"date": enc.get("date"), "mapLink": enc.get("mapdata", {}).get("map", {}).get("mapLink"), "eid":  enc.get("eid"),"completed": enc.get("completed")} \
            for enc in encounters]

@app.get("/encounter/{eid}/completed")
async def endOfEncounter(eid : str, currentUser : UserInDB = Depends(getCurrentActiveUser)):
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    if encounter is None:
        return {"isEnd" : True}
    initiative = main.setActiveInitiative(encounter)
    isEnd = main.endOfEncounter(initiative)
    if isEnd and not encounter.isComplete():
        logger.info("End of encounter - setting complete...")
        encounter.setComplete(True)
        await main.saveEncounter(encounter)
    return {"isEnd" : isEnd}

@app.get("/dashboard/{eid}/packet")
async def getEncounterMiniData(eid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounter = await getEncounter(eid, currentUser)
    players = encounter.get("players", [])
    monsters = encounter.get("monsters", [])
    pPacket = [{"name" : player.get("stats").get("name"), "level" : player.get("stats").get("level"),
               "characterClass" : player.get("stats").get("characterClass")} for player in players]
    mPacket = [{"name" : monster.get("name"), "cr" : monster.get("cr"), "size" : monster.get("size"),
                 "type" : monster.get("creatureType")} for monster in monsters]
    return {"players" : pPacket, "monsters" : mPacket}


@app.get("/dashboard/monsters")
def getMonsters():
    with open("CoreEngine/data/monster_list.json", "r") as pf:
        monster_list = json.load(pf)
    return monster_list

@app.get("/dashboard/players")
async def getPlayers(currentUser: UserInDB = Depends(getCurrentActiveUser)):
    players = await find_players_by_username(currentUser.username)
    return await players.to_list(length=None)

@app.get("/dashboard/weapons")
def getWeapons():
    with open("CoreEngine/data/weapons_list.json", "r") as wf:
        weapon_list = json.load(wf)
    return weapon_list
@app.get("/dashboard/player/availablespells")
def getSpells(classid : str, level : int):
    import math
    with open("CoreEngine/data/spell_list.json", "r") as sf:
        spellData = json.load(sf)
    relevantSpellData = []
    playerCap = -1
    if classid == "cleric" or classid == "sorcerer" or classid == "wizard" or classid == "bard" or classid == "druid" or classid == "warlock":
        playerCap = math.ceil(level / 2)  # Full casters
    elif (classid == "artificer" or classid == "paladin"
          or classid == "ranger"):
        playerCap = math.ceil(level / 3)  # Half casters
    for spell in spellData:
        if spell["level"] <= playerCap:
            found = False
            i = 0
            while not found and i < len(spell["classes"]):
                if classid.lower() == spell["classes"][i].lower():
                    relevantSpellData.append(spell)
                    found = True
                else:
                    i += 1
    return relevantSpellData
@app.post("/dashboard/players")
async def postPlayerToPlayerList(player : Union[AnyPlayer, Player], currentUser: UserInDB = Depends(getCurrentActiveUser)):
    def addClassPassives():
        #List of classes with relevant passives:
        #Barbarian, Bard, Fighter, Monk, Paladin, Ranger, Rogue
            #List of add and forget passives (DONE HERE):
                #(B)Magic Secrets, (Ro) Slippery Mind
            #Rest are on playerTurn() logic
        if playerObj.getClass().lower() == "bard":
            extraSpells = playerObj.getMagicalSecrets()
            for spell in extraSpells:
                playerObj.getMagicalSecret(spell)
                main.addChosenSpell(spell, playerObj)
        elif playerObj.getClass().lower() == "rogue":
            playerObj.setSaveProf("WIS", playerObj.getSaveProf("WIS") + playerObj.getProfBonus())
    playerJSON = player.model_dump(mode="json", by_alias=True)
    if playerJSON["stats"]["characterClass"].lower() != "sorcerer" and "metamagics" in playerJSON:
        del playerJSON["metamagics"]
        del playerJSON["chosenMetaMagics"]
        del playerJSON["sorceryPoints"]
    playerObj = main.getPlayerStats(playerJSON)
    main.getSavedWeapons(playerObj, playerJSON["weapons"])
    main.getSavedSpells(playerObj, playerJSON["spells"])
    addClassPassives()
    try:
        await main.savePlayer(playerObj)
    except PyMongoError as err:
        raise HTTPException(status_code=500, detail=f"Failed to save player: {err}")
    await addPlayerToUser(currentUser.username, playerJSON["stats"]["cid"])
    return dict(verification="true")




#USER AUTH METHODS
def loadRefreshStore() -> dict[str, Any]:
    if not REFRESH_STORE_PATH.exists():
        return {}
    return json.loads(REFRESH_STORE_PATH.read_text(encoding="utf-8"))
def saveRefreshStore(store: dict[str, Any]) -> None:
    tmp = REFRESH_STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    tmp.replace(REFRESH_STORE_PATH)
def addRefreshSession(username: str, jti: str, exp: int) -> None:
    store = loadRefreshStore()
    userEntry = store.setdefault(username, {})
    sessions = userEntry.setdefault("sessions", {})
    sessions[jti] = {"exp": exp}
    saveRefreshStore(store)
def hasRefreshSession(username: str, jti: str) -> bool:
    store = loadRefreshStore()
    userEntry = store.get(username, {})
    sessions = userEntry.get("sessions", {})
    return jti in sessions
def replaceRefreshSession(username: str, oldJti: str, newJti: str, newExp: int) -> bool:
    store = loadRefreshStore()
    userEntry = store.get(username, {})
    sessions = userEntry.get("sessions", {})

    if oldJti not in sessions:
        return False

    del sessions[oldJti]
    sessions[newJti] = {"exp": newExp}
    saveRefreshStore(store)
    return True
def revokeRefreshSession(username: str, jti: str) -> None:
    store = loadRefreshStore()
    userEntry = store.get(username, {})
    sessions = userEntry.get("sessions", {})

    if jti in sessions:
        del sessions[jti]

    if not sessions and username in store:
        del store[username]

    saveRefreshStore(store)
def revokeAllRefreshSessions(username: str) -> None:
    store = loadRefreshStore()
    if username in store:
        del store[username]
        saveRefreshStore(store)
def cleanupExpiredRefreshSessions() -> None:
    nowTs = int(datetime.now(timezone.utc).timestamp())
    store = loadRefreshStore()
    dirty = False

    for username in list(store.keys()):
        sessions = store[username].get("sessions", {})
        expiredJtis = [jti for jti, meta in sessions.items() if meta.get("exp", 0) <= nowTs]

        for jti in expiredJtis:
            del sessions[jti]
            dirty = True

        if not sessions:
            del store[username]
            dirty = True

    if dirty:
        saveRefreshStore(store)

def createAccessToken(*, subject: str, expiresMinutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    now = _now_utc()
    payload = {
        "sub": subject,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expiresMinutes)).timestamp()),
    }
    return jwt.encode(payload, ACCESS_SECRET_KEY, algorithm=ALGORITHM)
def createRefreshToken(*, subject: str, expiresDays: int = REFRESH_TOKEN_EXPIRE_DAYS) -> tuple[str, str]:
    #Returns (refresh_jwt, jti). We store the jti server-side for revocation/rotation.
    now = _now_utc()
    jti = getUUID()
    payload = {
        "sub": subject,
        "type": "refresh",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expiresDays)).timestamp()),
    }
    token = jwt.encode(payload, REFRESH_SECRET_KEY, algorithm=ALGORITHM)
    return token, jti
#AUTH METHODS LOCAL
def verifyPassword(plainPassword, hashed_password):
    return pwdContext.verify(plainPassword, hashed_password)
def getPasswordHash(password):
    return pwdContext.hash(password)
async def getUser(username : str):
    userData = await get_user_by_username(username)
    if userData:
        return UserInDB(**userData)
    else:
        raise HTTPException(status_code=404, detail="User not found")
async def authenticateUser(username : str, password : str):
    user = await getUser(username)
    if not user:
        return False
    if not verifyPassword(password, user.hashed_password):
        return False
    return user
def userToPublic(user: UserInDB) -> UserPublic:
    return UserPublic(
        uid=user.uid,
        username=user.username,
        email=user.email,
        disabled=bool(user.disabled),
        encounter_ids=user.encounter_ids,
        player_ids=user.player_ids
    )
async def createUser(userIn: UserCreate) -> UserInDB:
    # basic uniqueness check
    userData = await get_user_by_username(userIn.username)
    if userData:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already registered",
        )

    hashed = getPasswordHash(userIn.password)
    encounter_ids = []
    player_ids = []

    record = {
        "uid" : getUUID(),
        "username": userIn.username,
        "email": userIn.email,
        "disabled": False,
        "hashed_password": hashed,
        "auth_provider": "local",
        "encounter_ids": encounter_ids,
        "player_ids": player_ids,
        "google_sub": None,
    }
    await upsert_user_dict(record)
    return UserInDB(**record)
#AUTH METHODS GOOGLE
async def createGoogleUser(*, googleSub: str, email: str | None) -> UserInDB:
    baseUsername = f"g_{googleSub[:12]}"
    username = baseUsername
    i = 1
    while await get_user_by_username(username):
        i += 1
        username = f"{baseUsername}_{i}"

    encounter_ids = []
    player_ids = []

    record = {
        "uid" : getUUID(),
        "username": username,
        "email": email,
        "disabled": False,
        "hashed_password": None,
        "auth_provider": "google",
        "encounter_ids": encounter_ids,
        "player_ids": player_ids,
        "google_sub": googleSub,
    }
    await upsert_user_dict(record)
    return UserInDB(**record)
#AUTH HELPERS
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
async def issueAccessAuth(user, response):
    if isinstance(user, dict):
        username = user["username"]
    else:
        username = user.username
    access = createAccessToken(subject=username)
    refresh, jti = createRefreshToken(subject=username)

    refreshPayload = jwt.decode(refresh, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    addRefreshSession(username, jti, refreshPayload["exp"])

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS,
    )

    return {"access_token": access, "token_type": "bearer"}

#AUTH ENDPOINTS
@app.post("/signup", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def signup(userIn: UserCreate):
    user = await createUser(userIn)
    return userToPublic(user)
@app.post("/auth/login")
async def login(response: Response, formData: OAuth2PasswordRequestForm = Depends()):
    cleanupExpiredRefreshSessions()
    user = await authenticateUser(formData.username, formData.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    return await issueAccessAuth(user, response)
@app.post("/auth/google")
async def authGoogle(body: GoogleAuthRequest, response: Response):
    #Does both signin and signup logic for google accounts.
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CLIENT_ID is not configured",
        )
    try:
        claims = google_id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=30
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        )

    googleSub = claims.get("sub")
    email = claims.get("email")

    if not googleSub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google token missing subject",
        )
    user = await getUserByGoogleSub(googleSub)
    if not user:
        user = await createGoogleUser(googleSub=googleSub, email=email)
        if not isinstance(user, dict):
            user = user.model_dump(mode="json", by_alias=True)
    if user.get("disabled"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return await issueAccessAuth(user, response)
@app.post("/auth/refresh")
async def refreshToken(
    response: Response,
    refreshToken: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME)
):
    if not refreshToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token"
        )

    try:
        payload = jwt.decode(refreshToken, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong token type"
        )

    username = payload.get("sub")
    oldJti = payload.get("jti")

    if not username or not oldJti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed refresh token"
        )

    if not hasRefreshSession(username, oldJti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked"
        )

    access = createAccessToken(subject=username)

    newRefresh, newJti = createRefreshToken(subject=username)
    newPayload = jwt.decode(newRefresh, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])

    replaced = replaceRefreshSession(username, oldJti, newJti, newPayload["exp"])
    if not replaced:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked"
        )

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=newRefresh,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS,
    )
    return {"access_token": access, "token_type": "bearer"}
@app.post("/auth/logout")
async def logout(
    response: Response,
    refreshToken: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME)
):
    if refreshToken:
        try:
            payload = jwt.decode(refreshToken, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("type") == "refresh" and payload.get("sub") and payload.get("jti"):
                revokeRefreshSession(payload["sub"], payload["jti"])
        except Exception:
            pass

    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH
    )

    return {"detail": "logged out"}
@app.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def changePassword(body: ChangePasswordRequest, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    if currentUser.auth_provider != "local" or not currentUser.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account uses an external provider (e.g., Google). Password changes are not available.",
        )
    if not verifyPassword(body.current_password, currentUser.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )
    newHash = getPasswordHash(body.new_password)

    # Assuming userDb is keyed by username:
    userData = await get_user_by_username(currentUser.username)
    if not userData:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User record not found",
        )

    userData["hashed_password"] = newHash
    await upsert_user_dict(userData)

    return {"detail": "Password changed successfully"}
@app.post("/auth/set-disabled", status_code=status.HTTP_204_NO_CONTENT)
async def setDisabled(body: SetDisabledRequest, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    #TODO: for now, allow self-toggle (useful for testing)
    # Later, implement admin checks.
    userData = await get_user_by_username(currentUser.username)
    if not userData:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User record not found",
        )
    userData["disabled"] = bool(body.disabled)
    await upsert_user_dict(userData)
    return {"detail": "Disabled user"}
