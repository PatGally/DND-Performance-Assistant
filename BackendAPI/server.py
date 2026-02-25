import json
import logging
import os
import sys
from typing import Union, List, Annotated
import uuid

import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field

from logs.loggingConfig import setupLogging
from BackendAPI.models import ActionRequest, Monster, Player, Encounter, Spell, Weapon, MonAction
from BackendAPI.models.DNDClasses import Barbarian, Bard, Cleric, Druid, Fighter, Paladin, Sorcerer

from dotenv import load_dotenv
import main
from fastapi import FastAPI, Request
import time

setupLogging()
logger = logging.getLogger("backend")
load_dotenv()

origins = [os.getenv("ORIGIN1"), os.getenv("ORIGIN2")]
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], #DELETE, PUT, etc
    allow_headers=["*"], #Specific requests from specific sources.
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    logger.info("Incoming request: %s %s", request.method, request.url.path)
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        "Completed request: %s %s Status=%s Duration=%.4fs",request.method,request.url.path,response.status_code,duration)

    return response

ENCOUNTER_LIST = []
def refresh():
    with open("CoreEngine/data/encounter_list.json", "r") as rf: #TODO: DB pull here
        global ENCOUNTER_LIST
        ENCOUNTER_LIST = json.load(rf)
refresh()
AnyPlayer = Union[Fighter, Barbarian, Bard, Cleric, Druid, Paladin, Sorcerer]

def isPlayer(creature):
    if isinstance(creature, dict):
        if creature.get("stats", {}):
            return True
        else:
            return False
    elif isinstance(creature, Monster):
        return True
    else:
        return False
@app.get("/encounter/{eid}/creature/{cid}/position")
def getCreaturePosition(eid : str, cid : str):
    creature = getCreature(eid, cid)
    if isinstance(creature.get("stats", {}), dict):
        return creature.get("stats").get("position", [0, 0])
    return creature.get("position", [0, 0])
@app.get("/encounter/{eid}/creature/{cid}/actions", response_model = List[Union[Weapon, Spell, MonAction]])
def getCreatureActions(eid : str, cid : str):
    creature = getCreature(eid, cid)
    if isPlayer(creature):
        spells = creature.get("spells", [])
        weapons = creature.get("weapons", [])
        return weapons + spells
    actions = creature.get("actions", [])
    if creature.get("spellInfo", {}):
        actions += creature.get("spellInfo").get("spells", [])
    return actions
@app.get("/encounter/{eid}/creature/{cid}", response_model=Union[AnyPlayer, Monster])
def getCreature(eid : str, cid : str):
    enc = getEncounter(eid)
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
        raise ValueError(f"{cid} not a recognized creature.")
    print(creatures)
    return creatures[creatureIdx]
@app.post("/encounter/{eid}/creature")
def addtoEncounter(eid : str, creature : Union[AnyPlayer, Player, Monster]):
    encounter = getEncounter(eid)
    if isPlayer(creature):
        encounter.get("players", []).append(creature)
        pass
    else:
        encounter.get("monsters", []).append(creature)
    main.saveEncounter(main.loadEncounter(encounter))
    refresh()
    return {"verification" : "true"}
@app.get("/encounter/{eid}/state/maplink")
def getMapLink(eid : str):
    enc = getEncounter(eid)
    maplink = enc.get("maplink", None)
    return maplink
@app.get("/encounter/{eid}/state")
def getEncounter(eid : str):
    for encounter in ENCOUNTER_LIST:
        db_eid = encounter.get("eid", None)
        if eid == db_eid:
            logger.info(f"{eid} found!")
            return encounter
    logger.info(f"{eid} not found!")
@app.get("/encounter/{eid}/recommendation/{cid}")
def actionRecommendation(eid : str, cid : str):
    #Returns a list of all possible actions a given creature can perform, ordered by the rankings of best to worst.
    encounter = main.loadEncounter(getEncounter(eid))
    initiative = main.setActiveInitiative(encounter)
    players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
    playercids = [player.getCID().lower() for player in players]
    if cid.lower() in playercids:
        player = players[playercids.index(cid.lower())]
        rankings = main.playerTurn(player, initiative)
        return rankings
    else:
        monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
        monstercids = [monster.getCID().lower() for monster in monsters]
        if cid.lower() in monstercids:
            monster = monsters[monstercids.index(cid.lower())]
            rankings = main.monsterTurn(monster, initiative)
            logger.info("Rankings for %s: %s", eid, rankings)
            return rankings
@app.get("/uuid")
def getUUID():
    my_uuid_object = uuid.uuid4()
    my_uuid_string = str(my_uuid_object)
    logger.info(my_uuid_string)
    return my_uuid_string



