import asyncio
import copy
import itertools
import json
import math
import os
import re
from datetime import datetime
from typing import Set, List, Dict, Any, Tuple, Optional

from pymongo.errors import PyMongoError
from scipy.stats import norm
from ml.main_hooks import make_training_record, predict_action_weight
from CoreEngine import Weapon, Spell, Monster, Player, Encounter, MonAction
from CoreEngine.DNDClasses import (
    Barbarian,
    Bard,
    Cleric,
    Druid,
    Fighter,
    Paladin,
    Sorcerer,
)
from db.db_access import init_indexes, get_encounter_by_eid, upsert_player_dict, upsert_encounter_dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "CoreEngine/data")

PLAYER_LIST_FILE = os.path.join(DATA_DIR, "player_list.json")
MONSTER_LIST_FILE = os.path.join(DATA_DIR, "monster_list.json")
ENCOUNTER_LIST_FILE = os.path.join(DATA_DIR, "encounter_list.json")
CONDITION_LIST_FILE = os.path.join(DATA_DIR, "condition_list.json")
SPELL_LIST_FILE = os.path.join(DATA_DIR, "spell_list.json")
STATUS_EFFECT_LIST_FILE = os.path.join(DATA_DIR, "status_effect_list.json")
WEAPONS_LIST_FILE = os.path.join(DATA_DIR, "weapons_list.json")
BASIC_ACTION_LIST_FILE = os.path.join(DATA_DIR, "basic_actions.json")

Coord = Tuple[int, int]

# PLAYER/MONSTER/SPELL/WEAPON CREATE/SAVE/LOAD METHODS
def getPlayerStats(data):
    def getClassStats(data, playerdata, characterClass):
        if characterClass.lower() == "barbarian":
            rageCharges = data["rageCharges"]
            isRaging = data["isRaging"]
            return Barbarian(playerdata[0], playerdata[1], playerdata[2], playerdata[3], playerdata[4],
                             playerdata[5], playerdata[6], playerdata[7], playerdata[8], playerdata[9], playerdata[10],
                             playerdata[11], playerdata[12], playerdata[13],
                             playerdata[14], rageCharges, isRaging)
        elif characterClass.lower() == "bard":
            bardicCharges = data["bardicCharges"]
            bardicDieType = data["bardicDieType"]
            magicalSecrets = data["magicalSecrets"]
            return Bard(playerdata[0], playerdata[1], playerdata[2], playerdata[3], playerdata[4],
                        playerdata[5], playerdata[6], playerdata[7], playerdata[8], playerdata[9], playerdata[10],
                        playerdata[11], playerdata[12], playerdata[13], playerdata[14], playerdata[15], bardicCharges,
                        bardicDieType,
                        magicalSecrets)
        elif characterClass.lower() == "cleric":
            turnUndeadCharges = data["turnUndeadCharges"]
            destroyUndeadCap = data["destroyUndeadCap"]
            return Cleric(playerdata[0], playerdata[1], playerdata[2], playerdata[3], playerdata[4],
                          playerdata[5], playerdata[6], playerdata[7], playerdata[8], playerdata[9], playerdata[10],
                          playerdata[11], playerdata[12], playerdata[13], playerdata[14], playerdata[15],
                          turnUndeadCharges,
                          destroyUndeadCap)
        elif characterClass.lower() == "druid":
            monster = data["monster"]
            wildShaped = data["wildShaped"]
            wildShapeCharges = data["wildShapeCharges"]
            return Druid(playerdata[0], playerdata[1], playerdata[2], playerdata[3], playerdata[4],
                         playerdata[5], playerdata[6], playerdata[7], playerdata[8], playerdata[9], playerdata[10],
                         playerdata[11], playerdata[12], playerdata[13], playerdata[14], playerdata[15], monster,
                         wildShaped,
                         wildShapeCharges)
        elif characterClass.lower() == "fighter":
            secondWindCharges = data["secondWindCharges"]
            actionSurgeCharges = data["actionSurgeCharges"]
            extraAttackAmt = data["extraAttackAmt"]
            return Fighter(
                playerdata[0],
                playerdata[1],
                playerdata[2],
                playerdata[3],
                playerdata[4],
                playerdata[5],
                playerdata[6],
                playerdata[7],
                playerdata[8],
                playerdata[9],
                playerdata[10],
                playerdata[11],
                playerdata[12],
                playerdata[13],
                playerdata[14],
                secondWindCharges,
                actionSurgeCharges,
                extraAttackAmt,
            )
        elif characterClass.lower() == "paladin":
            layOnHandsPool = data["layOnHandsPool"]
            return Paladin(playerdata[0], playerdata[1], playerdata[2], playerdata[3], playerdata[4],
                           playerdata[5], playerdata[6], playerdata[7], playerdata[8], playerdata[9], playerdata[10],
                           playerdata[11], playerdata[12], playerdata[13], playerdata[14], playerdata[15],
                           layOnHandsPool)
        elif characterClass.lower() == "sorcerer":
            sorceryPoints = data["sorceryPoints"]
            chosenMetaMagics = data["chosenMetaMagics"]
            return Sorcerer(playerdata[0], playerdata[1], playerdata[2], playerdata[3], playerdata[4],
                            playerdata[5], playerdata[6], playerdata[7], playerdata[8], playerdata[9], playerdata[10],
                            playerdata[11], playerdata[12], playerdata[13], playerdata[14], playerdata[15],
                            sorceryPoints,
                            chosenMetaMagics)
        else:
            return Player(playerdata[0], playerdata[1], playerdata[2], playerdata[3], playerdata[4],
                          playerdata[5], playerdata[6], playerdata[7], playerdata[8], playerdata[9], playerdata[10],
                          playerdata[11], playerdata[12], playerdata[13], playerdata[14], playerdata[15])

    stats = data["stats"]
    saveProfs = stats["saveProfs"]
    saveProfs = {a: int(i) for a, i in saveProfs.items()}
    playerName = stats["name"]
    playerLvl = int(stats["level"])
    playerAC = int(stats["ac"])
    if "hp" in stats:
        playerHP = int(stats["hp"])
    else:
        playerHP = -1
    class_type = stats["characterClass"]
    playerStats = stats["statArray"]
    playerStats = {a: int(i) for a, i in playerStats.items()}

    conImmunes = stats.get("conImmunes", [])
    activeStatusEffects = stats["activeStatusEffects"]
    activeConditions = stats["activeConditions"]

    damImmunes = stats["damImmunes"]
    damResists = stats["damResists"]
    damVulns = stats["damVulns"]

    cid = stats["cid"]
    position = stats["position"]

    spellSlots = stats["spellSlots"]

    playerdata = [playerName, playerStats, saveProfs, playerAC, playerHP, class_type, playerLvl, conImmunes, damImmunes,
                  damResists, damVulns, activeStatusEffects, activeConditions, cid, position, spellSlots]
    return getClassStats(data, playerdata, class_type)
def getSavedWeapons(player, data):
    searchdata = copy.deepcopy(data)
    for i, w in enumerate(searchdata):
        if " " in w:
            searchdata[i] = w.split(" ")[0]
    with open(WEAPONS_LIST_FILE, "r") as wlrf:
        weapons = json.load(wlrf)
    for weapon in weapons:
        if weapon["name"].lower() in searchdata:
            idx = searchdata.index(weapon["name"].lower())
            weaponName = weapon["name"]
            properties = weapon["properties"]
            if " " in data[idx]:  # VERSATILE
                for i in range(0, 2):
                    diceProperties = properties["damage"][i].split("d")
                    diceNum = int(diceProperties[0])
                    diceType = int(diceProperties[1])
                    statType = properties["weaponStat"]
                    if len(statType) > 1:  # FINESSE
                        if player.getStat(statType[0]) >= player.getStat(statType[1]):
                            statType = statType[0]
                        else:
                            statType = statType[1]
                    else:
                        statType = statType[0]

                    damageType = properties["damageType"]
                    damMod = player.getMod(statType)

                    player.addWeapon(weaponName, statType, diceNum, diceType, damageType, damMod)
            else:
                diceProperties = properties["damage"][0].split("d")
                diceNum = int(diceProperties[0])
                diceType = int(diceProperties[1])
                statType = properties["weaponStat"]
                if len(statType) > 1:  # FINESSE
                    if player.getStat(statType[0]) >= player.getStat(statType[1]):
                        statType = statType[0]
                    else:
                        statType = statType[1]
                else:
                    statType = statType[0]

                damageType = properties["damageType"]
                damMod = player.getMod(statType)

                player.addWeapon(weaponName, statType, diceNum, diceType, damageType, damMod)
def getSavedSpells(player, data):
    if data:
        data = [data[i].lower() for i in range(len(data))]
    else:
        return
    with open(SPELL_LIST_FILE, "r") as splrf:
        spells = json.load(splrf)
    for spell in spells:
        if spell["spellname"].lower() in data:
            spellName = spell["spellname"]
            spellLvl = int(spell["level"])
            target = spell["targeting"]
            if isinstance(target, list):
                target = target[0]
            targetNum = int(target["number"])
            spellRange = target["range"] if "range" in target else 0
            spellRange = 5 if spellRange == "W" else int(spellRange)
            spellShape = target.get("shape", "")
            spellRadius = int(target["radius"]) if "radius" in target and target["radius"] else 0
            damType = target["damType"]
            if len(damType) == 1:
                damType = damType[0]
            selfTarget = False
            if "self" in target and target["self"]:
                selfTarget = True
            conditions = None
            if "conditions" in target:
                conditions = target["conditions"]
            statusEffect = None
            if "statusEffect" in target:
                statusEffect = target["statusEffect"]
            lingEffect = None
            if "lingEffect" in target:
                lingEffect = target["lingEffect"]
            extraEffect = None
            if "extraEffect" in target:
                extraEffect = target["extraEffect"]
            lingSaves = None
            if "lingSave" in target:
                lingSaves = target["lingSave"]
            scaling = None
            if "scaling" in target:
                scaling = target["scaling"]
            specialNotes = False
            if "specialNotes" in target:
                specialNotes = target["specialNotes"]
            actionCost = target["actionCost"]

            rolls = target["rolls"]
            rollType = rolls["rollType"]
            saveType = rolls["saveType"]
            halfSave = rolls["halfSave"]
            damage = rolls["damage"]
            damageMod = 0
            if "damageMod" in rolls:  # Accounts for schema error
                if rolls["damageMod"] == "spellMod":
                    damageMod = player.getSpellMod()
                elif rolls["damageMod"] != "":
                    damageMod = int(rolls["damageMod"])
            diceNum = 0
            diceType = 0
            if damage and damage != "none":
                damage = damage.split("d")
                diceNum = int(damage[0])
                diceType = int(damage[1])

            player.addSpell(spellName, spellLvl, selfTarget, targetNum,
                            spellRange, rollType, saveType, halfSave, damageMod, diceNum, diceType,
                            damType, conditions, statusEffect, lingEffect, extraEffect, lingSaves,
                            scaling, actionCost, specialNotes, spellShape, spellRadius)
def addChosenSpell(spell, player):
    spellName = spell["spellname"]
    spellLvl = spell["level"]

    if isinstance(spell["targeting"], list) and len(spell["targeting"]) > 1:  # Multiple possible effects
        for spellTarget in spell["targeting"]:
            newSpell = {
                "spellname": spellTarget["targetType"],
                "level": spellLvl,
                "targeting": spellTarget
            }
            addChosenSpell(newSpell, player)  # Adds the multiple types of effects as individual spells.
    else:
        if isinstance(spell["targeting"], list):
            targeting = spell["targeting"][0]
        else:
            targeting = spell["targeting"]
        selfTarget = targeting["self"]
        targetNum = int(targeting["number"])
        targetRange = int(targeting["range"])
        spellShape = targeting.get("shape", "")
        spellRadius = int(targeting["radius"]) if targeting["radius"] else 0
        damType = targeting["damType"]
        if len(damType) == 1:
            damType = damType[0]
        conditions = None
        if len(targeting["conditions"]) != 0:
            conditions = targeting["conditions"]
        statusEffect = None
        if targeting["statusEffect"]:
            statusEffect = targeting["statusEffect"]
        lingEffect = None
        if targeting["lingEffect"]:
            lingEffect = targeting["lingEffect"]
        extraEffect = None
        if targeting["extraEffect"]:
            extraEffect = targeting["extraEffect"]
        lingSaves = None
        if targeting["lingSave"]:
            lingSaves = targeting["lingSave"]
        scaling = targeting["scaling"]
        specialNotes = None
        if len(targeting["specialNotes"]) != 0:
            specialNotes = targeting["specialNotes"]
        actionCost = targeting["actionCost"]

        spellRolls = targeting["rolls"]
        rollType = spellRolls["rollType"]
        saveType = spellRolls["saveType"]
        halfSave = spellRolls["halfSave"]
        damageDice = spellRolls["damage"]
        diceNum = 0
        diceType = 0
        if damageDice != "":
            damageDice = damageDice.split("d")
            diceNum = int(damageDice[0])
            diceType = int(damageDice[1])
        damageMod = 0
        if "damageMod" in spellRolls:  # Accounts for schema error
            if spellRolls["damageMod"] == "spellMod":
                damageMod = player.getSpellMod()
            elif spellRolls["damageMod"] != "":
                damageMod = int(spellRolls["damageMod"])

        if spellLvl == 0:
            # Cantrips scale at lvls 5, 11, and 17.
            if scaling and "d" in scaling:
                if player.getLevel() >= 5:
                    diceNum += 1
                    if player.getLevel() >= 11:
                        diceNum += 1
                        if player.getLevel() >= 17:
                            diceNum += 1
            elif scaling and "extraTarget" in scaling:
                if player.getLevel() >= 5:
                    targetNum += 1
                    if player.getLevel() >= 11:
                        targetNum += 1
                        if player.getLevel() >= 17:
                            targetNum += 1

        player.addSpell(spellName, spellLvl, selfTarget, targetNum,
                        targetRange, rollType, saveType, halfSave, damageMod, diceNum, diceType,
                        damType, conditions, statusEffect, lingEffect, extraEffect, lingSaves,
                        scaling, actionCost, specialNotes, spellShape, spellRadius)

def findSpell(spellName, spellData):
    found = False
    i = 0
    while not found and i < len(spellData):
        if spellData[i]["spellname"] == spellName:
            found = True
        else:
            i += 1
    if found:
        return i
    else:
        return -1
async def savePlayer(player):
    # Adds a serialized player to an existing player_list JSON file.
    stats_dict = {
        "name": player.getName(),
        "level": str(player.getLevel()),
        "ac": str(player.getAC()),
        "hp": str(player.getHP()),
        "maxhp": str(player.getMaxHP()),
        "cid": str(player.getCID()),
        "position": player.getPosition(),
        "characterClass": player.getClass(),
        "conImmunes": player.getConImmunes(),
        "activeStatusEffects": player.getActiveStatusEffects(),
        "activeConditions": player.getActiveConditions(),
        "saveProfs": {
            stat: str(player.getSaveProf(stat))
            for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        },
        "damImmunes": player.getDamImmunities(),
        "damResists": player.getDamResistances(),
        "damVulns": player.getDamVulnerabilities(),
        "statArray": {
            stat: str(player.getStat(stat))
            for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        },
        "spellSlots": player.getSpellSlots(),
    }

    spells_list = []
    for i in range(player.getSpellLength()):
        spells_list.append(player.getSpell(i).getName().lower())

    weapons_list = []
    for i in range(player.getWeaponLength()):
        weapons_list.append(player.getWeapon(i).getName().lower())

    class_fields = {}

    cls = player.getClass().lower()

    if cls == "fighter":
        class_fields["secondWindCharges"] = player.getSecondWindCharges()
        class_fields["actionSurgeCharges"] = player.getActionSurge()
        class_fields["extraAttackAmt"] = player.getExtraAttackAmt()

    elif cls == "barbarian":
        class_fields["rageCharges"] = player.getRageCharges()
        class_fields["isRaging"] = player.isRaging()

    elif cls == "bard":
        class_fields["bardicCharges"] = player.getBardicCharges()
        class_fields["bardicDieType"] = player.getDieType()
        class_fields["magicalSecrets"] = player.getMagicalSecrets()

    elif cls == "cleric":
        class_fields["turnUndeadCharges"] = player.getTurnUndeadCharges()
        class_fields["destroyUndeadCap"] = player.getDestroyUndeadCap()

    elif cls == "druid":
        class_fields["monster"] = player.getMonster().toDict() if player.getMonster() else None
        class_fields["wildShaped"] = player.getWildShape()
        class_fields["wildShapeCharges"] = player.getWildShapeCharges()

    elif cls == "paladin":
        class_fields["layOnHandsPool"] = player.getLayOnHandsPool()

    elif cls == "sorcerer":
        class_fields["sorceryPoints"] = player.getSorceryPoints()
        class_fields["chosenMetaMagics"] = player.getChosenMetaMagics()

    player_dict = {
        "stats": stats_dict,
        "spells": spells_list,
        "weapons": weapons_list,
        **class_fields,
    }

    try:
        await upsert_player_dict(player_dict)
    except PyMongoError as err:
        raise err
def loadMonsterActions(monsterData):
    actionData = monsterData["actions"]
    actions = []
    for action in actionData:
        actionName = action["name"]
        # if isinstance(action["targeting"][0], list) and len(action["targeting"][0] > 1):
        # Multiple possible effects.
        # NOTE: This is not possible right now, as all current statblocks are NOT including actions with multiple possible effects.
        # It only takes the first possible effect from the list. If this is changed later, this code will be relevant.
        #     for actionTarget in action["targeting"][0]:
        #         newaction = {
        #             "actionname": actionTarget["targetType"],
        #             "level": actionLvl,
        #             "targeting": actionTarget
        #         }
        #         addChosenaction(newaction, player)  # Adds the multiple types of effects as individual actions.
        # else:
        numTarget = action.get("numTarget", -10)
        numTarget = int(action.get("number", 1)) if numTarget == -10 else int(numTarget)
        selfTarget = True if numTarget == 0 else False
        damType = action["damType"]
        if len(damType) == 1:
            damType = damType[0]
        actionCost = "action"
        recharge = action.get("recharge", [])
        actionRange = action["actionRange"]  # Unused for now, comes into play in mapping system
        actionDesc = action["desc"]
        actionShape = action["shape"]  # Unused for now, comes into play in mapping system
        extraDamage = action.get("extraDamage", [])
        # TODO: Ensure extra damage is added in and calculated in expectedDamage calcs later on.

        conditions = None
        if action["conditions"] is not None and len(action["conditions"]) != 0:
            conditions = action["conditions"]
        statusEffect = None
        if action["statusEffect"]:
            statusEffect = action["statusEffect"]
        lingEffect = None
        if action["lingEffect"]:
            lingEffect = action["lingEffect"]
        extraEffect = None
        if action["extraEffect"]:
            extraEffect = action["extraEffect"]
        lingSaves = None
        if action["lingSave"]:
            lingSaves = action["lingSave"]
        specialNotes = action.get("specialNotes", [])
        if specialNotes:
            specialNotes = action["specialNotes"]

        actionRolls = action["rolls"]
        rollType = actionRolls["rollType"]
        saveType = actionRolls["saveType"]
        halfSave = actionRolls["halfSave"]
        saveDC = actionRolls["saveDC"]
        damageDice = actionRolls["damage"]
        attackBonus = int(actionRolls["attackBonus"]) if "attackBonus" in actionRolls and actionRolls[
            "attackBonus"] else ""
        diceNum = 0
        diceType = 0
        if damageDice != "":
            damageDice = damageDice.split("d")
            diceNum = int(damageDice[0])
            diceType = int(damageDice[1])
        damageMod = 0
        if ("damMod" in actionRolls and actionRolls["damMod"] != "") or (
            "damageMod" in actionRolls and actionRolls["damageMod"] != ""
        ):  # Accounts for schema error
            damageMod = int(actionRolls.get("damageMod", 0))
            damageMod = int(actionRolls.get("damMod", 0)) if damageMod == 0 else damageMod
        actions.append(MonAction(actionName, actionDesc, selfTarget, numTarget, actionRange, actionShape,
                                 rollType, saveType, saveDC, halfSave,
                                 damageMod,diceNum, diceType,
                                 attackBonus, extraDamage, damType, conditions,
                                 statusEffect, lingEffect, extraEffect,
                                 lingSaves, actionCost, recharge, specialNotes))
    return actions
def loadMonsterSpells(monsterData):
    def loadSpell(spell):
        spellName = spell["spellname"]
        spellLvl = spell["level"]

        if (
            isinstance(spell["targeting"], list) and len(spell["targeting"]) > 1
        ):  # Multiple possible effects
            for spellTarget in spell["targeting"]:
                newSpell = {
                    "spellname": spellTarget["targetType"],
                    "level": spellLvl,
                    "targeting": spellTarget,
                }

                loadSpell(
                    newSpell
                )  # Adds the multiple types of effects as individual spells.
        else:
            if isinstance(spell["targeting"], list):
                targeting = spell["targeting"][0]
            else:
                targeting = spell["targeting"]
            selfTarget = targeting["self"]
            targetNum = int(targeting["number"])
            targetRange = int(targeting["range"])
            spellShape = targeting.get("shape", "")
            spellRadius = int(targeting["radius"]) if targeting["radius"] else 0
            damType = targeting["damType"]
            if len(damType) == 1:
                damType = damType[0]
            conditions = None
            if len(targeting["conditions"]) != 0:
                conditions = targeting["conditions"]
            statusEffect = None
            if targeting["statusEffect"]:
                statusEffect = targeting["statusEffect"]
            lingEffect = None
            if targeting["lingEffect"]:
                lingEffect = targeting["lingEffect"]
            extraEffect = None
            if targeting["extraEffect"]:
                extraEffect = targeting["extraEffect"]
            lingSaves = None
            if targeting["lingSave"]:
                lingSaves = targeting["lingSave"]
            scaling = targeting["scaling"]
            specialNotes = None
            if len(targeting["specialNotes"]) != 0:
                specialNotes = targeting["specialNotes"]

            actionCost = targeting["actionCost"]
            spellRolls = targeting["rolls"]
            rollType = spellRolls["rollType"]
            saveType = spellRolls["saveType"]
            halfSave = spellRolls["halfSave"]
            damageDice = spellRolls["damage"]
            diceNum = 0
            diceType = 0
            if damageDice != "":
                damageDice = damageDice.split("d")
                diceNum = int(damageDice[0])
                diceType = int(damageDice[1])
            damageMod = 0
            if "damageMod" in spellRolls:  # Accounts for schema error
                if spellRolls["damageMod"] != "" and spellRolls["damageMod"] != "spellMod":
                    damageMod = int(spellRolls["damageMod"])
                elif spellRolls["damageMod"] == "spellMod":
                    damageMod = int(monsterData["spellInfo"]["DC"]) - 10
            spellData = Spell(spellName, spellLvl, selfTarget, targetNum, targetRange,
                              rollType, saveType, halfSave, damageMod, diceNum,
                              diceType, damType, conditions, statusEffect, lingEffect,
                              extraEffect, lingSaves, scaling,
                              actionCost, specialNotes, spellShape, spellRadius)
            return spellData

    # Converts string names to actual spells if they exist in the spell list.
    spellJSON = monsterData["spellInfo"]
    if not spellJSON:
        return {}
    spellType = spellJSON["type"]
    spellDC = spellJSON["DC"]
    spellAttack = spellJSON["attackRoll"]
    spells = spellJSON["spells"]
    with open(SPELL_LIST_FILE, "r") as rf:
        rawSpellData = json.load(rf)
        for i, spell in enumerate(spells):
            if spell["name"].lower() in [s["spellname"].lower() for s in rawSpellData]:
                spellIdx = [s["spellname"].lower() for s in rawSpellData].index(spell["name"].lower())
                spells[i]["spellData"] = loadSpell(rawSpellData[spellIdx])
    if "spellSlots" in spellJSON:
        spellSlots = spellJSON["spellSlots"]
    else:
        spellSlots = []
    spellInfo = {
        "type": spellType,
        "DC": spellDC,
        "attackRoll": spellAttack,
        "spells": spells,
        "spellSlots": spellSlots,
    }
    return spellInfo

