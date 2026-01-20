import math

class Action:
    def __init__(self):
        self.__dice = 0
        self.__sides = 0
        self.__mean = 0
        self.__var = 0
        self.__stdev = 0
        self.__damMod = 0

    def calcMean(self):
        if self.__sides != 0 and self.__dice != 0:
            return ((sum([int(i) for i in range(1, self.__sides + 1)]) / self.__sides) * self.__dice) + self.__damMod
        return 0 + self.__damMod

    def setDice(self, diceNum, sidesNum, damMod):
        self.__dice = diceNum
        self.__sides = sidesNum
        self.__damMod = damMod
        self.__mean = self.calcMean()
        self.__var = self.calcVar()
        self.__stdev = math.sqrt(self.__var)

    def calcVar(self):
        if self.__sides != 0:
            one_die_mean = (self.__sides + 1) / 2
            var = (sum((i - one_die_mean) ** 2 for i in range(1, self.__sides + 1)) / self.__sides) * self.__dice
            return var
        return 0

    def getDiceNum(self):
        return self.__dice
    def setDiceNum(self, diceNum):
        self.__dice = diceNum

    def getSides(self):
        return self.__sides
    def setSides(self, sidesNum):
        self.__sides = sidesNum

    def getMean(self):
        return self.__mean
    def setMean(self, mean):
        self.__mean = mean
    def getVariance(self):
        return self.__var
    def setVariance(self, var):
        self.__var = var

    def getStDev(self):
        return self.__stdev
    def setStDev(self, stdev):
        self.__stdev = stdev

    def getDamMod(self):
        return self.__damMod
    def setDamMod(self, damMod):
        self.__damMod = damMod