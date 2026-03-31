import math


class Stats:
    def __init__(self, stats, saveProfs, damImmunes, damResists, damVulns, conImmunes,
                 activeStatusEffects, activeConditions, cid, position):
        self.__stats = stats
        self.__modifiers = self.calcMods()
        if saveProfs:
            self.__saveProfs = saveProfs
        else:
            self.__saveProfs = {
            "STR": self.__modifiers["STR"],
            "DEX": self.__modifiers["DEX"],
            "CON": self.__modifiers["CON"],
            "INT": self.__modifiers["INT"],
            "WIS": self.__modifiers["WIS"],
            "CHA": self.__modifiers["CHA"]
            }
        self.__health = 0
        self.__maxHealth = 0
        self.__damResists = damResists
        self.__damImmune = damImmunes
        self.__damVulns = damVulns
        self.__conImmunes = conImmunes
        self.__activeStatusEffects = activeStatusEffects
        self.__activeConditions = activeConditions
        self.__cid = cid
        self.__position = position

    def getCID(self):
        return self.__cid

    def setPosition(self, positions):
        self.__position = (positions)

    def getPosition(self):
        return self.__position

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

    def getSaveProf(self, stat):
        return self.__saveProfs[stat]
    def setSaveProf(self, stat, mod):
        self.__saveProfs[stat] = mod
    def setAllDamImmunes(self, damImmunes):
        self.__damImmune = damImmunes
    def getDamImmunities(self):
        return self.__damImmune
    def isImmune(self, damType):
        return True if damType in self.__damImmune else False
    def addDamImmunity(self, damType):
        self.__damImmune.append(damType)
    def removeDamImmunity(self, damType):
        self.__damImmune.remove(damType)
        return True
    def setAllDamResistances(self, damResists):
        self.__damResists = damResists
    def getDamResistances(self):
        return self.__damResists
    def isResistant(self, damType):
        return True if damType in self.__damResists else False
    def addDamResist(self, damType):
        self.__damResists.append(damType)
    def removeDamResist(self, damType):
        self.__damResists.remove(damType)
        return True

    def setAllDamVuls(self, damVulns):
        self.__damVulns = damVulns
    def getDamVulnerabilities(self):
        return self.__damVulns
    def isVulnerable(self, damType):
        return True if damType in self.__damVulns else False
    def addDamVulnerability(self, damType):
        self.__damVulns.append(damType)
    def removeDamVulnerability(self, damType):
        self.__damVulns.remove(damType)
        return True

    def setAllConImmuns(self, conImmuns):
        self.__conImmunes = conImmuns
    def getConImmunes(self):
        return self.__conImmunes
    def addConImmunity(self, condition):
        self.__conImmunes.append(condition)
    def removeConImmunity(self, condition):
        if condition in self.__conImmunes:
            self.__conImmunes.remove(condition)
    def isActiveConImmunity(self, condition):
        if condition.lower() in [c.lower() for c in self.__conImmunes]:
            return True

    def setAllActiveStatusEffects(self, newStatus):
        self.__activeStatusEffects = newStatus

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
    def setAllActiveConditions(self, newActiveCons):
        self.__activeConditions = newActiveCons

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