# ENCOUNTER CREATE/SAVE/LOAD METHODS
async def saveEncounter(encounter):
    # Adds a serialized encounter to an existing encounter_list JSON file.
    def saveClassStats(player, saveDict, characterClass):
        characterClass = characterClass.lower()

        if characterClass == "barbarian":
            saveDict["rageCharges"] = player.getRageCharges()
            saveDict["isRaging"] = player.isRaging()

        elif characterClass == "bard":
            saveDict["bardicCharges"] = player.getBardicCharges()
            saveDict["bardicDieType"] = player.getBardicDieType()
            saveDict["magicalSecrets"] = player.getMagicalSecrets()

        elif characterClass == "cleric":
            saveDict["turnUndeadCharges"] = player.getTurnUndeadCharges()
            saveDict["destroyUndeadCap"] = player.getDestroyUndeadCap()

        elif characterClass == "druid":
            saveDict["monster"] = player.getMonster()
            saveDict["wildShaped"] = player.isWildShaped()
            saveDict["wildShapeCharges"] = player.getWildShapeCharges()

        elif characterClass == "fighter":
            saveDict["secondWindCharges"] = player.getSecondWindCharges()
            saveDict["actionSurgeCharges"] = player.getActionSurgeCharges()
            saveDict["extraAttackAmt"] = player.getExtraAttackAmt()

        elif characterClass == "paladin":
            saveDict["layOnHandsPool"] = player.getLayOnHandsPool()

        elif characterClass == "sorcerer":
            saveDict["sorceryPoints"] = player.getSorceryPoints()
            saveDict["chosenMetaMagics"] = player.getChosenMetaMagics()

    monster_list = []
    for i in range(encounter.monsterSize()):
        monster_list.append(encounter.getMonster(i).toDict())

    player_list = []
    for i in range(encounter.playerSize()):
        player = encounter.getPlayer(i)
        stats_dict = {
            "name": player.getName(),
            "level": str(player.getLevel()),
            "ac": str(player.getAC()),
            "hp": str(player.getHP()),
            "maxhp": str(player.getMaxHP()),
            "cid": str(player.getCID()),
            "position": player.getPosition(),
            "characterClass": player.getClass(),
            "conImmunes": player.getConImmunes(),
            "activeStatusEffects": player.getActiveStatusEffects(),
            "activeConditions": player.getActiveConditions(),
            "saveProfs": {stat: str(player.getSaveProf(stat)) for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]},
            "damImmunes": player.getDamImmunities(),
            "damResists": player.getDamResistances(),
            "damVulns": player.getDamVulnerabilities(),
            "statArray": {stat: str(player.getStat(stat)) for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]},
            "spellSlots": player.getSpellSlots()
        }
        spells_list = []
        for j in range(player.getSpellLength()):
            spells_list.append(player.getSpell(j).getName().lower())

        weapons_list = []
        for j in range(player.getWeaponLength()):
            weapons_list.append(player.getWeapon(j).getName().lower())

        player_dict = {
            "stats": stats_dict,
            "spells": spells_list,
            "weapons": weapons_list,
        }
        saveClassStats(player, player_dict, player.getClass())
        player_list.append(player_dict)

    result_list = [encounter.getResultByIdx(i) for i in range(encounter.resultSize())]
    mapData = encounter.getMapData()
    if mapData:
        mapDataDict = {
                "map": {
                    "mapLink": str(mapData.get("map", {}).get("mapLink", "")),
                    "sourceType": str(mapData.get("map", {}).get("sourceType", "")),
                    "originPx": {
                        "x": int(mapData.get("map", {}).get("originPx", {}).get("x", 0)),
                        "y": int(mapData.get("map", {}).get("originPx", {}).get("y", 0))
                    },
                    "naturalSizePx": {
                        "w": int(mapData.get("map", {}).get("naturalSizePx", {}).get("w", 0)),
                        "h": int(mapData.get("map", {}).get("naturalSizePx", {}).get("h", 0))
                    }
                },
                "grid": {
                    "cellBounds": {
                        "cols": int(mapData.get("grid", {}).get("cellBounds", {}).get("cols", 0)),
                        "rows": int(mapData.get("grid", {}).get("cellBounds", {}).get("rows", 0))
                    },
                    "cellSizePx": int(mapData.get("grid", {}).get("cellSizePx", 0))
                },
                "layers": {
                    "creatureTokens": [
                        {
                            "cid": str(t.get("cid", "")),
                            "token_image": t.get("token_image")
                        }
                        for t in mapData.get("layers", {}).get("creatureTokens", [])
                    ],
                    "aoeTokens": [
                        {
                            "cid": t.get("cid"),
                            "resultID": t.get("resultID", ""),
                            "name": t.get("name"),
                            "shape": t.get("shape", ""),
                            "anchor": {
                                "x" : t.get("anchor").get("x"),
                                "y" : t.get("anchor").get("y")
                            },
                            "timing": t.get("timing"),
                            "token_image" : t.get("token_image"),
                            "positioning" : t.get("positioning")
                        }
                        for t in mapData.get("layers", {}).get("aoeTokens", [])
                    ]
                }
        }
    else:
        mapDataDict = None
    name = encounter.getName()
    encounter_dict = {
        "name": name,
        "date": encounter.getDate(),
        "eid": encounter.getEID(),
        "mapdata": mapDataDict,
        "completed": encounter.isComplete(),
        "monsters": monster_list,
        "players": player_list,
        "results": result_list,
        "initiative": encounter.getInitiative(),
    }

    try:
        await upsert_encounter_dict(encounter_dict)
    except PyMongoError as err:
        raise err
def loadEncounter(encounterData):
    # REFACTORING NOTES:
    # Uses encounterData from parameter instead of pulling it here.
    if encounterData["completed"]:
        return None
    mapData = encounterData["mapdata"] if "mapdata" in encounterData else {}
    encounter = Encounter(encounterData["name"], encounterData["date"], encounterData["eid"], mapData)

    for playerJSON in encounterData["players"]:
        playerObj = getPlayerStats(playerJSON)
        getSavedWeapons(playerObj, playerJSON["weapons"])
        getSavedSpells(playerObj, playerJSON["spells"])
        encounter.addPlayer(playerObj)
    for monsterJSON in encounterData["monsters"]:
        # name, cr, cType, stats, hp, maxHP, ac, saveProfs, lResists, damResists,
        # damImmunes, damVulns, conImmunes, lairAction, legAction
        name = monsterJSON["name"]
        cr = monsterJSON["cr"]
        cType = monsterJSON["creatureType"]
        stats = monsterJSON["statArray"]
        stats = {a: int(i) for a, i in stats.items()}
        hp = int(monsterJSON["hp"])
        maxHP = int(monsterJSON["maxhp"])
        ac = int(monsterJSON["ac"])
        saveProfs = {a: int(i) for a, i in monsterJSON["saveProfs"].items()}
        lResists = int(monsterJSON["lResists"])
        damResists = monsterJSON["damResists"]
        damImmunes = monsterJSON["damImmunes"]
        damVulns = monsterJSON["damVulns"]
        conImmunes = monsterJSON["conImmunes"]
        if "activeCons" in monsterJSON:
            acons = "activeCons"
            activeConditions = monsterJSON[acons]
        elif "activeConditions" in monsterJSON:
            acons = "activeConditions"
            activeConditions = monsterJSON[acons]
        else:
            activeConditions = []
        activeStatusEffects = monsterJSON["activeStatusEffects"]
        lairAction = bool(monsterJSON["lairAction"])
        magicResist = monsterJSON.get("magicResist", False)
        legActions = monsterJSON.get("legActions", [])
        enemy = bool(monsterJSON["enemy"])
        actions = loadMonsterActions(monsterJSON)
        spellInfo = loadMonsterSpells(monsterJSON)
        cid = monsterJSON.get("cid", "")
        position = monsterJSON.get("position", [0, 0])
        size = monsterJSON.get("size", "medium")
        movement = monsterJSON.get("movement", 0)
        encounter.addMonster(Monster(name, cr, cType, stats, hp, maxHP,
                                     ac, saveProfs, lResists, damResists,
                                     damImmunes, damVulns, conImmunes, activeConditions,
                                     activeStatusEffects, lairAction, magicResist,
                                     enemy, actions, spellInfo, legActions,
                                     cid, position, size, movement))
    for resultJSON in encounterData["results"]:
        encounter.addResult(resultJSON)

    encounter.setInitiative(encounterData["initiative"])
    return encounter

# GENERAL HELPER METHODS
def _as_int_feet(rng):
        if rng is None:
            return None
        if isinstance(rng, (int, float)):
            return int(rng)
        if isinstance(rng, str):
            s = rng.strip().lower()
            if s in {"self", "special", "unlimited"}:
                return None
            m = re.search(r"-?\d+", s)
            return int(m.group()) if m else None
        return None
def _chebyshev_tiles(p1, p2):
    # diagonal counts as 1 tile
    return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1]))
def _min_creature_distance_tiles(tiles_a, tiles_b):
    if not tiles_a or not tiles_b:
        return math.inf
    best = math.inf
    for a in tiles_a:
        for b in tiles_b:
            d = _chebyshev_tiles(a, b)
            if d < best:
                best = d
                if best == 0:  # overlapping tile: collision
                    return 0
    return best
def _normalize_occupied_tiles(pos):
    if pos is None:
        return []
    # If someone accidentally passes [r,c], wrap it
    if isinstance(pos, (list, tuple)) and len(pos) == 2 and all(isinstance(x, int) for x in pos):
        return [list(pos)]
    # Normal case: list of coordinates
    if isinstance(pos, (list, tuple)) and len(pos) > 0 and isinstance(pos[0], (list, tuple)):
        return [list(p) for p in pos if p is not None and len(p) == 2]
    return []
def normalizeTargetSets(targets, initiative):
    if isinstance(targets, dict) and "targetsHit" in targets:
        targets = targets["targetsHit"]
    elif isinstance(targets, dict) and "name" in targets:
        targets = [targets["name"]]
    for i, target in enumerate(targets):
        if isinstance(target, str):
            for creature in initiative:
                if creature["name"].lower() == target.lower():
                    targets[i] = copy.deepcopy(creature["Statblock"])
                    break
        elif isinstance(target, dict):
            if "name" in target and "targetScore" in target:
                for creature in initiative:
                    if creature["name"].lower() == target["name"].lower():
                        targets[i] = copy.deepcopy(creature["Statblock"])
                        break
            else:
                targets[i] = copy.deepcopy(target["Statblock"])
    return targets
def translateBasicAction(creature, action):
    # Should work for both monsters and players
    actionName = action["spellname"]
    targeting = action["targeting"][0]
    selfTarget = targeting["self"]
    targetNum = int(targeting["number"])
    damType = targeting["damType"]
    if len(damType) == 1:
        damType = damType[0]
    conditions = None
    if len(targeting["conditions"]) != 0:
        conditions = targeting["conditions"]
    statusEffect = None
    if targeting["statusEffect"]:
        statusEffect = targeting["statusEffect"]
    lingEffect = None
    if targeting["lingEffect"]:
        lingEffect = targeting["lingEffect"]
    extraEffect = None
    if targeting["extraEffect"]:
        extraEffect = targeting["extraEffect"]
    lingSaves = None
    if targeting["lingSave"]:
        lingSaves = targeting["lingSave"]

    actionRolls = targeting["rolls"]
    rollType = actionRolls["rollType"]
    saveType = actionRolls["saveType"]
    halfSave = actionRolls["halfSave"]
    damageDice = actionRolls["damage"]
    diceNum = 0
    diceType = 0
    if damageDice != "":
        damageDice = damageDice.split("d")
        diceNum = int(damageDice[0])
        diceType = int(damageDice[1])
    damageMod = 0
    if "damageMod" in targeting:  # Accounts for schema error
        if actionRolls["damageMod"] == "spellmod" and isinstance(creature, Player):
            damageMod = creature.getSpellMod()
        elif actionRolls["damageMod"] != "":
            damageMod = int(actionRolls["damageMod"])

    if actionName.lower() == "grapple":
        saveDC = 8 + creature.getProfBonus() + creature.getMod("STR")
    elif actionName.lower() == "shove" or actionName.lower() == "hide":
        saveDC = 8 + creature.getProfBonus() + creature.getMod("DEX")
    else:
        saveDC = 0

    return MonAction(actionName, "", selfTarget,
                     targetNum, 5, "", rollType, saveType,
                     saveDC, halfSave, damageMod, diceNum, diceType,
                     "", [], damType, conditions,
                     statusEffect, lingEffect, extraEffect, lingSaves,
                     "action", "", [])
def defineBasicActions(
    actionNames,
    actionTypes,
    actionProbs,
    actionEDams,
    actionImpacts,
    actionTargets,
    actionObjs,
    initEntry,
    initiative,
    isPlayerTurn,
):
    # Load basic actions
    try:
        with open(BASIC_ACTION_LIST_FILE, "r") as f:  # Basic actions are hardcoded into basic_actions file.
            actions = json.load(f)
    except FileNotFoundError:
        actions = []
    except json.JSONDecodeError:
        actions = []

    if len(actions) < 3:
        return

    if isPlayerTurn and not isinstance(initEntry, Player):
        creature = initEntry["Statblock"]
    elif not isinstance(initEntry, Monster):
        creature = initEntry["Statblock"]
    else:
        creature = initEntry

    grapple, shove, dodge = actions[0], actions[1], actions[2]
    grapple = translateBasicAction(creature, grapple)
    shove = translateBasicAction(creature, shove)
    dodge = translateBasicAction(creature, dodge)

    if actionViabilityCheck(grapple, initEntry, initiative, isPlayerTurn):
        grappleProb = calcTotalSaveProbability(creature, grapple, initiative)  # Calculate probability of save
        grappleProb["probSuccess"] = 0 if grappleProb["probSuccess"] < 0 else grappleProb["probSuccess"]
        grappleProb["probSuccess"] = 1 if grappleProb["probSuccess"] > 1 else grappleProb["probSuccess"]

        probToStr = f"{grappleProb['probSuccess']}"
        probToStr += f" - {grappleProb['probLingEffect']}LE" if grappleProb["probLingEffect"] else ""
        probToStr += f" - {grappleProb['probExtraEffect']}EE" if grappleProb["probExtraEffect"] else ""
        probToStr += f" - {grappleProb['probLingSaves']}LS" if grappleProb["probLingSaves"] else ""

        probTargets = grappleProb["target"] if grappleProb["probSuccess"] != 0 else ""
        targets = normalizeTargetSets(probTargets, initiative)
        grappleProb = probToStr

        grappleImpact = calcImpact(
            creature,
            grapple,
            grappleProb,
            0,
            targets,
            initiative,
        )
        grappleImpact = max(0.0, min(20.0, grappleImpact - 2))

        actionNames.append(grapple.getName())
        actionTypes.append("Basic")
        actionProbs.append(grappleProb)
        actionEDams.append(0)
        actionImpacts.append(grappleImpact)
        actionTargets.append(targets)
        actionObjs.append(grapple)

    if actionViabilityCheck(shove, initEntry, initiative, isPlayerTurn):
        shoveProb = calcTotalSaveProbability(creature, shove, initiative)
        shoveProb["probSuccess"] = 0 if shoveProb["probSuccess"] < 0 else shoveProb["probSuccess"]
        shoveProb["probSuccess"] = 1 if shoveProb["probSuccess"] > 1 else shoveProb["probSuccess"]

        probToStr = f"{shoveProb['probSuccess']}"
        probToStr += f" - {shoveProb['probLingEffect']}LE" if shoveProb["probLingEffect"] else ""
        probToStr += f" - {shoveProb['probExtraEffect']}EE" if shoveProb["probExtraEffect"] else ""
        probToStr += f" - {shoveProb['probLingSaves']}LS" if shoveProb["probLingSaves"] else ""

        probTargets = shoveProb["target"] if shoveProb["probSuccess"] != 0 else ""
        targets = normalizeTargetSets(probTargets, initiative)
        shoveProb = probToStr

        shoveImpact = calcImpact(
            creature,
            shove,
            shoveProb,
            0,
            targets,
            initiative,
        )
        shoveImpact = max(0.0, min(20.0, shoveImpact - 2))

        actionNames.append(shove.getName())
        actionTypes.append("Basic")
        actionProbs.append(shoveProb)
        actionEDams.append(0)
        actionImpacts.append(shoveImpact)
        actionTargets.append(targets)
        actionObjs.append(shove)

    if actionViabilityCheck(dodge, initEntry, initiative, isPlayerTurn):
        dodgeProb = 1.0
        dodgeTargets = [initEntry["Statblock"]]
        dodgeImpact = calcImpact(
            creature,
            dodge,
            dodgeProb,
            0,
            dodgeTargets,
            initiative,
        )
        dodgeImpact = max(0.0, min(20.0, dodgeImpact - 2))

        actionNames.append(dodge.getName())
        actionTypes.append("Basic")
        actionProbs.append(dodgeProb)
        actionEDams.append(0)
        actionImpacts.append(dodgeImpact)
        actionTargets.append(dodgeTargets)
        actionObjs.append(dodge)

def calcDamProbs(creatureStats, action, modifier, threshold):
    def prob_damage_at_least_normal(thresh, diceNum, sides, flatMod=0):
        # Approximates P(sum of dice + flatMod >= threshold)
        mu = diceNum * (sides + 1) / 2
        sigma = math.sqrt(diceNum * (sides**2 - 1) / 12)
        z = (thresh - flatMod - 0.5 - mu) / sigma
        return 1 - norm.cdf(z)

    def prob_damage_at_least(thresh, dice, sides, flat):
        if dice >= 6:
            return prob_damage_at_least_normal(thresh, dice, sides, flat)

        total = 0
        favorable = 0
        for roll in itertools.product(range(1, sides + 1), repeat=dice):
            dmg = sum(roll) + flat
            total += 1
            if dmg >= thresh:
                favorable += 1
        return favorable / total

    diceNum = action.getDiceNum()
    dieType = action.getSides()
    if threshold == "NORM":
        threshold = ((diceNum * dieType) + modifier) / 2
    if threshold == "MULT":
        threshold = (diceNum * dieType) + modifier

    normDamProb = 0
    critDamProb = 0
    if isinstance(creatureStats, Player) and not isinstance(action.getDamType(),
                                                            list) and action.getDamType().lower() == "healing":
        if creatureStats.isActiveCondition("Downed") or creatureStats.isActiveCondition("Stabilized"):
            normDamProb = 1.0
        elif action.getMean() != 0:
            normDamProb = action.getMean() / creatureStats.getHP()
        else:
            normDamProb = 0
        return normDamProb, 0
    if (
        isinstance(action.getDamType(), list)
        and len(action.getDamType()) != 1
        and len(action.getDamType()) != 0
    ):
        if action.getDamType()[-1] == "AND":
            numDamTypes = len(action.getDamType()) - 1
            # Assume a clean divide when having multiple damage types. 10d6 should only have 2 damTypes, never 3.
            # MEANING, there should never be a prime number of diceNums with multiple damageTypes.
            # Looking at you, Ice Storm. You suck.
            diceNums = list(itertools.repeat(diceNum / numDamTypes, numDamTypes))
            diceNums = [int(diceNum) for diceNum in diceNums]
            for i in range(len(diceNums)):
                if creatureStats.isImmune(action.getDamType()[i]):
                    diceNums[i] = 0
                elif creatureStats.isVulnerable(action.getDamType()[i]):
                    if not creatureStats.isResistant(action.getDamType()[i]):
                        diceNums[i] *= 2
                elif creatureStats.isResistant(action.getDamType()[i]):
                    diceNums[i] = math.floor(diceNums[i] / 2)
            diceNum = sum(diceNums)
            normDamProb += prob_damage_at_least(threshold, diceNum, dieType, modifier)
            critDamProb += prob_damage_at_least(
                threshold, 2 * diceNum, dieType, modifier
            )
        else:  # OR
            if all(True if creatureStats.isImmune(damType) and damType != "OR" else False for damType in
                   action.getDamType()):
                normDamProb = 0
                critDamProb = 0
            elif all(
                creatureStats.isResistant(damType) for damType in action.getDamType()
            ):
                if not any(
                    creatureStats.isVulnerable(damType)
                    for damType in action.getDamType()
                ):
                    normDamProb = prob_damage_at_least(
                        threshold * 2, diceNum, dieType, modifier
                    )
                    critDamProb = prob_damage_at_least(
                        threshold * 2, 2 * diceNum, dieType, modifier
                    )
                else:
                    normDamProb = prob_damage_at_least(
                        threshold, diceNum, dieType, modifier
                    )
                    critDamProb = prob_damage_at_least(
                        threshold, 2 * diceNum, dieType, modifier
                    )
            elif any(
                creatureStats.isVulnerable(damType) for damType in action.getDamType()
            ):
                diceNum *= 2
                normDamProb = prob_damage_at_least(
                    threshold, diceNum, dieType, modifier
                )
                critDamProb = prob_damage_at_least(
                    threshold, 2 * diceNum, dieType, modifier
                )
            else:
                normDamProb = prob_damage_at_least(
                    threshold, diceNum, dieType, modifier
                )
                critDamProb = prob_damage_at_least(
                    threshold, 2 * diceNum, dieType, modifier
                )
    else:
        creatureStats = creatureStats["Statblock"] if (isinstance(creatureStats, dict) and
                                                       "Statblock" in creatureStats) else creatureStats
        if creatureStats.isImmune(action.getDamType()):
            normDamProb = 0
            critDamProb = 0
        elif creatureStats.isVulnerable(action.getDamType()):
            if not creatureStats.isResistant(action.getDamType()):
                diceNum *= 2
                normDamProb = prob_damage_at_least(
                    threshold, diceNum, dieType, modifier
                )
                critDamProb = prob_damage_at_least(
                    threshold, 2 * diceNum, dieType, modifier
                )
            else:
                normDamProb = prob_damage_at_least(
                    threshold, diceNum, dieType, modifier
                )
                critDamProb = prob_damage_at_least(
                    threshold, 2 * diceNum, dieType, modifier
                )
        elif creatureStats.isResistant(action.getDamType()):
            # Halving final damage means threshold effectively doubles
            normDamProb = prob_damage_at_least(
                threshold * 2, diceNum, dieType, modifier
            )
            critDamProb = prob_damage_at_least(
                threshold * 2, 2 * diceNum, dieType, modifier
            )
        else:
            normDamProb = prob_damage_at_least(threshold, diceNum, dieType, modifier)
            critDamProb = prob_damage_at_least(
                threshold, 2 * diceNum, dieType, modifier
            )
    return normDamProb, critDamProb
def translateLingEffect(action, lingEffect, spellMod):
    if (
        isinstance(lingEffect, dict) and "repeat" in lingEffect
    ) or lingEffect == "repeat":
        action = copy.deepcopy(action)
        action.setLingEffects({})
        action.setLingSaves({})
        return action

    # 2. Parse damage info
    try:
        lingDieNum, lingDieType = map(int, lingEffect["rolls"]["damage"].split("d"))
    except Exception:
        lingDieNum, lingDieType = 0, 0

    # 3. Handle damage modifier
    damMod = 0
    if "damageMod" in lingEffect["rolls"]:
        dm = lingEffect["rolls"]["damageMod"]
        if dm == "spellMod":
            damMod = spellMod
        elif isinstance(dm, str) and dm.isdigit():
            damMod = int(dm)

    # 4. Build the lingering Spell object
    if "number" in lingEffect:
        numTarget = int(lingEffect["number"])
    else:
        numTarget = action.getNumTarget()

    if "specialNotes" in lingEffect:
        specialNotes = lingEffect["specialNotes"]
    else:
        specialNotes = []

    if "conditions" in lingEffect:
        conditions = lingEffect["conditions"]
    else:
        conditions = []

    if "statusEffect" in lingEffect:
        statusEffect = lingEffect["statusEffect"]
    else:
        statusEffect = []


    lingDamType = lingEffect["damType"]
    if isinstance(lingDamType, list) and len(lingDamType) == 1:
        lingDamType = lingDamType[0]
    lingSpell = Spell(
        action.getName(), action.getLvl(), action.getSelfTarget(), numTarget,
        action.getActionRange(), lingEffect["rolls"]["rollType"], lingEffect["rolls"]["saveType"],
        lingEffect["rolls"]["halfSave"],
        damMod, lingDieNum, lingDieType, lingDamType,
        conditions, statusEffect, {}, {}, {}, "", "",
        specialNotes, action.getShape(), action.getActionRadius()
    )
    return lingSpell
