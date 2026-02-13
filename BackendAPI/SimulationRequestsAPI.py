import json
import os
import sys
from typing import Dict, Union, List

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from BackendAPI.models import Sorcerer, ActionRequest, Monster, Player, Encounter, Spell, Weapon, MonAction
from dotenv import load_dotenv
from main import ensureList, endSpellEffect, setActiveInitiative

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

with open("../CoreEngine/data/encounter_list.json", "r") as rf: #TODO: DB pull here
    encounter_list = json.load(rf)
AnyPlayer = Union[Sorcerer]

# class Encounter(BaseModel):
#     name : str
#     hp : int
#
# class DamageRequest(BaseModel):
#     amount: int

# CREATURES: List[Union[Sorcerer, Monster]] = [#TEMP: Theoretical list of players based on encounter
#     Sorcerer.model_validate({
#         "className": "Sorcerer",
#         "cid" : "p1",
#         "lvl": 8,
#         "sorceryPoints": 5,
#         "chosenMetaMagics": [],
#         "stats": {
#             "name": "Test Sorcerer",
#             "level": 5,
#             "ac": 13,
#             "class": "sorcerer",
#             "statArray": [10, 14, 12, 18, 12, 16],
#             "hp": "66",
#             "maxHP": "30",
#             "activeConditions": [],
#             "activeStatusEffects": []
#         },
#         "weapons": [{
#                 "name": "pike",
#                 "properties": {
#                     "damage": "1d10",
#                     "damageType": "piercing",
#                     "weaponStat": "STR"
#                 }
#             }],
#         "spells": []
#     }),
#     Sorcerer.model_validate({
#         "className": "Sorcerer",
#         "cid" : "p2",
#         "lvl": 5,
#         "sorceryPoints": 5,
#         "chosenMetaMagics": [],
#         "stats": {
#             "name": "Test Sorcerer",
#             "level": 5,
#             "ac": 13,
#             "class": "sorcerer",
#             "statArray": [10, 14, 12, 18, 12, 16],
#             "hp": "70",
#             "maxHP": "30",
#             "activeConditions": [],
#             "activeStatusEffects": []
#         },
#         "weapons": [],
#         "spells": [{
#                 "spellname": "Cloud of Daggers",
#                 "level": "2",
#                 "targeting": [
#                     {
#                         "self": "false",
#                         "number": "-1",
#                         "rolls": {
#                             "rollType": "autoHit",
#                             "saveType": "none",
#                             "halfSave": "false",
#                             "damage": "4d4",
#                             "damageMod": "0"
#                         },
#                         "damType": [
#                             "slashing"
#                         ],
#                         "conditions": [],
#                         "statusEffect": [
#                             {
#                                 "name": "Concentration",
#                                 "effect": {}
#                             }
#                         ],
#                         "lingEffect": {
#                             "repeat": "true"
#                         },
#                         "extraEffect": {},
#                         "lingSave": {},
#                         "scaling": "2d4",
#                         "specialNotes": [],
#                         "actionCost": "action"
#                     }
#                 ]
#             }]
#     }),
#     Sorcerer.model_validate({
#         "className": "Sorcerer",
#         "cid" : "p3",
#         "lvl": 13,
#         "sorceryPoints": 5,
#         "chosenMetaMagics": [],
#         "stats": {
#             "name": "Test Sorcerer",
#             "level": 13,
#             "ac": 18,
#             "class": "sorcerer",
#             "statArray": [10, 14, 12, 18, 12, 16],
#             "hp": "100",
#             "maxHP": "30",
#             "activeConditions": [],
#             "activeStatusEffects": []
#         },
#         "weapons": [],
#         "spells": []
#     }),
#     Monster.model_validate({
#         "name": "Aboleth",
#         "cid" : "m4",
#         "cr": "10",
#         "creatureType": "Aberration",
#         "statArray": [
#             21,
#             9,
#             15,
#             18,
#             15,
#             18
#         ],
#         "hit_points": 135,
#         "AC": 17,
#         "saveProfs": [
#             5,
#             -1,
#             2,
#             4,
#             2,
#             4
#         ],
#         "lResists": "0",
#         "damResists": "",
#         "damImmunes": "",
#         "damVulns": "",
#         "conImmunes": "",
#         "magicResist": "false",
#         "lairAction": "false",
#         "actions": [
#             {
#                 "name": "Tail",
#                 "desc": "Melee Weapon Attack: +9 to hit, reach 10 ft., one target. Hit: 15 (3d6 + 5) bludgeoning damage.",
#                 "actionRange": "10",
#                 "numTarget": 1,
#                 "shape": "",
#                 "rolls": {
#                     "rollType": "toHit",
#                     "saveType": "",
#                     "halfSave": "false",
#                     "saveDC": "",
#                     "damage": "3d6",
#                     "attackBonus": 9,
#                     "damMod": 5
#                 },
#                 "damType": [
#                     "bludgeoning"
#                 ],
#                 "conditions": [
#                     ""
#                 ],
#                 "statusEffect": [],
#                 "lingEffect": {},
#                 "extraEffect": {},
#                 "lingSave": {},
#                 "actionCost": "action",
#                 "recharge": "",
#                 "specialNotes": [],
#                 "extraDamage": []
#             },
#             {
#                 "name": "Enslave (3/day)",
#                 "desc": "The aboleth targets one creature it can see within 30 ft. of it. The target must succeed on a DC 14 Wisdom saving throw or be magically charmed by the aboleth until the aboleth dies or until it is on a different plane of existence from the target. The charmed target is under the aboleth's control and can't take reactions, and the aboleth and the target can communicate telepathically with each other over any distance.\nWhenever the charmed target takes damage, the target can repeat the saving throw. On a success, the effect ends. No more than once every 24 hours, the target can also repeat the saving throw when it is at least 1 mile away from the aboleth.",
#                 "actionRange": "",
#                 "numTarget": 1,
#                 "shape": "",
#                 "rolls": {
#                     "rollType": "save",
#                     "saveType": "wisdom",
#                     "halfSave": "false",
#                     "saveDC": "14",
#                     "damage": "",
#                     "attackBonus": 0,
#                     "damMod": ""
#                 },
#                 "damType": [
#                     ""
#                 ],
#                 "conditions": [
#                     ""
#                 ],
#                 "statusEffect": [],
#                 "lingEffect": {},
#                 "extraEffect": {},
#                 "lingSave": {
#                     "saveType": "wisdom",
#                     "saveDC": "14",
#                     "timing": ""
#                 },
#                 "actionCost": "action",
#                 "recharge": "",
#                 "specialNotes": [],
#                 "extraDamage": []
#             }
#         ],
#         "legActions": [
#             {
#                 "name": "Detect",
#                 "desc": "The aboleth makes a Wisdom (Perception) check.",
#                 "cost": 1
#             },
#             {
#                 "name": "Tail Swipe",
#                 "desc": "The aboleth makes one tail attack.",
#                 "action": {
#                     "name": "Tail",
#                     "desc": "Melee Weapon Attack: +9 to hit, reach 10 ft., one target. Hit: 15 (3d6 + 5) bludgeoning damage.",
#                     "actionRange": "10",
#                     "numTarget": 1,
#                     "shape": "",
#                     "rolls": {
#                         "rollType": "toHit",
#                         "saveType": "",
#                         "halfSave": "false",
#                         "saveDC": "",
#                         "damage": "3d6",
#                         "attackBonus": 9,
#                         "damMod": 5
#                     },
#                     "damType": [
#                         "bludgeoning"
#                     ],
#                     "conditions": [
#                         ""
#                     ],
#                     "statusEffect": [],
#                     "lingEffect": {},
#                     "extraEffect": {},
#                     "lingSave": {},
#                     "actionCost": "action",
#                     "recharge": "",
#                     "specialNotes": [],
#                     "extraDamage": []
#                 },
#                 "cost": 1
#             },
#             {
#                 "name": "Psychic Drain (Costs 2 Actions)",
#                 "desc": "One creature charmed by the aboleth takes 10 (3d6) psychic damage, and the aboleth regains hit points equal to the damage the creature takes.",
#                 "cost": 2
#             }
#         ],
#         "spellInfo": {},
#         "multiattack": {
#             "name": "Multiattack",
#             "total": 3,
#             "split": []
#         }
#     })
# ]
# AnyCreature = Union[Sorcerer, Monster]

