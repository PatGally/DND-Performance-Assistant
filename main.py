import asyncio
import copy
import itertools
import json
import math
import os
import re
from collections import deque
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
DEFAULT_PLAYER_MOVEMENT_MAX = 30

# Monster multiattack is stored with the encounter because the current CoreEngine
# Monster model does not consistently expose it across versions.
def normalizeMonsterMultiattack(payload) -> Dict[str, Any]:
    """Normalize the persisted monster multiattack payload.

    ``split`` is the authoritative sequence. ``total`` is normalized to the
    number of attacks represented by the split so stale stat-block data cannot
    create or remove attacks during execution.
    """
    if not isinstance(payload, dict):
        return {}

    raw_split = payload.get("split", [])
    if not isinstance(raw_split, list):
        return {}

    split = []
    for raw_item in raw_split:
        if not isinstance(raw_item, dict):
            continue

        name = str(raw_item.get("name", "")).strip()
        try:
            number = int(raw_item.get("number", 0))
        except (TypeError, ValueError):
            continue

        if not name or number <= 0:
            continue

        split.append({"name": name, "number": number})

    if not split:
        return {}

    total = sum(item["number"] for item in split)
    return {
        "name": str(payload.get("name", "Multiattack")).strip() or "Multiattack",
        "total": total,
        "split": split,
    }


def setMonsterMultiattack(monster, payload) -> Dict[str, Any]:
    """Attach normalized multiattack data without requiring a CoreEngine change."""
    multiattack = normalizeMonsterMultiattack(payload)

    for setter_name in ("setMultiattack", "setMultiAttack"):
        setter = getattr(monster, setter_name, None)
        if callable(setter):
            try:
                setter(copy.deepcopy(multiattack))
                break
            except (AttributeError, TypeError, ValueError):
                continue

    # Always retain an engine-independent copy. Some CoreEngine releases expose
    # a setter without a matching getter/toDict field, which otherwise makes the
    # definition disappear as soon as an encounter is reconstructed or saved.
    setattr(monster, "_dndpa_multiattack", copy.deepcopy(multiattack))
    return multiattack


def getMonsterMultiattack(monster) -> Dict[str, Any]:
    """Read multiattack data from either CoreEngine or the compatibility field."""
    # The compatibility copy is populated directly from the persisted encounter
    # and is therefore the authority when an engine field is stale or absent.
    normalized = normalizeMonsterMultiattack(
        getattr(monster, "_dndpa_multiattack", None)
    )
    if normalized:
        return normalized

    for getter_name in ("getMultiattack", "getMultiAttack"):
        getter = getattr(monster, getter_name, None)
        if callable(getter):
            try:
                value = getter()
            except TypeError:
                continue
            normalized = normalizeMonsterMultiattack(value)
            if normalized:
                return normalized

    for attribute_name in (
        "multiattack",
        "multiAttack",
        "_Monster__multiattack",
        "_Monster__multiAttack",
    ):
        normalized = normalizeMonsterMultiattack(getattr(monster, attribute_name, None))
        if normalized:
            return normalized

    return {}


def getMonsterActionByName(monster, action_name):
    """Return a concrete MonAction using a case-insensitive action name."""
    if not action_name:
        return None

    getter = getattr(monster, "getActionByName", None)
    if callable(getter):
        try:
            action = getter(action_name)
        except (KeyError, TypeError, ValueError):
            action = None

        # A case-sensitive CoreEngine lookup may return a truthy bad-object
        # sentinel for a persisted split such as "bite" when the real action is
        # named "Bite". Do not let that sentinel bypass the fallback below.
        if action:
            is_bad = getattr(action, "isBadObj", None)
            if not callable(is_bad) or not is_bad():
                return action

    wanted = str(action_name).strip().lower()
    for index in range(monster.getActionLength()):
        action = monster.getAction(index)
        if action.getName().strip().lower() == wanted:
            return action

    return None


def expandMonsterMultiattack(multiattack) -> List[str]:
    """Expand a split payload into the exact ordered child-action sequence."""
    normalized = normalizeMonsterMultiattack(multiattack)
    sequence = []
    for item in normalized.get("split", []):
        sequence.extend([item["name"]] * item["number"])
    return sequence


def buildMonsterMultiattackActionPayload(monster) -> Optional[Dict[str, Any]]:
    """Build the synthetic action returned by the creature-actions endpoint."""
    multiattack = getMonsterMultiattack(monster)
    if not multiattack:
        return None

    sequence = []
    for index, action_name in enumerate(expandMonsterMultiattack(multiattack)):
        child_action = getMonsterActionByName(monster, action_name)
        if child_action is None or child_action.isBadObj():
            return None
        sequence.append({
            "index": index,
            "name": child_action.getName(),
            "action": child_action.toDict(),
        })

    sequence_description = ", ".join(
        f'{item["number"]} x {item["name"]}'
        for item in multiattack["split"]
    )

    return {
        "name": multiattack["name"],
        "desc": f"Use one action to perform: {sequence_description}.",
        "number": "0",
        "actionRange": "0",
        "shape": "",
        "rolls": {
            "rollType": "multiattack",
            "saveType": "",
            "halfSave": False,
            "saveDC": 0,
            "damage": "none",
            "attackBonus": "0",
            "damageMod": "0",
        },
        "extraDamage": [],
        "damType": [],
        "conditions": [],
        "statusEffect": [],
        "lingEffect": {},
        "extraEffect": {},
        "lingSave": {},
        "recharge": "",
        "actionCost": "Action",
        "specialNotes": ["Multiattack"],
        "multiattack": {
            **copy.deepcopy(multiattack),
            "sequence": sequence,
        },
    }


def _multiattackProbability(value) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    match = re.match(r"\s*(-?\d*\.?\d+)", str(value))
    if not match:
        return 0.0
    return max(0.0, min(1.0, float(match.group(1))))


