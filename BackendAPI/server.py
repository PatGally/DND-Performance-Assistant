import json
import logging
import os
from typing import Union, List, Optional, Any
import uuid
from fastapi.middleware.cors import CORSMiddleware
from logs.loggingConfig import setupLogging
from BackendAPI.models import Monster, Player, Encounter, MonAction, ActionRequest, Spell, Weapon
from BackendAPI.models.DNDClasses import Barbarian, Bard, Cleric, Druid, Fighter, Paladin, Sorcerer
from pymongo.errors import PyMongoError
from dotenv import load_dotenv
import httpx
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
from db.db_access import init_indexes, get_user_by_username, get_encounter_by_eid, get_player_by_cid, \
    upsert_encounter_dict, find_encounters_by_username, find_players_by_username, upsert_user_dict, addEncounterToUser, \
    addPlayerToUser, deleteEncounterByEid, deletePlayerByCid
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
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creature = await getCreatureObj(encounter, cid)
    if isPlayer(creature):
        actions = []
        spells = [creature.getSpell(i).toDict() for i in range(creature.getSpellLength())]
        weapons = [creature.getWeapon(i).toDict() for i in range(creature.getWeaponLength())]
        actions.extend(spells)
        actions.extend(weapons)
    else:
        actions = [creature.getAction(i).toDict() for i in range(creature.getActionLength())]
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
async def addtoEncounter(eid : str, creature : Union[AnyPlayer, Player, Monster], currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounter = await getEncounter(eid, currentUser)
    if isPlayer(creature):
        requireOwnedPlayer(creature["stats"]["cid"], currentUser)
        encounter.get("players", []).append(creature)
        pass
    else:
        encounter.get("monsters", []).append(creature)
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
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    initiative = main.setActiveInitiative(encounter)

    players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
    playercids = [player.getCID().lower() for player in players]

    if cid.lower() in playercids:
        player = players[playercids.index(cid.lower())]
        rankings = main.playerTurn(player, initiative, encounter_id=eid)
        logger.info("Rankings for %s: %s", eid, rankings)
        return rankings
    else:
        monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
        monstercids = [monster.getCID().lower() for monster in monsters]
        if cid.lower() in monstercids:
            monster = monsters[monstercids.index(cid.lower())]
            rankings = main.monsterTurn(monster, initiative, encounter_id=eid)
            logger.info("Rankings for %s: %s", eid, rankings)
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
async def endPreEffect(eid : str, cid : str, resultID : str, currentUser : UserInDB = Depends(getCurrentActiveUser)):
    encounter = await getEncounter(eid, currentUser)
    creatureObj = await getCreatureObj(encounter, cid)

    statEffects = creatureObj.getActiveStatusEffects()
    idx = 0
    effect = {}
    for eff in statEffects:
        if eff["name"].lower() in ["lingsave", "lingeffect"]:
            if isinstance(eff["effect"]["resultID"], list):
                for i, id in enumerate(eff["effect"]["resultID"]):
                    if resultID == id:
                        idx = i
                        effect = eff
                        break
            elif resultID == eff["effect"]["resultID"]:
                idx = 0
                effect = eff
                break

    if not effect:
        raise HTTPException(status_code=500, detail="Effect not found.")

    main.endSpellEffect(effect, idx, creatureObj)
    await main.saveEncounter(encounter)

def unpackEntry(entry, activeInitiative):
    actor = entry["actor"]
    actorObj = ""
    action = entry["action"]
    targets = entry["targets"]
    selectedTargets = []
    isSpell = False

    for creature in activeInitiative:
        if creature["name"].lower() == actor.lower():
            actorObj = creature["Statblock"]
            print("Found actor!")
            spell = creature["Statblock"].getSpellByName(action)
            if spell:
                isSpell = True
                action = spell
            if isPlayer(creature["Statblock"]) and not isSpell:
                for i in range(creature["Statblock"].getWeaponLength()):
                    weapon = creature["Statblock"].getWeapon(i)
                    if weapon.getName().lower() == action.lower():
                        action = weapon
            elif not isSpell:
                monAction = creature["Statblock"].getActionByName(action)
                action = monAction if monAction else action

        if creature["Statblock"].getCID() in targets:
            selectedTargets.append(creature["Statblock"])

    if isinstance(action, str):
        if action.lower() in ["dodge", "shove", "grapple"]:
            bActions = getBasicActions()
            if action.lower() == "grapple":
                action = main.translateBasicAction(actorObj, bActions[0])
            elif action.lower() == "shove":
                action = main.translateBasicAction(actorObj, bActions[1])
            else:
                action = main.translateBasicAction(actorObj, bActions[2])
        else:
            raise HTTPException(status_code=500, detail="Action not found.")

    if isinstance(action, dict):
        if "spellData" in action:
            action = action["spellData"]
        else:
            print("Unknown action", action)

    return actorObj, action, targets, isSpell, selectedTargets

@app.post("/encounter/{eid}/simulate/ruleset")
async def rulesetSimulate(
    eid: str,
    entry: ActionRequest,
    currentUser: UserInDB = Depends(getCurrentActiveUser)
):
    def _persist_lingering_aoe_token(encounter, token: dict) -> None:
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

        # Upsert by resultID so resubmits do not duplicate
        aoe_tokens = [
            existing
            for existing in aoe_tokens
            if existing.get("resultID") != token.get("resultID")
        ]
        aoe_tokens.append(token)

        layers["aoeTokens"] = aoe_tokens
        map_data["layers"] = layers
        _set_map_data(encounter, map_data)

    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    mapdata = encounter.getMapData()
    activeInitiative = main.setActiveInitiative(encounter)

    token_model = entry.token
    entry = entry.model_dump(mode="json", by_alias=True)
    actorObj, action, targets, isSpell, selectedTargets = unpackEntry(entry, activeInitiative)
    actor = actorObj.getName()

    token = token_model.model_dump(mode="json") if token_model else None
    if token:
        token["anchor"] = {"x" : token["anchor"][0], "y" : token["anchor"][1]}

    if not action:
        raise HTTPException(status_code=500, detail="Action not found.")

    encInitiative = encounter.getInitiative()
    actionCost = action.getActionCost()

    for creature in encInitiative:
        if creature["name"].lower() == actor.lower():
            if isSpell:
                lvl = action.getLvl()
                if lvl > 0:
                    if actorObj.getSpellSlot(lvl) > 0:
                        actorObj.setSpellSlots(lvl, actorObj.getSpellSlot(lvl) - 1)
                    else:
                        raise HTTPException(status_code=500, detail="Insufficient spell slot")

            if actionCost == "action" and creature["actionResource"]:
                creature["actionResource"] -= 1
                break
            elif actionCost == "bonus action":
                if creature["bonusActionResource"]:
                    creature["bonusActionResource"] -= 1
                    break
                elif creature["actionResource"]:
                    creature["actionResource"] -= 1
                    break
                else:
                    raise HTTPException(status_code=500, detail="Insufficient action resources")
            else:
                raise HTTPException(status_code=500, detail="Invalid Action cost")

    main.executeAction(actorObj, action, selectedTargets, entry, activeInitiative, mapdata)

    # Persist lingering AOE template into mapdata before save
    _persist_lingering_aoe_token(encounter, token)

    main.logActionResult(encounter, entry)
    await main.saveEncounter(encounter)

    return {"ok": True}
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
async def preTurnSimulate(eid : str, entry : PreTurnRequest, currentUser : UserInDB = Depends(getCurrentActiveUser)):
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    mapdata = encounter.getMapData()
    activeInitiative = main.setActiveInitiative(encounter)
    entry = entry.model_dump(mode="json", by_alias=True)

    actorObj, action, targets, isSpell, selectedTargets = unpackEntry(entry, activeInitiative)
    main.executeAction(actorObj, action, selectedTargets, entry, activeInitiative, mapdata)
    await main.saveEncounter(encounter)
    if entry["preTurnMeta"].lower() == "lingsave" and entry["rollResult"][0] == "y":
        print("Saved out")
        return {"savedOut" : True}
    else:
        return {"savedOut" : False}

@app.post("/encounter/{eid}/creature/{cid}/simulate/movement")
async def movementSimulate(eid : str, cid : str, newPos : List[List[int]], currentUser : UserInDB = Depends(getCurrentActiveUser)):
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    creature = await getCreatureObj(encounter, cid)
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
    for pos2D in allPositions:
        for pos in newPos:
            if pos in pos2D and currentPos not in pos2D:
                bad = True
                message = f"Position collision detected"

    #TODO in summer: Check if newPos is within movement range of currentPos, according to movementResource of creature.

    if bad:
        raise HTTPException(status_code=500, detail=message)
    creature.setPosition(newPos)

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
            print("Creature entered lingering token, adding lingeffect...")
            creature.addStatusEffect({
                "name" : "lingeffect",
                "effect" : {
                    "action" : [concEffect["effect"]["action"]],
                    "resultID" : [token["resultID"]]
                }
            })
    else:
        #Moved out of a lingering token -> remove lingeffect associated with that token.
        if creature.getActiveStatusEffect("lingeffect"):
            tokenIDs = [t["resultID"] for t in tokens]
            lingEff = creature.getActiveStatusEffect("lingeffect")
            for ridx, rid in enumerate(lingEff["effect"]["resultID"]):
                if rid in tokenIDs:
                    print("Creature left lingering token, removing lingeffect...")
                    if len(lingEff["effect"]["resultID"]) == 1:
                        creature.removeStatusEffect("lingeffect")
                        break
                    else:
                        del lingEff["effect"]["resultID"][ridx]
                        del lingEff["effect"]["action"][ridx]
                        break


    await main.saveEncounter(encounter)

@app.get("/uuid")
def getUUID():
    myUuidObject = uuid.uuid4()
    myUuidString = str(myUuidObject)
    logger.info(myUuidString)
    return myUuidString

@app.put("/encounter/{eid}/setcompleted")
async def setCompleted(eid, currentUser : UserInDB = Depends(getCurrentActiveUser)):
    encounter = main.loadEncounter(await getEncounter(eid, currentUser))
    encounter.setComplete(True)
    await main.saveEncounter(encounter)
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

        for effect in current_creature.getActiveStatusEffects() or []:
            effect_name = str(effect.get("name", "")).lower()
            if effect_name not in {"lingsave", "lingeffect"}:
                continue

            pre_effects.append(effect)

            effect_data = effect.get("effect", {})
            result_ids = main.ensureList(effect_data.get("resultID", []))

            for i, result_id in enumerate(result_ids):
                if result_id == -1:
                    continue

                result = encounter_obj.getResultByID(result_id)
                if not result:
                    continue

                if "turnCount" in result and "turnCap" in result:
                    if int(result["turnCount"]) >= int(result["turnCap"]):
                        main.endSpellEffect(
                            effect,
                            i,
                            current_creature,
                            main.setActiveInitiative(encounter_obj)
                        )
                    else:
                        result["turnCount"] += 1

        return pre_effects
    def get_creature_from_turn(turn_obj, encounter_obj):
        turn_name = str(turn_obj.get("name", "")).lower()
        turn_type = turn_obj.get("turnType", "")

        if turn_type == "lairAction":
            return "LAIR_ACTION"

        if turn_type == "Player":
            for i in range(encounter_obj.playerSize()):
                player = encounter_obj.getPlayer(i)
                if player.getName().lower() == turn_name:
                    return player

        elif turn_type == "Monster":
            for i in range(encounter_obj.monsterSize()):
                monster = encounter_obj.getMonster(i)
                if monster.getName().lower() == turn_name:
                    return monster

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
        logger.info("New currentTurnCreature: " + current_turn["name"])

        current_creature = get_creature_from_turn(current_turn, encounter)
        if current_creature is None:
            logger.warning(f"Could not resolve creature for initiative entry: {current_turn}")
            current_index = next_index
            continue

        if current_creature == "LAIR_ACTION":
            logger.info("Lair action turn — stopping initiative advance.")
            found_turn = True
            break

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

    logger.info(f"preEffects: {preE}")
    return preE
@app.get("/encounter/{eid}/initiative/currentturn")
async def getTurn(eid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounter = await getEncounter(eid, currentUser)
    initiative = encounter.get("initiative", [])
    for turn in initiative:
        if turn["currentTurn"]:
            return turn["name"]
    return {"error" : "no turns in initiative!"}
@app.get("/encounter/{eid}/initiative")
async def getSimulationInitiative(eid : str, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    def setActiveInitiativeWLair(encounter):
        import copy
        initiative = copy.deepcopy(encounter.getInitiative())

        for i, creature in enumerate(initiative):
            # Add creature statblock to their associated turn
            # SHALLOW COPY OF MONSTER/PLAYER OBJECTS - Changes to creature["Statblock"] affect associated object in encounter
            if creature["turnType"].lower() == "player":
                for i in range(encounter.playerSize()):
                    if creature["name"].lower() == encounter.getPlayer(i).getName().lower():
                        creature["Statblock"] = encounter.getPlayer(i)
                        break
            elif creature["turnType"].lower() == "monster":
                for i in range(encounter.monsterSize()):
                    if (
                            creature["name"].lower()
                            == encounter.getMonster(i).getName().lower()
                    ):
                        creature["Statblock"] = encounter.getMonster(i)
                        break
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
async def postEncounter(encounter : Encounter, currentUser: UserInDB = Depends(getCurrentActiveUser)):
    encounterJSON = encounter.model_dump(mode="json", by_alias=True)
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
    initiative = main.setActiveInitiative(encounter)
    return {"isEnd" : main.endOfEncounter(initiative)}

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
    logger.info("Spell data from get spells: %s", relevantSpellData)
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
            clock_skew_in_seconds=10
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