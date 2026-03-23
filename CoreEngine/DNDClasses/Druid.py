import json
from CoreEngine import Player, Monster
import os

import main

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MONSTER_LIST_FILE = os.path.join(BASE_DIR, "..", "data", "monster_list_NEW.json")

class Druid(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions, cid, position, spellSlots, monster=None, wildShaped=None, wildShapeCharges=-1):
        super().__init__(name, stats, saveProfs, ac, hp, class_type,
                         level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions,
                         cid, position, spellSlots)
        self.__monster = {} if monster is None else monster
        self.__wildShaped = False if wildShaped is None else wildShaped
        self.__wildShapeCharges = 2 if wildShapeCharges is None else wildShapeCharges

    def setWildShape(self, name):
        monster = self.loadMonsterStats(name)

        activeConditions = []
        activeStatusEffects = []
        magicResist = False
        enemy = False
        spellInfo = {}

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
        actions = main.loadMonsterActions(monster)

        self.__monster = Monster(name, cr, cType, stats,hp, maxHP, ac, saveProfs,lResists, damResists,
                                damImmunes, damVulns, conImmunes,activeConditions, activeStatusEffects,
                                 lairAction, magicResist, enemy,actions, spellInfo, legActions)

    def loadMonsterStats(self, wildShapeName):
        with open(MONSTER_LIST_FILE, "r") as f:
            monsters = json.load(f)

        for monster in monsters:
            if monster["name"].lower() == wildShapeName.lower():
                return monster

        return {}

    def getMonster(self):
        return self.__monster

    def getWildShapeCharges(self):
        return self.__wildShapeCharges

    def getWildShape(self):
        return self.__monster

    def isWildShaped(self):
        return self.__wildShaped

    def toggleWildShape(self):
        if not self.__wildShaped:
            if self.__wildShapeCharges > 0:
                self.__wildShaped = True
                self.__wildShapeCharges -= 1
            else:
                return False
        else:
            self.__wildShaped = False
            return True