def _multiattackNumericTotal(value) -> float:
    if isinstance(value, (list, tuple)):
        return sum(_multiattackNumericTotal(item) for item in value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _multiattackTargetNames(target) -> List[str]:
    names = []

    if target is None:
        return names
    if isinstance(target, str):
        return [target]
    if isinstance(target, (list, tuple)):
        for item in target:
            names.extend(_multiattackTargetNames(item))
        return names
    if isinstance(target, dict):
        if "targetsHit" in target:
            return _multiattackTargetNames(target.get("targetsHit"))
        if "Statblock" in target:
            return _multiattackTargetNames(target.get("Statblock"))
        if "name" in target:
            return [str(target["name"])]
        return names
    if hasattr(target, "getName"):
        return [str(target.getName())]

    return names


def _multiattackTargetObjects(target) -> List[Any]:
    objects = []
    if target is None or isinstance(target, str):
        return objects
    if isinstance(target, (list, tuple)):
        for item in target:
            objects.extend(_multiattackTargetObjects(item))
        return objects
    if isinstance(target, dict):
        if "targetsHit" in target:
            return _multiattackTargetObjects(target.get("targetsHit"))
        if "Statblock" in target:
            statblock = target.get("Statblock")
            return [statblock] if statblock is not None else []
        return objects
    if hasattr(target, "getName"):
        return [target]
    return objects


def buildMonsterMultiattackRecommendation(
    monster,
    analyzed_actions: List[Dict[str, Any]],
    initiative_entry: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Combine child-action analytics into one rankable multiattack option.

    Expected damage and impact are additive. Probability is the mean child
    success probability; expected damage already captures the number of attacks,
    so multiplying every probability would incorrectly suppress multiattack.
    """
    multiattack = getMonsterMultiattack(monster)
    if not multiattack:
        return None
    if initiative_entry is not None and not initiative_entry.get("actionResource", 0):
        return None

    analyzed_by_name = {
        str(action.get("name", "")).strip().lower(): action
        for action in analyzed_actions
        if isinstance(action, dict)
    }

    sequence = []
    probabilities = []
    expected_damage = 0.0
    impact = 0.0
    aggregate_target_objects = []
    aggregate_target_names = []

    for index, configured_name in enumerate(expandMonsterMultiattack(multiattack)):
        child = analyzed_by_name.get(configured_name.strip().lower())
        child_action = getMonsterActionByName(monster, configured_name)
        if child is None or child_action is None:
            # A multiattack is only viable when every required child is viable.
            return None

        child_probability = _multiattackProbability(child.get("prob", 0.0))
        child_damage = _multiattackNumericTotal(child.get("eDam", 0.0))
        child_impact = _multiattackNumericTotal(child.get("impact", 0.0))
        child_target_names = _multiattackTargetNames(child.get("target"))

        probabilities.append(child_probability)
        expected_damage += child_damage
        impact += child_impact
        aggregate_target_objects.extend(_multiattackTargetObjects(child.get("target")))
        aggregate_target_names.extend(child_target_names)

        sequence.append({
            "index": index,
            "name": child_action.getName(),
            "action": child_action.toDict(),
            "target": child_target_names,
            "prob": child_probability,
            "eDam": child_damage,
            "impact": child_impact,
        })

    unique_objects = []
    seen_object_names = set()
    for target in aggregate_target_objects:
        target_name = str(target.getName()).lower()
        if target_name in seen_object_names:
            continue
        seen_object_names.add(target_name)
        unique_objects.append(target)

    unique_target_names = []
    seen_names = set()
    for name in aggregate_target_names:
        normalized_name = str(name).strip().lower()
        if not normalized_name or normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        unique_target_names.append(str(name))

    aggregate_target = unique_objects if unique_objects else unique_target_names
    probability = sum(probabilities) / len(probabilities) if probabilities else 0.0

    return {
        "name": multiattack["name"],
        "type": "Multiattack",
        "prob": probability,
        "eDam": expected_damage,
        "percentage": [],
        "percentages": [],
        "impact": impact,
        "actions": None,
        "target": aggregate_target,
        "multiattack": {
            **copy.deepcopy(multiattack),
            "sequence": sequence,
        },
    }

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
    movementMax = int(stats.get("movementMax", DEFAULT_PLAYER_MOVEMENT_MAX))

    spellSlots = stats["spellSlots"]

    playerdata = [playerName, playerStats, saveProfs, playerAC, playerHP, class_type, playerLvl, conImmunes, damImmunes,
                  damResists, damVulns, activeStatusEffects, activeConditions, cid, position, spellSlots]
    player = getClassStats(data, playerdata, class_type)
    player.setMovementMax(movementMax)
    return player
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
        "movementMax": player.getMovementMax(),
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
        class_fields["actionSurgeCharges"] = player.getActionSurgeCharges()
        class_fields["extraAttackAmt"] = player.getExtraAttackAmt()

    elif cls == "barbarian":
        class_fields["rageCharges"] = player.getRageCharges()
        class_fields["isRaging"] = player.isRaging()

    elif cls == "bard":
        class_fields["bardicCharges"] = player.getBardicCharges()
        class_fields["bardicDieType"] = player.getBardicDieType()
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
        monster = encounter.getMonster(i)
        monster_dict = monster.toDict()
        multiattack = getMonsterMultiattack(monster)
        if multiattack:
            monster_dict["multiattack"] = copy.deepcopy(multiattack)
        monster_list.append(monster_dict)

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
            "movementMax": player.getMovementMax(),
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
                        "cols": int((mapData.get("grid", {}).get("cellBounds", {}).get("cols", mapData.get("grid", {}).get("cellBounds", {}).get("col", 0))) or 0),
                        "rows": int((mapData.get("grid", {}).get("cellBounds", {}).get("rows", mapData.get("grid", {}).get("cellBounds", {}).get("row", 0))) or 0)
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
        "initiative": encounter.getInitiative()
    }

    try:
        await upsert_encounter_dict(encounter_dict)
    except PyMongoError as err:
        raise err
def loadEncounter(encounterData):
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
        movementMax = monsterJSON.get("movementMax", DEFAULT_PLAYER_MOVEMENT_MAX)
        monsterObj = Monster(name, cr, cType, stats, hp, maxHP,
                             ac, saveProfs, lResists, damResists,
                             damImmunes, damVulns, conImmunes, activeConditions,
                             activeStatusEffects, lairAction, magicResist,
                             enemy, actions, spellInfo, legActions,
                             cid, position, size, movementMax)

        # Multiattack is persisted beside the monster stat block because not
        # every CoreEngine Monster version serializes it. Reattach it whenever
        # an encounter is reconstructed so the actions and recommendation
        # endpoints can build their synthetic Multiattack entries.
        setMonsterMultiattack(monsterObj, monsterJSON.get("multiattack", {}))
        encounter.addMonster(monsterObj)
    for resultJSON in encounterData["results"]:
        encounter.addResult(resultJSON)

    encounter.setInitiative(encounterData.get("initiative"))
    return encounter

# GENERAL HELPER METHODS
def getCreatureFromInitiativeEntry(encounter, entry):
    cid = str(entry.get("cid", ""))
    if not cid:
        return None

    turn_type = str(entry.get("turnType", "")).lower()
    if turn_type == "player":
        return encounter.getPlayerByCID(cid)
    if turn_type == "monster":
        return encounter.getMonsterByCID(cid)

    creature = encounter.getPlayerByCID(cid)
    return creature if creature else encounter.getMonsterByCID(cid)
def findInitiativeEntryByCID(creature, initiative):
    creature_cid = str(creature.getCID())
    for entry in initiative:
        if str(entry.get("cid", "")) == creature_cid:
            return entry
    raise ValueError(f"Creature {creature_cid} not found in initiative.")
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
def min_creature_distance_tiles(tiles_a, tiles_b):
    def _chebyshev_tiles(p1, p2):
        # diagonal counts as 1 tile
        return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1]))
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
def shortest_movement_distance_tiles(start_tiles, target_tiles, blocking_positions, max_tiles, rows=-1, cols=-1):
    def _state(tiles):
        normalized = _normalize_occupied_tiles(tiles)
        return tuple(sorted((int(p[0]), int(p[1])) for p in normalized))
    def _valid(state):
        if rows != -1 and cols != -1:
            return all(0 <= x < cols and 0 <= y < rows and (x, y) not in blocked for x, y in state)
        else:
            return all((x, y) not in blocked for x, y in state)

    start = _state(start_tiles)
    target = _state(target_tiles)
    max_tiles = int(max_tiles)
    blocked = set()
    directions = [
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),           (1, 0),
        (-1, 1),  (0, 1),  (1, 1)
    ]

    for positions in blocking_positions or []:
        blocked.update(tuple(tile) for tile in _normalize_occupied_tiles(positions))

    if not start or not target or len(start) != len(target) or max_tiles < 0:
        return math.inf
    if not _valid(start) or not _valid(target):
        return math.inf
    if start == target:
        return 0

    queue = deque([(start, 0)])
    visited = {start}
    while queue:
        state, distance = queue.popleft()
        if distance >= max_tiles:
            continue
        for dx, dy in directions:
            next_state = tuple(sorted((x + dx, y + dy) for x, y in state))
            if next_state in visited or not _valid(next_state):
                continue
            if next_state == target:
                return distance + 1
            visited.add(next_state)
            queue.append((next_state, distance + 1))

    return math.inf
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
    elif isinstance(targets, dict) and "cid" in targets:
        targets = [targets["cid"]]
    elif isinstance(targets, Player) or isinstance(targets, Monster):
        targets = [targets]
    for i, target in enumerate(targets):
        if isinstance(target, str):
            for creature in initiative:
                if creature["cid"] == target:
                    targets[i] = copy.deepcopy(creature["Statblock"])
                    break
        elif isinstance(target, dict):
            if "cid" in target and "targetScore" in target:
                for creature in initiative:
                    if creature["cid"] == target["cid"]:
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
    actionNames, actionTypes, actionProbs, actionEDams, actionImpacts, actionTargets,
    actionMovementReccs, actionObjs, initEntry, initiative, isPlayerTurn,
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
        grappleMovementRecc = grappleProb.get("movementRecc", [])

        probToStr = f"{grappleProb['probSuccess']}"
        probToStr += f" - {grappleProb['probLingEffect']}LE" if grappleProb["probLingEffect"] else ""
        probToStr += f" - {grappleProb['probExtraEffect']}EE" if grappleProb["probExtraEffect"] else ""
        probToStr += f" - {grappleProb['probLingSave']}LS" if grappleProb["probLingSave"] else ""

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
        actionMovementReccs.append(grappleMovementRecc)
        actionObjs.append(grapple)

    if actionViabilityCheck(shove, initEntry, initiative, isPlayerTurn):
        shoveProb = calcTotalSaveProbability(creature, shove, initiative)
        shoveProb["probSuccess"] = 0 if shoveProb["probSuccess"] < 0 else shoveProb["probSuccess"]
        shoveProb["probSuccess"] = 1 if shoveProb["probSuccess"] > 1 else shoveProb["probSuccess"]
        shoveMovementRecc = shoveProb.get("movementRecc", [])

        probToStr = f"{shoveProb['probSuccess']}"
        probToStr += f" - {shoveProb['probLingEffect']}LE" if shoveProb["probLingEffect"] else ""
        probToStr += f" - {shoveProb['probExtraEffect']}EE" if shoveProb["probExtraEffect"] else ""
        probToStr += f" - {shoveProb['probLingSave']}LS" if shoveProb["probLingSave"] else ""

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
        actionMovementReccs.append(shoveMovementRecc)
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
        actionMovementReccs.append([])
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
    action_level = action.getLvl() if hasattr(action, "getLvl") else 0

    lingSpell = Spell(
        action.getName(), action_level, action.getSelfTarget(), numTarget,
        action.getActionRange(), lingEffect["rolls"]["rollType"], lingEffect["rolls"]["saveType"],
        lingEffect["rolls"]["halfSave"],
        damMod, lingDieNum, lingDieType, lingDamType,
        conditions, statusEffect, {}, {}, {}, "", "",
        specialNotes, action.getShape(), action.getActionRadius()
    )
    return lingSpell
def calcLingeringEffectProbability(player, target, action, lingEffect, successProb):
    # 1. Repeat check
    if isinstance(action, Weapon):
        return 0
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
    if isinstance(spell, Weapon):
        return 0
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
        if isValidTarget(action, creature, player,isPlayerTurn):
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
def isValidTarget(action, creature, actor, isPlayerTurn=True):
    validTarget = False
    if isPlayerTurn:
        if isinstance(action, Weapon) or ((isinstance(action, Spell) or isinstance(action, MonAction)) and action.getDamType() != "healing"):
            if (creature["turnType"] == "Monster"
                    and not creature["Statblock"].isActiveStatusEffect("SwitchSides")
                    and not creature["Statblock"].isActiveCondition("Dead")
                    and not creature["Statblock"].isActiveCondition("Out of Combat")):
                validTarget = True
            else:
                validTarget = False
        elif action.getDamType() == "healing" or "healing" in action.getDamType():
            if (creature["turnType"] == "Player"
                    or (creature["turnType"] == "Monster" and creature["Statblock"].isActiveStatusEffect("SwitchSides"))
                    and not creature["Statblock"].isActiveCondition("Dead")
                    and not creature["Statblock"].isActiveCondition("Out of Combat")):
                if (action.getSpecialNotes()
                        and any([("only" in note.lower() or "immune" in note.lower()) for note in action.getSpecialNotes()])):
                    for note in action.getSpecialNotes():
                        if "only" in note.lower():
                            if creature["Statblock"].getCreatureType().lower() == note.lower().split("only")[0]:
                                validTarget = True
                                break
                            else:
                                validTarget = False
                                break
                        elif "immune" in note.lower():
                            if creature["Statblock"].getCreatureType().lower() == note.lower().split("immune")[0]:
                                validTarget = False
                                break
                            else:
                                validTarget = True
                                break
                else:
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
                if (action.getSpecialNotes()
                        and any([("humanoidimmune" in note.lower()) for note in
                                 action.getSpecialNotes()])):
                    for note in action.getSpecialNotes():
                        if "humanoidimmune" in note.lower():
                            validTarget = False
                            break
                else:
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
    actor_tiles = _normalize_occupied_tiles(actor.getStartingAnchor())
    if not isinstance(action, Weapon):
        actionRangeFeet = _as_int_feet(action.getActionRange()) + _as_int_feet(actor.getMovementMax())
    else:
        actionRangeFeet = 5 + _as_int_feet(actor.getMovementMax())
    if actionRangeFeet is None:
        return False
    rangeTiles = math.ceil(actionRangeFeet // 5)
    others_tiles = [creature.getPosition()]
    for target_tiles in others_tiles:
        min_d = min_creature_distance_tiles(actor_tiles, target_tiles)
        if min_d <= rangeTiles:
            return True
    return False
def ensureList(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


_DURATION_WORD_VALUES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_DURATION_AMOUNT = r"(?P<amount>\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
_DURATION_PATTERNS = (
    # Existing data often uses compact values such as "1Turn" or "2Turns".
    (re.compile(rf"(?<!\w){_DURATION_AMOUNT}\s*turns?\b", re.IGNORECASE), 1),
    (re.compile(rf"(?<!\w){_DURATION_AMOUNT}\s*rounds?\b", re.IGNORECASE), 1),
    # One D&D combat round is six seconds, so one minute is ten rounds.
    (re.compile(rf"(?<!\w){_DURATION_AMOUNT}\s*minutes?\b", re.IGNORECASE), 10),
)


def _durationAmount(match) -> int:
    raw_amount = str(match.group("amount")).strip().lower()
    if raw_amount.isdigit():
        return int(raw_amount)
    return _DURATION_WORD_VALUES.get(raw_amount, 0)


def _durationTextsFromPayload(payload) -> List[str]:
    """Read duration text from structured lingering/extra-effect payloads."""
    if payload in (None, "", {}, []):
        return []

    if isinstance(payload, str):
        return [payload]

    if isinstance(payload, (list, tuple)):
        texts = []
        for item in payload:
            texts.extend(_durationTextsFromPayload(item))
        return texts

    if not isinstance(payload, dict):
        return []

    texts = []
    special_notes = payload.get("specialNotes", payload.get("special_notes"))
    texts.extend(_durationTextsFromPayload(special_notes))

    for key in ("duration", "desc", "description"):
        value = payload.get(key)
        if value not in (None, ""):
            texts.append(str(value))

    for key in ("turnCount", "turnCap"):
        value = payload.get(key)
        try:
            numeric_value = int(value)
        except (TypeError, ValueError):
            continue
        if numeric_value > 0:
            texts.append(f"{numeric_value}Turn")

    return texts


def _getActionDurationTexts(action) -> List[str]:
    """Return duration-bearing action text in priority order.

    Structured special notes are checked first. Monster actions such as
    Frightful Presence frequently keep their duration only in ``desc``, so the
    action description is also inspected.
    """
    if action is None:
        return []

    texts = []

    special_notes_getter = getattr(action, "getSpecialNotes", None)
    if callable(special_notes_getter):
        try:
            special_notes = special_notes_getter() or []
        except Exception:
            special_notes = []

        if isinstance(special_notes, str):
            special_notes = [special_notes]

        if isinstance(special_notes, (list, tuple)):
            texts.extend(str(note) for note in special_notes if note not in (None, ""))

    for getter_name in ("getDesc", "getDescription"):
        getter = getattr(action, getter_name, None)
        if not callable(getter):
            continue
        try:
            description = getter()
        except Exception:
            continue
        if description not in (None, ""):
            texts.append(str(description))

    to_dict = getattr(action, "toDict", None)
    if callable(to_dict):
        try:
            action_dict = to_dict()
        except Exception:
            action_dict = None

        if isinstance(action_dict, dict):
            for key in ("desc", "description"):
                description = action_dict.get(key)
                if description not in (None, ""):
                    texts.append(str(description))

            for key in (
                "lingEffect",
                "lingSave",
                "extraEffect",
                "lingEffects",
                "lingSaves",
            ):
                texts.extend(_durationTextsFromPayload(action_dict.get(key)))

    for getter_name in ("getLingEffects", "getLingSaves", "getExtraEffect"):
        getter = getattr(action, getter_name, None)
        if not callable(getter):
            continue
        try:
            payload = getter()
        except Exception:
            continue
        texts.extend(_durationTextsFromPayload(payload))

    # Preserve priority while avoiding repeated parsing of the same text.
    unique_texts = []
    seen = set()
    for text in texts:
        normalized = text.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_texts.append(normalized)

    return unique_texts


def getTurnCapFromSpecialNotes(action) -> Optional[int]:
    """Convert an action duration to affected-creature turns.

    Supported forms include ``1Turn``, ``2 rounds``, and ``1 minute``. Since
    D&D combat rounds last six seconds, each minute is converted to 10 rounds.
    """
    for text in _getActionDurationTexts(action):
        matches = []

        for pattern, multiplier in _DURATION_PATTERNS:
            for match in pattern.finditer(text):
                amount = _durationAmount(match)
                if amount > 0:
                    matches.append((match.start(), amount * multiplier))

        if matches:
            # Use the first duration mentioned in this prioritized text. This
            # correctly selects "frightened for 1 minute" before later text
            # such as immunity lasting 24 hours.
            matches.sort(key=lambda item: item[0])
            return matches[0][1]

    return None
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
    currentCasterCells: List[List[int]],
    movementMax: int,
    originMode : str = "placed"
):
    result = bestAoePositioningDebug(
        rangeFt=rangeFt,
        radiusFt=radiusFt,
        shape=shape,
        allCreaturePositions=allCreaturePositions,
        allTargets=allTargets,
        casterCells=casterCells,
        currentCasterCells=currentCasterCells,
        movementMax=movementMax,
        originMode=originMode
    )
    return {"targetsHit" : result["targetsHit"],
            "positioning" : [[x, y] for x, y in result["coveredCells"]],
            "movementRecc" : result["movementRecc"]}
def getOrientedTemplateMasks(
        shapeKind: str,
        sizeCells: int,
        lineWidthCells: Optional[int] = None,
) -> List[Tuple[str, Set[Coord]]]:

    def squareMaskLookup(sideCells: int) -> Set[Coord]:
        # Anchor is top-left.
        return {(dx, dy) for dx in range(sideCells) for dy in range(sideCells)}
    def cardinalLineMaskLookup(
            orientation: str,
            lengthCells: int,
            widthCells: int,
    ) -> Set[Coord]:
        mask = set()

        if orientation == "up":
            for step in range(lengthCells):
                y = -step
                for x in range(0, widthCells):
                    mask.add((x, y))
            return mask

        if orientation == "right":
            for step in range(lengthCells):
                x = step
                for y in range(0, widthCells):
                    mask.add((x, y))
            return mask

        if orientation == "down":
            for step in range(lengthCells):
                y = step
                for x in range(0, widthCells):
                    mask.add((x, y))
            return mask

        if orientation == "left":
            for step in range(lengthCells):
                x = -step
                for y in range(0, widthCells):
                    mask.add((x, y))
            return mask

        raise ValueError(f"Unsupported cardinal orientation: {orientation}")
    def diagonalLineMaskLookup(lengthCells: int, widthCells: int) -> Set[Coord]:
        mask = set()

        for step in range(lengthCells):
            # main slice
            for offset in range(widthCells):
                mask.add((step + offset, -step))

            # bridge into the next diagonal step so the ribbon stays continuous
            if step < lengthCells - 1:
                for offset in range(widthCells):
                    mask.add((step + offset, -(step + 1)))

        return mask

    def thinDiagonalLineMaskLookup(lengthCells: int, widthCells: int) -> Set[Coord]:
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

        up = cardinalLineMaskLookup("up", sizeCells, widthCells)
        right = cardinalLineMaskLookup("right", sizeCells, widthCells)
        down = cardinalLineMaskLookup("down", sizeCells, widthCells)
        left = cardinalLineMaskLookup("left", sizeCells, widthCells)

        if widthCells != 1:
            upRight = diagonalLineMaskLookup(sizeCells, widthCells)
        else:
            upRight = thinDiagonalLineMaskLookup(sizeCells, widthCells)

        return [
            ("up", up),
            ("up_right", upRight),
            ("right", right),
            ("down_right", rotateMask90(upRight)),
            ("down", down),
            ("down_left", rotateMask180(upRight)),
            ("left", left),
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
        currentCasterCells: List[List[int]],
        movementMax: int,
        originMode: str = "placed"
):
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
                cid = target["cid"]
                probSuccess = target["probSuccess"]
                badTarget = len(positions & coveredNonViableCells)
                total = len(positions)
                if badTarget > 0:
                    targetScore = (probSuccess * 100) + 100
                    score -= targetScore
                else:
                    targetScore = probSuccess * 100.0
                    score += targetScore

                targetBreakdown.append({
                    "cid": cid,
                    "probSuccess": probSuccess,
                    "tilesHit": hits,
                    "tilesTotal": total,
                    "targetScore": targetScore,
                })

        score -= len(emptyCells) * 1.0
        for coord in covered:
            x, y = coord
            if x < 0 or y < 0:
                score -= score * 0.001

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
        return any(distanceCells(anchor, c) <= rangeCells for c in casterCellSet)
    def translateCasterCells(casterCellSet: Set[Coord], offset: Coord) -> Set[Coord]:
        dx, dy = offset
        return {(x + dx, y + dy) for x, y in casterCellSet}
    def findCandidateCasterDestinations(
            casterCellSet: Set[Coord],
            movementCells: int,
            occupiedCells: Set[Coord],
    ) -> List[Tuple[int, Set[Coord]]]:
        if not casterCellSet:
            return []

        blockedCells = occupiedCells - casterCellSet
        directions = [
            (-1, -1), (0, -1), (1, -1),
            (-1, 0),           (1, 0),
            (-1, 1),  (0, 1),  (1, 1),
        ]
        candidates = [(0, casterCellSet)]
        queue = deque([((0, 0), 0)])
        visitedOffsets = {(0, 0)}

        while queue:
            offset, distance = queue.popleft()
            if distance >= movementCells:
                continue

            for dx, dy in directions:
                nextOffset = (offset[0] + dx, offset[1] + dy)
                if nextOffset in visitedOffsets:
                    continue
                visitedOffsets.add(nextOffset)

                translatedCells = translateCasterCells(casterCellSet, nextOffset)
                if translatedCells & blockedCells:
                    continue

                nextDistance = distance + 1
                candidates.append((nextDistance, translatedCells))
                queue.append((nextOffset, nextDistance))

        return candidates
    def findLeastMovementCasterDestination(
            anchor: Coord,
            casterDestinations: List[Tuple[int, Set[Coord]]],
            normalRangeCells: int,
    ) -> Optional[Set[Coord]]:
        for _, destinationCells in casterDestinations:
            if anchorWithinPlacedRange(anchor, destinationCells, normalRangeCells):
                return destinationCells
        return None

    def buildSelfOriginCone(
            casterCellSet: Set[Coord],
            anchorCell: Coord,
            orientationName: str,
            direction: Coord,
            lengthCells: int,
    ) -> Set[Coord]:
        def diagonalSelfConeMaskLookup(lengthCells: int) -> Set[Coord]:
            mask = set()
            for dx in range(lengthCells):
                for negDy in range(lengthCells):
                    if 0 <= dx + negDy < lengthCells:
                        mask.add((dx, -negDy))
            return mask

        # Cardinal self-origin cones use the normal cone masks
        if direction in {(0, -1), (1, 0), (0, 1), (-1, 0)}:
            coneMasks = dict(getOrientedTemplateMasks("cone", lengthCells))
            relMask = coneMasks[orientationName]
        else:
            baseMask = diagonalSelfConeMaskLookup(lengthCells)

            if direction == (1, -1):
                relMask = baseMask
            elif direction == (1, 1):
                relMask = rotateMask90(baseMask)
            elif direction == (-1, 1):
                relMask = rotateMask180(baseMask)
            elif direction == (-1, -1):
                relMask = rotateMask270(baseMask)
            else:
                raise ValueError(f"Unsupported direction: {direction}")

        covered = {(anchorCell[0] + mx, anchorCell[1] + my) for mx, my in relMask}
        covered -= casterCellSet
        return covered

    def buildSelfOriginLine(
            casterCellSet: Set[Coord],
            anchorCell: Coord,
            orientationName: str,
            direction: Coord,
            lengthCells: int,
            widthCells: int,
    ) -> Set[Coord]:
        def buildThinDiagonalSelfOriginLine(
                casterCellSet: Set[Coord],
                anchorCell: Coord,
                direction: Coord,
                lengthCells: int,
        ) -> Set[Coord]:
            dx, dy = direction

            covered = {
                (anchorCell[0] + dx * step, anchorCell[1] + dy * step)
                for step in range(1, lengthCells + 1)
            }

            covered -= casterCellSet
            return covered
        isDiagonal = direction in {(1, -1), (1, 1), (-1, 1), (-1, -1)}
        isSingleCellCaster = len(casterCellSet) == 1

        # Old behavior for medium/smaller 1x1 tokens with width-1 diagonal lines
        if isDiagonal and isSingleCellCaster and widthCells == 1:
            return buildThinDiagonalSelfOriginLine(
                casterCellSet=casterCellSet,
                anchorCell=anchorCell,
                direction=direction,
                lengthCells=lengthCells,
            )

        # New behavior for larger monsters or wider diagonal lines
        lineMasks = dict(
            getOrientedTemplateMasks(
                shapeKind="line",
                sizeCells=lengthCells,
                lineWidthCells=widthCells,
            )
        )

        relMask = lineMasks[orientationName]
        covered = {(anchorCell[0] + dx, anchorCell[1] + dy) for dx, dy in relMask}
        covered -= casterCellSet
        return covered
    def getCasterBounds(casterCellSet: Set[Coord]) -> Tuple[int, int, int, int]:
        xs = [x for x, _ in casterCellSet]
        ys = [y for _, y in casterCellSet]
        return min(xs), max(xs), min(ys), max(ys)
    def getDirectionalLineAnchors(
            casterCellSet: Set[Coord],
            direction: Coord,
    ) -> List[Coord]:
        minX, maxX, minY, maxY = getCasterBounds(casterCellSet)

        if direction == (0, -1):  # up
            return sorted([(x, y) for (x, y) in casterCellSet if y == minY])

        if direction == (1, 0):  # right
            return sorted([(x, y) for (x, y) in casterCellSet if x == maxX])

        if direction == (0, 1):  # down
            return sorted([(x, y) for (x, y) in casterCellSet if y == maxY])

        if direction == (-1, 0):  # left
            return sorted([(x, y) for (x, y) in casterCellSet if x == minX])

        if direction == (1, -1):  # up_right
            return [(maxX, minY)]

        if direction == (1, 1):  # down_right
            return [(maxX, maxY)]

        if direction == (-1, 1):  # down_left
            return [(minX, maxY)]

        if direction == (-1, -1):  # up_left
            return [(minX, minY)]

        return []
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
    def getDirectionalConeAnchors(
            casterCellSet: Set[Coord],
            direction: Coord,
    ) -> List[Coord]:
        if direction in {(0, -1), (1, 0), (0, 1), (-1, 0)}:
            return sorted(getFrontEdgeCells(casterCellSet, direction))

        return [getDiagonalSelfOriginAnchorCell(casterCellSet, direction)]

    shapeKind, lineWidthFt = parseShape(shape)

    # radiusFt now controls the actual AOE template size.
    sizeCells = max(1, math.ceil(int(radiusFt) / 5))
    rangeCells = max(0, math.ceil(int(rangeFt) / 5))
    movementCells = max(0, int(movementMax) // 5)
    if originMode == "self":
        rangeCells = 0
    lineWidthCells = max(1, math.ceil(lineWidthFt / 5)) if lineWidthFt else None

    unparsedCells = []
    [unparsedCells.extend(pos) for pos in allCreaturePositions]
    allCells: Set[Coord] = {tuple(p) for p in unparsedCells}
    casterCellSet: Set[Coord] = normalizeCellSet(casterCells)
    currentCasterCellSet: Set[Coord] = normalizeCellSet(currentCasterCells)
    #NOTE: Full set of all legal caster positions to move into.
    casterDestinations = findCandidateCasterDestinations(
        casterCellSet=casterCellSet,
        movementCells=movementCells,
        occupiedCells=allCells - currentCasterCellSet,
    )

    normalizedTargets = []
    viableCellsToTarget: Dict[Coord, Dict[str, Any]] = {}

    for target in allTargets:
        normalizedTarget = {
            "cid": target["cid"],
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
            "movementRecc": []
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
            "movementRecc": []
        }

    best = {
        "coveredCells": set(),
        "anchor": None,
        "orientation": None,
        "score": float("-inf"),
        "targetsHit": [],
        "movementRecc": []
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
                "movementRecc": []
            }

        for _, translatedCasterCells in casterDestinations:
            # Origins that cannot possibly cover a viable target do not need full scoring.
            maxTemplateReach = (sizeCells * 2) + (lineWidthCells or 1)
            if viableCells and not any(
                    min(distanceCells(casterCell, targetCell) for casterCell in translatedCasterCells)
                    <= maxTemplateReach
                    for targetCell in viableCells
            ):
                continue

            movementRecc = [] if translatedCasterCells == currentCasterCellSet else [
                [x, y] for x, y in sorted(translatedCasterCells)
            ]

            if shapeKind in {"circle", "square"}:
                for orientationName, relMask in orientedMasks:
                    for anchor in translatedCasterCells:
                        ax, ay = anchor
                        covered = {(ax + dx, ay + dy) for dx, dy in relMask}
                        covered -= translatedCasterCells

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
                                "movementRecc": movementRecc,
                            }
                continue

            # cone / line need special 8-direction self-origin logic
            for orientationName, direction in get8Directions():
                if shapeKind == "line":
                    anchorCandidates = getDirectionalLineAnchors(translatedCasterCells, direction)

                    for anchorCell in anchorCandidates:
                        covered = buildSelfOriginLine(
                            casterCellSet=translatedCasterCells,
                            anchorCell=anchorCell,
                            orientationName=orientationName,
                            direction=direction,
                            lengthCells=sizeCells,
                            widthCells=lineWidthCells or 1,
                        )

                        score, targetBreakdown = scoreMaskPlacement(
                            covered=covered,
                            allTargets=normalizedTargets,
                            viableCellSet=viableCells,
                            nonViableCells=nonViableCells,
                        )

                        if score > best["score"]:
                            best = {
                                "coveredCells": covered,
                                "anchor": [anchorCell],
                                "orientation": orientationName,
                                "score": score,
                                "targetsHit": targetBreakdown,
                                "movementRecc": movementRecc,
                            }

                    continue

                if shapeKind == "cone":
                    anchorCandidates = getDirectionalConeAnchors(translatedCasterCells, direction)

                    for anchorCell in anchorCandidates:
                        covered = buildSelfOriginCone(
                            casterCellSet=translatedCasterCells,
                            anchorCell=anchorCell,
                            orientationName=orientationName,
                            direction=direction,
                            lengthCells=sizeCells,
                        )

                        score, targetBreakdown = scoreMaskPlacement(
                            covered=covered,
                            allTargets=normalizedTargets,
                            viableCellSet=viableCells,
                            nonViableCells=nonViableCells,
                        )

                        if score > best["score"]:
                            best = {
                                "coveredCells": covered,
                                "anchor": [anchorCell],
                                "orientation": orientationName,
                                "score": score,
                                "targetsHit": targetBreakdown,
                                "movementRecc": movementRecc,
                            }

        best["coveredCells"] = sorted(best["coveredCells"])
        return best

    #PLACE-ORIGIN
    PLACEMENT_EXPANSION_RADIUS = 2
    CANDIDATE_CUTOFF = 10

    effectiveRangeCells = rangeCells + movementCells

    for orientationName, relMask in orientedMasks:
        candidateAnchors = generateCandidateAnchors(
            relMask=relMask,
            focusCells=viableCells,
            casterCellSet=casterCellSet,
            rangeCells=effectiveRangeCells,
        )

        seedResults = []

        for anchor in sorted(candidateAnchors):
            casterDestination = findLeastMovementCasterDestination(
                anchor, casterDestinations, rangeCells
            )
            if casterDestination is None:
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

            seedResults.append((score, anchor, covered, targetBreakdown))

            if score > best["score"]:
                best = {
                    "coveredCells": covered,
                    "anchor": anchor,
                    "orientation": orientationName,
                    "score": score,
                    "targetsHit": targetBreakdown,
                    "movementRecc": [] if casterDestination == currentCasterCellSet else [
                        [x, y] for x, y in sorted(casterDestination)
                    ],
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
            if casterCellSet and not anchorWithinPlacedRange(anchor, casterCellSet, effectiveRangeCells):
                continue

            casterDestination = findLeastMovementCasterDestination(
                anchor, casterDestinations, rangeCells
            )
            if casterDestination is None:
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
                    "movementRecc": [] if casterDestination == currentCasterCellSet else [
                        [x, y] for x, y in sorted(casterDestination)
                    ],
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
    if isValidTarget(action, creature, player, isPlayerTurn):
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
    blockedCells = [
        creature["Statblock"].getPosition()
        for creature in initiative
        if creature["Statblock"] is not player
    ]
    if not isinstance(action, Weapon) and action.getNumTarget() == 0:
        return 0, {}
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False

    percentages = []
    for creature in initiative:
        if isValidTarget(action, creature, player, isPlayerTurn):
            if not isinstance(action, Weapon):
                percentages.append(creature["Statblock"].getHP() / creature["Statblock"].getMaxHP())
            if not isinstance(action, Weapon) and action.getMean() == 0 and action.getNumTarget() == 1:
                viableTargets.append(creature["Statblock"])
                continue
            if isinstance(action, Weapon):
                eDamages.append(calcIndividualExpectedDamage(player, action, creature))
                viableTargets.append(creature["Statblock"])
            else:
                if action.getRollType().lower() in ["save", "autohit", "tohit"]:
                    if action.getNumTarget() >= 1:
                        eDamages.append(calcIndividualExpectedDamage(player, action, creature))
                        viableTargets.append(creature["Statblock"])
                    elif action.getNumTarget() in [-1, -2]:
                        targets = [creature for creature in initiative]
                        for i, target in enumerate(targets):
                            #EDam targets use expected damage instead of probSuccess
                            #Potentially leads to different AOE subsets, which is resolved through impact rating checks.
                            if isValidTarget(action, target, player, isPlayerTurn):
                                targets[i] = {
                                    "cid": target["Statblock"].getCID(),
                                    "probSuccess": calcIndividualExpectedDamage(player, action, target),
                                    "positioning": target["Statblock"].getPosition(),
                                    "viable" : True
                                }
                            else:
                                targets[i] = {
                                    "cid": target["Statblock"].getCID(),
                                    "probSuccess": calcIndividualExpectedDamage(player, action, target),
                                    "positioning": target["Statblock"].getPosition(),
                                    "viable" : False
                                }
                        positions = [creature["Statblock"].getPosition() for creature in initiative]
                        actionRange = action.getActionRange()
                        radius = action.getActionRadius()
                        shape = action.getShape()
                        casterCells = player.getStartingAnchor()
                        currentCasterCells = player.getPosition()
                        movementMax = player.getMovementMax()
                        aoeType = "placed" if action.getNumTarget() == -1 else "self"

                        eDam, token = avgOverAOETargets(targets, positions, actionRange,
                                                        radius, shape, casterCells,
                                                        currentCasterCells, movementMax, aoeType)
                        movementRecc = token["movementRecc"]
                        return round(eDam, 2), token, movementRecc
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
                    eDamages.append(calcIndividualExpectedDamage(player, action, creature) + weaponDam)
                    viableTargets.append(creature)
                else:
                    raise ValueError("Bad rollType!")
    if len(viableTargets) != 0 and all([eDam != 0 for eDam in eDamages]):
        if not isinstance(action, Weapon) and (action.getDamType() == "healing" or "healing" in action.getDamType() or action.getMean() == 0):
            if action.getNumTarget() == 1:
                targetSuccess, movementRecc = calcSingleTargetBestMovement(
                    player, action, percentages, viableTargets, blockedCells
                )
                return eDamages[viableTargets.index(targetSuccess)], targetSuccess, movementRecc
            elif action.getNumTarget() > 1:
                targetSuccess, movementRecc = calcMultiTargetBestMovement(
                    player, action, percentages, viableTargets, blockedCells
                )
                return eDamages[viableTargets.index(targetSuccess)], targetSuccess, movementRecc
        else:
            if isinstance(action, Weapon) or action.getNumTarget() == 1:
                targetSuccess, movementRecc = calcSingleTargetBestMovement(
                    player, action, eDamages, viableTargets, blockedCells
                )
                return eDamages[viableTargets.index(targetSuccess)], targetSuccess, movementRecc
            elif action.getNumTarget() > 1:
                targetSuccess, movementRecc = calcMultiTargetBestMovement(
                    player, action, eDamages, viableTargets, blockedCells
                )
                return eDamages[viableTargets.index(targetSuccess)], targetSuccess, movementRecc
    else:
        return 0, {}
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
    if isValidTarget(action, creature, player, isPlayerTurn):
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
def calcMultiTargetBestMovement(player, action, successScores, targets, blockedCells):
    def _get_starting_anchor():
        if hasattr(player, "getStartingAnchor"):
            return player.getStartingAnchor()
        return player.getPosition()
    def _get_target_position(target):
        statblock = target["Statblock"] if isinstance(target, dict) and "Statblock" in target else target
        return statblock.getPosition()
    def _state(tiles):
        normalized = _normalize_occupied_tiles(tiles)
        return tuple(sorted((int(p[0]), int(p[1])) for p in normalized))
    def _state_to_list(state):
        return [[x, y] for x, y in state]
    def _valid(state, blocked):
        return all((x, y) not in blocked for x, y in state)
    def _targets_in_range(state, range_tiles):
        actor_tiles = _state_to_list(state)
        return [
            index for index, position in enumerate(targetPositions)
            if min_creature_distance_tiles(actor_tiles, position) <= range_tiles
        ]
    def _best_targets_for_state(state, range_tiles, num_targets):
        reachable = _targets_in_range(state, range_tiles)
        reachable.sort(key=lambda index: (-successScores[index], index))
        selected = reachable[:num_targets]
        return selected, sum(successScores[index] for index in selected)

    if not successScores or not targets or len(successScores) != len(targets):
        return [], []

    numTargets = min(action.getNumTarget(), len(targets))
    if numTargets <= 0:
        return [], []

    actionRange = 5 if isinstance(action, Weapon) else _as_int_feet(action.getActionRange())
    if actionRange is None:
        return [], []

    movementTiles = player.getMovementMax() // 5
    rangeTiles = math.ceil(actionRange / 5)
    startState = _state(_get_starting_anchor())
    if not startState:
        return [], []
    currentState = _state(player.getPosition())

    targetPositions = [_get_target_position(target) for target in targets]
    bestOverallIndices = sorted(
        range(len(targets)), key=lambda index: (-successScores[index], index)
    )[:numTargets]
    startIndices, startScore = _best_targets_for_state(startState, rangeTiles, numTargets)
    if set(bestOverallIndices).issubset(startIndices):
        return [targets[index] for index in startIndices], []

    blocked = set()
    directions = [
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),           (1, 0),
        (-1, 1),  (0, 1),  (1, 1)
    ]
    for position in blockedCells:
        blocked.update(tuple(tile) for tile in _normalize_occupied_tiles(position))

    bestState = startState
    bestIndices = startIndices
    bestRank = (len(startIndices), startScore, 0)
    queue = deque([(startState, 0)])
    visited = {startState}
    while queue:
        state, distance = queue.popleft()
        selected, score = _best_targets_for_state(state, rangeTiles, numTargets)
        rank = (len(selected), score, -distance)
        if rank > bestRank:
            bestState = state
            bestIndices = selected
            bestRank = rank
        if distance >= movementTiles:
            continue
        for dx, dy in directions:
            nextState = tuple(sorted((x + dx, y + dy) for x, y in state))
            if nextState in visited or not _valid(nextState, blocked):
                continue
            visited.add(nextState)
            queue.append((nextState, distance + 1))

    selectedTargets = [targets[index] for index in bestIndices]
    movementRecc = [] if bestState == currentState else _state_to_list(bestState)
    return selectedTargets, movementRecc
def calcSingleTargetBestMovement(player, action, successScores, targets, blockedCells):
    def _get_target_position(target):
        statblock = target["Statblock"] if isinstance(target, dict) and "Statblock" in target else target
        return statblock.getPosition()
    def _state(tiles):
        normalized = _normalize_occupied_tiles(tiles)
        return tuple(sorted((int(p[0]), int(p[1])) for p in normalized))
    def _state_to_list(state):
        return [[x, y] for x, y in state]
    def _valid(state, blocked):
        return all((x, y) not in blocked for x, y in state)
    def _in_range(state, target_positions, range_tiles):
        return min_creature_distance_tiles(_state_to_list(state), target_positions) <= range_tiles

    scoreSuccess = max(successScores)
    targetSuccess = targets[successScores.index(scoreSuccess)]
    targetSuccessPos = _get_target_position(targetSuccess)
    actionRange = 5 if isinstance(action, Weapon) else _as_int_feet(action.getActionRange())

    movementTiles = player.getMovementMax() // 5
    rangeTiles = math.ceil(actionRange // 5)
    startState = _state(player.getStartingAnchor())
    currentState = _state(player.getPosition())

    if _in_range(startState, targetSuccessPos, rangeTiles):
        return targetSuccess, []

    blocked = set()
    directions = [
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),           (1, 0),
        (-1, 1),  (0, 1),  (1, 1)
    ]

    for position in blockedCells:
        blocked.update(tuple(tile) for tile in _normalize_occupied_tiles(position))

    queue = deque([(startState, 0)])
    visited = {startState}
    while queue:
        state, distance = queue.popleft()
        if distance >= movementTiles:
            continue
        for dx, dy in directions:
            nextState = tuple(sorted((x + dx, y + dy) for x, y in state))
            if nextState in visited or not _valid(nextState, blocked):
                continue
            if _in_range(nextState, targetSuccessPos, rangeTiles):
                print("Match found with range", rangeTiles)
                if nextState == currentState:
                    print(nextState, "is current state.")
                    return targetSuccess, []
                print("Returning", nextState)
                return targetSuccess, _state_to_list(nextState)
            visited.add(nextState)
            queue.append((nextState, distance + 1))

    print("FAILURE")
    return targetSuccess, None

def calcTotalToHitProbability(player, action, initiative):
    # Only 1 or >1 targets for spells; also covers weapons.
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False

    successProbs = []
    targets = []
    movementRecc = []
    blockedCells = [
        creature["Statblock"].getPosition()
        for creature in initiative
        if creature["Statblock"] is not player
    ]

    lingEffectProb = 0
    checkLingEffects = True if isinstance(action, Spell) and action.getLingEffects() else False

    extraEffectProb = 0
    checkExtraEffects = True if isinstance(action, Spell) and action.getExtraEffect() else False

    lingSavesProb = 0
    checkLingSaves = True if isinstance(action, Spell) and action.getLingSaves() else False

    if isinstance(action, Weapon) or action.getNumTarget() == 1:
        for creature in initiative:
            if isValidTarget(action, creature, player, isPlayerTurn):
                successProb = calcIndividualToHitProbability(player, action, creature)
                successProbs.append(successProb)
                targets.append(creature)
        if len(successProbs) != 0:
            targetSuccess, movementRecc = calcSingleTargetBestMovement(player,
                                                action,successProbs, targets, blockedCells)
            probSuccess = successProbs[targets.index(targetSuccess)]
        else:
            probSuccess = 0
            targetSuccess = []
        if checkLingEffects and targetSuccess:
            lingEffectProb = calcLingeringEffectProbability(player, targetSuccess,action, action.getLingEffects(),
                                                            probSuccess)
        if checkExtraEffects and targetSuccess:
            # In terms of probability of success, lingEffects and extraEffects are the same.
            extraEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getExtraEffect(),
                                                             probSuccess)
        if checkLingSaves and targetSuccess:
            lingSavesProb = calcLingeringSavesProbability(player, targetSuccess,
                                                          action)
        if len(successProbs) != 0:
            probSuccess = round(probSuccess, 2)
            lingEffectProb = round(lingEffectProb, 2)
            extraEffectProb = round(extraEffectProb, 2)
            lingSavesProb = round(lingSavesProb, 2)
            return {
                "probSuccess": probSuccess,
                "probLingEffect": lingEffectProb,
                "probExtraEffect": extraEffectProb,
                "probLingSave": lingSavesProb,
                "target" : [targetSuccess["cid"]],
                "movementRecc" : movementRecc
            }
        return 0
    elif action.getNumTarget() > 1:
        successScores = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player, isPlayerTurn):
                successProb = calcIndividualToHitProbability(player, action, creature)
                successScores.append(successProb)
                targets.append(creature)
        if len(successScores) != 0:
            weights, movementRecc = calcMultiTargetBestMovement(
                player, action, successScores, targets, blockedCells
            )
        else:
            weights = []
        if weights:
            #Average across best n targets
            successProbs = 0
            numMonsters = 0

            for creature in weights:
                # Weights are selected targets, which are parallel to successProbs
                successProb = successScores[targets.index(creature)]
                successProbs += successProb
                if checkLingEffects:
                    lingEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                     action.getLingEffects(),
                                                                     successProb)
                if checkExtraEffects:
                    extraEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                      action.getExtraEffect(),
                                                                      successProb)
                if checkLingSaves:
                    lingSavesProb += calcLingeringSavesProbability(player, creature, action)
                numMonsters += 1
            if numMonsters != 0:
                probSuccess = successProbs / numMonsters
                lingEffectProb = lingEffectProb / numMonsters
                extraEffectProb = extraEffectProb / numMonsters
                lingSavesProb = lingSavesProb / numMonsters
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
                    "probLingSave": lingSavesProb,
                    "target": [weight["cid"] for weight in weights],
                    "movementRecc": movementRecc
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
            if "only" in note.lower() and creatureType not in specialNotes:
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
def avgOverAOETargets(
        creatures, allPositions, actionRange, radius, shape,
        casterCells, currentCasterCells, movementMax, aoeType="placed"
):
    #Cache is in the targets dict
    aoeToken = bestAoePositioning(actionRange, radius, shape,
                                  allPositions, creatures, casterCells,
                                  currentCasterCells, movementMax, aoeType)
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
    movementRecc = []
    blockedCells = [
        creature["Statblock"].getPosition()
        for creature in initiative
        if creature["Statblock"] is not player
    ]
    if isinstance(player, Player):
        isPlayerTurn = True
    else:
        isPlayerTurn = False
    if action.getNumTarget() == 1:
        successProbs = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player, isPlayerTurn):
                if isinstance(player, Player) or isinstance(action, Spell):
                    successProb = calcIndividualSaveProbability(
                        action, player.getDC(), creature["Statblock"]
                    )
                else:
                    successProb = calcIndividualSaveProbability(action, action.getDC(), creature["Statblock"])
                successProbs.append(successProb)
                targets.append(creature)
        if len(targets) != 0:
            targetSuccess, movementRecc = calcSingleTargetBestMovement(
                player, action, successProbs, targets, blockedCells
            )
            probSuccess = successProbs[targets.index(targetSuccess)]
        else:
            probSuccess = 0
            targetSuccess = []
        if checkLingEffects and targetSuccess:
            lingEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getLingEffects(),
                                                            probSuccess)
        if checkExtraEffects and targetSuccess:
            # In terms of probability of success, lingEffects and extraEffects are the same.
            extraEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getExtraEffect(),
                                                            probSuccess)
        if checkLingSaves and targetSuccess:
            lingSavesProb = calcLingeringSavesProbability(player, targetSuccess, action)
        if targetSuccess:
            targetSuccess = [targetSuccess["cid"]]
    elif action.getNumTarget() > 1:
        successScores = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player, isPlayerTurn):
                if isinstance(player, Player) or isinstance(action, Spell):
                    successProb = calcIndividualSaveProbability(action, player.getDC(), creature["Statblock"])
                else:
                    successProb = calcIndividualSaveProbability(action, action.getDC(), creature["Statblock"])
                successScores.append(successProb)
                targets.append(creature)
        if successScores:
            weights, movementRecc = calcMultiTargetBestMovement(
                player, action, successScores, targets, blockedCells
            )
        else:
            return 0
        if not weights:
            return 0

        selectedSuccessProbs = []
        for creature in weights:
            successProb = successScores[targets.index(creature)]
            selectedSuccessProbs.append(successProb)
            if checkLingEffects:
                lingEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                 action.getLingEffects(),
                                                                 successProb)
            if checkExtraEffects:
                extraEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                  action.getExtraEffect(),
                                                                  successProb)
            if checkLingSaves:
                lingSavesProb += calcLingeringSavesProbability(player, creature, action)

        numTargets = len(weights)
        probSuccess = sum(selectedSuccessProbs) / numTargets
        lingEffectProb = lingEffectProb / numTargets
        extraEffectProb = extraEffectProb / numTargets
        lingSavesProb = lingSavesProb / numTargets
        targetSuccess = [target["cid"] for target in weights]
    elif action.getNumTarget() in [-1, -2]:
        targets = [creature for creature in initiative]
        targetsCopy = [creature["Statblock"] for creature in targets]
        for i, target in enumerate(targets):
            if isValidTarget(action, target, player, isPlayerTurn):
                target = target["Statblock"]
                targets[i] = {
                    "cid" : target.getCID(),
                    "probSuccess" : calcIndividualSaveProbability(action, player.getDC(), target),
                    "positioning" : target.getPosition(),
                    "viable" : True
                }
            else:
                target = target["Statblock"]
                targets[i] = {
                    "cid": target.getCID(),
                    "probSuccess": calcIndividualSaveProbability(action, player.getDC(), target),
                    "positioning": target.getPosition(),
                    "viable" : False
                }
        positions = [creature["Statblock"].getPosition() for creature in initiative]
        actionRange = action.getActionRange()
        radius = action.getActionRadius()
        shape = action.getShape()
        casterCells = player.getStartingAnchor()
        currentCasterCells = player.getPosition()
        movementMax = player.getMovementMax()
        aoeType = "placed" if action.getNumTarget() == -1 else "self"
        probSuccess, token = avgOverAOETargets(targets, positions,
                                               actionRange, radius, shape,
                                               casterCells, currentCasterCells,
                                               movementMax, aoeType)
        if not token:
            return 0
        movementRecc = token["movementRecc"]
        finalTargets = []
        for creature in targetsCopy:
            if creature.getCID() in [t["cid"].lower() for t in token["targetsHit"]]:
                finalTargets.append(creature)
                if checkLingEffects or checkExtraEffects:
                    successProbIdx = [t["cid"] for t in token["targetsHit"]].index(creature.getCID())
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
        "probLingSave": lingSavesProb,
        "target" : targetSuccess,
        "movementRecc" : movementRecc
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
    movementRecc = []
    blockedCells = [
        creature["Statblock"].getPosition()
        for creature in initiative
        if creature["Statblock"] is not player
    ]
    if action.getMean() != 0:
        probInitDams = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player,isPlayerTurn):
                probNormDam, probCritDam = calcDamProbs(creature["Statblock"], action, action.getDamMod(), "NORM")
                probInitDams.append((probNormDam + probCritDam))
                targets.append(creature)
        if probInitDams:
            targetSuccess, movementRecc = calcSingleTargetBestMovement(
                player, action, probInitDams, targets, blockedCells
            )
            probInitDam = probInitDams[targets.index(targetSuccess)]
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
        "probLingSave": round(lingSavesProb, 2),
        "target" : targetSuccess,
        "movementRecc" : movementRecc
    }
def calcIndividualAutoHitProbability(action, creature):
    try:
        specImm, specRes, specVuln = saveSpecialNotesCheck(action, creature)
    except TypeError:
        return 0
    if action.getMean() != 0:
        if action.getDamType() == "healing" or "healing" in action.getDamType():
            if isinstance(creature, dict):
                damProb = 1 - (creature["Statblock"].getHP() / creature["Statblock"].getMaxHP())
            else:
                damProb = 1 - (creature.getHP() / creature.getMaxHP())
        else:
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
    movementRecc = []
    blockedCells = [
        creature["Statblock"].getPosition()
        for creature in initiative
        if creature["Statblock"] is not player
    ]

    if action.getNumTarget() == 1:
        successProbs = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player, isPlayerTurn):
                if action.getSpecialNotes() and any("HPCap" in note for note in action.getSpecialNotes()):
                    hpCap = 0
                    specialNotes = action.getSpecialNotes()
                    for note in specialNotes:
                        if "HPCap" in note:
                            hpCap = int(note.split("HPCap")[1])
                    if creature["Statblock"].getHP() < hpCap:
                        successProbs.append(1)
                    else:
                        successProbs.append(0)
                else:
                    successProb = calcIndividualAutoHitProbability(action, creature["Statblock"])
                    successProbs.append(successProb)
                targets.append(creature)
        if len(targets) != 0:
            targetSuccess, movementRecc = calcSingleTargetBestMovement(
                player, action, successProbs, targets, blockedCells
            )
            probSuccess = successProbs[targets.index(targetSuccess)]
        else:
            probSuccess = 0
            targetSuccess = []
        if checkLingEffects and targetSuccess:
            lingEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getLingEffects(),
                                                            probSuccess)
        if checkExtraEffects and targetSuccess:
            # In terms of probability of success, lingEffects and extraEffects are the same.
            extraEffectProb = calcLingeringEffectProbability(player, targetSuccess, action, action.getExtraEffect(),
                                                             probSuccess)
        if checkLingSaves and targetSuccess:
            lingSavesProb = calcLingeringSavesProbability(player, targetSuccess, action)
        if targetSuccess:
            targetSuccess = [targetSuccess["cid"]]
    elif action.getNumTarget() > 1:
        successScores = []
        targets = []
        for creature in initiative:
            if isValidTarget(action, creature, player, isPlayerTurn):
                successProb = calcIndividualAutoHitProbability(action, creature["Statblock"])
                successScores.append(successProb)
                targets.append(creature)
        if successScores:
            weights, movementRecc = calcMultiTargetBestMovement(
                player, action, successScores, targets, blockedCells
            )
        else:
            return 0
        if not weights:
            return 0

        selectedSuccessProbs = []
        for creature in weights:
            successProb = successScores[targets.index(creature)]
            selectedSuccessProbs.append(successProb)
            if checkLingEffects:
                lingEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                 action.getLingEffects(),
                                                                 successProb)
            if checkExtraEffects:
                extraEffectProb += calcLingeringEffectProbability(player, creature, action,
                                                                  action.getExtraEffect(),
                                                                  successProb)
            if checkLingSaves:
                lingSavesProb += calcLingeringSavesProbability(player, creature, action)

        numTargets = len(weights)
        probSuccess = sum(selectedSuccessProbs) / numTargets
        lingEffectProb = lingEffectProb / numTargets
        extraEffectProb = extraEffectProb / numTargets
        lingSavesProb = lingSavesProb / numTargets
        targetSuccess = [target["cid"] for target in weights]
    elif action.getNumTarget() in [-1, -2]:
        targets = [creature for creature in initiative]
        targetsCopy = [creature["Statblock"] for creature in targets]
        for i, target in enumerate(targets):
            if isValidTarget(action, target, player, isPlayerTurn):
                target = target["Statblock"]
                targets[i] = {
                    "cid" : target.getCID(),
                    "probSuccess" : calcIndividualAutoHitProbability(action,target),
                    "positioning" : target.getPosition(),
                    "viable" : True
                }
            else:
                target = target["Statblock"]
                targets[i] = {
                    "cid" : target.getCID(),
                    "probSuccess": calcIndividualAutoHitProbability(action,target),
                    "positioning": target.getPosition(),
                    "viable" : False
                }
        positions = [creature["Statblock"].getPosition() for creature in initiative]
        actionRange = action.getActionRange()
        radius = action.getActionRadius()
        shape = action.getShape()
        casterCells = player.getStartingAnchor()
        currentCasterCells = player.getPosition()
        movementMax = player.getMovementMax()
        aoeType = "placed" if action.getNumTarget() == -1 else "self"
        probSuccess, token = avgOverAOETargets(targets, positions, actionRange,
                                               radius, shape, casterCells,
                                               currentCasterCells, movementMax, aoeType)
        for creature in targetsCopy:
            if creature.getCID() in [t["cid"] for t in token["targetsHit"]]:
                if checkLingEffects or checkExtraEffects:
                    successProbIdx = [t["cid"] for t in token["targetsHit"]].index(creature.getCID())
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
        movementRecc = token["movementRecc"]
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
        "probLingSave": lingSavesProb,
        "target" : targetSuccess,
        "movementRecc" : movementRecc
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
                if condition.lower() not in [c["cond"].lower() if isinstance(c, dict) else c.lower() for c in
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
                if " - " in probSuccess:
                    extraProb = probSuccess.split(" - ")
                else:
                    extraProb = 0.5 #TODO: Edge case where autoHit is given 1.0 probSuccess, even with extra effect. Sleet Storm
                if isinstance(extraProb, list) and len(extraProb) == 1:
                    extraProb = extraProb[0]
                elif isinstance(extraProb, list):
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
            try:
                extraImpact = calcImpact(
                    player,
                    extraEffect,
                    extraProb,
                    extraEffect.getMean(),
                    initiative,
                    False,
                    True,
                )
            except:
                extraImpact = 0
        else:
            try:
                extraImpact = calcImpact(
                    player, extraEffect, extraProb, extraEffect.getMean(), initiative
                )
            except:
                extraImpact = 0 #TODO: Edge case continued on sleet storm
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

    if isinstance(condToAdd, dict):
        condition_name = str(
            condToAdd.get("cond", condToAdd.get("name", ""))
        ).strip()
    else:
        condition_name = str(condToAdd).strip()

    if not condition_name:
        return False

    with open(CONDITION_LIST_FILE, "r") as f:
        condData = json.load(f)

    if not any(
        condition_name.lower() == str(condition.get("name", "")).lower()
        for condition in condData
        if isinstance(condition, dict)
    ):
        return False

    active_conditions = creature.getActiveConditions() or []
    for index, active_condition in enumerate(active_conditions):
        if isinstance(active_condition, dict):
            active_name = str(
                active_condition.get("cond", active_condition.get("name", ""))
            ).strip()
        else:
            active_name = str(active_condition).strip()

        if active_name.lower() != condition_name.lower():
            continue

        # Legacy encounters may store a condition as a bare string. Convert it
        # in place so the source result can be timed and removed correctly.
        if not isinstance(active_condition, dict):
            active_conditions[index] = {
                "cond": active_name or condition_name,
                "resultID": [resultID],
            }
            return True

        raw_result_ids = ensureList(
            active_condition.get(
                "resultID", active_condition.get("resultid", [])
            )
        )
        unique_result_ids = []
        for current_id in raw_result_ids:
            if not any(
                _sameResultID(current_id, existing_id)
                for existing_id in unique_result_ids
            ):
                unique_result_ids.append(current_id)

        result_key = "resultID"
        active_condition.pop("resultid", None)
        active_condition[result_key] = unique_result_ids

        if any(
            _sameResultID(resultID, current_id)
            for current_id in unique_result_ids
        ):
            return False

        unique_result_ids.append(resultID)
        return True

    creature.addCondition({"cond": condition_name, "resultID": [resultID]})
    return True
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


def _dedupeLingeringEffectData(effect_data) -> bool:
    """Normalize parallel lingering arrays and keep one entry per result ID."""
    if not isinstance(effect_data, dict):
        return False

    original = copy.deepcopy(effect_data)
    result_ids = ensureList(effect_data.get("resultID", []))
    raw_actions = effect_data.get("action")
    if not raw_actions:
        raw_actions = effect_data.get("spell", [])
    actions = ensureList(raw_actions)
    actors = ensureList(effect_data.get("actor", []))

    unique_result_ids = []
    unique_actions = []
    unique_actors = []

    for index, result_id in enumerate(result_ids):
        if result_id in (None, "", -1, "-1"):
            continue
        if any(
            _sameResultID(result_id, existing_id)
            for existing_id in unique_result_ids
        ):
            continue

        action = (
            actions[index]
            if index < len(actions)
            else actions[0] if actions else None
        )
        actor = (
            actors[index]
            if index < len(actors)
            else actors[0] if actors else ""
        )

        unique_result_ids.append(result_id)
        unique_actions.append(action)
        unique_actors.append(actor)

    effect_data["resultID"] = unique_result_ids
    effect_data["action"] = unique_actions
    effect_data.pop("spell", None)

    if any(actor not in (None, "") for actor in unique_actors):
        effect_data["actor"] = unique_actors
    else:
        effect_data.pop("actor", None)

    return effect_data != original


def dedupeCreatureLingeringEffects(creature) -> bool:
    """Repair duplicate lingering sources already stored on a creature."""
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    changed = False

    for active_effect in creature.getActiveStatusEffects() or []:
        if not isinstance(active_effect, dict):
            continue
        if str(active_effect.get("name", "")).strip().lower() not in {
            "lingeffect",
            "lingsave",
        }:
            continue

        changed = _dedupeLingeringEffectData(
            active_effect.setdefault("effect", {})
        ) or changed

    return changed


def addStatusEffect(effect, creature, resultID):
    """Add or merge one status effect without corrupting parallel result data."""
    effect = copy.deepcopy(effect)
    creature = creature["Statblock"] if isinstance(creature, dict) else creature

    if not isinstance(effect, dict):
        return False

    effect_name = str(effect.get("name", "")).strip()
    if not effect_name:
        return False

    effect_data = effect.setdefault("effect", {})
    if not isinstance(effect_data, dict):
        effect_data = {}
        effect["effect"] = effect_data

    active_status_effects = creature.getActiveStatusEffects() or []
    existing = next(
        (
            active
            for active in active_status_effects
            if isinstance(active, dict)
            and str(active.get("name", "")).lower() == effect_name.lower()
        ),
        None,
    )

    # Lingering effects store parallel action/resultID/actor arrays. Handle
    # these before the normal attribute-based merge because they do not have
    # an ``attribute`` field.
    if effect_name.lower() in {"lingeffect", "lingsave"}:
        incoming_actions = ensureList(
            effect_data.get("action", effect_data.get("spell", []))
        )
        incoming_result_ids = ensureList(effect_data.get("resultID", []))
        incoming_actors = ensureList(effect_data.get("actor", []))

        if not incoming_result_ids:
            incoming_result_ids = [resultID]

        # One action and one actor belong to each result ID. Duplicate a single
        # supplied value when the payload represents several linked results.
        if len(incoming_actions) == 1 and len(incoming_result_ids) > 1:
            incoming_actions = incoming_actions * len(incoming_result_ids)
        if len(incoming_actors) == 1 and len(incoming_result_ids) > 1:
            incoming_actors = incoming_actors * len(incoming_result_ids)

        if existing is not None:
            existing_data = existing.setdefault("effect", {})
            _dedupeLingeringEffectData(existing_data)
            existing_actions = existing_data.setdefault("action", [])
            existing_result_ids = existing_data.setdefault("resultID", [])
            existing_actors = existing_data.setdefault("actor", [])

            changed = False
            for index, incoming_result_id in enumerate(incoming_result_ids):
                if any(
                    _sameResultID(incoming_result_id, current_result_id)
                    for current_result_id in existing_result_ids
                ):
                    continue

                incoming_action = (
                    incoming_actions[index]
                    if index < len(incoming_actions)
                    else incoming_actions[0] if incoming_actions else None
                )
                incoming_actor = (
                    incoming_actors[index]
                    if index < len(incoming_actors)
                    else incoming_actors[0] if incoming_actors else ""
                )

                existing_result_ids.append(incoming_result_id)
                existing_actions.append(incoming_action)
                existing_actors.append(incoming_actor)
                changed = True

            return changed

        effect_data["action"] = incoming_actions
        effect_data["resultID"] = incoming_result_ids
        if incoming_actors:
            effect_data["actor"] = incoming_actors
        _dedupeLingeringEffectData(effect_data)

        creature.addStatusEffect(effect)
        return True

    incoming_attributes = ensureList(effect_data.get("attribute", []))
    if incoming_attributes:
        effect_data["attribute"] = incoming_attributes

    if existing is not None:
        existing_data = existing.setdefault("effect", {})
        existing_result_ids = ensureList(existing_data.get("resultID", []))
        existing_data["resultID"] = existing_result_ids

        if not incoming_attributes:
            if any(
                _sameResultID(resultID, current_result_id)
                for current_result_id in existing_result_ids
            ):
                return False
            existing_result_ids.append(resultID)
            return True

        existing_attributes = ensureList(existing_data.get("attribute", []))
        existing_data["attribute"] = existing_attributes

        changed = False
        for attribute in incoming_attributes:
            if attribute in existing_attributes:
                continue
            existing_attributes.append(attribute)
            existing_result_ids.append(resultID)
            changed = True

        return changed

    if incoming_attributes:
        effect_data["resultID"] = [resultID] * len(incoming_attributes)
    else:
        effect_data["resultID"] = [resultID]

    creature.addStatusEffect(effect)
    return True


def removeStatusEffect(name, creature):
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    for effect in creature.getActiveStatusEffects():
        if name.lower() == effect["name"].lower():
            return creature.removeStatusEffect(name)


def _sameResultID(left, right) -> bool:
    return left == right or str(left) == str(right)


def getCreatureResultIDs(creature) -> List[Any]:
    """Collect unique action-result IDs currently attached to a creature."""
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    result_ids = []

    for condition in creature.getActiveConditions() or []:
        if not isinstance(condition, dict):
            continue
        condition_result_ids = condition.get(
            "resultID", condition.get("resultid", [])
        )
        for result_id in ensureList(condition_result_ids):
            if result_id in (None, -1, "-1"):
                continue
            if not any(_sameResultID(result_id, current) for current in result_ids):
                result_ids.append(result_id)

    for status_effect in creature.getActiveStatusEffects() or []:
        if not isinstance(status_effect, dict):
            continue
        effect_data = status_effect.get("effect", {})
        for result_id in ensureList(effect_data.get("resultID", [])):
            if result_id in (None, -1, "-1"):
                continue
            if not any(_sameResultID(result_id, current) for current in result_ids):
                result_ids.append(result_id)

    return result_ids


def removeResultEffects(resultID, creature) -> bool:
    """Remove every condition/status-effect association created by one result ID."""
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    removed = False

    conditions = creature.getActiveConditions() or []
    condition_idx = 0
    while condition_idx < len(conditions):
        condition = conditions[condition_idx]
        if not isinstance(condition, dict):
            condition_idx += 1
            continue

        result_id_key = "resultID" if "resultID" in condition else "resultid"
        result_ids = ensureList(condition.get(result_id_key, []))
        remaining_ids = [
            current_id
            for current_id in result_ids
            if not _sameResultID(current_id, resultID)
        ]

        if len(remaining_ids) == len(result_ids):
            condition_idx += 1
            continue

        removed = True
        if remaining_ids:
            condition[result_id_key] = remaining_ids
            condition_idx += 1
        else:
            del conditions[condition_idx]

    status_effects = creature.getActiveStatusEffects() or []
    status_idx = 0
    while status_idx < len(status_effects):
        status_effect = status_effects[status_idx]
        if not isinstance(status_effect, dict):
            status_idx += 1
            continue

        effect_data = status_effect.get("effect", {})
        raw_result_ids = effect_data.get("resultID", [])

        if isinstance(raw_result_ids, list):
            original_result_ids = list(raw_result_ids)
            matching_indices = [
                idx
                for idx, current_id in enumerate(original_result_ids)
                if _sameResultID(current_id, resultID)
            ]

            if not matching_indices:
                status_idx += 1
                continue

            removed = True
            for idx in reversed(matching_indices):
                del raw_result_ids[idx]

                for parallel_key in ("attribute", "action", "spell", "actor"):
                    parallel_values = effect_data.get(parallel_key)
                    if (
                        isinstance(parallel_values, list)
                        and len(parallel_values) == len(original_result_ids)
                    ):
                        del parallel_values[idx]

            if raw_result_ids:
                status_idx += 1
            else:
                del status_effects[status_idx]
            continue

        if _sameResultID(raw_result_ids, resultID):
            removed = True
            del status_effects[status_idx]
            continue

        status_idx += 1

    return removed


def _updateLegacyTurnCount(result) -> None:
    numeric_counts = []
    for count in result.get("turnCounts", {}).values():
        try:
            numeric_counts.append(int(count))
        except (TypeError, ValueError):
            continue
    result["turnCount"] = max(numeric_counts, default=0)


def clearCreatureResultTimer(resultID, creature, encounter) -> bool:
    """Clear one creature's timer metadata for a result that ended early."""
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    result = encounter.getResultByID(resultID)
    if not result:
        return False

    creature_key = str(creature.getCID())
    changed = False

    turn_counts = result.get("turnCounts")
    if isinstance(turn_counts, dict) and creature_key in turn_counts:
        del turn_counts[creature_key]
        changed = True

    expired_creatures = result.get("expiredCreatures")
    if isinstance(expired_creatures, dict) and creature_key in expired_creatures:
        del expired_creatures[creature_key]
        changed = True

    _updateLegacyTurnCount(result)
    return changed


def pruneCreatureTurnCounts(creature, encounter) -> bool:
    """
    Remove stale per-creature timer entries after a single effect is removed.

    A result keeps counting when any sibling condition/status effect on the
    creature still references that result ID.
    """
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    creature_key = str(creature.getCID())
    active_result_ids = getCreatureResultIDs(creature)
    changed = False

    for result_idx in range(encounter.resultSize()):
        result = encounter.getResultByIdx(result_idx)
        result_id = result.get("resultID")
        if result_id in (None, -1, "-1"):
            continue

        if any(_sameResultID(result_id, active_id) for active_id in active_result_ids):
            continue

        turn_counts = result.get("turnCounts")
        if isinstance(turn_counts, dict) and creature_key in turn_counts:
            del turn_counts[creature_key]
            changed = True

        expired_creatures = result.get("expiredCreatures")
        if isinstance(expired_creatures, dict) and creature_key in expired_creatures:
            del expired_creatures[creature_key]
            changed = True

        _updateLegacyTurnCount(result)

    return changed


def endTimedResultForCreature(resultID, creature, encounter) -> bool:
    """End all active effects and timer metadata from one result for one creature."""
    removed_effects = removeResultEffects(resultID, creature)
    removed_timer = clearCreatureResultTimer(resultID, creature, encounter)
    return removed_effects or removed_timer


def _hasPendingPreTurnResult(resultID, creature) -> bool:
    creature = creature["Statblock"] if isinstance(creature, dict) else creature

    for status_effect in creature.getActiveStatusEffects() or []:
        if not isinstance(status_effect, dict):
            continue
        if str(status_effect.get("name", "")).strip().lower() not in {
            "lingeffect",
            "lingsave",
        }:
            continue

        effect_data = status_effect.get("effect", {})
        if any(
            _sameResultID(resultID, current_id)
            for current_id in ensureList(effect_data.get("resultID", []))
        ):
            return True

    return False


def advanceTimedEffects(creature, encounter) -> List[Any]:
    """
    Advance each unique timed result once for this creature's turn.

    The caller may snapshot pre-turn effects before calling this function. A
    ``1Turn`` result is marked expired as that turn begins. Lingering effects
    remain attached until their pending pre-turn resolution is submitted;
    ordinary timed effects are removed immediately. Counts are stored per
    creature so a multi-target action does not expire early for later targets.
    """
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    creature_key = str(creature.getCID())
    expired_result_ids = []

    for result_id in getCreatureResultIDs(creature):
        result = encounter.getResultByID(result_id)
        if not result:
            continue

        try:
            turn_cap = int(result.get("turnCap", 0))
        except (TypeError, ValueError):
            continue

        if turn_cap <= 0:
            continue

        turn_counts = result.setdefault("turnCounts", {})
        expired_creatures = result.setdefault("expiredCreatures", {})

        # A lingering save/effect that reached its cap must remain available
        # until the frontend submits that pre-turn resolution. Repeated reads
        # must not advance it again while it is pending.
        if expired_creatures.get(creature_key, False):
            expired_result_ids.append(result_id)
            _updateLegacyTurnCount(result)
            continue

        try:
            current_count = int(turn_counts.get(creature_key, 0))
        except (TypeError, ValueError):
            current_count = 0

        new_count = current_count + 1
        turn_counts[creature_key] = new_count

        if new_count >= turn_cap:
            expired_result_ids.append(result_id)
            expired_creatures[creature_key] = True

            if _concentrationForResult(creature, result_id) is not None:
                # Duration belongs to the spell source, not merely one target.
                # Ending it here removes every linked effect and AOE token.
                endConcentrationForResult(result_id, encounter)
            elif not _hasPendingPreTurnResult(result_id, creature):
                removeResultEffects(result_id, creature)
                turn_counts.pop(creature_key, None)

        _updateLegacyTurnCount(result)

    return expired_result_ids


def finalizeTimedResult(resultID, creature, encounter) -> bool:
    """Remove effects re-applied by an already-expired pre-turn simulation."""
    creature = creature["Statblock"] if isinstance(creature, dict) else creature
    result = encounter.getResultByID(resultID)
    if not result:
        return False

    creature_key = str(creature.getCID())
    if not result.get("expiredCreatures", {}).get(creature_key, False):
        return False

    return endTimedResultForCreature(resultID, creature, encounter)
def endOfEncounter(initiative):
    allPlayersDead = True
    for playerTurns in initiative:
        if playerTurns["turnType"] == "Player":
            if (not playerTurns["Statblock"].isActiveCondition("Dead")
                    and not playerTurns["Statblock"].isActiveCondition("Out of Combat")
                    and not playerTurns["Statblock"].isActiveCondition("Downed")):
                allPlayersDead = False
                break
    allMonstersDead = True
    for monsterTurn in initiative:
        if monsterTurn["turnType"] == "Monster":
            if (not monsterTurn["Statblock"].isActiveCondition("Dead")
                    and not monsterTurn["Statblock"].isActiveCondition("Out of Combat"))\
                    and not monsterTurn["Statblock"].isActiveCondition("Downed"):
                allMonstersDead = False
                break
    return allPlayersDead or allMonstersDead
def endConcentration(player, concentration, initiative, mapdata):
    """End concentration and remove every effect linked to its result ID."""
    if isinstance(player, dict):
        player = player["Statblock"]

    effect = concentration.get("effect", {}) if isinstance(concentration, dict) else {}
    if not isinstance(effect, dict):
        effect = {}

    concentration_targets = effect.get("concentrationTargets", [])
    if not isinstance(concentration_targets, list):
        concentration_targets = []

    target_keys = {
        str(target).strip().lower()
        for target in concentration_targets
        if target not in (None, "")
    }

    result_id = effect.get("resultID")
    is_summon = bool(effect.get("summonConc"))

    player.removeStatusEffect("Concentration")

    if result_id not in (None, ""):
        initiative_index = 0

        while initiative_index < len(initiative):
            entry = initiative[initiative_index]
            creature = entry.get("Statblock") if isinstance(entry, dict) else None

            if creature is None:
                initiative_index += 1
                continue

            has_linked_effect = any(
                _sameResultID(existing_id, result_id)
                for existing_id in getCreatureResultIDs(creature)
            )
            if not has_linked_effect:
                initiative_index += 1
                continue

            if is_summon and creature is not player:
                creature_keys = {
                    str(creature.getCID()).strip().lower(),
                    str(creature.getName()).strip().lower(),
                }
                if not target_keys or not target_keys.isdisjoint(creature_keys):
                    del initiative[initiative_index]
                    continue

            removeResultEffects(result_id, creature)
            initiative_index += 1

    if isinstance(mapdata, dict):
        layers = mapdata.get("layers")
        if isinstance(layers, dict):
            tokens = layers.get("aoeTokens")
            if isinstance(tokens, list) and result_id not in (None, ""):
                layers["aoeTokens"] = [
                    token
                    for token in tokens
                    if not (
                        isinstance(token, dict)
                        and _sameResultID(token.get("resultID"), result_id)
                    )
                ]


def _concentrationForResult(creature, resultID):
    creature = creature["Statblock"] if isinstance(creature, dict) else creature

    for status_effect in creature.getActiveStatusEffects() or []:
        if not isinstance(status_effect, dict):
            continue
        if str(status_effect.get("name", "")).strip().lower() != "concentration":
            continue

        effect_data = status_effect.get("effect", {})
        if not isinstance(effect_data, dict):
            continue
        if _sameResultID(effect_data.get("resultID"), resultID):
            return status_effect

    return None


def _hasNonConcentrationResultEffect(creature, resultID) -> bool:
    creature = creature["Statblock"] if isinstance(creature, dict) else creature

    for condition in creature.getActiveConditions() or []:
        if not isinstance(condition, dict):
            continue
        result_ids = condition.get("resultID", condition.get("resultid", []))
        if any(
            _sameResultID(current_id, resultID)
            for current_id in ensureList(result_ids)
        ):
            return True

    for status_effect in creature.getActiveStatusEffects() or []:
        if not isinstance(status_effect, dict):
            continue
        if str(status_effect.get("name", "")).strip().lower() == "concentration":
            continue

        effect_data = status_effect.get("effect", {})
        if not isinstance(effect_data, dict):
            continue
        if any(
            _sameResultID(current_id, resultID)
            for current_id in ensureList(effect_data.get("resultID", []))
        ):
            return True

    return False


def _hasActiveAoeTokenForResult(mapdata, resultID) -> bool:
    if not isinstance(mapdata, dict):
        return False
    layers = mapdata.get("layers", {})
    if not isinstance(layers, dict):
        return False
    tokens = layers.get("aoeTokens", [])
    if not isinstance(tokens, list):
        return False

    return any(
        isinstance(token, dict)
        and _sameResultID(token.get("resultID"), resultID)
        for token in tokens
    )


def _clearAllResultTimers(resultID, encounter) -> bool:
    result = encounter.getResultByID(resultID)
    if not isinstance(result, dict):
        return False

    changed = False
    if result.get("turnCounts"):
        result["turnCounts"] = {}
        changed = True
    if result.get("expiredCreatures"):
        result["expiredCreatures"] = {}
        changed = True
    if result.get("turnCount", 0) != 0:
        result["turnCount"] = 0
        changed = True
    return changed


def endConcentrationForResult(resultID, encounter) -> bool:
    """Force-end one concentration source and all linked effects/tokens."""
    if resultID in (None, "", -1, "-1"):
        return False

    initiative = setActiveInitiative(encounter)
    mapdata = encounter.getMapData()

    for entry in initiative:
        creature = entry.get("Statblock") if isinstance(entry, dict) else entry
        if creature is None:
            continue

        concentration = _concentrationForResult(creature, resultID)
        if concentration is None:
            continue

        endConcentration(creature, concentration, initiative, mapdata)
        _clearAllResultTimers(resultID, encounter)
        return True

    return False


def reconcileConcentrationForResult(resultID, encounter) -> bool:
    """End concentration only when its source no longer owns any live effect.

    A result remains active while at least one creature has a linked condition
    or status effect, or while a lingering AOE token (for example Moonbeam)
    remains on the map.
    """
    if resultID in (None, "", -1, "-1"):
        return False

    initiative = setActiveInitiative(encounter)
    mapdata = encounter.getMapData()
    concentration_exists = False

    for entry in initiative:
        creature = entry.get("Statblock") if isinstance(entry, dict) else entry
        if creature is None:
            continue
        if _concentrationForResult(creature, resultID) is not None:
            concentration_exists = True
            break

    if not concentration_exists:
        return False

    if _hasActiveAoeTokenForResult(mapdata, resultID):
        return False

    for entry in initiative:
        creature = entry.get("Statblock") if isinstance(entry, dict) else entry
        if creature is not None and _hasNonConcentrationResultEffect(
            creature, resultID
        ):
            return False

    return endConcentrationForResult(resultID, encounter)


def executeAction(actor, action, selectedTargets, actionResult, initiative, mapdata):
    def applyEffectToTarget(creature, succeeded, damage, action, actionResult):
        resultID = actionResult["resultID"]
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
            action_conditions = []
            action_status_effects = []

            if hasattr(action, "getConditions") and action.getConditions():
                action_conditions.extend(action.getConditions())

            if actionResult.get("conditions"):
                action_conditions.extend(actionResult["conditions"])

            if hasattr(action, "getStatusEffects") and action.getStatusEffects():
                action_status_effects.extend(action.getStatusEffects())

            if actionResult.get("statusEffects"):
                action_status_effects.extend(actionResult["statusEffects"])

            for cond in action_conditions:
                addCondition(cond, creature, resultID)

            for effect in action_status_effects:
                if effect.get("name", "").lower() != "concentration":
                    addStatusEffect(effect, creature, resultID)

            if hasattr(action, "getLingSaves") and action.getLingSaves():
                if creature.isActiveStatusEffect("lingsave"):
                    lingSaves = creature.getActiveStatusEffect("lingsave")
                    if not any(resultID == rID for rID in lingSaves["effect"]["resultID"]):
                        if "spell" in lingSaves["effect"]:
                            lingSaves["effect"]["spell"].append(action.toDict())
                        else:
                            lingSaves["effect"].setdefault("action", []).append(action.toDict())
                        lingSaves["effect"]["resultID"].append(actionResult["resultID"])
                        lingSaves["effect"].setdefault("actor", []).append(
                            str(actor.getCID() if hasattr(actor, "getCID") else actor.getName())
                        )
                else:
                    newLingSave = {
                        "name": "lingSave",
                        "effect": {
                            "action": [action.toDict()],
                            "resultID": [actionResult["resultID"]],
                            "actor": [str(actor.getCID() if hasattr(actor, "getCID") else actor.getName())],
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

    main_roll_type = (
        "weapon"
        if isinstance(action, Weapon)
        else action.getRollType().lower()
    )
    if isinstance(action, MonAction):
        main_save_dc = action.getDC()
    else:
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

    # A pre-turn resolution reuses the original spell/action payload. If that
    # original action required concentration, executing the lingering save or
    # lingering effect must not start concentration again. Doing so previously
    # entered the normal concentration setup with a pre-turn request body, which
    # has no ``actionResult["effect"]`` field and raised ``KeyError: 'effect'``.
    is_pre_turn_resolution = (
        str(actionResult.get("actionType", "")).strip().lower() == "preturn"
    )

    action_status_effects = (
        action.getStatusEffects()
        if hasattr(action, "getStatusEffects")
        else []
    ) or []
    starts_concentration = any(
        isinstance(status_effect, dict)
        and str(status_effect.get("name", "")).strip().lower() == "concentration"
        for status_effect in action_status_effects
    )

    if (
        isinstance(action, Spell)
        and starts_concentration
        and not is_pre_turn_resolution
    ):
        # Starting a new concentration spell always ends the actor's previous
        # concentration first. The old target-array mutation code was both
        # unnecessary and unsafe because ActionRequest/pre-turn payloads do not
        # contain an ``effect`` object.
        existing_concentration = next(
            (
                status_effect
                for status_effect in actor.getActiveStatusEffects() or []
                if isinstance(status_effect, dict)
                and str(status_effect.get("name", "")).strip().lower()
                == "concentration"
            ),
            None,
        )
        if existing_concentration is not None:
            endConcentration(actor, existing_concentration, initiative, mapdata)

        concentration_targets = [
            str(
                target["Statblock"].getCID()
                if isinstance(target, dict)
                else target.getCID()
            )
            for target in selectedTargets
        ]

        actor.addStatusEffect({
            "name": "Concentration",
            "effect": {
                "resultID": actionResult["resultID"],
                "concentrationTargets": concentration_targets,
                "action": action.toDict(),
            },
        })

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
        damTypes = action.getDamType() #Apply status effects to damages
        if isinstance(damTypes, list):
            if len(damTypes) == 1:
                dType = damTypes[0]
                if creature.isResistant(dType):
                    raw_damage /= 2
                elif creature.isVulnerable(dType):
                    raw_damage *= 2
                elif creature.isImmune(dType):
                    raw_damage *= 0
            if "AND" in damTypes:
                for dType in damTypes:
                    if creature.isResistant(dType):
                        raw_damage /= 2
                    elif creature.isVulnerable(dType):
                        raw_damage *= 2
                    elif creature.isImmune(dType):
                        raw_damage *= 0
            elif "OR" in damTypes:
                if all(creature.isResistant(dType) for dType in damTypes):
                    raw_damage /= 2
                elif all(creature.isImmune(dType) for dType in damTypes):
                    raw_damage *= 0
                elif any(creature.isVulnerable(dType) for dType in damTypes):
                    raw_damage *= 2
        if isinstance(damTypes, str):
            if creature.isResistant(damTypes):
                raw_damage /= 2
            elif creature.isVulnerable(damTypes):
                raw_damage *= 2
            elif creature.isImmune(damTypes):
                raw_damage *= 0
        applied_damage = _applied_damage_amount( #Normalize damages
            raw_damage,
            succeeded,
            main_roll_type,
            half_save=main_half_save,
            is_healing=main_is_healing,
        )

        if idx < len(damages):
            damages[idx] = applied_damage

        creature = applyEffectToTarget(
            creature, succeeded, applied_damage, action, actionResult
        )

        if hasattr(action, "getLingEffects") and action.getLingEffects():
            actor_spell_mod = (
                actor.getSpellMod()
                if hasattr(actor, "getSpellMod")
                else 0
            )
            transLingEffect = translateLingEffect(
                action,
                action.getLingEffects(),
                actor_spell_mod,
            )
            newLingEffect = {
                "name": "lingEffect",
                "effect": {
                    "action": [transLingEffect.toDict()],
                    "resultID": [actionResult["resultID"]],
                    "actor": [str(actor.getCID() if hasattr(actor, "getCID") else actor.getName())],
                },
            }
            # Route both new and existing lingering effects through the same
            # result-aware merge. Directly appending here created another queue
            # item every time the same Flaming Sphere source was processed.
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

    turn_cap = getTurnCapFromSpecialNotes(action)
    if turn_cap is not None:
        actionResult["turnCount"] = 0
        actionResult["turnCap"] = turn_cap
        turn_counts = actionResult.setdefault("turnCounts", {})
        for target in selectedTargets:
            target_obj = target["Statblock"] if isinstance(target, dict) else target
            if any(
                _sameResultID(actionResult.get("resultID"), active_result_id)
                for active_result_id in getCreatureResultIDs(target_obj)
            ):
                turn_counts.setdefault(str(target_obj.getCID()), 0)

        if starts_concentration and _concentrationForResult(
            actor, actionResult.get("resultID")
        ) is not None:
            # Area spells can remain active with no creature currently inside
            # them, so their duration is owned by the concentrating caster.
            turn_counts.setdefault(str(actor.getCID()), 0)


def endSpellEffect(effect, idx, creature, initiative=None):
    """End one result-linked lingering effect and all effects it created."""
    result_ids = ensureList(effect.get("effect", {}).get("resultID", []))
    if idx < 0 or idx >= len(result_ids):
        return False

    return removeResultEffects(result_ids[idx], creature)

#ENCOUNTER RUNTIME METHODS
def merge_sort_spells(spell_list):
    #Sort by name and level
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
    actionMovementReccs = []
    actionObjects = []

    for i in range(len(spellList)):
        if actionViabilityCheck(spellList[i], initEntry, initiative, isPlayerTurn):
            spellName = spellList[i].getName()
            try:
                spellProb = 0
                spellEDam = -1
                pMovementRecc = []
                eMovementRecc = []
                if spellList[i].getSelfTarget():
                    spellProb = 1.0
                    spellEDam = 0
                    probTargets = [creature.getCID()]
                    eTargets = [creature.getCID()]
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
                        else:
                            if spellList[i].getStatusEffects() and any(
                                    [se["name"] == "Summon" for se in spellList[i].getStatusEffects()]):
                                spellProb = 1.0
                                spellEDam = 0
                            else:
                                spellProb = calcTotalAutoHitProbability(creature, spellList[i], initiative)
                    elif spellList[i].getRollType().lower() == "onhit":
                        spellProb = calcOnHitProbability(spellList[i],
                                                         [creature.getWeapon(i) for i in
                                                          range(creature.getWeaponLength())],
                                                         creature, initiative)
                    if isinstance(spellProb, dict):
                        spellProb["probSuccess"] = 0 if spellProb["probSuccess"] < 0 else spellProb["probSuccess"]
                        spellProb["probSuccess"] = 1 if spellProb["probSuccess"] > 1 else spellProb["probSuccess"]
                        probToStr = f"{spellProb['probSuccess']}" if spellProb['probSuccess'] else f"0.0"
                        probToStr += f" - {spellProb['probLingEffect']}LE" if spellProb['probLingEffect'] else ""
                        probToStr += f" - {spellProb['probExtraEffect']}EE" if spellProb['probExtraEffect'] else ""
                        probToStr += f" - {spellProb['probLingSave']}LS" if spellProb['probLingSave'] else ""
                        probTargets = spellProb["target"] if spellProb["probSuccess"] != 0 else ""
                        pMovementRecc = spellProb.get("movementRecc", [])
                    else:
                        spellProb = 0 if spellProb < 0 else spellProb
                        spellProb = 1 if spellProb > 1 else spellProb
                        probToStr = spellProb
                        probTargets = {}
                    spellProb = probToStr
                    try:
                        if spellEDam == -1:
                            spellEDam, eTargets, eMovementRecc = calcTotalExpectedDamage(
                                creature, spellList[i], initiative
                            )
                        else:
                            spellEDam = 0
                            eTargets = {}
                    except TypeError:
                        spellEDam = 0
                        eTargets = {}

                if not probTargets and not eTargets:
                    continue
                probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                eTargetsNorm = normalizeTargetSets(eTargets, initiative)

                if probTargetsNorm and eTargetsNorm and {target.getCID() for target in probTargetsNorm} == {
                    target.getCID() for target in eTargetsNorm}:
                    # Good case.
                    spellImpact = calcImpact(creature, spellList[i], spellProb,
                                             spellEDam, probTargetsNorm, initiative)
                    target = probTargets
                    movementRecc = pMovementRecc
                else:
                    # Bad case.
                    if not probTargetsNorm and eTargetsNorm:
                        spellImpact = calcImpact(creature, spellList[i], spellProb,
                                                 spellEDam, eTargetsNorm, initiative)
                        target = eTargets
                        movementRecc = eMovementRecc
                    elif not eTargetsNorm and probTargetsNorm:
                        spellImpact = calcImpact(creature, spellList[i], spellProb,
                                                 spellEDam, probTargetsNorm, initiative)
                        target = probTargets
                        movementRecc = pMovementRecc
                    elif not probTargetsNorm and not eTargetsNorm:
                        spellImpact = 0
                        target = None
                        movementRecc = []
                    else:
                        spellImpact1 = calcImpact(creature, spellList[i], spellProb,
                                                  spellEDam, probTargetsNorm, initiative)
                        spellImpact2 = calcImpact(creature, spellList[i], spellProb,
                                                  spellEDam, eTargetsNorm, initiative)
                        spellImpact = max([spellImpact1, spellImpact2])
                        targetIdx = [spellImpact1, spellImpact2].index(spellImpact)
                        target = probTargets if targetIdx == 0 else eTargets
                        movementRecc = pMovementRecc if targetIdx == 0 else eMovementRecc

                if spellList[i].getDamType() == "healing" or "healing" in spellList[i].getDamType() and spellList[
                    i].getMean() != 0:
                    if isinstance(target, list):
                        healMod = []
                        for t in target:
                            healMod.append(1 - (t.getHP() / t.getMaxHP()))
                        healMod = (sum(healMod) / len(healMod)) if healMod else 0
                    elif isinstance(target, dict):
                        if "targetsHit" in target:
                            healMod = []
                            for t in target["targetsHit"]:
                                healMod.append(1 - (t.getHP() / t.getMaxHP()))
                            healMod = (sum(healMod) / len(healMod)) if healMod else 0
                        else:
                            healMod = 0
                    else:
                        healMod = 1 - (target.getHP() / target.getMaxHP())
                    spellImpact *= healMod
                    spellEDam *= healMod

                actionNames.append(spellName)
                actionTypes.append(f"Lvl {spellList[i].getLvl()} spell")
                actionProbs.append(spellProb)
                actionEDams.append(spellEDam)
                actionImpacts.append(spellImpact)
                if isinstance(target, Player) or isinstance(target, Monster):
                    target = [target]
                actionTargets.append(target)
                actionMovementReccs.append(movementRecc)
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
                    elif "Statblock" in target:  # TODO: If it goes here, action is broken. fix it later.
                        if isinstance(spellEDam, list):
                            actionPercentages.append(round(spellEDam[i] / target["Statblock"].getHP(), 2))
                        else:
                            actionPercentages.append(round(spellEDam / target["Statblock"].getHP(), 2))
                else:
                    hp = target.getHP()
                    if isinstance(spellEDam, list):
                        actionPercentages.append(round(spellEDam[i] / hp, 2))
                    else:
                        actionPercentages.append(round(spellEDam / hp, 2))
            except:
                continue
    actions = []
    for i in range(len(actionNames)):
        try:
            actions.append({"name": actionNames[i], "type" : actionTypes[i], "prob": actionProbs[i], "eDam": actionEDams[i],
                "percentage" : actionPercentages[i], "impact": actionImpacts[i],
                "actions" : actionObjects[i], "target" : actionTargets[i],
                "movementRecc" : actionMovementReccs[i]})
        except IndexError:
            actionPercentages.insert(i, 0)
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

        SEG_RE = re.compile( #Parses the probability
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

            if action_type.startswith("lvl ") and action_type.endswith(" spell"):
                middle = action_type[4:-6].strip()
                level = int(middle)

                if level in (0, 1, 2):
                    return 0.97

                return 1.03 + (0.03 * ((2 ** (level - 3)) - 1))

            return 1.0
        def get_percentage_multiplier(pct):
            #Normalized between 0-1, so .25 is significant
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
                if "action_obj" in x and x["action_obj"] and "healing" not in x["action_obj"].getDamType():
                    typeMult = get_type_multiplier(x.get("type"))
                else:
                    typeMult = .8
                pctMult = get_percentage_multiplier(pct)

                x["eDam"] = rawEDam
                x["impact"] = rawImpact
                x["percentageValue"] = pct
                x["typeMultiplier"] = typeMult
                x["percentageMultiplier"] = pctMult

                x["rankEDam"] = rawEDam * typeMult * pctMult
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
                x["base_weight"] = float((1.0 if x["pareto"] else 0.0) + x["topsis"])

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
                        action["target"]["targetsHit"][i] = t.getCID() if not isinstance(t, str) else t
                elif isinstance(action["target"], dict) and "Statblock" in action["target"]:
                    # TODO: If it is this case, action is broken (Ex: Smites). Fix later.
                    action["target"] = [action["target"]["Statblock"].getCID()]
                elif isinstance(action["target"], str):
                    action["target"] = [action["target"]]
                else:
                    for i, t in enumerate(action["target"]):
                        action["target"][i] = t.getCID() if not isinstance(t, str) else t
        return overallRankings

    rankings = getBaseRankings()
    prepared = []

    for action in rankings:
        row = dict(action)

        row["base_rank"] = int(action["overallRank"])

        row["prob"] = max(0.0, min(1.0, float(row["prob"])))
        row["eDam"] = float(row["eDam"])
        row["impact"] = float(row["impact"])

        row["base_weight"] = float(row.get("base_weight", 0.0))

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
                raise Exception(f"[rankActions] ML scoring failed for {row.get('name')}: {exc}")

        prepared.append(row)

    prepared.sort(key=lambda x: x["final_weight"], reverse=True)

    for i, action in enumerate(prepared, start=1):
        action["overallRank"] = i

    for action in prepared:
        action.pop("actions", None)
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

    if not isinstance(action, Weapon):
        if action.getNumTarget() == 0:
            return True
        if action.getDamType() == "healing" or "healing" in action.getDamType():
            return True
        if action.getSpecialNotes():
            def invalidSpecialNote(note):
                note = note.lower()
                onlyType = "only" in note
                cType = note.split("only")[0].lower() if onlyType else note.split("immune")[0].lower()
                if onlyType and not any([c["Statblock"].getCreatureType().lower() == cType for c in initiative]):
                    return True
                else:
                    for c in initiative:
                        if isinstance(c["Statblock"], Monster) and c["Statblock"].getCreatureType().lower() != cType:
                            return False
                    return True
            notes = action.getSpecialNotes()
            if any([("only" in note.lower() or "immune" in note.lower()) for note in action.getSpecialNotes()]):
                for note in notes:
                    if "only" in note.lower() or "immune" in note.lower():
                        if invalidSpecialNote(note):
                            return False
                        else:
                            break

    actor_tiles = _normalize_occupied_tiles(activeInitiativeEntry["startingAnchor"])

    others_tiles = []
    for entry in initiative:
        sb = entry.get("Statblock")
        if (sb is None or sb is activeInitiativeEntry["Statblock"]
                or not isValidTarget(action, entry, activeInitiativeEntry["Statblock"], isPlayerTurn)):
            continue
        pos = sb.getPosition() if hasattr(sb, "getPosition") else sb.get("position")
        tiles = _normalize_occupied_tiles(pos)
        if tiles:
            others_tiles.append(tiles)

    if not actor_tiles or not others_tiles:
        return False

    if not isinstance(action, Weapon):
        actionRangeFeet = _as_int_feet(action.getActionRange()) + _as_int_feet(creature.getMovementMax())
    else:
        actionRangeFeet = 5 + creature.getMovementMax()
    if actionRangeFeet is None:
        return False

    rangeTiles = math.ceil(actionRangeFeet // 5)

    for target_tiles in others_tiles:
        min_d = min_creature_distance_tiles(actor_tiles, target_tiles)
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
    actionMovementReccs = []
    actionObjects = []
    actions = []

    initEntry = findInitiativeEntryByCID(creature, initiative)

    defineBasicActions(actionNames, actionTypes, actionProbs,
                       actionEDams, actionImpacts, actionTargets,
                       actionMovementReccs,
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
    mInitEntry = initEntry

    for monAction in monActions:
        if monAction.isBadObj():
            continue

        actionName = monAction.getName()

        if actionViabilityCheck(monAction, mInitEntry, initiative, False):
            try:
                actionProb = 0
                actionEDam = -1
                pMovementRecc = []
                eMovementRecc = []

                if monAction.getSelfTarget():
                    actionProb = 1.0
                    actionEDam = 0
                    probTargets = [creature.getCID()]
                    probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                    actionImpact = calcImpact(creature, monAction, actionProb,
                                              actionEDam, probTargetsNorm, initiative)
                    target = probTargets
                    movementRecc = []
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
                        probToStr += f" - {actionProb['probLingSave']}LS" if actionProb['probLingSave'] else ""
                        probTargets = actionProb["target"] if actionProb["probSuccess"] != 0 else ""
                        pMovementRecc = actionProb.get("movementRecc", [])
                    else:
                        actionProb = 0 if actionProb < 0 else actionProb
                        actionProb = 1 if actionProb > 1 else actionProb
                        probTargets = ""
                        probToStr = actionProb
                        pMovementRecc = []

                    actionProb = probToStr
                    actionEDam, eTargets, eMovementRecc = calcTotalExpectedDamage(
                        creature, monAction, initiative
                    )

                    if not probTargets and not eTargets:
                        continue

                    probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                    eTargetsNorm = normalizeTargetSets(eTargets, initiative)

                    if {target.getCID() for target in probTargetsNorm} == {target.getCID() for target in eTargetsNorm}:
                        actionImpact = calcImpact(creature, monAction, actionProb, actionEDam, probTargetsNorm, initiative)
                        target = probTargets
                        movementRecc = pMovementRecc
                    else:
                        if not probTargetsNorm and not eTargetsNorm:
                            actionImpact = 0
                            target = {}
                            movementRecc = []
                        elif not probTargetsNorm:
                            actionImpact = calcImpact(creature, monAction, actionProb,
                                                  actionEDam, eTargetsNorm, initiative)
                            target = eTargets
                            movementRecc = eMovementRecc
                        elif not eTargetsNorm:
                            actionImpact = calcImpact(creature, monAction, actionProb,
                                                  actionEDam, probTargetsNorm, initiative)
                            target = probTargets
                            movementRecc = pMovementRecc
                        else:
                            actionImpact1 = calcImpact(creature, monAction, actionProb, actionEDam, probTargetsNorm, initiative)
                            actionImpact2 = calcImpact(creature, monAction, actionProb, actionEDam, eTargetsNorm, initiative)
                            actionImpact = max([actionImpact1, actionImpact2])
                            targetIdx = [actionImpact1, actionImpact2].index(actionImpact)
                            target = probTargets if targetIdx == 0 else eTargets
                            movementRecc = pMovementRecc if targetIdx == 0 else eMovementRecc

                actionNames.append(actionName)
                actionTypes.append("monAction")
                actionProbs.append(actionProb)
                actionEDams.append(actionEDam)
                actionImpacts.append(actionImpact)
                actionTargets.append(target)
                actionMovementReccs.append(movementRecc)
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
            except:
                print("Error with", actionName)
                continue
        else:
            print(actionName, "not viable.")
            continue

    actions = []
    for i in range(len(actionNames)):
        try:
            actions.append(
                {"name": actionNames[i], "type": actionTypes[i], "prob": actionProbs[i], "eDam": actionEDams[i],
                 "percentage": actionPercentages[i], "impact": actionImpacts[i],
                 "actions": actionObjects[i], "target": actionTargets[i],
                 "movementRecc": actionMovementReccs[i]})
        except IndexError:
            actionPercentages.insert(i, 0)
    multiattack_recommendation = buildMonsterMultiattackRecommendation(
        creature,
        actions,
        initiative_entry=mInitEntry,
    )
    if multiattack_recommendation is not None:
        actions.append(multiattack_recommendation)

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
    actionMovementReccs = []
    actionObjects = []
    pInitEntry = findInitiativeEntryByCID(player, initiative)

    defineBasicActions(actionNames, actionTypes, actionProbs,
                       actionEDams, actionImpacts, actionTargets,
                       actionMovementReccs,
                       actionObjects, pInitEntry,initiative, True)
    actionPercentages.extend([0, 0, 0])
    if player.getWeaponLength() > 0:
        for i in range(player.getWeaponLength()):
            weapon = player.getWeapon(i)
            if actionViabilityCheck(weapon, pInitEntry, initiative, True):
                weaponProb = calcTotalToHitProbability(player, weapon, initiative)
                pMovementRecc = []
                if isinstance(weaponProb, dict):
                    probTargets = weaponProb["target"]
                    pMovementRecc = weaponProb.get("movementRecc", [])
                    weaponProb = weaponProb["probSuccess"]
                else:
                    try:
                        weaponProb = int(weaponProb)
                        probTargets = {}
                    except Exception:
                        weaponProb = 0
                        probTargets = {}

                weaponEDam, eTargets, eMovementRecc = calcTotalExpectedDamage(player, weapon, initiative)
                probTargetsNorm = normalizeTargetSets(probTargets, initiative)
                eTargetsNorm = normalizeTargetSets(eTargets, initiative)

                if probTargetsNorm == eTargetsNorm:
                    weaponImpact = calcImpact(player, weapon, weaponProb, weaponEDam, probTargetsNorm, initiative)
                    target = probTargets
                    movementRecc = pMovementRecc
                else:
                    if not probTargetsNorm and not eTargetsNorm:
                        weaponImpact = 0
                        target = {}
                        movementRecc = []
                    elif not probTargetsNorm:
                        weaponImpact = calcImpact(player, weapon, weaponProb, weaponEDam, eTargetsNorm, initiative)
                        target = eTargets
                        movementRecc = eMovementRecc
                    elif not eTargetsNorm:
                        weaponImpact = calcImpact(player, weapon, weaponProb, weaponEDam, probTargetsNorm, initiative)
                        target = probTargets
                        movementRecc = pMovementRecc
                    else:
                        weaponImpact1 = calcImpact(player, weapon, weaponProb, weaponEDam, probTargetsNorm, initiative)
                        weaponImpact2 = calcImpact(player, weapon, weaponProb, weaponEDam, eTargetsNorm, initiative)
                        weaponImpact = max([weaponImpact1, weaponImpact2])
                        targetIdx = [weaponImpact1, weaponImpact2].index(weaponImpact)
                        target = probTargets if targetIdx == 0 else eTargets
                        movementRecc = pMovementRecc if targetIdx == 0 else eMovementRecc

                if player.getClass().lower() in ["barbarian", "paladin", "ranger"] and player.getLevel() >= 5:
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
                actionMovementReccs.append(movementRecc)
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

    actions = []
    for i in range(len(actionNames)):
        try:
            actions.append(
                {"name": actionNames[i], "type": actionTypes[i], "prob": actionProbs[i], "eDam": actionEDams[i],
                 "percentage": actionPercentages[i], "impact": actionImpacts[i],
                 "actions": actionObjects[i], "target": actionTargets[i],
                 "movementRecc": actionMovementReccs[i]})
        except IndexError:
            actionPercentages.insert(i, 0)
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
        if creature["turnType"].lower() == "lairaction":
            todeli = ci
            continue
        creatureObj = getCreatureFromInitiativeEntry(encounter, creature)
        if creatureObj:
            creatureObj.setStartingAnchor(creature["startingAnchor"])
            creature["Statblock"] = creatureObj
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
def handle_charges(creature, spells):
    if isinstance(creature, Monster) and creature.isCaster() and not creature.hasSpellSlots():
        for spell in spells:
            spell["charges"] = str(spell["charges"])
            for i, spellData in enumerate(creature.getSpellInfo()["spells"]):
                if spellData["name"].lower() == spell["name"] and spellData["charges"] != "At Will":
                    creature.getSpellInfo()["spells"][i]["charges"] = spell["charges"]
def unpackEntry(entry, activeInitiative):
    #Used for rulesetSimulate in order to receive action data from various entries.
    actor = entry["actor"]
    actorObj = ""
    action = entry["action"]
    targets = entry["targets"]
    selectedTargets = []
    isSpell = False

    for creature in activeInitiative:
        if creature["cid"] == actor:
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
        testEID = "e9055b57-1d5a-433c-bce6-87436ecd9627"
        testCID = "6996762f-e893-4b49-9a5a-c2248c7ef1c4"

        encounter = await get_encounter_by_eid(testEID)
        encounter = loadEncounter(encounter)
        #
        # actionResult = {
        #     "action": "Hurl Flame",
        #     "actionEDam": 10,
        #     "actionImpact": 1.07,
        #     "actionProb": 0.7200000000000001,
        #     "actionRanking": 1,
        #     "actionType": "MonAction",
        #     "actor": "Barbed Devil",
        #     "base_weight": 12.057500000000001,
        #     "candidateCount": 6,
        #     "conditions": [],
        #     "extraOutcome": {
        #         "extraRollResults": [],
        #         "extraDiceResults": []
        #     },
        #     "final_weight": 7.112488384246827,
        #     "ml_weight": 7.112488384246827,
        #     "outcome": {
        #         "diceResults": [15],
        #         "rollResults": ["19"]
        #     },
        #     "resultID": "91f57a28-649c-4006-b700-502c6e2ad5bf",
        #     "statusEffects": [],
        #     "targets": ["56f5f763-4e6b-4e5f-8cc5-5046dbc0e2a9"],
        #     "timestamp": "13:54:46",
        #     "token": None,
        #     "useML": True
        # }

        creature = encounter.getMonsterByCID(testCID)

        # creature = encounter.getPlayerByCID(testCID)
        # creature.setSpellSlots(6, 0)
        # creature.setSpellSlots(5, 0)
        # await saveEncounter()
        initiative = setActiveInitiative(encounter)
        monsterTurn(creature, initiative, testEID)
        # mapdata = encounter.getMapData()
        # actorObj, action, targets, isSpell, selectedTargets = unpackEntry(actionResult, initiative)
        #                     actionResult, initiative, mapdata))


        # actorObj, action, targets, isSpell, selectedTargets = unpackEntry(actionRequest, initiative)
        #
        # if not action:
        #     return


        # await saveEncounter(encounter)

    asyncio.run(terminal_test())


if __name__ == "__main__":
    main()