def calcLingeringEffectProbability(player, target, action, lingEffect, successProb):
    # 1. Repeat check
    if "repeat" in lingEffect and lingEffect["repeat"] == True:
        return successProb
    try:
        lingSpell = translateLingEffect(action, lingEffect, player.getSpellMod())
    except:
        return 0

    # 5. Route to correct probability function
    roll_type = lingSpell.getRollType().lower()
    if roll_type == "tohit":
        lingEffectProb = calcIndividualToHitProbability(player, lingSpell, target)
    elif roll_type == "save":
        lingEffectProb = calcIndividualSaveProbability(lingSpell, player.getDC(),  target)
    elif roll_type == "autohit":
        lingEffectProb = calcIndividualAutoHitProbability(lingSpell, target)
    else:
        lingEffectProb = 0
    # No spells have onHit lingering effects
    return lingEffectProb
def calcLingeringSavesProbability(player, target, spell):
    target = target[0] if isinstance(target, list) else target
    if isinstance(target, dict):
        target = target["Statblock"]
    if not target.isActiveStatusEffect("SwitchSides") \
            and not target.isActiveCondition("Dead") \
            and not target.isActiveCondition("Out of Combat"):
        saveProb = ((21 - player.getDC()) + target.getSaveProf(
            spell.getLingSaves()["saveType"])) / 20
        saveProb = min(max(saveProb, 0), 1)
        return saveProb
    return 0
def getMultiTargetWeights(player, action, initiative):
    modifier = player.getSpellMod()
    weights = []
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    for creature in initiative:
        if isValidTarget(action, creature, player.getPosition(),isPlayerTurn):
            eDam = calcIndividualExpectedDamage(player, action, creature)
            hp = creature["Statblock"].getHP()
            if action.getRollType().lower() == "tohit":
                probNormalHit, critChance = defProbHit(
                    player, creature["Statblock"], modifier
                )
                killDamProb, killCritDamProb = calcDamProbs(
                    creature["Statblock"], action, modifier, hp
                )
                killProb = probNormalHit * killDamProb + critChance * killCritDamProb
            elif action.getRollType().lower() == "save":
                specImm, specRes, specVuln = saveSpecialNotesCheck(
                    action, creature["Statblock"]
                )
                probFail = 1 - defSave(action, player.getDC(), creature["Statblock"])
                modifier = action.getDamMod()
                killDamProb = calcDamProbs(creature["Statblock"], action, modifier, hp)[
                    0
                ]
                if action.getHalfSave():
                    probSave = 1 - probFail
                    saveKillDamProb = calcDamProbs(
                        creature["Statblock"], action, modifier, hp * 2
                    )[0]
                    killProb = probSave * saveKillDamProb + probFail * killDamProb
                else:
                    killProb = probFail * killDamProb
                resetSaveSpecialNotesCheck(
                    specImm, specRes, specVuln, creature["Statblock"]
                )
            elif action.getRollType().lower() == "autohit":
                killProb = calcDamProbs(creature["Statblock"], action, modifier, hp)[0]
            else:
                killProb = 0

            weights.append(
                {
                    "Weight": (eDam / max(hp, 1)) + 1.5 * killProb,
                    "Creature": copy.deepcopy(creature),
                }
            )
    weights = sorted(weights, key=lambda x: x["Weight"], reverse=True)
    weights = [weight["Creature"] for weight in weights]
    weights = weights[0 : min(action.getNumTarget(), len(weights))]
    return weights
def isValidTarget(action, creature, actorPos, isPlayerTurn=True):
    if isPlayerTurn:
        if isinstance(action, Weapon) or (isinstance(action, Spell) and action.getDamType() != "healing"):
            if (creature["turnType"] == "Monster"
                    and not creature["Statblock"].isActiveStatusEffect("SwitchSides")
                    and not creature["Statblock"].isActiveCondition("Dead")
                    and not creature["Statblock"].isActiveCondition("Out of Combat")):
                validTarget = True
            else:
                validTarget = False
        elif action.getDamType() == "healing":
            if (creature["turnType"] == "Player"
                    or (creature["turnType"] == "Monster" and creature["Statblock"].isActiveStatusEffect("SwitchSides"))
                    and not creature["Statblock"].isActiveCondition("Dead")
                    and not creature["Statblock"].isActiveCondition("Out of Combat")):
                validTarget = True
            else:
                validTarget = False
        else:
            validTarget = False
    else:
        if isinstance(action, MonAction) or isinstance(action, Spell) and action.getDamType() != "healing":
            if (creature["turnType"] == "Player"
                    and not creature["Statblock"].isActiveStatusEffect("SwitchSides")
                    and not creature["Statblock"].isActiveCondition("Dead")
                    and not creature["Statblock"].isActiveCondition("Out of Combat")):
                validTarget = True
            else:
                validTarget = False
        elif action.getDamType() == "healing":
            if (creature["turnType"] == "Monster"
                    or (creature["turnType"] == "Player" and creature["Statblock"].isActiveStatusEffect("SwitchSides"))
                    and not creature["Statblock"].isActiveCondition("Dead")
                    and not creature["Statblock"].isActiveCondition("Out of Combat")):
                validTarget = True
            else:
                validTarget = False
        else:
            validTarget = False
    if not validTarget:
        return False

    creature = creature["Statblock"] if "Statblock" in creature else creature
    actor_tiles = _normalize_occupied_tiles(actorPos)
    if not isinstance(action, Weapon):
        actionRangeFeet = _as_int_feet(action.getActionRange())
    else:
        actionRangeFeet = 5
    if actionRangeFeet is None:
        return False
    rangeTiles = math.ceil(actionRangeFeet / 5)
    others_tiles = [creature.getPosition()]
    for target_tiles in others_tiles:
        min_d = _min_creature_distance_tiles(actor_tiles, target_tiles)
        if min_d <= rangeTiles:
            return True
    return False
def ensureList(x):
    return x if isinstance(x, list) else [x]
def _cr_to_float(cr_str: str) -> float:
    s = str(cr_str).strip()
    if "/" in s:
        num, den = s.split("/")
        return float(num) / float(den)
    return float(s)
def bestAoePositioning(
    rangeFt: int,
    radiusFt: int,
    shape: str,
    allCreaturePositions: List[List[int]],
    allTargets: List[Dict[str, Any]],
    casterCells : List[List[int]],
    originMode : str = "placed"
) -> Dict[str, Any]:
    result = bestAoePositioningDebug(
        rangeFt=rangeFt,
        radiusFt=radiusFt,
        shape=shape,
        allCreaturePositions=allCreaturePositions,
        allTargets=allTargets,
        casterCells=casterCells,
        originMode=originMode
    )
    # result = {
    #     "coveredCells": covered,
    #     "anchor": anchor,
    #     "orientation": orientationName,
    #     "score": score,
    #     "targetsHit": targetBreakdown,
    # }
    return {"targetsHit" : result["targetsHit"], "positioning" : [[x, y] for x, y in result["coveredCells"]]}
    # return [[x, y] for x, y in result["coveredCells"]]
def getOrientedTemplateMasks(
        shapeKind: str,
        sizeCells: int,
        lineWidthCells: Optional[int] = None,
) -> List[Tuple[str, Set[Coord]]]:

    def squareMaskLookup(sideCells: int) -> Set[Coord]:
        # Anchor is top-left.
        return {(dx, dy) for dx in range(sideCells) for dy in range(sideCells)}

    def lineMaskLookup(lengthCells: int, widthCells: int) -> Set[Coord]:
        # Cardinal "up" line. Anchor is center of near edge.
        halfLeft = widthCells // 2
        halfRight = widthCells - halfLeft - 1

        mask = set()
        for step in range(lengthCells):
            y = -step
            for x in range(-halfLeft, halfRight + 1):
                mask.add((x, y))
        return mask

    def diagonalLineMaskLookup(lengthCells: int, widthCells: int) -> Set[Coord]:
        # Diagonal "up_right" line. Anchor is near endpoint.
        # Centerline: (0,0), (1,-1), (2,-2), ...
        # Width grows along the perpendicular diagonal.
        halfLeft = widthCells // 2
        halfRight = widthCells - halfLeft - 1

        mask = set()
        for step in range(lengthCells):
            cx = step
            cy = -step
            for offset in range(-halfLeft, halfRight + 1):
                mask.add((cx + offset, cy + offset))
        return mask

    def coneMaskLookup(lengthCells: int) -> Set[Coord]:
        mask = set()

        for step in range(1, lengthCells + 1):
            y = -step
            halfWidth = (step - 1) // 2
            for x in range(-halfWidth, halfWidth + 1):
                mask.add((x, y))

        return mask

    def diagonalConeMaskLookup(lengthCells: int) -> Set[Coord]:
        mask = set()

        for dx in range(lengthCells + 1):
            for negDy in range(lengthCells + 1):
                if 1 <= dx + negDy <= lengthCells:
                    mask.add((dx, -negDy))

        return mask

    def circleMaskLookup(radiusCells: int) -> Set[Coord]:
        mask = set()
        r2 = radiusCells ** 2

        for dy in range(-radiusCells, radiusCells + 1):
            remaining = r2 - (dy * dy)
            if remaining < 0:
                continue

            maxDx = math.isqrt(remaining)
            for dx in range(-maxDx, maxDx + 1):
                mask.add((dx, dy))

        return mask

    if shapeKind == "circle":
        base = circleMaskLookup(sizeCells)
        return [("center", base)]

    if shapeKind == "square":
        base = squareMaskLookup(sizeCells)
        return [("fixed", base)]

    if shapeKind == "cone":
        up = coneMaskLookup(sizeCells)
        upRight = diagonalConeMaskLookup(sizeCells)

        return [
            ("up", up),
            ("up_right", upRight),
            ("right", rotateMask90(up)),
            ("down_right", rotateMask90(upRight)),
            ("down", rotateMask180(up)),
            ("down_left", rotateMask180(upRight)),
            ("left", rotateMask270(up)),
            ("up_left", rotateMask270(upRight)),
        ]

    if shapeKind == "line":
        widthCells = lineWidthCells if lineWidthCells is not None else 1

        up = lineMaskLookup(sizeCells, widthCells)
        upRight = diagonalLineMaskLookup(sizeCells, widthCells)

        return [
            ("up", up),
            ("up_right", upRight),
            ("right", rotateMask90(up)),
            ("down_right", rotateMask90(upRight)),
            ("down", rotateMask180(up)),
            ("down_left", rotateMask180(upRight)),
            ("left", rotateMask270(up)),
            ("up_left", rotateMask270(upRight)),
        ]

    raise ValueError(f"Unsupported shape kind: {shapeKind}")
def rotateMask90(mask: Set[Coord]) -> Set[Coord]:
        return {(-y, x) for x, y in mask}
def rotateMask180(mask: Set[Coord]) -> Set[Coord]:
        return {(-x, -y) for x, y in mask}
def rotateMask270(mask: Set[Coord]) -> Set[Coord]:
        return {(y, -x) for x, y in mask}
def bestAoePositioningDebug(
        rangeFt: int,
        radiusFt: int,
        shape: str,
        allCreaturePositions: List[List[int]],
        allTargets: List[Dict[str, Any]],
        casterCells: List[List[int]],
        originMode: str = "placed"
) -> Dict[str, Any]:
    def parseShape(shape: str) -> Tuple[str, Optional[int]]:
        s = shape.strip().lower()

        if s == "circle":
            return "circle", None
        if s == "cone":
            return "cone", None
        if s == "square":
            return "square", None
        if s == "line":
            return "line", 5

        if "line" in s:
            match = re.search(r"(\d+)", s)
            if match:
                return "line", int(match.group(1))
            return "line", 5

        raise ValueError(f"Unsupported shape string: {shape}")
    def scoreMaskPlacement(
            covered: Set[Coord],
            allTargets: List[Dict[str, Any]],
            viableCellSet: Set[Coord],
            nonViableCells: Set[Coord],
    ) -> Tuple[float, List[Dict[str, Any]]]:

        coveredViableCells = covered & viableCellSet
        coveredNonViableCells = covered & nonViableCells
        emptyCells = covered - coveredViableCells - coveredNonViableCells

        score = 0.0
        targetBreakdown = []

        for target in allTargets:
            positions = target["positioning"]
            if isinstance(positions, list):
                positions = set(tuple(coord) for coord in positions)
            hits = len(covered & positions)

            if hits > 0:
                name = target["name"]
                probSuccess = target["probSuccess"]
                badTarget = len(positions & coveredNonViableCells)
                total = len(positions)
                if badTarget > 0:
                    targetScore = (probSuccess * 100) + 35
                    score -= targetScore
                else:
                    targetScore = probSuccess * 100.0
                    score += targetScore

                targetBreakdown.append({
                    "name": name,
                    "probSuccess": probSuccess,
                    "tilesHit": hits,
                    "tilesTotal": total,
                    "targetScore": targetScore,
                })

        score -= len(emptyCells) * 1.0
        for coord in covered:
            x, y = coord
            if x < 0 or y < 0:
                score -= score * 0.01

        targetBreakdown.sort(
            key=lambda t: (-t["targetScore"], -t["probSuccess"])
        )
        return score, targetBreakdown
    def normalizeCellSet(cellsLike: List[List[int]]) -> set[Coord]:
        return {tuple(p) for p in cellsLike}
    def distanceCells(a: Coord, b: Coord) -> int:
        # abs(x1 - x2) + abs(y1 - y2)
        return abs(a[0] - b[0]) + abs(a[1] - b[1])
    def anchorWithinPlacedRange(anchor: Coord, casterCellSet: Set[Coord], rangeCells: int) -> bool:
        if rangeCells <= 0:
            return True
        return any(distanceCells(anchor, c) <= rangeCells for c in casterCellSet)

    def buildSelfOriginCone(
            casterCellSet: Set[Coord],
            direction: Coord,
            lengthCells: int,
    ) -> Set[Coord]:
        def directionToOrientationName(direction: Coord) -> str:
            return {
                (0, -1): "up",
                (1, -1): "up_right",
                (1, 0): "right",
                (1, 1): "down_right",
                (0, 1): "down",
                (-1, 1): "down_left",
                (-1, 0): "left",
                (-1, -1): "up_left",
            }[direction]

        def getFrontCornerCell(casterCellSet: Set[Coord], direction: Coord) -> Coord:
            xs = [x for x, _ in casterCellSet]
            ys = [y for _, y in casterCellSet]

            if direction == (1, -1):  # up_right
                return (max(xs), min(ys))
            if direction == (1, 1):  # down_right
                return (max(xs), max(ys))
            if direction == (-1, 1):  # down_left
                return (min(xs), max(ys))
            if direction == (-1, -1):  # up_left
                return (min(xs), min(ys))

            raise ValueError(f"Not a diagonal direction: {direction}")

        def getDiagonalSelfOriginAnchorCell(casterCellSet: Set[Coord], direction: Coord) -> Coord:
            corner = getFrontCornerCell(casterCellSet, direction)
            return (corner[0] + direction[0], corner[1] + direction[1])

        def diagonalSelfConeMaskLookup(lengthCells: int) -> Set[Coord]:
            mask = set()
            for dx in range(lengthCells):
                for negDy in range(lengthCells):
                    if 0 <= dx + negDy < lengthCells:
                        mask.add((dx, -negDy))
            return mask

        orientationName = directionToOrientationName(direction)
        covered = set()

        # Cardinal self-origin cones stay exactly as they are now
        if direction in {(0, -1), (1, 0), (0, 1), (-1, 0)}:
            coneMasks = dict(getOrientedTemplateMasks("cone", lengthCells))
            relMask = coneMasks[orientationName]

            frontEdge = getFrontEdgeCells(casterCellSet, direction)

            for ax, ay in frontEdge:
                for mx, my in relMask:
                    covered.add((ax + mx, ay + my))

            covered -= casterCellSet
            return covered

        # Diagonal self-origin cones must start from the diagonal anchor cell,
        # not from the caster corner.
        baseMask = diagonalSelfConeMaskLookup(lengthCells)

        if direction == (1, -1):  # up_right
            relMask = baseMask
        elif direction == (1, 1):  # down_right
            relMask = rotateMask90(baseMask)
        elif direction == (-1, 1):  # down_left
            relMask = rotateMask180(baseMask)
        elif direction == (-1, -1):  # up_left
            relMask = rotateMask270(baseMask)
        else:
            raise ValueError(f"Unsupported direction: {direction}")

        ax, ay = getDiagonalSelfOriginAnchorCell(casterCellSet, direction)

        for mx, my in relMask:
            covered.add((ax + mx, ay + my))

        covered -= casterCellSet
        return covered
    def buildSelfOriginLine(
            casterCellSet: Set[Coord],
            direction: Coord,
            lengthCells: int,
            widthCells: int,
    ) -> Set[Coord]:
        def getPerp(direction: Coord) -> Coord:
            # 90-degree perpendicular in grid coordinates.
            dx, dy = direction
            return (-dy, dx)
        dx, dy = direction
        px, py = getPerp(direction)

        frontEdge = getFrontEdgeCells(casterCellSet, direction)

        halfLeft = widthCells // 2
        halfRight = widthCells - halfLeft - 1

        covered = set()

        for fx, fy in frontEdge:
            for step in range(1, lengthCells + 1):  # starts at 1, not 0
                cx = fx + dx * step
                cy = fy + dy * step

                for w in range(-halfLeft, halfRight + 1):
                    covered.add((cx + px * w, cy + py * w))

        covered -= casterCellSet
        return covered
    def get8Directions() -> List[Tuple[str, Coord]]:
        return [
            ("up", (0, -1)),
            ("up_right", (1, -1)),
            ("right", (1, 0)),
            ("down_right", (1, 1)),
            ("down", (0, 1)),
            ("down_left", (-1, 1)),
            ("left", (-1, 0)),
            ("up_left", (-1, -1)),
        ]
    def getFrontEdgeCells(casterCellSet: Set[Coord], direction: Coord) -> Set[Coord]:
        #Returns the caster cells furthest forward in the chosen direction.
        #Uses dot-product projection so it works for diagonal directions too.
        dx, dy = direction
        if not casterCellSet:
            return set()

        max_proj = max((x * dx + y * dy) for x, y in casterCellSet)
        return {
            (x, y)
            for x, y in casterCellSet
            if x * dx + y * dy == max_proj
        }
    def generateCandidateAnchors(
            relMask: Set[Coord],
            focusCells: Set[Coord],
            casterCellSet: Set[Coord],
            rangeCells: int,
    ) -> Set[Coord]:
        #focusCells is either viableCells or allCells
        #Return value allows for search by target, not search by each cell (brute force).
        anchors = set()

        for tx, ty in focusCells:
            for dx, dy in relMask:
                anchor = (tx - dx, ty - dy)

                if casterCellSet and not anchorWithinPlacedRange(anchor, casterCellSet, rangeCells):
                    continue

                anchors.add(anchor)
        return anchors
    def expandAnchorNeighborhood(seedAnchors: Set[Coord], radius: int = 1) -> Set[Coord]:
        expanded = set(seedAnchors)
        for ax, ay in seedAnchors:
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if (ax + dx) > 0 and (ay + dy) > 0:
                        expanded.add((ax + dx, ay + dy))
        return expanded
    def getDiagonalSelfOriginAnchorCell(casterCellSet: Set[Coord], direction: Coord) -> Coord:
        xs = [x for x, _ in casterCellSet]
        ys = [y for _, y in casterCellSet]

        if direction == (1, -1):  # up_right
            corner = (max(xs), min(ys))
        elif direction == (1, 1):  # down_right
            corner = (max(xs), max(ys))
        elif direction == (-1, 1):  # down_left
            corner = (min(xs), max(ys))
        elif direction == (-1, -1):  # up_left
            corner = (min(xs), min(ys))
        else:
            raise ValueError(f"Not a diagonal direction: {direction}")

        return (corner[0] + direction[0], corner[1] + direction[1])

    shapeKind, lineWidthFt = parseShape(shape)

    # radiusFt now controls the actual AOE template size.
    sizeCells = max(1, math.ceil(int(radiusFt) / 5))
    rangeCells = max(0, math.ceil(int(rangeFt) / 5))
    if originMode == "self":
        rangeCells = 0
    lineWidthCells = max(1, math.ceil(lineWidthFt / 5)) if lineWidthFt else None

    unparsedCells = []
    [unparsedCells.extend(pos) for pos in allCreaturePositions]
    allCells: Set[Coord] = {tuple(p) for p in unparsedCells}
    casterCellSet: Set[Coord] = normalizeCellSet(casterCells)

    normalizedTargets = []
    viableCellsToTarget: Dict[Coord, Dict[str, Any]] = {}

    for target in allTargets:
        normalizedTarget = {
            "name": target["name"],
            "probSuccess": float(target["probSuccess"]) if target["probSuccess"] else 0.0,
            "positioning": {tuple(p) for p in target["positioning"]},
        }
        normalizedTargets.append(normalizedTarget)

        if target["viable"]:
            for pos in normalizedTarget["positioning"]:
                viableCellsToTarget[pos] = normalizedTarget

    viableCells: Set[Coord] = set(viableCellsToTarget.keys())
    nonViableCells: Set[Coord] = allCells - viableCells

    if not allTargets:
        return {
            "coveredCells": [],
            "anchor": None,
            "orientation": None,
            "score": float("-inf"),
            "targetsHit": [],
        }

    orientedMasks = getOrientedTemplateMasks(
        shapeKind=shapeKind,
        sizeCells=sizeCells,
        lineWidthCells=lineWidthCells,
    )

    xs = [x for x, _ in allCells | viableCells]
    ys = [y for _, y in allCells | viableCells]

    if not xs or not ys:
        return {
            "coveredCells": [],
            "anchor": None,
            "orientation": None,
            "score": float("-inf"),
            "targetsHit": [],
        }

    best = {
        "coveredCells": set(),
        "anchor": None,
        "orientation": None,
        "score": float("-inf"),
        "targetsHit": [],
    }

    # SELF-ORIGIN
    if originMode.lower() == "self":
        if not casterCellSet:
            return {
                "coveredCells": [],
                "anchor": None,
                "orientation": None,
                "score": float("-inf"),
                "targetsHit": [],
            }

        # circle / square can still use the simpler anchor-based logic for now
        if shapeKind in {"circle", "square"}:
            for orientationName, relMask in orientedMasks:
                for anchor in casterCellSet:
                    ax, ay = anchor
                    covered = {(ax + dx, ay + dy) for dx, dy in relMask}
                    covered -= casterCellSet

                    score, targetBreakdown = scoreMaskPlacement(
                        covered=covered,
                        allTargets=normalizedTargets,
                        viableCellSet=viableCells,
                        nonViableCells=nonViableCells,
                    )

                    if score > best["score"]:
                        best = {
                            "coveredCells": covered,
                            "anchor": anchor,
                            "orientation": orientationName,
                            "score": score,
                            "targetsHit": targetBreakdown,
                        }

            best["coveredCells"] = sorted(best["coveredCells"])
            return best

        # cone / line need special 8-direction self-origin logic
        #Shapes are rebuilt in buildSelfOrigin___ due to needing to account for front edge
        for orientationName, direction in get8Directions():
            # anchor is mostly metadata now; useless for user. Use for debugging
            if direction in {(1, -1), (1, 1), (-1, 1), (-1, -1)}:
                anchor_meta = [getDiagonalSelfOriginAnchorCell(casterCellSet, direction)]
            else:
                frontEdge = getFrontEdgeCells(casterCellSet, direction)
                anchor_meta = sorted(frontEdge)

            if shapeKind == "line":
                covered = buildSelfOriginLine(
                    casterCellSet=casterCellSet,
                    direction=direction,
                    lengthCells=sizeCells,
                    widthCells=lineWidthCells or 1,
                )
            elif shapeKind == "cone":
                covered = buildSelfOriginCone(
                    casterCellSet=casterCellSet,
                    direction=direction,
                    lengthCells=sizeCells,
                )
            else:
                continue

            score, targetBreakdown = scoreMaskPlacement(
                covered=covered,
                allTargets=allTargets,
                viableCellSet=viableCells,
                nonViableCells=nonViableCells,
            )

            if score > best["score"]:
                best = {
                    "coveredCells": covered,
                    "anchor": anchor_meta,
                    "orientation": orientationName,
                    "score": score,
                    "targetsHit": targetBreakdown,
                }

        best["coveredCells"] = sorted(best["coveredCells"])
        return best

    #PLACE-ORIGIN
    PLACEMENT_EXPANSION_RADIUS = 2
    CANDIDATE_CUTOFF = 10

    for orientationName, relMask in orientedMasks:
        candidateAnchors = generateCandidateAnchors(
            relMask=relMask,
            focusCells=viableCells,
            casterCellSet=casterCellSet,
            rangeCells=rangeCells,
        )

        seedResults = []

        for anchor in sorted(candidateAnchors):
            ax, ay = anchor
            covered = {(ax + dx, ay + dy) for dx, dy in relMask}

            # Cheap skips
            if not (covered & viableCells):
                continue
            if not (covered & allCells):
                continue

            score, targetBreakdown = scoreMaskPlacement(
                covered=covered,
                allTargets=normalizedTargets,
                viableCellSet=viableCells,
                nonViableCells=nonViableCells,
            )

            seedResults.append((score, anchor, covered, targetBreakdown))

            if score > best["score"]:
                best = {
                    "coveredCells": covered,
                    "anchor": anchor,
                    "orientation": orientationName,
                    "score": score,
                    "targetsHit": targetBreakdown,
                }

        if not seedResults:
            continue

        seedResults.sort(key=lambda x: x[0], reverse=True)
        topSeedAnchors = {anchor for _, anchor, _, _ in seedResults[:CANDIDATE_CUTOFF]}

        expandedAnchors = expandAnchorNeighborhood(
            topSeedAnchors,
            radius=PLACEMENT_EXPANSION_RADIUS
        )

        # Only keep anchors we have not already checked for this orientation
        expandedAnchors -= candidateAnchors

        for anchor in sorted(expandedAnchors): #Extra check around anchors by radius, as placing an AOE inbetween candidates can sometimes be better
            if casterCellSet and not anchorWithinPlacedRange(anchor, casterCellSet, rangeCells):
                continue

            ax, ay = anchor
            covered = {(ax + dx, ay + dy) for dx, dy in relMask}

            # Cheap skips
            if not (covered & viableCells):
                continue
            if not (covered & allCells):
                continue

            score, targetBreakdown = scoreMaskPlacement(
                covered=covered,
                allTargets=normalizedTargets,
                viableCellSet=viableCells,
                nonViableCells=nonViableCells,
            )

            if score > best["score"]:
                best = {
                    "coveredCells": covered,
                    "anchor": anchor,
                    "orientation": orientationName,
                    "score": score,
                    "targetsHit": targetBreakdown,
                }

    best["coveredCells"] = sorted(best["coveredCells"])
    return best

