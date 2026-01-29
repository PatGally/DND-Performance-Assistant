import json
from CoreEngine import Player, Monster
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MONSTER_LIST_FILE = os.path.join(BASE_DIR, "..", "data", "monster_list_NEW.json")

class Druid(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions)
        self.__monster = None

    def setWildShape(self, name):
        monster = self.loadMonsterStats(name)

        activeConditions = ""
        activeStatusEffects = ""
        magicResist = False
        enemy = False
        actions = []
        spellInfo = None

        name = monster["name"]
        cr = int(monster["cr"])
        cType = monster["creatureType"]
        stats = monster["statArray"]
        maxHP = int(monster["hit_points"])
        hp = maxHP
        ac = int(monster["AC"])
        saveProfs = monster["saveProfs"]
        lResists = monster["lResists"]
        damResists = monster["damResists"]
        damImmunes = monster["damImmunes"]
        damVulns = monster["damVulns"]
        conImmunes = monster["conImmunes"]
        lairAction = monster["lairAction"]
        legActions = monster["legAction"]

        self.__monster = Monster(name, cr, cType, stats,hp, maxHP, ac, saveProfs,lResists, damResists,
                                damImmunes, damVulns, conImmunes,activeConditions, activeStatusEffects,
                                 lairAction, magicResist, enemy,actions, spellInfo, legActions)

    def loadMonsterStats(self, wildShapeName):
        with open(MONSTER_LIST_FILE, "r") as f:
            monsters = json.load(f)

        for monster in monsters:
            if monster["name"] == wildShapeName:
                return monster

        raise ValueError(f"Monster '{wildShapeName}' not found")

    def getWildShape(self):
        return self.__monster