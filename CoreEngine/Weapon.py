from .Action import Action

class Weapon(Action):
    def __init__(self, name, statType, diceNum, diceType, damageType, damMod):
        super().__init__()
        self.__name = name
        self.__damageType = damageType
        self.__statType = statType
        self.setDice(diceNum, diceType, damMod)
        self.__actionCost = "action"

    def toDict(self):
        return {
            "name" : self.__name,
            "properties" : {
                "damage" : f"{self.getDiceNum()}d{self.getSides()}",
                "damageType" : self.__damageType,
                "weaponStat" : self.__statType
            }
        }

    def getName(self):
        return self.__name

    def setName(self, name):
        self.__name = name

    def getDamType(self):
        return self.__damageType

    def setDamType(self, damageType):
        self.__damageType = damageType

    def getStatType(self):
        return self.__statType

    def setStatType(self, statType):
        self.__statType = statType

    def getActionCost(self):
        return self.__actionCost