# EXPECTED DAMAGE METHODS
def calcIndividualExpectedDamage(player, action, creature):
    # Only for weapon attacks and single-target spells.
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    if isValidTarget(action, creature, player.getPosition(), isPlayerTurn):
        creatureStats = creature["Statblock"]
        probNormalHit = -1
        critChance = -1
        modifier = 0
        damModifier = 0
        if isinstance(action, Weapon):
            modifier = player.getMod(action.getStatType())
            probNormalHit, critChance = defProbHit(player, creatureStats, modifier)
            damModifier = modifier
        else:
            if action.getRollType().lower() == "tohit":
                if isinstance(action, Spell):
                    modifier = player.getSpellMod()
                else:
                    modifier = action.getAttackBonus()
                probNormalHit, critChance = defProbHit(player, creatureStats, modifier)
                damModifier = action.getDamMod()
            elif action.getRollType().lower() == "save":
                probNormalHit = 1 - defSave(action, int(player.getDC()), creatureStats)
                critChance = 0
                damModifier = action.getDamMod()
            elif (
                action.getRollType().lower() == "autohit"
                or action.getRollType().lower() == "onhit"
            ):
                probNormalHit = 1.0
                critChance = 0
                damModifier = action.getDamMod()

        diceNum = copy.deepcopy(action.getDiceNum())
        dieType = copy.deepcopy(action.getSides())

        expectedNormalDamage = ((diceNum * (dieType + 1)) / 2) + damModifier
        expectedCritDamage = ((expectedNormalDamage - modifier) * 2) + damModifier

        if (
            isinstance(action.getDamType(), list)
            and len(action.getDamType()) != 1
            and len(action.getDamType()) != 0
        ):
            if action.getDamType()[-1] == "AND":
                numDamTypes = len(action.getDamType()) - 1
                # Assume a clean divide when having multiple damage types. 10d6 should only have 2 damTypes, never 3.
                diceNums = list(itertools.repeat(diceNum / numDamTypes, numDamTypes))
                diceNums = [int(diceNum) for diceNum in diceNums]
                for i in range(len(diceNums)):
                    if creatureStats.isImmune(action.getDamType()[i]):
                        diceNums[i] = 0
                    elif creatureStats.isVulnerable(action.getDamType()[i]):
                        if not creatureStats.isResistant(action.getDamType()[i]):
                            diceNums[i] *= 2
                    elif creatureStats.isResistant(action.getDamType()[i]):
                        diceNums[i] = math.floor(diceNums[i] / 2)
                diceNum = sum(diceNums)
                expectedNormalDamage = ((diceNum * (dieType + 1)) / 2) + modifier
                expectedCritDamage = ((expectedNormalDamage - modifier) * 2) + modifier
            else:  # OR
                if all(
                    creatureStats.isImmune(damType) for damType in action.getDamType()
                ):
                    expectedNormalDamage = 0
                    expectedCritDamage = 0
                elif all(
                    creatureStats.isResistant(damType)
                    for damType in action.getDamType()
                ):
                    if not any(
                        creatureStats.isVulnerable(damType)
                        for damType in action.getDamType()
                    ):
                        expectedNormalDamage /= 2
                        expectedCritDamage /= 2
                elif any(
                    creatureStats.isVulnerable(damType)
                    for damType in action.getDamType()
                ):
                    expectedNormalDamage *= 2
                    expectedCritDamage *= 2
        else:
            damType = action.getDamType()
            if creatureStats.isImmune(damType):
                expectedNormalDamage *= 0
                expectedCritDamage *= 0
            elif creatureStats.isVulnerable(damType):
                if not creatureStats.isResistant(damType):
                    expectedNormalDamage *= 2
                    expectedCritDamage *= 2
            elif creatureStats.isResistant(damType):
                expectedNormalDamage /= 2
                expectedCritDamage /= 2

        expectedDamage = (
            probNormalHit * expectedNormalDamage + critChance * expectedCritDamage
        )
        return round(expectedDamage, 3)
    else:
        return 0.0
def calcTotalExpectedDamage(player, action, initiative):
    eDamages = []
    viableTargets = []
    if not isinstance(action, Weapon) and action.getNumTarget() == 0:
        return 0, {}
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    # if isinstance(action, Spell) and action.getRollType().lower() == "onhit":
    #     weaponMean = 0
    for creature in initiative:
        if isValidTarget(action, creature, player.getPosition(), isPlayerTurn):
            if isinstance(action, Weapon):
                eDamages.append(calcIndividualExpectedDamage(player, action, creature))
                viableTargets.append(creature)
            else:
                if action.getRollType().lower() in ["save", "autohit", "tohit"]:
                    if action.getNumTarget() == 1:
                        eDamages.append(calcIndividualExpectedDamage(player, action, creature))
                        viableTargets.append(creature)
                    elif action.getNumTarget() > 1:
                        weights = getMultiTargetWeights(player, action, initiative)
                        if weights:
                            tempTargetStore = action.getNumTarget()
                            action.setNumTarget(1)
                            for weight in weights:
                                eDamages.append(calcIndividualExpectedDamage(player, action, weight))
                                viableTargets.append(weight)
                            action.setNumTarget(tempTargetStore)
                            return sum(eDamages) / len(eDamages), viableTargets
                        return 0, {}
                    elif action.getNumTarget() in [-1, -2]:
                        targets = [creature for creature in initiative]
                        for i, target in enumerate(targets):
                            #EDam targets use expected damage instead of probSuccess
                            #Potentially leads to different AOE subsets, which is resolved through impact rating checks.
                            if isValidTarget(action, target, player.getPosition(), isPlayerTurn):
                                targets[i] = {
                                    "name": target["Statblock"].getName(),
                                    "probSuccess": calcIndividualExpectedDamage(player, action, target),
                                    "positioning": target["Statblock"].getPosition(),
                                    "viable" : True
                                }
                            else:
                                targets[i] = {
                                    "name": target["Statblock"].getName(),
                                    "probSuccess": calcIndividualExpectedDamage(player, action, target),
                                    "positioning": target["Statblock"].getPosition(),
                                    "viable" : False
                                }
                        positions = [creature["Statblock"].getPosition() for creature in initiative]
                        actionRange = action.getActionRange()
                        radius = action.getActionRadius()
                        shape = action.getShape()
                        casterCells = player.getPosition()
                        aoeType = "placed" if action.getNumTarget() == -1 else "self"

                        eDam, token = avgOverAOETargets(targets, positions, actionRange,
                                                        radius, shape, casterCells, aoeType)
                        return round(eDam, 2), token
                    else:
                        raise ValueError("Invalid numTarget!")
                elif action.getRollType().lower() == "onhit":
                    # Get the expected damage for the highest probToHit weapon
                    if player.getWeaponLength() == 0:
                        return 0, {}
                    weaponDamages = []
                    for i in range(player.getWeaponLength()):
                        weaponDamages.append(
                            calcIndividualExpectedDamage(
                                player, player.getWeapon(i), creature
                            )
                        )
                    weaponDam = max(weaponDamages)
                    # weaponMean = player.getWeapon(weaponDamages.index(weaponDam)).getMean()
                    eDamages.append(calcIndividualExpectedDamage(player, action, creature) + weaponDam)
                    viableTargets.append(creature)
                else:
                    raise ValueError("Bad rollType!")
    if len(viableTargets) != 0 and all(eDamages) != 0:
        return round(max(eDamages), 2), viableTargets[eDamages.index(max(eDamages))]
    else:
        return 0, {}


# PROB OF SUCCESS METHODS
def defProbHit(player, creatureStats, mod):
    toHitMod = player.getProfBonus() + mod
    critChance = 0.05  # 1 in 20
    toHitMod, critChance = influenceToHit(player, creatureStats, toHitMod, critChance)
    probHit = min(max((21 - creatureStats.getAC() + toHitMod) / 20, 0.05), 0.95)

    autoCritConditions = ["Paralyzed", "Unconscious"]
    # checking for players being able to autocrit
    autoCrit = False
    if creatureStats.isActiveStatusEffect("autocrit"):
        if (
            "attack rolls against"
            in creatureStats.getActiveStatusEffect("autocrit")["effect"]["attribute"]
        ):
            probHit = 1.0
            autoCrit = True
    elif any(
        condition in creatureStats.getActiveConditions()
        for condition in autoCritConditions
    ):
        probHit = 1.0
        autoCrit = True
    if not autoCrit:
        probNormalHit = probHit - critChance
    else:
        probNormalHit = 0
        critChance = 1.0
    return probNormalHit, critChance
def influenceToHit(player, creatureStats, toHitMod, critChance):
    activeStatEffects = []  # Ensure no duplicate stat effects are applied

    # Check for player status effects
    if player.isActiveStatusEffect("Advantage"):
        advEffect = player.getActiveStatusEffect("Advantage")
        if "attack rolls for" in advEffect["effect"]["attribute"]:
            critChance = 0.0975  # See documentation
            toHitMod += int(
                player.getActiveStatusEffect("Advantage")["effect"]["rolls"]
            )
            activeStatEffects.append("Advantage")
    elif player.isActiveStatusEffect("Disadvantage"):
        disadvEffect = player.getActiveStatusEffect("Disadvantage")
        if "attack rolls for" in disadvEffect["effect"]["attribute"]:
            if "Advantage" not in activeStatEffects:
                critChance = 0.025  # See documentation
            else:
                critChance = 0.05
            toHitMod += int(
                player.getActiveStatusEffect("Disadvantage")["effect"]["rolls"]
            )
            activeStatEffects.append("Disadvantage")
    elif player.isActiveStatusEffect("Buff"):
        buffEffect = player.getActiveStatusEffect("Buff")
        if "attack rolls for" in buffEffect["effect"]["attribute"]:
            buffDieNum, buffDieType = buffEffect["effect"]["rolls"].split("d")
            buffDieNum, buffDieType = int(buffDieNum), int(buffDieType)
            toHitMod += sum([int(i) for i in range(1, buffDieType + 1)]) / buffDieType
            activeStatEffects.append("Buff")
        elif "AC" in buffEffect["effect"]["attribute"]:
            buffNum = buffEffect["effect"]["rolls"]
            buffNum = int(buffNum)
            toHitMod -= buffNum
            activeStatEffects.append("Buff")
    elif player.isActiveStatusEffect("Debuff"):
        buffEffect = player.getActiveStatusEffect("Debuff")
        if "attack rolls for" in buffEffect["effect"]["attribute"]:
            buffDieNum, buffDieType = buffEffect["effect"]["rolls"].split("d")
            buffDieNum, buffDieType = int(buffDieNum), int(buffDieType)
            toHitMod -= sum([int(i) for i in range(1, buffDieType + 1)]) / buffDieNum
            activeStatEffects.append("Debuff")

    # Check for player conditions (Hardcoded)
    disadvForConditions = ["Blinded", "Frightened", "Poisoned", "Prone", "Restrained"]
    advForConditions = ["Invisible", "GreaterInvisible"]
    if (
        any(
            condition in player.getActiveConditions()
            for condition in disadvForConditions
        )
        and "Disadvantage" not in activeStatEffects
    ):
        toHitMod += -4
        if "Advantage" not in activeStatEffects:
            critChance = 0.025  # See documentation
        else:
            critChance = 0.05
        activeStatEffects.append("Disadvantage")
    elif (
        any(condition in player.getActiveConditions() for condition in advForConditions)
        and "Advantage" not in activeStatEffects
    ):
        toHitMod += 4
        if "Disadvantage" not in activeStatEffects:
            critChance = 0.0975  # See documentation
        else:
            critChance = 0.05
        activeStatEffects.append("Advantage")

    # Checking for monster status effects
    if (
        creatureStats.isActiveStatusEffect("Advantage")
        and "Advantage" not in activeStatEffects
    ):
        advEffect = creatureStats.getActiveStatusEffect("Advantage")
        if "attack rolls against" in advEffect["effect"]["attribute"]:
            if "Disadvantage" not in activeStatEffects:
                critChance = 0.0975  # See documentation
            else:
                critChance = 0.05
            toHitMod += int(
                creatureStats.getActiveStatusEffect("Advantage")["effect"]["rolls"]
            )
            activeStatEffects.append("Advantage")
    elif (
        creatureStats.isActiveStatusEffect("Disadvantage")
        and "Disadvantage" not in activeStatEffects
    ):
        if "Advantage" not in activeStatEffects:
            critChance = 0.025  # See documentation
        else:
            critChance = 0.05
        disadvEffect = creatureStats.getActiveStatusEffect("Disadvantage")
        if "attack rolls against" in disadvEffect["effect"]["attribute"]:
            toHitMod += int(
                creatureStats.getActiveStatusEffect("Disadvantage")["effect"]["rolls"]
            )
            activeStatEffects.append("Disadvantage")
    elif creatureStats.isActiveStatusEffect("Buff"):
        buffEffect = creatureStats.getActiveStatusEffect("Buff")
        if "attack rolls against" in buffEffect["effect"]["attribute"]:
            buffDieNum, buffDieType = buffEffect["effect"]["rolls"].split("d")
            buffDieNum, buffDieType = int(buffDieNum), int(buffDieType)
            toHitMod += sum([int(i) for i in range(1, buffDieType + 1)]) / buffDieType
    elif creatureStats.isActiveStatusEffect("Debuff"):
        buffEffect = creatureStats.getActiveStatusEffect("Debuff")
        if "attack rolls against" in buffEffect["effect"]["attribute"]:
            buffDieNum, buffDieType = buffEffect["effect"]["rolls"].split("d")
            buffDieNum, buffDieType = int(buffDieNum), int(buffDieType)
            toHitMod -= sum([int(i) for i in range(1, buffDieType + 1)]) / buffDieNum

    # Checking for monster conditions
    advAgainstConditions = ["Blinded", "Prone", "Restrained", "Stunned"]
    if (
        any(
            condition in creatureStats.getActiveConditions()
            for condition in advForConditions
        )
        and "Disadvantage" not in activeStatEffects
    ):
        toHitMod += -4
        if "Advantage" not in activeStatEffects:
            critChance = 0.025  # See documentation
        else:
            critChance = 0.05
        activeStatEffects.append("Disadvantage")
    elif (
        any(
            condition in creatureStats.getActiveConditions()
            for condition in advAgainstConditions
        )
        and "Advantage" not in activeStatEffects
    ):
        toHitMod += 4
        if "Disadvantage" not in activeStatEffects:
            critChance = 0.0975  # See documentation
        else:
            critChance = 0.05
        activeStatEffects.append("Advantage")

    return toHitMod, critChance
def calcIndividualToHitProbability(player, action, creature):
    creatureStats = creature["Statblock"]
    modifier = 0
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    if isValidTarget(action, creature, player.getPosition(), isPlayerTurn):
        if isinstance(action, Weapon):
            modifier = player.getMod(action.getStatType())
        elif isinstance(action, MonAction):
            modifier = action.getAttackBonus()
        elif isinstance(action, Spell):
            modifier = player.getSpellMod()
        else:
            return None
    else:
        return None

    probNormalHit, critChance = defProbHit(player, creatureStats, modifier)
    if isinstance(action, MonAction):
        modifier = action.getDamMod()
    normDamProb, critDamProb = calcDamProbs(creatureStats, action, modifier, "NORM")

    # NOTE: No specialNotes relevant to probability of success in all toHit spells
    successProb = probNormalHit * normDamProb + critChance * critDamProb
    return successProb
def calcTotalToHitProbability(player, action, initiative):
    # Only 1 or >1 targets for spells; also covers weapons.
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    if isinstance(action, Weapon) or action.getNumTarget() == 1:
        successProbs = []
        targets = []

        lingEffectProb = 0
        checkLingEffects = True if isinstance(action, Spell) and action.getLingEffects() else False

        extraEffectProb = 0
        checkExtraEffects = (
            True if isinstance(action, Spell) and action.getExtraEffect() else False
        )

        lingSavesProb = 0
        checkLingSaves = (
            True if isinstance(action, Spell) and action.getLingSaves() else False
        )

        for creature in initiative:
            if isValidTarget(action, creature, player.getPosition(), isPlayerTurn):
                successProb = calcIndividualToHitProbability(player, action, creature)
                successProbs.append(successProb)
                targets.append(creature)
        if len(successProbs) != 0:
            probSuccess = max(successProbs)
            targetSuccess = targets[successProbs.index(probSuccess)]
        else:
            probSuccess = 0
            targetSuccess = []
        if checkLingEffects:
            lingEffectProb = calcLingeringEffectProbability(player, targetSuccess,action, action.getLingEffects(),
                                                            probSuccess)
        if checkExtraEffects:
            # In terms of probability of success, lingEffects and extraEffects are the same.
            extraEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getExtraEffect(),
                                                             probSuccess)
        if checkLingSaves:
            lingSavesProb = calcLingeringSavesProbability(player, targetSuccess,action)
        if len(successProbs) != 0:
            probSuccess = round(probSuccess, 2)
            lingEffectProb = round(lingEffectProb, 2)
            extraEffectProb = round(extraEffectProb, 2)
            lingSavesProb = round(lingSavesProb, 2)
            return {
                "probSuccess": probSuccess,
                "probLingEffect": lingEffectProb,
                "probExtraEffect": extraEffectProb,
                "probLingSaves": lingSavesProb,
                "target" : [targetSuccess["name"]]
            }
        return 0
    elif action.getNumTarget() > 1:
        weights = getMultiTargetWeights(player, action, initiative)
        if weights:
            #Average across best n targets
            successProbs = 0
            numMonsters = 0

            lingEffectProbs = 0
            checkLingEffects = True if isinstance(action, Spell) and action.getLingEffects() else False

            extraEffectProbs = 0
            checkExtraEffects = True if isinstance(action, Spell) and action.getExtraEffect() else False

            lingSavesProbs = 0
            checkLingSaves = True if isinstance(action, Spell) and action.getLingSaves() else False

            for creature in weights:
                if isValidTarget(action, creature, player.getPosition(),isPlayerTurn):
                    successProb = calcIndividualToHitProbability(player, action, creature)
                    successProbs += successProb
                    if checkLingEffects:
                        lingEffectProbs += calcLingeringEffectProbability(player, creature, action,
                                                                        action.getLingEffects(),
                                                                        successProb)
                    if checkExtraEffects:
                        extraEffectProbs += calcLingeringEffectProbability(player, creature, action,
                                                                         action.getExtraEffect(),
                                                                         successProb)
                    if checkLingSaves:
                        lingSavesProbs += calcLingeringSavesProbability(player, creature, action)
                    numMonsters += 1
            if numMonsters != 0:
                probSuccess = successProbs / numMonsters
                lingEffectProb = lingEffectProbs / numMonsters
                extraEffectProb = extraEffectProbs / numMonsters
                lingSavesProb = lingSavesProbs / numMonsters
            else:
                probSuccess = 0
                lingEffectProb = 0
                extraEffectProb = 0
                lingSavesProb = 0
            if successProbs != 0:
                probSuccess = round(probSuccess, 2)
                lingEffectProb = round(lingEffectProb, 2)
                extraEffectProb = round(extraEffectProb, 2)
                lingSavesProb = round(lingSavesProb, 2)
                return {
                    "probSuccess": probSuccess,
                    "probLingEffect": lingEffectProb,
                    "probExtraEffect": extraEffectProb,
                    "probLingSaves": lingSavesProb,
                    "target": [weight["name"] for weight in weights]
                }
            return 0
        else:
            return 0
    else:
        raise ValueError("Bad NumTargets!")
def defSave(spell, dc, creatureStats):
    saveMod = creatureStats.getSaveProf(spell.getSaveType())
    activeStatEffects = []  # Ensure no duplicate stat effects are applied

    # Check for creatureStats status effects
    if creatureStats.isActiveStatusEffect("Advantage"):
        advEffect = creatureStats.getActiveStatusEffect("Advantage")
        if f"{spell.getSaveType()} save" in advEffect["effect"]["attribute"] or "ALL save" in advEffect["effect"][
            "attribute"]:
            saveMod += int(creatureStats.getActiveStatusEffect("Advantage")["effect"]["rolls"])
            activeStatEffects.append("Advantage")
    elif creatureStats.isActiveStatusEffect("Disadvantage"):
        disadvEffect = creatureStats.getActiveStatusEffect("Disadvantage")
        if (
            f"{spell.getSaveType()} save" in disadvEffect["effect"]["attribute"]
            or "ALL save" in disadvEffect["effect"]["attribute"]
        ):
            saveMod -= int(
                creatureStats.getActiveStatusEffect("Disadvantage")["effect"]["rolls"]
            )
            activeStatEffects.append("Disadvantage")
    elif creatureStats.isActiveStatusEffect("Buff"):
        buffEffect = creatureStats.getActiveStatusEffect("Buff")
        if f"{spell.getSaveType()} save" in buffEffect["effect"]["attribute"] or "ALL save" in buffEffect["effect"][
            "attribute"]:
            try:
                buffDieNum, buffDieType = buffEffect["effect"]["rolls"].split("d")
                buffDieNum, buffDieType = int(buffDieNum), int(buffDieType)
                saveMod += sum([i for i in range(1, buffDieType + 1)]) / buffDieType
                activeStatEffects.append("Buff")
            except:
                pass
    elif creatureStats.isActiveStatusEffect("Debuff"):
        buffEffect = creatureStats.getActiveStatusEffect("Debuff")
        if (
            f"{spell.getSaveType()} save" in buffEffect["effect"]["attribute"]
            or "ALL save" in buffEffect["effect"]["attribute"]
        ):
            try:
                buffDieNum, buffDieType = buffEffect["effect"]["rolls"].split("d")
                buffDieNum, buffDieType = int(buffDieNum), int(buffDieType)
                saveMod -= sum([i for i in range(1, buffDieType + 1)]) / buffDieType
                activeStatEffects.append("Debuff")
            except:
                pass
    if creatureStats.isActiveCondition("Restrained"):
        if (
            "Disadvantage" not in activeStatEffects
            and not creatureStats.isActiveStatusEffect("Disadvantage")
        ):
            saveMod -= 4
    if creatureStats.isActiveStatusEffect("autofail") or creatureStats.isActiveCondition("Paralyzed") \
            or creatureStats.isActiveCondition("Petrified") or creatureStats.isActiveCondition("Stunned") \
            or creatureStats.isActiveCondition("Unconscious"):
        saveProb = 0
    else:
        saveProb = ((21 - dc) + saveMod) / 20
    return saveProb
