import math


class Stats:
    def __init__(self, stats, damImmunes, damResists, damVulns, conImmunes, activeStatusEffects, activeConditions):
        self.__stats = {
            "STR": stats[0],
            "DEX": stats[1],
            "CON": stats[2],
            "INT": stats[3],
            "WIS": stats[4],
            "CHA": stats[5]
        }
        self.__modifiers = self.calcMods()
        self.__health = 0
        self.__maxHealth = 0
        self.__damResists = damResists
        self.__damImmunes = damImmunes
        self.__damVulns = damVulns
        self.__conImmunes = conImmunes
        self.__activeStatusEffects = activeStatusEffects
        self.__activeConditions = activeConditions

    def setHP(self, hp):
        self.__health = hp

    def getHP(self):
        return self.__health

    def setMaxHP(self, max):
        self.__maxHealth = max

    def getMaxHP(self):
        return self.__maxHealth

    def calcMods(self):
        modifiers = {}
        for stat in self.__stats:
            mod = math.floor((self.__stats[stat] - 10) / 2)
            modifiers[stat] = mod
        return modifiers

    def updateStat(self, stat, value):
        if (stat in self.__stats) and value:
            self.__stats[stat] = value
            self.__modifiers[stat] = math.floor((value - 10) / 2)

    def getStat(self, stat):
        return self.__stats[stat]

    def getMod(self, stat):
        return self.__modifiers[stat]

    def getDamImmunities(self):
        return self.__damImmunes
    def isImmune(self, damType):
        return True if damType in self.__damImmunes else False
    def addDamImmunity(self, damType):
        self.__damImmunes.append(damType)
    def removeDamImmunity(self, damType):
        self.__damImmunes.remove(damType)
        return True

    def getDamResistances(self):
        return self.__damResists
    def isResistant(self, damType):
        return True if damType in self.__damResists else False
    def addDamResist(self, damType):
        self.__damResists.append(damType)
    def removeDamResist(self, damType):
        self.__damResists.remove(damType)
        return True

    def getDamVulnerabilities(self):
        return self.__damVulns
    def isVulnerable(self, damType):
        return True if damType in self.__damVulns else False
    def addDamVulnerability(self, damType):
        self.__damVulns.append(damType)
    def removeDamVulnerability(self, damType):
        self.__damVulns.remove(damType)
        return True

    def getConImmunities(self):
        return self.__conImmunes
    def addConImmunity(self, condition):
        self.__conImmunes.append(condition)
    def removeConImmunity(self, condition):
        if condition in self.__conImmunes:
            self.__conImmunes.remove(condition)
    def isActiveConImmunity(self, condition):
        if condition.lower() in [c.lower() for c in self.__conImmunes]:
            return True

    def getActiveStatusEffects(self):
        return self.__activeStatusEffects
    def getActiveStatusEffect(self, effect):
        for status in self.__activeStatusEffects:
            if effect.lower() == status["name"].lower():
                return status
        return None
    def addStatusEffect(self, effect):
        effect["name"] = effect["name"].lower()
        self.__activeStatusEffects.append(effect)
    def removeStatusEffect(self, effectName):
        for i, effect in enumerate(self.__activeStatusEffects):
            if effect["name"].lower() == effectName.lower():
                self.__activeStatusEffects.remove(effect)
                return True
        return False
    def isActiveStatusEffect(self, effect):
        for status in self.__activeStatusEffects:
            if effect.lower() == status["name"].lower():
                return True
        return False

    def getActiveConditions(self):
        return self.__activeConditions
    def addCondition(self, condition):
        if isinstance(condition, dict):
            condition["cond"] = condition["cond"].lower()
        else:
            condition = condition.lower()
        self.__activeConditions.append(condition)
    def removeCondition(self, conditionName):
        for i, condition in enumerate(self.__activeConditions):
            if isinstance(condition, dict) and conditionName.lower() == condition["cond"].lower():
                self.__activeConditions.remove(condition)
                return True
            elif not isinstance(condition, dict) and conditionName.lower() == condition.lower():
                self.__activeConditions.remove(condition)
                return True
        return False
    def isActiveCondition(self, condition):
        for cond in self.__activeConditions:
            if isinstance(cond, dict):
                if cond["cond"].lower() == condition.lower():
                    return True
            elif cond.lower() == condition.lower():
                    return True
        return False


