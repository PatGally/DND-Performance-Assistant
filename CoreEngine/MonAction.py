from .Action import Action

class MonAction(Action):
    def __init__(self, name, desc, selfTarget, numTarget, actionRange, shape,
                 rollType, saveType, saveDC, halfSave, damageMod, diceNum, diceType, attackBonus,
                 extraDamage, damType, conditions, statusEffects, lingEffects, extraEffect,
                 lingSaves, actionCost, recharge, specialNotes):
        super().__init__()
        self.__name = name
        self.__desc = desc
        self.__selfTarget = selfTarget
        self.__numTarget = numTarget
        self.__actionRange = actionRange
        self.__shape = shape
        self.__actionRadius = actionRange
        self.__rollType = rollType
        self.__saveType = saveType
        self.__saveDC = saveDC
        self.__attackBonus = attackBonus
        self.__halfSave = halfSave
        self.__extraDamage = extraDamage
        self.__damType = damType
        self.__conditions = conditions
        self.__statusEffects = statusEffects
        self.__lingEffects = lingEffects
        self.__extraEffect = extraEffect
        self.__lingSaves = lingSaves
        self.__specialNotes = specialNotes
        self.__actionCost = actionCost
        self.__recharge = recharge
        self.setDice(diceNum, diceType, damageMod)
        badObj = False
        if self.__rollType not in ["tohit", "save"] and not self.__saveType and not self.__saveDC \
            and not self.__conditions and not self.__statusEffects and not self.__lingEffects and not self.__extraEffect \
            and not self.__damType and not self.getMean():
            badObj = True
        self.__badObj = badObj

    def toDict(self):
        if not isinstance(self.__damType, list):
            damType = [self.__damType]
        else:
            damType = self.__damType
        return {
            "name" : self.__name,
            "desc" : self.__desc,
            "number" : str(self.__numTarget),
            "actionRange" : self.__actionRange,
            "shape" : self.__shape,
            "rolls": {
                "rollType": self.__rollType,
                "saveType": self.__saveType,
                "halfSave": self.__halfSave,
                "saveDC": self.__saveDC,
                "damage": f"{self.getDiceNum()}d{self.getSides()}" if self.getDiceNum() > 0 and self.getSides() in [4, 6, 8, 10, 12, 20, 100] else "",
                "attackBonus" : str(self.__attackBonus),
                "damageMod": str(self.getDamMod())
            },
            "extraDamage" : self.__extraDamage,
            "damType": damType,
            "conditions": self.__conditions,
            "statusEffect": self.__statusEffects,
            "lingEffect": self.__lingEffects,
            "extraEffect": self.__extraEffect,
            "lingSave": self.__lingSaves,
            "recharge" : self.__recharge,
            "actionCost" : self.__actionCost,
            "specialNotes": self.__specialNotes
        }

    def isBadObj(self):
        return self.__badObj

    def getName(self):
        return self.__name
    def setName(self, value):
        self.__name = value

    def getShape(self):
        return self.__shape

    def getSelfTarget(self):
        return self.__selfTarget
    def setSelfTarget(self, value):
        self.__selfTarget = value

    def getNumTarget(self):
        return self.__numTarget
    def setNumTarget(self, value):
        self.__numTarget = value

    def getRollType(self):
        return self.__rollType
    def setRollType(self, value):
        self.__rollType = value

    def getSaveType(self):
        return self.__saveType
    def setSaveType(self, value):
        self.__saveType = value

    def setDC(self, dc):
        self.__saveDC = dc
    def getDC(self):
        return self.__saveDC

    def getAttackBonus(self):
        return self.__attackBonus
    def setAttackBonus(self, ab):
        self.__attackBonus = ab

    def getHalfSave(self):
        return self.__halfSave
    def setHalfSave(self, value):
        self.__halfSave = value

    def getDamType(self):
        return self.__damType
    def setDamType(self, value):
        self.__damType = value
    def addDamType(self, dType):
        if isinstance(self.__damType, list):
            self.__damType.append(dType)
        else:
            pass

    def getConditions(self):
        return self.__conditions
    def setConditions(self, value):
        self.__conditions = value

    def getStatusEffects(self):
        return self.__statusEffects
    def setStatusEffects(self, value):
        self.__statusEffects = value

    def getLingEffects(self):
        return self.__lingEffects
    def setLingEffects(self, value):
        self.__lingEffects = value

    def getExtraEffect(self):
        return self.__extraEffect
    def setExtraEffect(self, value):
        self.__extraEffect = value

    def getLingSaves(self):
        return self.__lingSaves
    def setLingSaves(self, value):
        self.__lingSaves = value

    def getSpecialNotes(self):
        return self.__specialNotes
    def setSpecialNotes(self, value):
        self.__specialNotes = value

    def getActionCost(self):
        return self.__actionCost

    def getActionRange(self):
        return self.__actionRange
    def setActionRange(self, ar):
        self.__actionRange = ar

    def getActionRadius(self):
        return self.__actionRadius
    def setActionRadius(self, value):
        self.__actionRadius = value