# temp_data = {"name" : "Hello, World", "hp" : 30}

#OLD ROUTES
# @app.get("/encounter", response_model=Encounter)
# async def getEncounter():
#     return Encounter(name=temp_data["name"], hp=temp_data["hp"])
#
# @app.post("/encounter/damage")
# def postDamage(n : DamageRequest):
#     print("HIT /encounter/damage", n.amount, "hp was", temp_data["hp"])
#     temp_data.update({"hp" : temp_data.get("hp") - n.amount})
#     return Encounter(name=temp_data["name"], hp=temp_data["hp"])


#SORCERER ROUTES
# @app.get("/creatures/{cid}", response_model=AnyCreature)
# def getSorcerer(cid : str):
#     creature = [c for c in CREATURES if c.get(cid, None)]
#     if creature is None:
#         raise HTTPException(404, f"Unknown cid: {cid}")
#     return creature
#
# @app.get("/creatures", response_model=Dict[str, AnyCreature])
# def getPlayers():
#     return AnyCreature

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

@app.get("/encounter/{eid}/creature/{cid}", response_model=Union[Player, Monster])
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
    creatureIdx = cids.index(cid)
    return creatures[creatureIdx]

@app.post("/encounter/{eid}/creature")
def addtoEncounter(eid : str, creature : Union[AnyPlayer, Monster]):
    encounter = getEncounter(eid)
    if isPlayer(creature):
        encounter.get("players", []).append(creature)
        pass
    else:
        encounter.get("monsters", []).append(creature)
    return {"verification" : "true"}