def saveSpecialNotesCheck(action, creature):
    immunities, resistances, vulnerabilities = [], [], []
    if (
        not isinstance(action.getDamType(), list)
        and action.getDamType().lower() == "healing"
    ):
        return immunities, resistances, vulnerabilities
    specialNotes = action.getSpecialNotes()
    if specialNotes:
        creatureType = creature.getCreatureType() if isinstance(creature, Monster) else "humanoid"
        for note in specialNotes:
            if "only" in note.lower() and creatureType not in specialNotes():
                return None
            elif "immune" in note.lower() and creatureType in note:
                immunities = copy.deepcopy(creature.getDamImmunities())
                damType = action.getDamType()
                if isinstance(damType, list):
                    if damType[-1] == "AND" or damType[-1] == "OR":
                        for i in range(len(damType) - 1):
                            if not creature.isImmune(damType[i]):
                                creature.addDamImmunity(damType[i])
                    else:
                        raise ValueError("Listed damTypes MUST end in AND or OR!")
                else:
                    if not creature.isImmune(damType):
                        creature.addDamImmunity(damType)
                break
            elif "resist" in note.lower() and creatureType in note:
                resistances = copy.deepcopy(creature.getDamResistances())
                damType = action.getDamType()
                if isinstance(damType, list):
                    if damType[-1] == "AND" or damType[-1] == "OR":
                        for i in range(len(damType) - 1):
                            if not creature.isResistant(damType[i]):
                                creature.addDamResist(damType[i])
                    else:
                        raise ValueError("Listed damTypes MUST end in AND or OR!")
                else:
                    if not creature.isResistant(damType):
                        creature.addDamResist(damType)
                break
            elif "vulnerable" in note.lower() and creatureType in note:
                vulnerabilities = copy.deepcopy(creature.getDamVulnerabilities())
                damType = action.getDamType()
                if isinstance(damType, list):
                    if damType[-1] == "AND" or damType[-1] == "OR":
                        for i in range(len(damType) - 1):
                            if not creature.isVulnerable(damType[i]):
                                creature.addDamVuln(damType[i])
                    else:
                        raise ValueError("Listed damTypes MUST end in AND or OR!")
                else:
                    if not creature.isVulnerable(damType):
                        creature.addDamVulnerability(damType)
                break
    return immunities, resistances, vulnerabilities
def resetSaveSpecialNotesCheck(specImm, specRes, specVuln, creature):
    if specImm:
        for imm in creature.getDamImmunities():
            if imm not in specImm:
                creature.removeDamImmunity(imm)
    elif specRes:
        for res in creature.getDamResistances():
            if res not in specRes:
                creature.removeDamResist(res)
    elif specVuln:
        for vuln in creature.getDamVulnerabilities():
            if vuln not in specVuln:
                creature.removeDamVulnerability(vuln)
def avgOverAOETargets(creatures, allPositions, actionRange, radius, shape, casterCells, aoeType="placed"):
    #Cache is in the targets dict
    aoeToken = bestAoePositioning(actionRange, radius, shape,
                                  allPositions, creatures, casterCells, aoeType)
    numTargets = len(creatures)
    if numTargets == 0:
        return 0

    probs = [target["probSuccess"] for target in aoeToken["targetsHit"]]
    if probs:
        return sum(probs) / len(probs), aoeToken
    else:
        return 0, {}
def calcIndividualSaveProbability(action, dc, creature):
    try:
        specImm, specRes, specVuln = saveSpecialNotesCheck(action, creature)
    except TypeError:
        return 0
    # Defines chance the creature fails the save.
    probFail = 1 - defSave(action, dc, creature)
    modifier = action.getDamMod()
    failDamProb = calcDamProbs(creature, action, modifier, "NORM")[0]
    if action.getHalfSave():
        probSave = 1 - probFail
        saveDamProb = calcDamProbs(creature, action, modifier, "MULT")[0]
        probSuccess = (probSave * saveDamProb) + (probFail * failDamProb)
    elif action.getMean() != 0:  # Not all save spells deal damage
        probSuccess = probFail * failDamProb
    else:
        probSuccess = probFail

    resetSaveSpecialNotesCheck(specImm, specRes, specVuln, creature)
    return probSuccess
def calcTotalSaveProbability(player, action, initiative):
    # No 0 targets - everything else, fair game.
    lingEffectProb = 0
    checkLingEffects = True if action.getLingEffects() else False
    extraEffectProb = 0
    checkExtraEffects = True if action.getExtraEffect() else False
    lingSavesProb = 0
    checkLingSaves = True if action.getLingSaves() else False
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    if action.getNumTarget() == 1:
        successProbs = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player.getPosition(), isPlayerTurn):
                if isinstance(player, Player) or isinstance(action, Spell):
                    successProb = calcIndividualSaveProbability(
                        action, player.getDC(), creature["Statblock"]
                    )
                else:
                    successProb = calcIndividualSaveProbability(action, action.getDC(), creature["Statblock"])
                successProbs.append(successProb)
                targets.append(creature)
        if len(targets) != 0:
            probSuccess = max(successProbs)
            targetSuccess = [targets[successProbs.index(probSuccess)]]
        else:
            probSuccess = 0
            targetSuccess = []
        if checkLingEffects:
            lingEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getLingEffects(),
                                                            probSuccess)
        if checkExtraEffects:
            # In terms of probability of success, lingEffects and extraEffects are the same.
            extraEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getLingEffects(),
                                                            probSuccess)
        if checkLingSaves:
            lingSavesProb = calcLingeringSavesProbability(player, targetSuccess, action)
    elif action.getNumTarget() > 1:
        weights = getMultiTargetWeights(player, action, initiative)
        if weights:
            successProbs = []
            targets = []
            for creature in weights:
                if isValidTarget(action, creature, player.getPosition(), isPlayerTurn):
                    if isinstance(player, Player) or isinstance(action, Spell):
                        successProb = calcIndividualSaveProbability(action, player.getDC(), creature["Statblock"])
                    else:
                        successProb = calcIndividualSaveProbability(action, action.getDC(), creature["Statblock"])
                    successProbs.append(successProb)
                    targets.append(creature)

                    if checkLingEffects:
                        lingEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                        action.getLingEffects(),
                                                                        successProb)
                    if checkExtraEffects:
                        # In terms of probability of success, lingEffects and extraEffects are the same.
                        extraEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                         action.getLingEffects(),
                                                                         successProb)
                    if checkLingSaves:
                        lingSavesProb += calcLingeringSavesProbability(player, creature, action)

            if len(targets) != 0:
                probSuccess = sum(successProbs) / len(successProbs)
                lingEffectProb = lingEffectProb / len(targets)
                extraEffectProb = extraEffectProb / len(targets)
                lingSavesProb = lingSavesProb / len(targets)
            else:
                probSuccess = 0
                #other probs already defined as 0
            targetSuccess = targets
        else:
            return 0
    elif action.getNumTarget() in [-1, -2]:
        targets = [creature for creature in initiative]
        targetsCopy = [creature["Statblock"] for creature in targets]
        for i, target in enumerate(targets):
            if isValidTarget(action, target, player.getPosition(), isPlayerTurn):
                target = target["Statblock"]
                targets[i] = {
                    "name" : target.getName(),
                    "probSuccess" : calcIndividualSaveProbability(action, player.getDC(), target),
                    "positioning" : target.getPosition(),
                    "viable" : True
                }
            else:
                target = target["Statblock"]
                targets[i] = {
                    "name": target.getName(),
                    "probSuccess": calcIndividualSaveProbability(action, player.getDC(), target),
                    "positioning": target.getPosition(),
                    "viable" : False
                }
        positions = [creature["Statblock"].getPosition() for creature in initiative]
        actionRange = action.getActionRange()
        radius = action.getActionRadius()
        shape = action.getShape()
        casterCells = player.getPosition()
        aoeType = "placed" if action.getNumTarget() == -1 else "self"
        probSuccess, token = avgOverAOETargets(targets, positions,
                                               actionRange, radius, shape,
                                               casterCells, aoeType)

        if not token:
            return 0
        finalTargets = []
        for creature in targetsCopy:
            if creature.getName().lower() in [t["name"].lower() for t in token["targetsHit"]]:
                finalTargets.append(creature)
                if checkLingEffects or checkExtraEffects:
                    successProbIdx = [t["name"].lower() for t in token["targetsHit"]].index(creature.getName().lower())
                    successProb = targets[successProbIdx]["probSuccess"]
                    if checkLingEffects:
                        lingEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                         action.getLingEffects(),
                                                                         successProb)
                    if checkExtraEffects:
                        extraEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                          action.getLingEffects(),
                                                                          successProb)
                if checkLingSaves:
                    lingSavesProb += calcLingeringSavesProbability(player, creature, action)

        if len(finalTargets) != 0:
            lingEffectProb = lingEffectProb / len(finalTargets)
            extraEffectProb = extraEffectProb / len(finalTargets)
            lingSavesProb = lingSavesProb / len(finalTargets)
        else:
            probSuccess = 0
        targetSuccess = token
    else:
        raise ValueError("BAD VALUE FOR NUMTARGET")

    probSuccess = round(probSuccess, 2)
    lingEffectProb = round(lingEffectProb, 2)
    extraEffectProb = round(extraEffectProb, 2)
    lingSavesProb = round(lingSavesProb, 2)
    return {
        "probSuccess": probSuccess,
        "probLingEffect": lingEffectProb,
        "probExtraEffect": extraEffectProb,
        "probLingSaves": lingSavesProb,
        "target" : targetSuccess
    }
def calcOnHitProbability(action, weapons, player, initiative):
    # Only 1 target per spell.
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    probWeaponSuccess = []
    for weapon in weapons:
        probWeaponSuccess.append(calcTotalToHitProbability(player, weapon, initiative))
    if len(probWeaponSuccess) != 0:
        probWeaponSuccess = [prob["probSuccess"] for prob in probWeaponSuccess]
        probWeaponSuccess = max(probWeaponSuccess)  # Using the weapon with the highest chance of success...
    else:
        return 0
    if action.getMean() != 0:
        probInitDams = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player.getPosition(),isPlayerTurn):
                probNormDam, probCritDam = calcDamProbs(creature["Statblock"], action, action.getDamMod(), "NORM")
                probInitDams.append((probNormDam + probCritDam))
                targets.append(creature)
        if probInitDams:
            probInitDam = max(probInitDams)
            targetSuccess = targets[probInitDams.index(probInitDam)]
        else:
            return 0
    else:
        probInitDam = 1.0  # No initial damage, so init damage would be useless. Pass
        targetSuccess = []

    checkLingEffects = (
        True if isinstance(action, Spell) and action.getLingEffects() else False
    )
    checkExtraEffects = (
        True if isinstance(action, Spell) and action.getExtraEffect() else False
    )
    checkLingSaves = (
        True if isinstance(action, Spell) and action.getLingSaves() else False
    )
    if checkLingEffects:
        # LingEffects here would only repeat the initial effect, not the weapon's success prob.
        lingEffectProb = calcLingeringEffectProbability(player, action, action.getLingEffects(), initiative,
                                                        probInitDam)
    else:
        lingEffectProb = 0
    if checkExtraEffects:
        extraEffectProb = calcLingeringEffectProbability(
            player, action, action.getExtraEffect(), initiative, probInitDam
        )
    else:
        extraEffectProb = 0
    if checkLingSaves:
        lingSavesProb = calcLingeringSavesProbability(player, action, initiative)
    else:
        lingSavesProb = 0

    probSuccess = probWeaponSuccess * probInitDam
    return {
        "probSuccess": round(probSuccess, 2),
        "probLingEffect": round(lingEffectProb, 2),
        "probExtraEffect": round(extraEffectProb, 2),
        "probLingSaves": round(lingSavesProb, 2),
        "target" : targetSuccess
    }
def calcIndividualAutoHitProbability(action, creature):
    try:
        specImm, specRes, specVuln = saveSpecialNotesCheck(action, creature)
    except TypeError:
        return 0
    if action.getMean() != 0:
        damProb = calcDamProbs(creature, action, action.getDamMod(), "NORM")[0]
    else:
        if specImm:
            damProb = 0
        else:
            damProb = 1.0
    resetSaveSpecialNotesCheck(specImm, specRes, specVuln, creature)

    return damProb
def calcTotalAutoHitProbability(player, action, initiative):
    # All possible targets.
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False

    lingEffectProb = 0
    checkLingEffects = True if action.getLingEffects() else False
    extraEffectProb = 0
    checkExtraEffects = True if action.getExtraEffect() else False
    lingSavesProb = 0
    checkLingSaves = True if action.getLingSaves() else False

    if action.getNumTarget() == 1:
        successProbs = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player.getPosition(), isPlayerTurn):
                if action.getSpecialNotes() and "HPCap" in action.getSpecialNotes():
                    hpCap = 0
                    specialNotes = action.getSpecialNotes()
                    for note in specialNotes():
                        if "HPCap" in note:
                            hpCap = int(note.split("HPCap")[1])
                    if creature["Statblock"].getHP() < hpCap:
                        successProbs.append(1)
                    else:
                        successProbs.append(0)
                else:
                    if isinstance(player, Player) or isinstance(action, Spell):
                        successProb = calcIndividualAutoHitProbability(action, creature)
                    else:
                        successProb = calcIndividualAutoHitProbability(action, creature)
                    successProbs.append(successProb)
                targets.append(creature)
        if len(targets) != 0:
            probSuccess = max(successProbs)
            targetSuccess = [targets[successProbs.index(probSuccess)]]
        else:
            probSuccess = 0
            targetSuccess = []
        if checkLingEffects:
            lingEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getLingEffects(),
                                                            probSuccess)
        if checkExtraEffects:
            # In terms of probability of success, lingEffects and extraEffects are the same.
            extraEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getLingEffects(),
                                                             probSuccess)
        if checkLingSaves:
            lingSavesProb = calcLingeringSavesProbability(player, targetSuccess, action)
    elif action.getNumTarget() > 1:
        weights = getMultiTargetWeights(player, action, initiative)
        if weights:
            successProbs = []
            targets = []
            for creature in weights:
                if isValidTarget(action, creature, player.getPosition(),isPlayerTurn):
                    if isinstance(player, Player) or isinstance(action, Spell):
                        successProb = calcIndividualAutoHitProbability(action, creature["Statblock"])
                    else:
                        successProb = calcIndividualAutoHitProbability(action, creature["Statblock"])
                    successProbs.append(successProb)
                    targets.append(creature)
                    if checkLingEffects:
                        lingEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                         action.getLingEffects(),
                                                                         successProb)
                    if checkExtraEffects:
                        # In terms of probability of success, lingEffects and extraEffects are the same.
                        extraEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                          action.getLingEffects(),
                                                                          successProb)
                    if checkLingSaves:
                        lingSavesProb += calcLingeringSavesProbability(player, creature, action)

            if len(targets) != 0:
                probSuccess = sum(successProbs) / len(successProbs)
                lingEffectProb = lingEffectProb / len(targets)
                extraEffectProb = extraEffectProb / len(targets)
                lingSavesProb = lingSavesProb / len(targets)
            else:
                probSuccess = 0
                # other probs already defined as 0
            targetSuccess = targets
        else:
            return 0
    elif action.getNumTarget() in [-1, -2]:
        targets = [creature for creature in initiative]
        targetsCopy = [creature["Statblock"] for creature in targets]
        for i, target in enumerate(targets):
            if isValidTarget(action, target, player.getPosition(), isPlayerTurn):
                target = target["Statblock"]
                targets[i] = {
                    "name" : target.getName(),
                    "probSuccess" : calcIndividualAutoHitProbability(action,target),
                    "positioning" : target.getPosition(),
                    "viable" : True
                }
            else:
                target = target["Statblock"]
                targets[i] = {
                    "name": target.getName(),
                    "probSuccess": calcIndividualAutoHitProbability(action,target),
                    "positioning": target.getPosition(),
                    "viable" : False
                }
        positions = [creature["Statblock"].getPosition() for creature in initiative]
        actionRange = action.getActionRange()
        radius = action.getActionRadius()
        shape = action.getShape()
        casterCells = player.getPosition()
        aoeType = "placed" if action.getNumTarget() == -1 else "self"
        probSuccess, token = avgOverAOETargets(targets, positions, actionRange,
                                               radius, shape, casterCells, aoeType)
        for creature in targetsCopy:
            if creature.getName().lower() in [t["name"].lower() for t in token["targetsHit"]]:
                if checkLingEffects or checkExtraEffects:
                    successProbIdx = [t["name"].lower() for t in token["targetsHit"]].index(creature.getName().lower())
                    successProb = targets[successProbIdx]["probSuccess"]
                    if checkLingEffects:
                        lingEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                         action.getLingEffects(),
                                                                         successProb)
                    if checkExtraEffects:
                        extraEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                          action.getLingEffects(),
                                                                          successProb)
                if checkLingSaves:
                    lingSavesProb += calcLingeringSavesProbability(player, creature, action)

        if len(targets) != 0:
            lingEffectProb = lingEffectProb / len(targets)
            extraEffectProb = extraEffectProb / len(targets)
            lingSavesProb = lingSavesProb / len(targets)
        else:
            probSuccess = 0
        targetSuccess = token
    else:
        raise ValueError("Bad numTarget!")

    probSuccess = round(probSuccess, 2)
    lingEffectProb = round(lingEffectProb, 2)
    extraEffectProb = round(extraEffectProb, 2)
    lingSavesProb = round(lingSavesProb, 2)
    return {
        "probSuccess": probSuccess,
        "probLingEffect": lingEffectProb,
        "probExtraEffect": extraEffectProb,
        "probLingSaves": lingSavesProb,
        "target" : targetSuccess
    }

# IMPACT METHODS
def computePerTargetConditionImpact(action, probSuccess, creature, useProbSuccess=True):
    positiveConditionSeverities = {"invisible": 2, "greaterinvisible": 3}
    negativeConditionSeverities = {
        "blinded": 3,
        "charmed": 1,
        "frightened": 2,
        "incapacitated": 3,
        "paralyzed": 4,
        "petrified": 4,
        "prone": 1,
        "restrained": 2,
        "stunned": 4,
        "unconscious": 4,
        "out of combat": 6,
        "dead": 8,
    }

    # Check conditions creature currently has
    # Check conditions the action will apply
    # Average their severities and multiply by probSuccess
    severity = 0
    if (
        not isinstance(action.getDamType(), list)
        and action.getDamType().lower() != "healing"
    ):
        if action.getConditions():
            for condition in action.getConditions():
                if condition.lower() not in [c["cond"].lower() for c in
                                             creature.getActiveConditions()] and not creature.isActiveConImmunity(
                    condition.lower()):
                    severity += negativeConditionSeverities.get(condition.lower(), 0)
                    severity -= positiveConditionSeverities.get(condition.lower(), 0)
    else:
        if action.getConditions():
            for condition in action.getConditions():
                if "downed" in [
                    c["cond"].lower() for c in creature.getActiveConditions()
                ] or "stabilized" in [
                    c["cond"].lower() for c in creature.getActiveConditions()
                ]:
                    severity += 5
                    continue
                if condition.lower() not in [
                    c["cond"].lower() for c in creature.getActiveConditions()
                ]:
                    severity -= negativeConditionSeverities.get(condition.lower(), 0)
                    severity += positiveConditionSeverities.get(condition.lower(), 0)
    if useProbSuccess:
        if isinstance(probSuccess, list):
            return severity * probSuccess[0]
        return severity * probSuccess
    else:
        return severity
def computePerTargetSEImpact(action, probSuccess, creature, useProbSuccess=True):
    positiveEffectSeverities = {
        "advantage": 2,
        "resistance": 2,
        "vulnerability": 3,
        "immunity": 3,
        "buff": 1,
        "autocrit": 4,
    }
    negativeEffectSeverities = {
        "debuff": 1,
        "autofail": 4,
        "disadvantage": 2,
        "lingeffect": 1,
        "lingsave": 2,
        "summon": 4,
    }
    # Check status effects creature currently has
    # Check status effects the action will apply
    # Average their severities and multiply by probSuccess
    severity = 0
    activeEffects = []
    if (
        not isinstance(action.getDamType(), list)
        and action.getDamType().lower() != "healing"
        and not action.getSelfTarget()
    ):
        if action.getStatusEffects():
            for effect in action.getStatusEffects():
                if effect["name"].lower() not in activeEffects and effect[
                    "name"
                ].lower() not in [
                    c["name"].lower() for c in creature.getActiveStatusEffects()
                ]:
                    severity += negativeEffectSeverities.get(effect["name"].lower(), 0)
                    severity -= positiveEffectSeverities.get(effect["name"].lower(), 0)
                    activeEffects.append(effect["name"].lower())
    else:
        if action.getStatusEffects():
            for effect in action.getStatusEffects():
                if effect["name"].lower() not in activeEffects and effect[
                    "name"
                ].lower() not in [
                    c["name"].lower() for c in creature.getActiveStatusEffects()
                ]:
                    if (
                        effect["name"].lower() == "disadvantage"
                        and "attack rolls against" in effect["effect"]["attribute"]
                    ):
                        severity += negativeEffectSeverities.get(
                            effect["name"].lower(), 0
                        )
                    else:
                        severity -= negativeEffectSeverities.get(
                            effect["name"].lower(), 0
                        )
                        severity += positiveEffectSeverities.get(
                            effect["name"].lower(), 0
                        )
                    activeEffects.append(effect["name"].lower())
    if useProbSuccess:
        if isinstance(probSuccess, list):
            return severity * probSuccess[0]
        return severity * probSuccess
    else:
        return severity