@app.get("/encounter/{eid}/initiative/nextturn")
def getNextTurn(eid : str):
    encounter = main.loadEncounter(getEncounter(eid))
    initiative = encounter.getInitiative()
    for i, turn in enumerate(initiative):
        if turn["currentTurn"]:
            logger.info("currentTurn creature: " + turn["name"])
            turn["currentTurn"] = False
            if i == len(initiative) - 1:
                initiative[0]["currentTurn"] = True
                logger.info("New currentTurnCreature: " + initiative[0]["name"])
            else:
                initiative[i + 1]["currentTurn"] = True
                logger.info("New currentTurnCreature: " + initiative[i + 1]["name"])
            break
    currentCreature = {}
    for creature in initiative:
        #Add creature statblock to their associated turn
        #SHALLOW COPY OF MONSTER/PLAYER OBJECTS - Changes to creature["Statblock"] affect associated object in encounter
        if creature["turnType"] == "Player":
            for i in range(encounter.playerSize()):
                if creature["name"].lower() == encounter.getPlayer(i).getName().lower():
                    currentCreature = encounter.getPlayer(i)
                    break
        elif creature["turnType"] == "Monster":
            for i in range(encounter.monsterSize()):
                if creature["name"].lower() == encounter.getMonster(i).getName().lower():
                    currentCreature = encounter.getMonster(i)
                    break
    preEffects = []
    appendTurnCountResID = []
    refreshFlag = False
    for effect in currentCreature.getActiveStatusEffects():
        if effect["name"].lower() in ["lingsave", "lingeffect"]:
            preEffects.append(effect)

            # Deals with 1Turn shenanigans
            resultIDs = effect["effect"]["resultID"]
            resultIDs = main.ensureList(resultIDs)
            for i, resultID in enumerate(resultIDs):
                if resultID != -1:
                    result = encounter.getResultByID(resultID)
                    if "turnCount" in result and "turnCap" in result:
                        if int(result["turnCount"]) >= int(result["turnCap"]):
                            main.endSpellEffect(effect, i, currentCreature, main.setActiveInitiative(encounter))
                        else:
                            result["turnCount"] += 1
                            appendTurnCountResID.append(resultID)
                        refreshFlag = True

    main.saveEncounter(encounter)
    refresh()
    preEffects = {"preEffects" : preEffects, "refresh" : refreshFlag}
    logger.info(f"preEffects: {preEffects}")
    return preEffects
@app.get("/encounter/{eid}/initiative/currentturn")
def getTurn(eid : str):
    encounter = getEncounter(eid)
    initiative = encounter.get("initiative", [])
    for turn in initiative:
        if turn["currentTurn"]:
            return turn["name"]
    return {"error" : "no turns in initiative!"}
@app.get("/encounter/{eid}/initiative")
def getInitiative(eid : str):
    enc = getEncounter(eid)
    return enc.get("initiative", [])
@app.post("/encounter")
def postEncounter(encounter : Encounter):
    ENCOUNTER_LIST.append(encounter.model_dump(mode="json", by_alias=True))
    with open("CoreEngine/data/encounter_list.json", "w") as wf:
        json.dump(ENCOUNTER_LIST, wf, indent=4)
    refresh()
    return dict(verification="true")



@app.get("/dashboard/{eid}/packet")
def getEncounterMiniData(eid : str):
    encounter = getEncounter(eid)
    players = encounter.get("players", [])
    monsters = encounter.get("monsters", [])
    logger.info(players)
    logger.info(monsters)
    p_packet = [{"name" : player.get("stats").get("name"), "level" : player.get("stats").get("level"),
               "characterClass" : player.get("stats").get("characterClass")} for player in players]
    m_packet = [{"name" : monster.get("name"), "cr" : monster.get("cr"), "size" : monster.get("size")} for monster in monsters]
    return {"players" : p_packet, "monsters" : m_packet}
@app.get("/dashboard/players")
def getPlayers():
    with open("CoreEngine/data/player_list.json", "r") as pf:
        player_list = json.load(pf)
    return player_list
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
@app.get("/dashboard/encounters")
def getEncounterPacket():
    return [{"name" : enc.get("name"), "date" : enc.get("date"), "eid" : enc.get("eid"), "completed" : enc.get("completed")} for enc in ENCOUNTER_LIST]
@app.post("/dashboard/players")
def postPlayerToPlayerList(player : Union[AnyPlayer, Player]):
    # TODO: Replace with DB call to add in.
    def addClassPassives():
        #List of classes with relevant passives:
        #Barbarian, Bard, Fighter, Monk, Paladin, Ranger, Rogue
            #List of add and forget passives (here):
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
    playerObj = main.getPlayerStats(playerJSON)
    print(playerObj.getClass())
    main.getSavedWeapons(playerObj, playerJSON["weapons"])
    main.getSavedSpells(playerObj, playerJSON["spells"])
    addClassPassives()
    main.savePlayer(playerObj)
    return dict(verification="true")

#DEBUG ROUTE
@app.get("/__whoami")
def whoami():
    return {
        "file": __file__,
        "cwd": os.getcwd(),
        "python": sys.executable,
        "pid": os.getpid(),
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)