@app.get("/encounter/{eid}/state/maplink")
def getMapLink(eid : str):
    enc = getEncounter(eid)
    maplink = enc.get("maplink", None)
    return maplink
@app.get("/encounter/{eid}/state")
def getEncounter(eid : str):
    for encounter in encounter_list:
        db_eid = encounter.get("eid", None)
        if eid == db_eid:
            print(f"{eid} found!")
            return encounter
    print(f"{eid} not found!")

@app.get("/encounter/{eid}/initiative/nextturn")
def getNextTurn(eid : str):
    encounter = getEncounter(eid)
    initiative = encounter.get("initiative", [])
    for i, turn in enumerate(initiative):
        if turn["currentTurn"]:
            turn["currentTurn"] = False
            if i == len(initiative) - 1:
                initiative[0]["currentTurn"] = True
            else:
                initiative[i + 1]["currentTurn"] = True
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
            resultIDs = ensureList(resultIDs)
            for i, resultID in enumerate(resultIDs):
                if resultID != -1:
                    result = encounter.getResultByID(resultID)
                    if "turnCount" in result and "turnCap" in result:
                        if int(result["turnCount"]) >= int(result["turnCap"]):
                            endSpellEffect(effect, i, currentCreature, setActiveInitiative(encounter))
                        else:
                            result["turnCount"] += 1
                            appendTurnCountResID.append(resultID)
                        refreshFlag = True

    preEffects = {"preEffects" : preEffects, "refresh" : refreshFlag}
    return preEffects

@app.get("/encounter/{eid}/initiative")
def getInitiative(eid : str):
    enc = getEncounter(eid)
    return enc.get("initiative", [])

@app.post("/encounter")
def postEncounter(encounter : Encounter):
    encounter_list.append(encounter.model_dump(mode="json", by_alias=True))
    with open("../CoreEngine/data/encounter_list.json", "w") as wf:
        json.dump(encounter_list, wf, indent=4)
    return dict(verification="true")

@app.post("/dashboard/players")
def postPlayerToPlayerList(player : AnyPlayer):
    #TODO: Replace with DB call to add in.
    with open("../CoreEngine/data/player_list.json", "r") as rpf:
        player_list = json.load(rpf)
    player_list.append(player.model_dump(mode="json", by_alias=True))
    with open("../CoreEngine/data/player_list.json", "w") as wpf:
        json.dump(player_list, wpf, indent=4)
    return dict(verification="true")

# @app.post("/debug/damage")
# def resolve_outcome(p: ActionRequest):
#     targetedCreatures = []
#     cids = [c.get("cid", None) for c in CREATURES]
#     for cid in p.targets:
#         if cid in cids:
#             targetedCreatures.append([c for c in CREATURES if c.get(cid, None)][0])
#     if not targetedCreatures:
#         raise HTTPException(404, f"Unknown cids: {p.targets}")
#
#     damages = p.outcome["diceResults"]
#     if p.actionType.lower() == "tohit":
#         for i, roll in enumerate(p.outcome["rollResults"]):
#             if roll.lower() == "n":
#                 damages[i] = 0
#             elif roll.lower() == "crit":
#                 damages[i] = int(p.outcome["diceResults"][i]) * 2
#             else:
#                 damages[i] = int(p.outcome["diceResults"][i])
#     elif p.actionType.lower() == "save":
#         for i, roll in enumerate(p.outcome["rollResults"]):
#             if roll.lower() == "y":
#                 damages[i] = int(p.outcome["diceResults"][i]) / 2
#             else:
#                 damages[i] = int(p.outcome["diceResults"][i])
#     else:
#         for i, roll in enumerate(p.outcome["rollResults"]):
#             damages[i] = int(p.outcome["diceResults"][i])
#
#
#     for i, creature in enumerate(targetedCreatures):
#         if isinstance(creature, Monster):
#             print(f"HP CHANGED FROM {creature.hp}")
#             print(f"BY {damages[i]}")
#             creature.hp = str(int(creature.hp) - damages[i])
#             print(f"TO {creature.hp}")
#         else:
#             print(f"HP CHANGED FROM {creature.stats.hp}")
#             print(f"BY {damages[i]}")
#             creature.stats.hp = str(int(creature.stats.hp) - damages[i])
#             print(f"TO {creature.stats.hp}")
#     return dict(verification="true")

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
    uvicorn.run(app, host="0.0.0.0", port=8001) #default port. Runs the app for us.