def calcImpact(player, action, probSuccess, expectedDamage, targets,
               initiative, leRecursion=False, layeredRecursion=False):
    def computePerTargetDamageImpact(action, creature):
        base = min(expectedDamage, creature.getMaxHP() - creature.getHP())
        frac_restored = base / max(creature.getMaxHP(), 1)

        if (
            not isinstance(action.getDamType(), list)
            and action.getDamType().lower() == "healing"
        ):
            # Stronger scaling by how close to death they are
            missing_pct = (creature.getMaxHP() - creature.getHP()) / max(
                creature.getMaxHP(), 1
            )
            if creature.getHP() == creature.getMaxHP():
                missing_pct = 0
            urgency = 1 + (10 * missing_pct) ** 1.5  # 0 → 1, 50% → 1 + 2.5^4, 90% -> 1 + 4.25^4
            # Urgency dramatically scales with low HP

            damImpact = (frac_restored + urgency) * probSuccess
        else:
            try:
                damImpact = (min(int(expectedDamage) / creature.getMaxHP(), 1) * 10) * probSuccess
            except:
                if isinstance(probSuccess, list):
                    try:
                        damImpact = (
                            min(int(expectedDamage) / creature.getMaxHP(), 1) * 10
                        ) * probSuccess[0]
                    except:
                        damImpact = 0
                else:
                    damImpact = 0
            killProb = calcDamProbs(
                creature, action, action.getDamMod(), creature.getHP()
            )[0]
            if killProb > 0:
                damImpact += 3 * killProb

        return damImpact

    def computeCRWeight(creature):
        level = _cr_to_float(creature.getLevel())
        crW = math.log(1 + level)
        return crW

    def round_to_first_nonzero_decimal(n):
        if n == 0:
            return 0
        decimal_places = -math.floor(math.log10(abs(n)))
        if decimal_places < 0:
            decimal_places = 1
        decimal_places = max(decimal_places, 2)
        return round(n, decimal_places)

    def avgOverAOETargetsForImpact(perTarget, numCreatures):
        # --- CASE 1: trivial ---
        if numCreatures <= 1:
            return perTarget[0] if perTarget else 0

        # --- CASE 2: exact subset enumeration (2–10 creatures) ---
        if 2 <= numCreatures <= 10:
            import itertools

            total = 0
            count = 0
            # All non-empty subsets
            for r in range(1, numCreatures + 1):
                for subset in itertools.combinations(perTarget, r):
                    total += sum(subset)
                    count += 1
            return total / count if count > 0 else 0

        # --- CASE 3: Monte-Carlo sampling for 11+ creatures ---
        import random

        TRIALS = 1000
        impacts = []

        # adaptive variance control
        running_mean = 0
        running_sq = 0

        for i in range(1, TRIALS + 1):
            subset_impact = 0
            # random subset — each creature included with p = 0.5
            for val in perTarget:
                if random.random() < 0.5:
                    subset_impact += val
            impacts.append(subset_impact)

            # update mean/variance online
            delta = subset_impact - running_mean
            running_mean += delta / i
            running_sq += delta * (subset_impact - running_mean)

            if i >= 100:
                variance = running_sq / (i - 1)
                # If variance low enough, break early
                if variance < 0.01 * (running_mean**2 + 1e-9):
                    break

        return sum(impacts) / len(impacts)
    targets = copy.deepcopy(targets)
    for i,target in enumerate(targets):
        if isinstance(target, dict) and "Statblock" in target:
            targets[i] = target["Statblock"]

    perTarget = []
    checkExtraEffects = (
        True if isinstance(action, Spell) and action.getExtraEffect() else False
    )
    checkLingEffects = (
        True if isinstance(action, Spell) and action.getLingEffects() else False
    )
    checkLingSaves = (
        True if isinstance(action, Spell) and action.getLingSaves() else False
    )
    if isinstance(probSuccess, str):
        if checkExtraEffects:
            try:
                extraEffect = translateLingEffect(
                    action, action.getExtraEffect(), player.getSpellMod()
                )
            except:
                checkExtraEffects = False
            if checkExtraEffects:
                extraProb = probSuccess.split(" - ")
                if len(extraProb) == 1:
                    extraProb = extraProb[0]
                else:
                    for prob in extraProb:
                        if "EE" in prob:
                            extraProb = prob.split("EE")[0]
                            extraProb = float(extraProb)
                            break
        if checkLingEffects:
            try:
                lingEffect = translateLingEffect(
                    action, action.getLingEffects(), player.getSpellMod()
                )
            except:
                checkLingEffects = False
            if checkLingEffects:
                lingEffProb = probSuccess.split(" - ")
                if len(lingEffProb) == 1 or "LE" not in lingEffProb:
                    lingEffProb = lingEffProb[0]
                else:
                    for prob in lingEffProb:
                        if "LE" in prob:
                            lingEffProb = prob.split("LE")[0]
                        if "EE" in prob:
                            lingEffProb += f" - {prob}"
        if checkLingSaves:
            lingSProb = probSuccess.split(" - ")
            if len(lingSProb) == 1:
                lingSProb = lingSProb[0]
                lingSProb = float(lingSProb)
            else:
                for prob in lingSProb:
                    if "LS" in prob:
                        lingSProb = prob.split("LS")[0]
                        lingSProb = float(lingSProb)
                        break
        probSuccess = (
            probSuccess.split(" - ")[0] if " - " in probSuccess else probSuccess
        )
        probSuccess = float(probSuccess)
        if probSuccess == 0 and not checkLingEffects and not checkExtraEffects:
            return 0
    else:
        checkExtraEffects = False
        checkLingEffects = False
        checkLingSaves = False
    if isinstance(expectedDamage, str):
        expectedDamage = (
            expectedDamage.split(" - ")[1]
            if " - " in expectedDamage
            else expectedDamage
        )
        expectedDamage = (
            expectedDamage.split("W")[0] if "W" in expectedDamage else expectedDamage
        )
        expectedDamage = float(expectedDamage)

    extraImpact = 0
    lingEffImpact = 0
    lingSImpact = 0
    if checkExtraEffects:
        if leRecursion:
            extraImpact = calcImpact(
                player,
                extraEffect,
                extraProb,
                extraEffect.getMean(),
                initiative,
                False,
                True,
            )
        else:
            extraImpact = calcImpact(
                player, extraEffect, extraProb, extraEffect.getMean(), initiative
            )
    if checkLingEffects:
        lingEffImpact = calcImpact(
            player,
            lingEffect,
            lingEffProb,
            lingEffect.getMean(),
            initiative,
            True,
            False,
        )
    if checkLingSaves:
        lingSImpact = lingSProb
    for creature in targets:
        turnCount = 0
        if isinstance(action, Spell):
            specialNotes = action.getSpecialNotes()
            specialCase = False
            if specialNotes:
                for note in specialNotes:
                    if "hpcap" in note.lower():
                        cap = note.split("hpCap")[1]
                        cap = int(cap)
                        if creature.getHP() > cap:
                            perTarget.append(0)
                            specialCase = True
                            break
                    elif "only" in note.lower():
                        if isinstance(creature, Player):
                            if "humanoid" not in note.lower():
                                perTarget.append(0)
                                specialCase = True
                                break
                        elif creature.getCreatureType().lower() not in note.lower():
                            perTarget.append(0)
                            specialCase = True
                            break
                    elif "immune" in note.lower():
                        if isinstance(creature, Player):
                            if "humanoid" not in note.lower():
                                perTarget.append(0)
                                specialCase = True
                                break
                        elif creature.getCreatureType().lower() in note.lower():
                            perTarget.append(0)
                            specialCase = True
                            break
                    elif "turn" in note.lower():
                        turnCount = int(note.lower().split("turn")[0])
            if specialCase:
                continue

        if action.getMean() != 0:
            dmg = computePerTargetDamageImpact(action, creature)
        else:
            dmg = 0
        cond = 0
        statEff = 0
        lvlW = 0
        if not isinstance(action, Weapon) and not layeredRecursion and not leRecursion:
            cond = computePerTargetConditionImpact(action, probSuccess, creature)
            statEff = computePerTargetSEImpact(action, probSuccess, creature)
            if turnCount != 0:
                cond *= min((turnCount * 0.25), 1)
                statEff *= min((turnCount * 0.25), 1)
        if isinstance(action, Spell) and action.getLvl() >= 1:
            lvlW = math.log(int(action.getLvl()) + 1)

        crW = computeCRWeight(creature)
        impact_i = dmg
        try:
            impact_i += (cond + statEff) * crW
        except:
            try:
                impact_i += (cond + statEff) * math.floor(crW)
            except:
                impact_i += math.floor(crW)
        impact_i += lvlW  # influence from spell level
        perTarget.append(impact_i)

    for i in range(len(perTarget)):  # Normalize
        perTarget[i] = round_to_first_nonzero_decimal(perTarget[i])
        perTarget[i] = max(perTarget[i], 0)

    if isinstance(action, Weapon) or action.getNumTarget() == 1:
        if len(perTarget) > 0:
            impact = max(perTarget)
        else:
            impact = 0
    elif action.getNumTarget() in [-1, -2]:
        impact = avgOverAOETargetsForImpact(perTarget, len(perTarget))
    elif action.getNumTarget() > 1:
        perTarget.sort(reverse=True)
        idx = 0
        bestTargets = []
        while idx < len(perTarget) and idx < action.getNumTarget():
            bestTargets.append(perTarget[idx])
            idx += 1
        if len(bestTargets) != 0:
            impact = sum(bestTargets) / len(bestTargets)
        else:
            impact = 0
    else:
        impact = perTarget[0] if perTarget else 0

    impact += extraImpact
    impact += impact * lingSImpact
    impact += lingEffImpact
    # impact = min(impact, 20) #Removing impact cap for data analysis on accuracy
    return round_to_first_nonzero_decimal(impact)

# RESULT CREATE/SAVE METHODS
def logActionResult(encounter, actionResult):
    if isinstance(actionResult, dict):
        encounter.addResult(actionResult)
        return
    actionJSON = actionResult.model_dump(mode="json", by_alias=True)
    encounter.addResult(actionJSON)
