from Action import Action

class Spell(Action):
    def __init__(self, name, lvl, selfTarget,
                 numTarget, rollType, saveType, halfSave, damageMod, diceNum, diceType,
                 damType, conditions, statusEffects, lingEffects, extraEffect, lingSaves,
                 scaling, specialNotes):
        super().__init__()
        self.__name = name
        self.__lvl = lvl
        self.__selfTarget = selfTarget
        self.__numTarget = numTarget
        self.__rollType = rollType
        self.__saveType = saveType
        self.__halfSave = halfSave
        self.__damType = damType
        self.__conditions = conditions
        self.__statusEffects = statusEffects
        self.__lingEffects = lingEffects
        self.__extraEffect = extraEffect
        self.__lingSaves = lingSaves
        self.__scaling = scaling
        self.__specialNotes = specialNotes

        self.setDice(diceNum, diceType, damageMod)

    def toDict(self):
        return {
            "spellname" : self.__name,
            "level" : str(self.__lvl),
            "targeting" : {
                "self" : self.__selfTarget,
                "number" : str(self.__numTarget),
                "rolls" : {
                    "rollType" : self.__rollType,
                    "saveType" : self.__saveType,
                    "halfSave" : self.__halfSave,
                    "damage" : f"{self.getDiceNum()}d{self.getSides()}" if self.getDiceNum() > 1 and self.getSides() > 1 else "",
                    "damageMod" : str(self.getDamMod())
                },
                "damType" : self.__damType,
                "conditions" : self.__conditions,
                "statusEffect" : self.__statusEffects,
                "lingEffect" : self.__lingEffects,
                "extraEffect": self.__extraEffect,
                "lingSave" : self.__lingSaves,
                "scaling" : self.__scaling,
                "specialNotes" : self.__specialNotes
            }

        }

    def getName(self):
        return self.__name
    def setName(self, value):
        self.__name = value

    def getLvl(self):
        return self.__lvl
    def setLvl(self, value):
        self.__lvl = value

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

    def getHalfSave(self):
        return self.__halfSave
    def setHalfSave(self, value):
        self.__halfSave = value

    def getDamType(self):
        return self.__damType
    def setDamType(self, value):
        self.__damType = value

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

    def getScaling(self):
        return self.__scaling
    def setScaling(self, value):
        self.__scaling = value

    def getSpecialNotes(self):
        return self.__specialNotes
    def setSpecialNotes(self, value):
        self.__specialNotes = value