def logLingeringResult(resultID, creatureName, lingType, result):
    entry = {
        "resultID": resultID,
        "creature": creatureName,
        "lingType": lingType,
        "outcome": result,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    return entry

# SIMULATION METHODS
def addCondition(condToAdd, creature, resultID):
    if isinstance(creature, dict):
        creature = creature["Statblock"]
    with open(CONDITION_LIST_FILE, "r") as f:
        condData = json.load(f)
    for condition in condData:
        if condToAdd.lower() == condition['name'].lower():  # Find condition
            for activeCond in creature.getActiveConditions():
                match = False
                if isinstance(condToAdd, dict):
                    if isinstance(activeCond, dict):
                        if condToAdd["cond"].lower() == activeCond["cond"].lower():
                            match = True
                    else:
                        if condToAdd["cond"].lower() == activeCond.lower():
                            match = True
                elif isinstance(activeCond, dict):
                    if condToAdd.lower() == activeCond["cond"].lower():
                        match = True
                else:
                    if condToAdd.lower() == activeCond.lower():
                        match = True
                if match:
                    if isinstance(activeCond, dict):
                        if any(resultID == rID for rID in activeCond["resultID"]):
                            return False
                        activeCond["resultID"].append(resultID)
                        return True
                    return False

            condToAdd = {"cond": condToAdd, "resultID": [resultID]}
            creature.addCondition(condToAdd)
            return True
    return False
def removeCondition(condToRemove, creature):
    if isinstance(creature, dict):
        creature = creature["Statblock"]
    if condToRemove.lower() == "dead":
        return False
    with open(CONDITION_LIST_FILE, "r") as f:
        condData = json.load(f)
    for condition in condData:
        if condToRemove.lower() == condition["name"].lower():
            return creature.removeCondition(condToRemove)
    return False
def addStatusEffect(effect, creature, resultID):
    effect = copy.deepcopy(effect)
    if "attribute" in effect["effect"]:
        effect["effect"]["attribute"] = ensureList(effect["effect"]["attribute"])
    if isinstance(creature, dict):
        creature = creature["Statblock"]
    activeStatusEffects = creature.getActiveStatusEffects()
    for activeStatus in activeStatusEffects:
        if activeStatus["name"].lower() == effect["name"].lower():
            if "attribute" in activeStatus["effect"]:
                activeStatus["effect"]["attribute"] = ensureList(activeStatus["effect"]["attribute"])
            if all(item in activeStatus["effect"]["attribute"] for item in effect["effect"]["attribute"]):
                # All attributes are the exact same.
                if not any(resultID == rID for rID in activeStatus["effect"]["resultID"]):
                    activeStatus["effect"]["attribute"].extend(effect["effect"]["attribute"])
                    for i in range(len(effect["effect"]["attribute"])):
                        activeStatus["effect"]["resultID"].append(resultID)
                    return True
                else:
                    return False
            elif any(item in activeStatus["effect"]["attribute"] for item in effect["effect"]["attribute"]):
                # Any of the attributes match.
                nonActiveAttr = [item if item not in activeStatus["effect"]["attribute"] else None for item in
                                 effect["effect"]["attribute"]]
                for attr in nonActiveAttr:
                    if attr is not None:
                        activeStatus["effect"]["attribute"].append(attr)
                for i in range(len(nonActiveAttr)):
                    activeStatus["effect"]["resultID"].append(resultID) if nonActiveAttr[
                                                                               i] is not None and resultID != -1 else False
                return True
            if effect["name"].lower() in ["lingeffect", "lingsave"]:
                # If there is a match AND the effect is lingEffect/lingSave
                if any(resultID == rID for rID in activeStatus["effect"]["resultID"]):
                    return False
                if effect["name"].lower() == "lingeffect":
                    ling = creature.getActiveStatusEffect("lingEffect")
                else:
                    ling = creature.getActiveStatusEffect("lingsave")
                ling["effect"]["action"].extend(effect["action"])
                ling["effect"]["resultID"].extend(effect["resultID"])
    effect["effect"]["resultID"] = [resultID]
    creature.addStatusEffect(effect)
    return True
def removeStatusEffect(name, creature):
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    for effect in creature.getActiveStatusEffects():
        if name.lower() == effect["name"].lower():
            return creature.removeStatusEffect(name)
def endOfEncounter(initiative):
    allPlayersDead = True
    for playerTurns in initiative:
        if playerTurns["turnType"] == "Player":
            if not playerTurns["Statblock"].isActiveCondition("Dead") and not playerTurns[
                "Statblock"].isActiveCondition("Out of Combat"):
                allPlayersDead = False
                break
    allMonstersDead = True
    for monsterTurn in initiative:
        if monsterTurn["turnType"] == "Monster":
            if not monsterTurn["Statblock"].isActiveCondition("Dead") and not monsterTurn[
                "Statblock"].isActiveCondition("Out of Combat"):
                allMonstersDead = False
                break
    return allPlayersDead or allMonstersDead
def endConcentration(player, concentration, initiative, mapdata):
    if isinstance(player, dict):
        player = player["Statblock"]
    concTargets = concentration["effect"]["concentrationTargets"]
    summon = False
    if "summonConc" in concentration["effect"]:
        summon = True
    player.removeStatusEffect("concentration")
    cIdx = 0
    while cIdx < len(initiative):
        creature = initiative[cIdx]["Statblock"]
        summonedCreature = False
        if creature.getName() in concTargets:
            if creature.getActiveStatusEffects():
                if any(
                    isinstance(statusEffect["effect"]["resultID"], list)
                    and concentration["effect"]["resultID"]
                    in statusEffect["effect"]["resultID"]
                    for statusEffect in creature.getActiveStatusEffects()
                ):
                    # lingEffect has a list of resultIDs. Want to match with the ONE concentrationID, and remove it.
                    statEffects = creature.getActiveStatusEffects()
                    for i in range(len(statEffects)):
                        # Removes creature if it is a summoned creature
                        if summon:
                            if (
                                concentration["effect"]["resultID"]
                                in statEffects[i]["effect"]["resultID"]
                            ):
                                del initiative[cIdx]
                                summonedCreature = True
                                break

                        # Skip over any concentration effects the creature currently has
                        if not isinstance(statEffects[i]["effect"]["resultID"], list):
                            continue
                        # Remove any attributes associated with the ID
                        for j, resID in enumerate(statEffects[i]["effect"]["resultID"]):
                            if concentration["effect"]["resultID"] == resID:
                                del statEffects[i]["effect"]["resultID"][j]
                                if statEffects[i]["name"].lower() not in [
                                    "lingeffect",
                                    "lingsave",
                                ]:
                                    del statEffects[i]["effect"]["attribute"][j]
                                else:
                                    if "spell" in statEffects[i]["effect"]:
                                        del statEffects[i]["effect"]["spell"][j]
                                    else:
                                        del statEffects[i]["effect"]["action"][j]
                    if summonedCreature:
                        continue
                    seIdx = 0
                    while seIdx < len(statEffects):
                        statEffect = statEffects[seIdx]
                        if isinstance(statEffect["effect"]["resultID"], list) and len(
                                statEffect["effect"]["resultID"]) == 0:
                            # If no more resultID's left, then statusEffect is no longer active.
                            creature.removeStatusEffect(statEffect["name"])
                        else:
                            seIdx += 1
            if creature.getActiveConditions():
                if any(isinstance(condition, dict) and concentration["effect"]["resultID"] in condition["resultID"]
                       for condition in creature.getActiveConditions()
                       ):
                    conditions = creature.getActiveConditions()
                    cidx = 0
                    while cidx < len(conditions):
                        for j in range(len(conditions[cidx]["resultID"])):
                            if concentration["effect"]["resultID"] == conditions[cidx]["resultID"][j]:
                                del conditions[cidx]["resultID"][j]
                                break
                        if len(conditions[cidx]["resultID"]) == 0:
                            creature.removeCondition(conditions[cidx]["cond"])
                            continue
                        cidx += 1

        if not summonedCreature:
            cIdx += 1

    for tidx, token in enumerate(mapdata["layers"]["aoeTokens"]):
        if token["resultID"] in concentration["effect"]["resultID"]:
            del mapdata["layers"]["aoeTokens"][tidx]

def executeAction(actor, action, selectedTargets, actionResult, initiative, mapdata):
    def applyEffectToTarget(creature, succeeded, damage, action, resultID):
        rollType = action.getRollType().lower() if isinstance(action, Spell) or isinstance(action, MonAction) else "tohit"

        downed_before = creature.isActiveCondition("Downed")
        stable_before = creature.isActiveCondition("Stabilized")

        if (
            isinstance(action, Spell)
            and not isinstance(action.getDamType(), list)
            and action.getDamType().lower() == "healing"
        ):
            if damage > 0:
                creature.setHP(min(creature.getMaxHP(), creature.getHP() + damage))
        else:
            if damage > 0:
                creature.setHP(creature.getHP() - damage)

        creature.setHP(math.floor(creature.getHP()))

        if creature.isActiveCondition("downed") and damage > 0:
            removeCondition("downed", creature)
            addCondition("dead", creature, -1)

        if creature.getHP() <= 0:
            creature.setHP(0)
            if isinstance(creature, Player):
                addCondition(
                    "Downed" if damage < (creature.getMaxHP() + creature.getHP()) else "Dead",
                    creature,
                    resultID,
                )
            else:
                addCondition("Dead", creature, resultID)

        if creature.getHP() > 0:
            if downed_before:
                creature.removeCondition("Downed")
            if stable_before:
                creature.removeCondition("Stabilized")

        if (rollType == "save" and not succeeded) or (rollType != "save" and succeeded):
            if isinstance(action, Spell) and action.getConditions():
                for cond in action.getConditions():
                    addCondition(cond, creature, resultID)

            if isinstance(action, Spell) and action.getStatusEffects():
                for effect in action.getStatusEffects():
                    if effect["name"].lower() != "concentration":
                        addStatusEffect(effect, creature, resultID)

            if isinstance(action, Spell) and action.getLingSaves():
                if creature.isActiveStatusEffect("lingsave"):
                    lingSaves = creature.getActiveStatusEffect("lingsave")
                    if not any(resultID == rID for rID in lingSaves["effect"]["resultID"]):
                        if "spell" in lingSaves["effect"]:
                            lingSaves["effect"]["spell"].append(action.toDict())
                        else:
                            lingSaves["effect"]["action"].append(action.toDict())
                        lingSaves["effect"]["resultID"].append(actionResult["resultID"])
                else:
                    newLingSave = {
                        "name": "lingSave",
                        "effect": {
                            "action": [action.toDict()],
                            "resultID": [actionResult["resultID"]],
                        },
                    }
                    addStatusEffect(newLingSave, creature, actionResult["resultID"])

        return creature
    def _normalize_result_flag(result, roll_type, target_obj, save_dc):
        result_str = str(result).strip()

        if not result_str.isnumeric():
            return result_str.lower()

        if roll_type in ("weapon", "onhit", "tohit"):
            target_ac = target_obj.getAC()
            return "y" if int(result_str) >= target_ac else "n"

        if roll_type == "save":
            return "y" if int(result_str) >= save_dc else "n"

        return result_str.lower()
    def _applied_damage_amount(raw_damage, succeeded, roll_type, half_save=False, is_healing=False):
        try:
            raw_damage = int(raw_damage)
        except (TypeError, ValueError):
            raw_damage = 0

        if is_healing:
            return raw_damage if succeeded else 0

        if roll_type in ("weapon", "onhit", "autohit", "tohit"):
            return raw_damage if succeeded else 0

        if roll_type == "save":
            if not succeeded:
                return raw_damage
            return (raw_damage // 2) if half_save else 0

        return 0


    def _normalize_result_flag(result, roll_type, target_obj, save_dc):
        result_str = str(result).strip()

        if not result_str.isnumeric():
            return result_str.lower()

        if roll_type in ("weapon", "onhit", "tohit"):
            target_ac = target_obj.getAC()
            return "y" if int(result_str) >= target_ac else "n"

        if roll_type == "save":
            return "y" if int(result_str) >= save_dc else "n"

        return result_str.lower()

    def _applied_damage_amount(raw_damage, succeeded, roll_type, half_save=False, is_healing=False):
        try:
            raw_damage = int(raw_damage)
        except (TypeError, ValueError):
            raw_damage = 0

        if is_healing:
            return raw_damage if succeeded else 0

        if roll_type in ("weapon", "onhit", "autohit", "tohit"):
            return raw_damage if succeeded else 0

        if roll_type == "save":
            if not succeeded:
                return raw_damage
            return (raw_damage // 2) if half_save else 0

        return 0

    outcomes = actionResult["outcome"]["rollResults"]
    damages = actionResult["outcome"]["diceResults"]

    if len(damages) == 1 and len(selectedTargets) != 1:
        damages = [damages[0]] * len(selectedTargets)
        actionResult["outcome"]["diceResults"] = damages

    for i in range(len(damages)):
        try:
            damages[i] = int(damages[i])
        except (TypeError, ValueError):
            damages[i] = 0

    main_roll_type = "weapon" if isinstance(action, Weapon) else action.getRollType().lower()
    main_save_dc = actor.getDC() if hasattr(actor, "getDC") else 0

    for i, result in enumerate(list(actionResult["outcome"]["rollResults"])):
        if i >= len(selectedTargets):
            break

        target_obj = selectedTargets[i]["Statblock"] if isinstance(selectedTargets[i], dict) else selectedTargets[i]
        actionResult["outcome"]["rollResults"][i] = _normalize_result_flag(
            result,
            main_roll_type,
            target_obj,
            main_save_dc,
        )

    extra = actionResult.get("extraOutcome")
    extra_effect = action.getExtraEffect() if hasattr(action, "getExtraEffect") else None
    if extra and extra_effect:
        extra_roll_type = str(extra_effect.get("rolls", {}).get("rollType", "")).lower()
        extra_save_dc = actor.getDC() if hasattr(actor, "getDC") else 0
        extra_outcomes = extra.get("extraRollResults", [])
        extra_damages = extra.get("extraDiceResults", [])

        if len(extra_damages) == 1 and len(selectedTargets) != 1:
            extra_damages = [extra_damages[0]] * len(selectedTargets)
            extra["extraDiceResults"] = extra_damages

        for i in range(len(extra_damages)):
            try:
                extra_damages[i] = int(extra_damages[i])
            except (TypeError, ValueError):
                extra_damages[i] = 0

        for i, result in enumerate(list(extra_outcomes)):
            if i >= len(selectedTargets):
                break

            target_obj = selectedTargets[i]["Statblock"] if isinstance(selectedTargets[i], dict) else selectedTargets[i]
            extra_outcomes[i] = _normalize_result_flag(
                result,
                extra_roll_type,
                target_obj,
                extra_save_dc,
            )

    if (
        isinstance(action, Spell)
        and action.getStatusEffects()
        and "concentration" in [se["name"].lower() for se in action.getStatusEffects()]
    ):
        concEffect = {
            "name": "Concentration",
            "effect": {
                "resultID": actionResult["resultID"],
                "concentrationTargets": [
                    t["Statblock"].getName() if isinstance(t, dict) else t.getName()
                    for t in selectedTargets
                ],
                "action": action.toDict(),
            },
        }
        for se in actor.getActiveStatusEffects():
            if se["name"].lower() == "concentration":
                if any(
                    effect in se["effect"]["concentrationTargets"]
                    for effect in concEffect["effect"]["concentrationTargets"]
                ):
                    oldTargets = se["effect"]["concentrationTargets"]
                    endConcentration(actor, se, initiative, mapdata)
                    cetidx = 0
                    while cetidx < len(concEffect["effect"]["concentrationTargets"]):
                        cet = concEffect["effect"]["concentrationTargets"][cetidx]
                        if cet in oldTargets and cet not in [c["name"] for c in initiative]:
                            del concEffect["effect"]["concentrationTargets"][cetidx]
                            del actionResult["targets"][cetidx]
                            del actionResult["effect"]["action"][cetidx]
                            del actionResult["outcome"]["diceResults"][cetidx]
                            del actionResult["outcome"]["rollResults"][cetidx]
                            del selectedTargets[cetidx]
                            continue
                        cetidx += 1
                else:
                    endConcentration(actor, se, initiative, mapdata)
                break
        actor.addStatusEffect(concEffect)

    main_is_healing = (
        isinstance(action, Spell)
        and not isinstance(action.getDamType(), list)
        and action.getDamType().lower() == "healing"
    )
    main_half_save = bool(action.getHalfSave()) if hasattr(action, "getHalfSave") else False

    for idx, target in enumerate(selectedTargets):
        creature = target["Statblock"] if isinstance(target, dict) else target
        succeeded = idx < len(outcomes) and str(outcomes[idx]).lower() in ("y", "crit")

        raw_damage = damages[idx] if idx < len(damages) else 0
        damTypes = action.getDamType()
        if isinstance(damTypes, list):
            if len(damTypes) == 1:
                dType = damTypes[0]
                if creature.isResistant(dType):
                    raw_damage /= 4
                elif creature.isVulnerable(dType):
                    raw_damage *= 1.5
                elif creature.isImmune(dType):
                    raw_damage /= 2
            if "AND" in damTypes:
                for dType in damTypes:
                    if creature.isResistant(dType):
                        raw_damage /= 4
                    elif creature.isVulnerable(dType):
                        raw_damage *= 1.5
                    elif creature.isImmune(dType):
                        raw_damage /= 2
            elif "OR" in damTypes:
                if all(creature.isResistant(dType) for dType in damTypes):
                    raw_damage /= 2
                elif all(creature.isImmune(dType) for dType in damTypes):
                    raw_damage *= 0
                elif any(creature.isVulnerable(dType) for dType in damTypes):
                    raw_damage *= 2
        if isinstance(damTypes, str):
            if creature.isResistant(damTypes):
                raw_damage /= 4
            elif creature.isVulnerable(damTypes):
                raw_damage *= 1.5
            elif creature.isImmune(damTypes):
                raw_damage /= 2
        applied_damage = _applied_damage_amount(
            raw_damage,
            succeeded,
            main_roll_type,
            half_save=main_half_save,
            is_healing=main_is_healing,
        )

        if idx < len(damages):
            damages[idx] = applied_damage

        creature = applyEffectToTarget(
            creature, succeeded, applied_damage, action, actionResult["resultID"]
        )

        if isinstance(action, Spell) and action.getLingEffects():
            transLingEffect = translateLingEffect(
                action, action.getLingEffects(), actor.getSpellMod()
            )
            if creature.isActiveStatusEffect("lingEffect"):
                lingEffect = creature.getActiveStatusEffect("lingEffect")
                if "spell" in lingEffect["effect"]:
                    lingEffect["effect"]["spell"].append(transLingEffect.toDict())
                else:
                    lingEffect["effect"]["action"].append(transLingEffect.toDict())
                lingEffect["effect"]["resultID"].append(actionResult["resultID"])
            else:
                newLingEffect = {
                    "name": "lingEffect",
                    "effect": {
                        "action": [transLingEffect.toDict()],
                        "resultID": [actionResult["resultID"]],
                    },
                }
                addStatusEffect(newLingEffect, creature, actionResult["resultID"])

    extra = actionResult.get("extraOutcome", None)
    extra_effect = action.getExtraEffect() if hasattr(action, "getExtraEffect") else None
    if extra and extra_effect:
        extraOutcomes = extra.get("extraRollResults", [])
        extraDamages = extra.get("extraDiceResults", [])

        if extraOutcomes or extraDamages:
            if len(extraDamages) == 1 and len(selectedTargets) != 1:
                extraDamages = [extraDamages[0]] * len(selectedTargets)
                extra["extraDiceResults"] = extraDamages

            extraRollType = str(extra_effect.get("rolls", {}).get("rollType", "")).lower()
            extraHalfSave = bool(extra_effect.get("rolls", {}).get("halfSave", False))

            extraDamType = extra_effect.get("damType")
            if isinstance(extraDamType, list):
                extraIsHealing = len(extraDamType) == 1 and str(extraDamType[0]).lower() == "healing"
            else:
                extraIsHealing = str(extraDamType).lower() == "healing"

            for idx, target in enumerate(selectedTargets):
                creature = target["Statblock"] if isinstance(target, dict) else target
                succeededExtra = idx < len(extraOutcomes) and str(extraOutcomes[idx]).lower() in ("y", "crit")

                rawDamageExtra = extraDamages[idx] if idx < len(extraDamages) else 0
                appliedDamageExtra = _applied_damage_amount(
                    rawDamageExtra,
                    succeededExtra,
                    extraRollType,
                    half_save=extraHalfSave,
                    is_healing=extraIsHealing,
                )

                if idx < len(extraDamages):
                    extraDamages[idx] = appliedDamageExtra

                downed_before = creature.isActiveCondition("Downed")
                stable_before = creature.isActiveCondition("Stabilized")

                if extraIsHealing:
                    if appliedDamageExtra > 0:
                        creature.setHP(min(creature.getMaxHP(), creature.getHP() + appliedDamageExtra))
                else:
                    if appliedDamageExtra > 0:
                        creature.setHP(creature.getHP() - appliedDamageExtra)

                creature.setHP(math.floor(creature.getHP()))

                if creature.getHP() <= 0:
                    creature.setHP(0)
                    if isinstance(creature, Player):
                        addCondition(
                            "Downed" if appliedDamageExtra < (creature.getMaxHP() + creature.getHP()) else "Dead",
                            creature,
                            actionResult["resultID"],
                        )
                    else:
                        addCondition("Dead", creature, actionResult["resultID"])

                if creature.getHP() > 0:
                    if downed_before:
                        creature.removeCondition("Downed")
                    if stable_before:
                        creature.removeCondition("Stabilized")

                if (extraRollType == "save" and not succeededExtra) or (
                    extraRollType != "save" and succeededExtra
                ):
                    if "conditions" in extra_effect and extra_effect["conditions"]:
                        for cond in extra_effect["conditions"]:
                            addCondition(cond, creature, actionResult["resultID"])
                    if "statusEffect" in extra_effect and extra_effect["statusEffect"]:
                        for effect in extra_effect["statusEffect"]:
                            if effect["name"].lower() != "concentration":
                                addStatusEffect(effect, creature, actionResult["resultID"])

    if isinstance(action, Spell) and action.getSpecialNotes():
        specialNotes = action.getSpecialNotes()
        for note in specialNotes:
            if "turn" in note.lower():
                actionResult["turnCount"] = 0
                actionResult["turnCap"] = int(note.lower().split("turn")[0])
                break

def endSpellEffect(effect, idx, creature):
    # Ends any long-lasting effect that a creature has from a given spell
    # - and ends concentration if nobody else is under that spell.
    effectID = effect["effect"]["resultID"][idx]
    # lingEffect = False

    del effect["effect"]["resultID"][idx]
    if effect["name"].lower() in ["lingsave", "lingeffect"]:
        if effect["name"].lower() == "lingeffect":
            lingEffect = True
        if "spell" in effect["effect"]:
            del effect["effect"]["spell"][idx]
        else:
            del effect["effect"]["action"][idx]

    # Removes associated statEffects and conditions from creature.
    for condition in creature.getActiveConditions():
        if isinstance(condition, dict):
            for ri, resultID in enumerate(condition["resultID"]):
                if effectID == resultID:
                    del condition["resultID"][ri]
                    break
            if len(condition["resultID"]) == 0:
                removeCondition(condition["cond"], creature)
    statEffects = creature.getActiveStatusEffects()
    i = 0
    while i < len(statEffects):
        se = statEffects[i]
        if (
                se["name"].lower() != "concentration"
                and effectID in se["effect"]["resultID"]
        ):
            for ri, resultID in enumerate(se["effect"]["resultID"]):
                if effectID == resultID:
                    del statEffects[i]["effect"]["resultID"][ri]
                    if len(se[i]["effect"]["resultID"]) == 0:
                        del statEffects[i]
                    break
        i += 1
    #This part is optional from the MTHcap. Do we want to let lingsave concentration die if its not targeting anything?
    #Or do we leave that to user choice?
    # if not lingEffect:
    #     for target in initiative:
    #         target = target["Statblock"]
    #         if target.isActiveStatusEffect("concentration"):
    #             concEffect = target.getActiveStatusEffect("concentration")
    #             if concEffect["effect"]["resultID"] == effectID:
    #                 remainingTargets = False
    #                 for effectTarget in initiative:
    #                     effectTarget = effectTarget["Statblock"]
    #                     if (
    #                         effectTarget.isActiveStatusEffect(effect["name"])
    #                         and effectID
    #                         in effectTarget.getActiveStatusEffect(effect["name"])["effect"][
    #                             "resultID"
    #                         ]
    #                     ):
    #                         remainingTargets = True
    #                         break
    #                 if not remainingTargets:
    #                     endConcentration(target, concEffect, initiative)
    #                 break

#ENCOUNTER RUNTIME METHODS
def merge_sort_spells(spell_list):
    if len(spell_list) <= 1:
        return spell_list

    mid = len(spell_list) // 2
    left_half = merge_sort_spells(spell_list[:mid])
    right_half = merge_sort_spells(spell_list[mid:])

    return merge_spells(left_half, right_half)
def merge_spells(left, right):
    result = []
    i = j = 0

    while i < len(left) and j < len(right):
        left_spell = left[i]
        right_spell = right[j]

        # Primary key: spell level
        if left_spell.getLvl() < right_spell.getLvl():
            result.append(left_spell)
            i += 1
        elif left_spell.getLvl() > right_spell.getLvl():
            result.append(right_spell)
            j += 1
        else:
            # Secondary key: alphabetical by name (case-insensitive)
            if left_spell.getName().lower() <= right_spell.getName().lower():
                result.append(left_spell)
                i += 1
            else:
                result.append(right_spell)
                j += 1

    while i < len(left):
        result.append(left[i])
        i += 1

    while j < len(right):
        result.append(right[j])
        j += 1

    return result
def processSpellAnalytics(spellList, initEntry, initiative, isPlayerTurn):
    creature = initEntry["Statblock"]
    actionNames = []
    actionTypes = []
    actionProbs = []
    actionEDams = []
    actionPercentages = []
    actionImpacts = []
    actionTargets = []
    actionObjects = []   # add this

    for i in range(len(spellList)):
        if actionViabilityCheck(spellList[i], initEntry, initiative, isPlayerTurn):
            spellName = spellList[i].getName()
            try:
                spellProb = 0
                spellEDam = -1
                if spellList[i].getSelfTarget():
                    spellProb = 1.0
                    spellEDam = 0
                    probTargets = [creature.getName()]
                    eTargets = [creature.getName()]
                else:
                    if spellList[i].getRollType().lower() == "tohit":
                        spellProb = calcTotalToHitProbability(creature, spellList[i], initiative)
                    elif spellList[i].getRollType().lower() == "save":
                        spellProb = calcTotalSaveProbability(creature, spellList[i], initiative)
                    elif spellList[i].getRollType().lower() == "autohit":
                        if spellList[i].getDiceNum() == 0 and not spellList[i].getLingSaves() \
                                and not spellList[i].getLingEffects() and not spellList[i].getExtraEffect() \
                                and not (spellList[i].getSpecialNotes() and "HPCap" in spellList[i].getSpecialNotes()):
                            spellProb = 1.0
                            spellEDam = 0

                        else:
                            if spellList[i].getStatusEffects() and any(
                                    [se["name"] == "Summon" for se in spellList[i].getStatusEffects()]):
                                spellProb = 1.0
                                spellEDam = 0
                            else:
                                spellProb = calcTotalAutoHitProbability(creature, spellList[i], initiative)
                    elif spellList[i].getRollType().lower() == "onhit":
                        spellProb = calcOnHitProbability(spellList[i],
                                                         [creature.getWeapon(i) for i in range(creature.getWeaponLength())],
                                                         creature, initiative)
                    if isinstance(spellProb, dict):
                        spellProb["probSuccess"] = 0 if spellProb["probSuccess"] < 0 else spellProb["probSuccess"]
                        spellProb["probSuccess"] = 1 if spellProb["probSuccess"] > 1 else spellProb["probSuccess"]
                        probToStr = f"{spellProb['probSuccess']}" if spellProb['probSuccess'] else f"0.0"
                        probToStr += f" - {spellProb['probLingEffect']}LE" if spellProb['probLingEffect'] else ""
                        probToStr += f" - {spellProb['probExtraEffect']}EE" if spellProb['probExtraEffect'] else ""
                        probToStr += f" - {spellProb['probLingSaves']}LS" if spellProb['probLingSaves'] else ""
                        probTargets = spellProb["target"] if spellProb["probSuccess"] != 0 else ""
                    else:
                        spellProb = 0 if spellProb < 0 else spellProb
                        spellProb = 1 if spellProb > 1 else spellProb
                        probToStr = spellProb
                        probTargets = {}
                    spellProb = probToStr
                    try:
                        #TODO: Failed burning hands eDam, prob and impact worked.
                        spellEDam, eTargets = calcTotalExpectedDamage(creature, spellList[i],
                                                                   initiative) if spellEDam == -1 else spellEDam
                    except TypeError:
                        spellEDam = 0
                        eTargets = {}

                if not probTargets and not eTargets:
                    continue
                probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                eTargetsNorm = normalizeTargetSets(eTargets, initiative)

                if probTargetsNorm and eTargetsNorm and {target.getName() for target in probTargetsNorm} == {target.getName() for target in eTargetsNorm}:
                    #Good case.
                    spellImpact = calcImpact(creature, spellList[i], spellProb,
                                             spellEDam, probTargetsNorm, initiative)
                    target = probTargets
                else:
                    #Bad case.
                    if not probTargetsNorm and eTargetsNorm:
                        spellImpact = calcImpact(creature, spellList[i], spellProb,
                                             spellEDam, eTargetsNorm, initiative)
                        target = eTargets
                    elif not eTargetsNorm and probTargetsNorm:
                        spellImpact = calcImpact(creature, spellList[i], spellProb,
                                                 spellEDam, probTargetsNorm, initiative)
                        target = probTargets
                    elif not probTargetsNorm and not eTargetsNorm:
                        spellImpact = 0
                        target = None
                    else:
                        spellImpact1 = calcImpact(creature, spellList[i], spellProb,
                                                  spellEDam, probTargetsNorm, initiative)
                        spellImpact2 = calcImpact(creature, spellList[i], spellProb,
                                                 spellEDam, eTargetsNorm, initiative)
                        spellImpact = max([spellImpact1, spellImpact2])
                        targetIdx = [spellImpact1, spellImpact2].index(spellImpact)
                        target = probTargets if targetIdx == 0 else eTargets

                actionNames.append(spellName)
                actionTypes.append(f"Lvl {spellList[i].getLvl()} spell")
                actionProbs.append(spellProb)
                actionEDams.append(spellEDam)
                actionImpacts.append(spellImpact)
                actionTargets.append(target)
                actionObjects.append(spellList[i])
                if isinstance(target, list):
                    percentages = []
                    for i, t in enumerate(target):
                        hp = t.getHP()
                        if isinstance(spellEDam, list):
                            percentages.append(round(spellEDam[i] / hp, 2))
                        else:
                            percentages.append(round(spellEDam / hp, 2))
                    actionPercentages.append(percentages)
                elif isinstance(target, dict):
                    if "targetsHit" in target:
                        percentages = []
                        for i, t in enumerate(target["targetsHit"]):
                            hp = t.getHP()
                            if isinstance(spellEDam, list):
                                percentages.append(round(spellEDam[i] / hp, 2))
                            else:
                                percentages.append(round(spellEDam / hp, 2))
                        actionPercentages.append(percentages)
                else:
                    hp = target.getHP()
                    if isinstance(spellEDam, list):
                        actionPercentages.append(round(spellEDam[i] / hp, 2))
                    else:
                        actionPercentages.append(round(spellEDam / hp, 2))
            except:
                continue

    actions = [{"name": actionNames[i], "type" : actionTypes[i], "prob": actionProbs[i], "eDam": actionEDams[i],
                "percentage" : actionPercentages[i], "impact": actionImpacts[i],
                "actions" : actionObjects[i], "target" : actionTargets[i]} for
               i in range(len(actionNames))]
    return actions

def processClassAbilityAnalytics(abilities, player, initiative):
    # TODO: Read through abilities list
    # abilities are the already translated class objects
    # Then process using player and initiative like other analytics.
    pass

def _extract_prob_value(prob) -> float:
    if isinstance(prob, (int, float)):
        return float(prob)

    if isinstance(prob, str):
        try:
            return float(prob.split(" - ")[0].strip())
        except Exception:
            return 0.0

    if isinstance(prob, dict):
        return float(prob.get("probSuccess", 0.0))

    return 0.0
def _score_action_with_ml(
    *,
    actor,
    action_obj,
    targets,
    encounter_id: str,
    prob : float,
    expected_damage: float,
    impact: float,
    base_weight : int
):
    heuristic_components = {
        "expected_damage": float(expected_damage or 0.0),
        "impact_score": float(impact or 0.0),
        "kill_chance": 0.0,
        "prob_success": prob,
    }

    context = {
        "expected_damage": float(expected_damage or 0.0),
        "impact_score": float(impact or 0.0),
        "num_targets": len(targets) if isinstance(targets, list) else 0,
    }

    record = make_training_record(
        action=action_obj,
        actor=actor,
        targets=targets,
        encounter_id=encounter_id,
        base_weight=base_weight,
        heuristic_components=heuristic_components,
        context=context,
    )

    ml_weight = predict_action_weight(record)
    return ml_weight, record


def _extract_prob_value(prob) -> float:
    if isinstance(prob, (int, float)):
        return float(prob)

    if isinstance(prob, str):
        try:
            return float(prob.split(" - ")[0].strip())
        except Exception:
            return 0.0

    if isinstance(prob, dict):
        return float(prob.get("probSuccess", 0.0))

    return 0.0
def _score_action_with_ml(
    *,
    actor,
    action_obj,
    targets,
    encounter_id: str,
    prob : float,
    expected_damage: float,
    impact: float,
    base_weight : int
):
    heuristic_components = {
        "expected_damage": float(expected_damage or 0.0),
        "impact_score": float(impact or 0.0),
        "kill_chance": 0.0,
        "prob_success": prob,
    }

    context = {
        "expected_damage": float(expected_damage or 0.0),
        "impact_score": float(impact or 0.0),
        "num_targets": len(targets) if isinstance(targets, list) else 0,
    }

    record = make_training_record(
        action=action_obj,
        actor=actor,
        targets=targets,
        encounter_id=encounter_id,
        base_weight=base_weight,
        heuristic_components=heuristic_components,
        context=context,
    )

    ml_weight = predict_action_weight(record)
    return ml_weight, record
def rankActions(actions, actor=None, encounter_id=None, use_ml=True):
    def getBaseRankings():
        KEYS = ("prob", "rankEDam", "rankImpact")

        SEG_RE = re.compile(
            r"^\s*(?P<a>\d*\.?\d+)\s*(?:-\s*(?P<b>\d*\.?\d+))?\s*(?P<tag>LS|LE|EE)?\s*$",
            re.IGNORECASE,
        )

        def _mid(a, b):
            return (a + b) / 2.0 if b is not None else a

        def _safe_float(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def parse_prob_segments(prob_str_or_num):
            if isinstance(prob_str_or_num, (int, float)):
                return float(prob_str_or_num), {}

            if not isinstance(prob_str_or_num, str):
                raise TypeError(f"Unsupported prob type: {type(prob_str_or_num)}")

            s = prob_str_or_num.strip()
            if s and s[0] == "-":
                s = s[1:]

            chunks = [c.strip() for c in s.split(" - ")]
            if not chunks:
                raise ValueError(f"Empty prob string: {prob_str_or_num!r}")

            m0 = SEG_RE.match(chunks[0])
            if not m0:
                raise ValueError(
                    f"Could not parse initial prob chunk: {chunks[0]!r} of {s}"
                )

            a0 = float(m0.group("a"))
            b0 = float(m0.group("b")) if m0.group("b") is not None else None
            initial = _mid(a0, b0)

            parts = {}
            for chunk in chunks[1:]:
                m = SEG_RE.match(chunk)
                if not m:
                    continue

                a = float(m.group("a"))
                b = float(m.group("b")) if m.group("b") is not None else None
                tag = (m.group("tag") or "").upper()

                if tag not in {"LS", "LE", "EE"}:
                    raise ValueError(f"Missing/invalid tag in chunk: {chunk!r}")

                parts[tag] = _mid(a, b)

            return initial, parts

        def prob_score_weighted(initial, parts, weights=None):
            if weights is None:
                weights = {"INIT": 0.70, "LS": 0.10, "LE": 0.10, "EE": 0.10}

            used = {"INIT": weights["INIT"]}
            for tag in ("LS", "LE", "EE"):
                if tag in parts:
                    used[tag] = weights.get(tag, 0.0)

            denom = sum(used.values())
            score = used["INIT"] * initial

            for tag in ("LS", "LE", "EE"):
                if tag in parts:
                    score += used[tag] * parts[tag]

            return score / denom if denom else initial

        def prob_score_multiplicative(initial, parts):
            score = initial
            for tag in ("LS", "LE", "EE"):
                if tag in parts:
                    score *= parts[tag]
            return score

        def extract_percentage_value(percentages):
            """
            percentages is always a list.
            Returns the highest normalized value from the list, from 0.0 to 1.0.
            """
            if not percentages:
                return 0.0

            normalized = []
            for value in percentages:
                if isinstance(value, str):
                    value = value.strip().replace("%", "")

                pct = _safe_float(value, 0.0)

                # normalize 32 -> 0.32
                if pct > 1.0:
                    pct /= 100.0

                pct = max(0.0, min(pct, 1.0))
                normalized.append(pct)

            return max(normalized) if normalized else 0.0

        def get_type_multiplier(action_type):
            if not isinstance(action_type, str):
                return 1.0

            action_type = action_type.strip().lower()

            if action_type == "weapon":
                return 0.95

            if action_type == "monaction":
                return 1.0

            if action_type == "basic":
                return 0.2

            # Expected format: "Lvl # Spell"
            # Using lower() per your request
            if action_type.startswith("lvl ") and action_type.endswith(" spell"):
                middle = action_type[4:-6].strip()  # text between "lvl " and " spell"
                level = int(middle)

                if level in (0, 1, 2):
                    return 0.97

                # exponential ramp starting at level 3
                # 3 -> 1.03
                # 4 -> 1.06
                # 5 -> 1.12
                # 6 -> 1.24
                # 7 -> 1.48
                # 8 -> 1.96
                # 9 -> 2.92
                return 1.03 + (0.03 * ((2 ** (level - 3)) - 1))

            return 1.0

        def get_percentage_multiplier(pct):
            """
            pct is normalized 0.0 - 1.0
            25%+ gets a meaningful bump.
            """
            if pct >= 0.75:
                return 2.00
            if pct >= 0.50:
                return 1.65
            if pct >= 0.25:
                return 1.35
            if pct >= 0.10:
                return 1.12
            return 1.00 + (pct * 0.20)

        def prepare_actions_for_ranking(actions, score_mode="weighted"):
            out = []

            for a in actions:
                x = dict(a)
                x["probDisplay"] = a["prob"]

                init, parts = parse_prob_segments(a["prob"])
                x["probInit"] = init
                x["probParts"] = parts

                if score_mode == "weighted":
                    x["prob"] = prob_score_weighted(init, parts)
                else:
                    x["prob"] = prob_score_multiplicative(init, parts)

                if float(x["prob"]) < 0:
                    x["prob"] = 0.0
                    x["probDisplay"] = 0.0
                elif float(x["prob"]) > 1.0:
                    x["prob"] = 1.0
                    x["probDisplay"] = 1.0

                rawEDam = _safe_float(x.get("eDam"), 0.0)
                rawImpact = _safe_float(x.get("impact"), 0.0)

                pct = extract_percentage_value(x.get("percentages", []))
                typeMult = get_type_multiplier(x.get("type"))
                pctMult = get_percentage_multiplier(pct)

                x["eDam"] = rawEDam
                x["impact"] = rawImpact
                x["percentageValue"] = pct
                x["typeMultiplier"] = typeMult
                x["percentageMultiplier"] = pctMult

                # Heavier emphasis on damage-based chunking
                x["rankEDam"] = rawEDam * typeMult * pctMult

                # Impact adjusted too, but less aggressively
                x["rankImpact"] = rawImpact * ((typeMult * 0.75) + (pctMult * 0.25))

                out.append(x)

            return out

        def pareto_front_set(actions, keys=KEYS):
            front_ids = set()
            for a in actions:
                dominated = False
                for b in actions:
                    if a is b:
                        continue
                    ge_all = all(b[k] >= a[k] for k in keys)
                    gt_any = any(b[k] > a[k] for k in keys)
                    if ge_all and gt_any:
                        dominated = True
                        break
                if not dominated:
                    front_ids.add(id(a))
            return front_ids

        def topsis_scores_minmax(actions, keys=KEYS, weights=None, eps=1e-12):
            if not actions:
                return {}

            if weights is None:
                weights = {k: 1.0 for k in keys}

            mins = {k: min(a[k] for a in actions) for k in keys}
            maxs = {k: max(a[k] for a in actions) for k in keys}

            norm_rows = []
            for a in actions:
                row = {}
                for k in keys:
                    rng = maxs[k] - mins[k]
                    if abs(rng) < eps:
                        v = 0.0
                    else:
                        v = (a[k] - mins[k]) / (rng + eps)
                    row[k] = v * weights[k]
                norm_rows.append((a, row))

            ideal_best = {k: max(r[k] for _, r in norm_rows) for k in keys}
            ideal_worst = {k: min(r[k] for _, r in norm_rows) for k in keys}

            scores = {}
            for a, r in norm_rows:
                d_pos = math.sqrt(sum((r[k] - ideal_best[k]) ** 2 for k in keys))
                d_neg = math.sqrt(sum((r[k] - ideal_worst[k]) ** 2 for k in keys))
                scores[id(a)] = d_neg / (d_pos + d_neg + eps)

            return scores

        def rank_all_actions(actions, weights=None):
            front_ids = pareto_front_set(actions)
            scores = topsis_scores_minmax(actions, weights=weights)

            enriched = []
            for a in actions:
                x = dict(a)
                x["pareto"] = id(a) in front_ids
                x["topsis"] = scores.get(id(a), 0.0)
                enriched.append(x)

            enriched.sort(key=lambda x: (x["pareto"], x["topsis"]), reverse=True)

            for i, x in enumerate(enriched, start=1):
                x["overallRank"] = i

            return enriched

        overallRankings = prepare_actions_for_ranking(actions)
        overallRankings = rank_all_actions(
            overallRankings,
            weights={
                "prob": 1.0,
                "rankEDam": 1.35,
                "rankImpact": 1.25,
            },
        )

        for action in overallRankings:
            if "target" in action and action["target"]:
                if "targetsHit" in action["target"]:
                    for i, t in enumerate(action["target"]["targetsHit"]):
                        action["target"]["targetsHit"][i] = t.getName() if not isinstance(t, str) else t
                else:
                    for i, t in enumerate(action["target"]):
                        action["target"][i] = t.getName() if not isinstance(t, str) else t
        return overallRankings

    prepared = []

    rankings = getBaseRankings()
    prepared = []
    total_actions = len(rankings)

    for action in rankings:
        row = dict(action)

        row["base_rank"] = int(action["overallRank"])

        # Higher is better for ML + final sorting
        row["base_weight"] = float(total_actions - row["base_rank"] + 1)

        row["prob"] = max(0.0, min(1.0, float(row["prob"])))
        row["eDam"] = float(row["eDam"])
        row["impact"] = float(row["impact"])

        row["ml_weight"] = None
        row["final_weight"] = row["base_weight"]

        if (
            use_ml
            and actor is not None
            and encounter_id is not None
            and row.get("action_obj") is not None
        ):
            try:
                ml_weight, ml_record = _score_action_with_ml(
                    actor=actor,
                    action_obj=row["action_obj"],
                    targets=row.get("target", []),
                    encounter_id=encounter_id,
                    prob=row["prob"],
                    expected_damage=row["eDam"],
                    impact=row["impact"],
                    base_weight=row["base_weight"],
                )
                row["ml_weight"] = ml_weight
                row["ml_record"] = ml_record
                row["final_weight"] = ml_weight
            except Exception as exc:
                print(f"[rankActions] ML scoring failed for {row.get('name')}: {exc}")

        prepared.append(row)

    prepared.sort(key=lambda x: x["final_weight"], reverse=True)

    for i, action in enumerate(prepared, start=1):
        action["overallRank"] = i

    for action in prepared:
        if "target" in action and action["target"]:
            if isinstance(action["target"], list):
                new_targets = []
                for t in action["target"]:
                    if isinstance(t, str):
                        new_targets.append(t)
                    elif hasattr(t, "getName"):
                        new_targets.append(t.getName())
                    else:
                        new_targets.append(t)
                action["target"] = new_targets
            elif isinstance(action["target"], dict) and "targetsHit" in action["target"]:
                fixed = []
                for t in action["target"]["targetsHit"]:
                    if isinstance(t, str):
                        fixed.append(t)
                    elif hasattr(t, "getName"):
                        fixed.append(t.getName())
                    else:
                        fixed.append(t)
                action["target"]["targetsHit"] = fixed

    for action in prepared:
        action.pop("action_obj", None)
        action.pop("ml_record", None)

    return prepared
def actionViabilityCheck(action, activeInitiativeEntry, initiative, isPlayerTurn):
    def spellSlotValidity(spellSlots):
        spellLvl = action.getLvl() - 1
        if spellLvl < 0:
            return True
        else:
            slot = spellSlots[spellLvl]
            if int(slot[0]) > 0:
                return True
            else:
                for i in range(spellLvl + 1, 8):
                    slot = spellSlots[i]
                    if int(slot[0]) > 0:
                        return True
        return False

    creature = activeInitiativeEntry["Statblock"]
    if activeInitiativeEntry["actionResource"] == 0:
        # Bonus actions can be used as actions
        if isinstance(action, Weapon):
            return False
        elif action.getActionCost().lower() == "action":
            return False
    if activeInitiativeEntry["bonusActionResource"] == 0:
        # Actions cannot be used as bonus actions
        if not isinstance(action, Weapon) and action.getActionCost().lower() == "bonus action":
            return False

    if isinstance(action, Spell):
        if isinstance(creature, Player):
            if not spellSlotValidity(creature.getSpellSlots()):
                return False
        else:
            spellInfo = creature.getSpellInfo()
            if spellInfo:
                if "spellSlots" in spellInfo and spellInfo["spellSlots"]:
                    if not spellSlotValidity(spellInfo["spellSlots"]):
                        return False
                else:
                    mSpells = [spell["name"].lower() for spell in spellInfo["spells"]]
                    if action.getName().lower() in mSpells:
                        mSpellIdx = mSpells.index(action.getName().lower())
                        charges = spellInfo["spells"][mSpellIdx]["charges"]
                        if charges.isdigit() and int(charges) < 0:
                            return False
                    else:
                        return False

    if not isinstance(action, Weapon) and action.getNumTarget() == 0:
        return True
    actor_tiles = _normalize_occupied_tiles(activeInitiativeEntry["Statblock"].getPosition())

    others_tiles = []
    for entry in initiative:
        sb = entry.get("Statblock")
        if (sb is None or sb is activeInitiativeEntry["Statblock"]
                or not isValidTarget(action, entry, activeInitiativeEntry["Statblock"].getPosition(), isPlayerTurn)):
            continue
        pos = sb.getPosition() if hasattr(sb, "getPosition") else sb.get("position")
        tiles = _normalize_occupied_tiles(pos)
        if tiles:
            others_tiles.append(tiles)

    if not actor_tiles or not others_tiles:
        return False

    if not isinstance(action, Weapon):
        actionRangeFeet = _as_int_feet(action.getActionRange())
    else:
        actionRangeFeet = 5
    if actionRangeFeet is None:
        return False

    rangeTiles = math.ceil(actionRangeFeet / 5)

    for target_tiles in others_tiles:
        min_d = _min_creature_distance_tiles(actor_tiles, target_tiles)
        if min_d <= rangeTiles:
            return True

    return False
def monsterTurn(creature, initiative, encounter_id=None):
    if endOfEncounter(initiative):
        return {}

    actionNames = []
    actionTypes = []
    actionProbs = []
    actionEDams = []
    actionPercentages = []
    actionImpacts = []
    actionTargets = []
    actionObjects = []
    actions = []

    initEntry = initiative[[i["name"] for i in initiative].index(creature.getName())]

    defineBasicActions(actionNames, actionTypes, actionProbs,
                       actionEDams, actionImpacts, actionTargets,
                       actionObjects, initEntry, initiative, False)
    actionPercentages.extend([0, 0, 0])
    if creature.isCaster():
        monSpells = [creature.getSpell(i) for i in range(creature.getSpellLength())]
        validSpells = []
        for spell in monSpells:
            if "spellData" in spell:
                validSpells.append(spell["spellData"])

        spellList = merge_sort_spells(validSpells)
        spellData = processSpellAnalytics(spellList, initEntry, initiative, False)
        actions.extend(spellData)

    monActions = [creature.getAction(i) for i in range(creature.getActionLength())]
    mInitEntry = initiative[[i["name"].lower() for i in initiative].index(creature.getName().lower())]

    for monAction in monActions:
        if monAction.isBadObj():
            continue

        actionName = monAction.getName()

        if actionViabilityCheck(monAction, mInitEntry, initiative, False):
            try:
                actionProb = 0
                actionEDam = -1

                if monAction.getSelfTarget():
                    actionProb = 1.0
                    actionEDam = 0
                    probTargets = [creature.getName()]
                    probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                    actionImpact = calcImpact(creature, monAction, actionProb,
                                              actionEDam, probTargetsNorm, initiative)
                    target = probTargets
                else:
                    if monAction.getRollType().lower() == "tohit":
                        actionProb = calcTotalToHitProbability(creature, monAction, initiative)
                    elif monAction.getRollType().lower() == "save":
                            actionProb = calcTotalSaveProbability(creature, monAction, initiative)
                    if isinstance(actionProb, dict):
                        actionProb["probSuccess"] = 0 if actionProb["probSuccess"] < 0 else actionProb["probSuccess"]
                        actionProb["probSuccess"] = 1 if actionProb["probSuccess"] > 1 else actionProb["probSuccess"]
                        probToStr = f"{actionProb['probSuccess']}" if actionProb['probSuccess'] else f"0.0"
                        probToStr += f" - {actionProb['probLingEffect']}LE" if actionProb['probLingEffect'] else ""
                        probToStr += f" - {actionProb['probExtraEffect']}EE" if actionProb['probExtraEffect'] else ""
                        probToStr += f" - {actionProb['probLingSaves']}LS" if actionProb['probLingSaves'] else ""
                        probTargets = actionProb["target"] if actionProb["probSuccess"] != 0 else ""
                    else:
                        actionProb = 0 if actionProb < 0 else actionProb
                        actionProb = 1 if actionProb > 1 else actionProb
                        probTargets = ""
                        probToStr = actionProb

                    actionProb = probToStr
                    actionEDam, eTargets = calcTotalExpectedDamage(creature,
                                                                  monAction, initiative) if actionEDam == -1 else actionEDam

                    if not probTargets and not eTargets:
                        continue

                    probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                    eTargetsNorm = normalizeTargetSets(eTargets, initiative)

                    if {target.getName() for target in probTargetsNorm} == {target.getName() for target in eTargetsNorm}:
                        actionImpact = calcImpact(creature, monAction, actionProb, actionEDam, probTargetsNorm, initiative)
                        target = probTargets
                    else:
                        if not probTargetsNorm and not eTargetsNorm:
                            actionImpact = 0
                            target = {}
                        elif not probTargetsNorm:
                            actionImpact = calcImpact(creature, monAction, actionProb,
                                                  actionEDam, eTargetsNorm, initiative)
                            target = eTargets
                        elif not eTargetsNorm:
                            actionImpact = calcImpact(creature, monAction, actionProb,
                                                  actionEDam, probTargetsNorm, initiative)
                            target = probTargets
                        else:
                            actionImpact1 = calcImpact(creature, monAction, actionProb, actionEDam, probTargetsNorm, initiative)
                            actionImpact2 = calcImpact(creature, monAction, actionProb, actionEDam, eTargetsNorm, initiative)
                            actionImpact = max([actionImpact1, actionImpact2])
                            targetIdx = [actionImpact1, actionImpact2].index(actionImpact)
                            target = probTargets if targetIdx == 0 else eTargets

                actionNames.append(actionName)
                actionTypes.append("monAction")
                actionProbs.append(actionProb)
                actionEDams.append(actionEDam)
                actionImpacts.append(actionImpact)
                actionTargets.append(target)
                actionObjects.append(monAction)
                if isinstance(target, list):
                    percentages = []
                    for i, t in enumerate(target):
                        hp = t.getHP()
                        if isinstance(actionEDam, list):
                            percentages.append(round(actionEDam[i] / hp, 2))
                        else:
                            percentages.append(round(actionEDam / hp, 2))
                    actionPercentages.append(percentages)
                elif isinstance(target, dict):
                    if "targetsHit" in target:
                        percentages = []
                        for i, t in enumerate(target["targetsHit"]):
                            hp = t.getHP()
                            if isinstance(actionEDam, list):
                                percentages.append(round(actionEDam[i] / hp, 2))
                            else:
                                percentages.append(round(actionEDam / hp, 2))
                        actionPercentages.append(percentages)
                else:
                    hp = target.getHP()
                    if isinstance(actionEDam, list):
                        actionPercentages.append(round(actionEDam[i] / hp, 2))
                    else:
                        actionPercentages.append(round(actionEDam / hp, 2))
            except TypeError:
                continue

    actions.extend(
        [{"name": actionNames[i], "type" : actionTypes[i], "prob": actionProbs[i], "eDam": actionEDams[i],
          "percentages" : actionPercentages[i], "action_obj" : actionObjects[i],
          "impact": actionImpacts[i], "target" : actionTargets[i]}
         for i in range(len(actionNames))])
    return rankActions(
        actions,
        actor=creature,
        encounter_id=encounter_id,
        use_ml=True
    )

def playerTurn(player, initiative, encounter_id=None):
    def translateClassAbilities():
        pass

    if endOfEncounter(initiative):
        return {}

    actionNames = []
    actionTypes = []
    actionProbs = []
    actionEDams = []
    actionPercentages = []
    actionImpacts = []
    actionTargets = []
    actionObjects = []
    pInitEntry = initiative[[i["name"].lower() for i in initiative].index(player.getName().lower())]

    defineBasicActions(actionNames, actionTypes, actionProbs,
                       actionEDams, actionImpacts, actionTargets,
                       actionObjects, pInitEntry,initiative, True)
    actionPercentages.extend([0, 0, 0])
    if player.getWeaponLength() > 0:
        for i in range(player.getWeaponLength()):
            weapon = player.getWeapon(i)

            if actionViabilityCheck(weapon, pInitEntry, initiative, True):
                weaponProb = calcTotalToHitProbability(player, weapon, initiative)
                if isinstance(weaponProb, dict):
                    probTargets = weaponProb["target"]
                    weaponProb = weaponProb["probSuccess"]
                else:
                    try:
                        weaponProb = int(weaponProb)
                        probTargets = {}
                    except Exception:
                        weaponProb = 0
                        probTargets = {}

                weaponEDam, eTargets = calcTotalExpectedDamage(player, weapon, initiative)
                probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                eTargetsNorm = normalizeTargetSets(eTargets, initiative)

                if probTargetsNorm == eTargetsNorm:
                    weaponImpact = calcImpact(player, weapon, weaponProb, weaponEDam, probTargetsNorm, initiative)
                    target = probTargets
                else:
                    if not probTargetsNorm and not eTargetsNorm:
                        weaponImpact = 0
                        target = {}
                    elif not probTargetsNorm:
                        weaponImpact = calcImpact(player, weapon, weaponProb, weaponEDam, eTargetsNorm, initiative)
                        target = eTargets
                    elif not eTargetsNorm:
                        weaponImpact = calcImpact(player, weapon, weaponProb, weaponEDam, probTargetsNorm, initiative)
                        target = probTargets
                    else:
                        weaponImpact1 = calcImpact(player, weapon, weaponProb, weaponEDam, probTargetsNorm, initiative)
                        weaponImpact2 = calcImpact(player, weapon, weaponProb, weaponEDam, eTargetsNorm, initiative)
                        weaponImpact = max([weaponImpact1, weaponImpact2])
                        targetIdx = [weaponImpact1, weaponImpact2].index(weaponImpact)
                        target = probTargets if targetIdx == 0 else eTargets

                if player.getClass().lower() in ["barbarian", "paladin", "ranger"]:
                    weaponEDam += weaponEDam
                    weaponImpact += weaponImpact
                elif player.getClass().lower() in ["fighter"]:
                    weaponEDam *= player.getExtraAttackAmt()
                    weaponImpact *= player.getExtraAttackAmt()

                actionNames.append(weapon.getName())
                actionTypes.append("Weapon")
                actionProbs.append(weaponProb)
                actionEDams.append(weaponEDam)
                actionImpacts.append(weaponImpact)
                actionTargets.append(target)
                actionObjects.append(weapon)
                if isinstance(target, list):
                    percentages = []
                    for i, t in enumerate(target):
                        hp = t.getHP()
                        if isinstance(weaponEDam, list):
                            percentages.append(round(weaponEDam[i] / hp, 2))
                        else:
                            percentages.append(round(weaponEDam / hp, 2))
                    actionPercentages.append(percentages)
                elif isinstance(target, dict):
                    if "targetsHit" in target:
                        percentages = []
                        for i, t in enumerate(target["targetsHit"]):
                            hp = t.getHP()
                            if isinstance(weaponEDam, list):
                                percentages.append(round(weaponEDam[i] / hp, 2))
                            else:
                                percentages.append(round(weaponEDam / hp, 2))
                        actionPercentages.append(percentages)
                else:
                    hp = target.getHP()
                    if isinstance(weaponEDam, list):
                        actionPercentages.append(round(weaponEDam[i] / hp, 2))
                    else:
                        actionPercentages.append(round(weaponEDam / hp, 2))

    actions = [{"name": actionNames[i], "type" : actionTypes[i], "prob": actionProbs[i], "eDam": actionEDams[i],
                "percentages" : actionPercentages[i], "action_obj" : actionObjs[i],
                "impact": actionImpacts[i], "target" : actionTargets[i]} for
               i in range(len(actionNames))]
    if player.getSpellLength() > 0:
        spellList = [player.getSpell(i) for i in range(player.getSpellLength())]
        spellList = merge_sort_spells(spellList)
        spellActions = processSpellAnalytics(spellList, pInitEntry, initiative, True)
        actions.extend(spellActions)

    return rankActions(
        actions,
        actor=player,
        encounter_id=encounter_id,
        use_ml=True,
    )

def setActiveInitiative(encounter):
    initiative = copy.deepcopy(encounter.getInitiative())
    todeli = -1
    for ci, creature in enumerate(initiative):
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
        elif creature["turnType"].lower() == "lairaction":
            todeli = ci
            continue
    if todeli != -1:
        del initiative[todeli]
    return initiative

#MANUAL ENTRIES
def handle_stat_array(creature, values):
    for statName, statValue in values.items():
        creature.updateStat(statName, statValue)
def handle_save_profs(creature, values):
    for profName, profValue in values.items():
        creature.setSaveProf(profName, profValue)
def handle_dam_resistances(creature, damResists):
    creature.setAllDamResistances(damResists)
def handle_dam_immunes(creature, damImmunes):
    creature.setAllDamImmunes(damImmunes)
def handle_dam_vulns(creature, damVulns):
    creature.setAllDamVuls(damVulns)
def handle_con_immunes(creature, conImmuns):
    creature.setAllConImmunes(conImmuns)
def handle_active_conditions(creature, newCons):
    creature.setAllActiveConditions(newCons)
def handle_active_status_effects(creature, newStatus):
    creature.setAllActiveStatusEffects(newStatus)
def handle_hp(creature, value):
    creature.setHP(value)
def handle_position(creature, positions):
    creature.setPosition(positions)
def handle_ac(creature, value):
    creature.setAC(value)
def handle_l_resists(creature, lResists):
    creature.setlResists(lResists)
def handle_spell_slots(creature, values):
    for i, slot in enumerate(values):
        creature.setSpellSlots(i + 1, int(slot[0]))

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
            spell = creature["Statblock"].getSpellByName(action)
            if spell:
                isSpell = True
                action = spell
            if isinstance(creature["Statblock"], Player) and not isSpell:
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
            with open("./CoreEngine/data/basic_actions.json", "r") as br:
                bActions = json.load(br)
            if action.lower() == "grapple":
                action = translateBasicAction(actorObj, bActions[0])
            elif action.lower() == "shove":
                action = translateBasicAction(actorObj, bActions[1])
            else:
                action = translateBasicAction(actorObj, bActions[2])
        else:
            return {}

    if isinstance(action, dict):
        if "spellData" in action:
            action = action["spellData"]

    return actorObj, action, targets, isSpell, selectedTargets

def main():
    async def terminal_test():
        await init_indexes()
        # testEID = "85dbb1a3-8cde-4f89-b515-0b685ac0e251" #TestDemo4
        testEID = "4f9ff0bc-15da-41cd-8723-429e2ec65042" #htgtgtgtht
        # testCID = "c6f1bafd-6c9c-4e85-9a9b-59c38e67340e" #Lich


        testCID = "e5e48c65-2a0c-4ecf-bc1f-57915b335095" #Ancient Brass Dragon
        encounter = await get_encounter_by_eid(testEID)
        encounter = loadEncounter(encounter)

        actionRequest = {
            "resultID": "8144e8eb-4903-47ae-8ac3-d6ed9db24e25",
            "actor": "Ancient Brass Dragon",
            "action": "Bite",
            "actionType": "MonAction",
            "actionProb": 0,
            "actionEDam": 0,
            "actionImpact": 0,
            "targets": [
                "1e90f504-747d-4a21-89c7-807177add357"
            ],
            "conditions": [],
            "statusEffects": [],
            "outcome": {
                "rollResults": [
                    "19"
                ],
                "diceResults": [
                    10
                ]
            },
            "extraOutcome": {
                "extraRollResults": [],
                "extraDiceResults": []
            },
            "timestamp": "23:18:00",
            "token": {}
        }
        # print(encounter)
        # creature = encounter.getPlayerByCID(testCID)
        # creature.addSpell("Moonbeam", 2, False, -1, 300, "save", "CON",
        #                   True, 0, 2, 10, "radiant", [], [{
        #                                                     "name": "Concentration",
        #                                                     "effect": {}
        #                                                  }],
        #                 {"repeat" : True}, {}, {}, "", "action", [], "circle", 5)
        creature = encounter.getMonsterByCID(testCID)
        initiative = setActiveInitiative(encounter)
        mapdata = encounter.getMapData()

        # actorObj, action, targets, isSpell, selectedTargets = unpackEntry(actionRequest, initiative)
        #
        # if not action:
        #     return

        # print(executeAction(actorObj, action,
        #             selectedTargets, actionRequest,
        #                     initiative, mapdata))

        # await saveEncounter(encounter)

        # print(monsterTurn(creature, initiative)) #MONSTER
        # print(playerTurn(creature, initiative)) #PLAYER

        #TODO: Try PA recommendations, check for correctness
        #TODO: Try rulesetSimulate alot, check for correctness.

    asyncio.run(terminal_test())


if __name__ == "__main__":
    main()