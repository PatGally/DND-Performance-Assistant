from .Stats import Stats

class Monster(Stats):
    def __init__(self, name, cr, cType, stats, hp, maxHP, ac, saveProfs, lResists, damResists, damImmunes, damVulns,
                 conImmunes, activeConditions, activeStatusEffects, lairAction, magicResist,
                 enemy, actions, spellInfo, legActions):
        super().__init__(stats, saveProfs, damImmunes, damResists, damVulns, conImmunes, activeStatusEffects, activeConditions)
        self.__name = name
        self.__cr = cr
        self.__creatureType = cType
        self.setHP(hp)
        self.setMaxHP(maxHP)
        self.__ac = ac
        self.__lResists = lResists
        self.__lairAction = lairAction
        self.__magicResist = magicResist
        self.__enemy = enemy
        self.__actions = actions
        self.__spellInfo = spellInfo
        self.__caster = True if spellInfo else False
        self.__legActions = legActions

    def setName(self, name):
        self.__name = name
    def getName(self):
        return self.__name
    def setLevel(self, cr):
        self.__cr = cr
    def getLevel(self):
        return self.__cr
    def setCreatureType(self, creatureType):
        self.__creatureType = creatureType
    def getCreatureType(self):
        return self.__creatureType
    def setAC(self, ac):
        self.__ac = ac
    def getAC(self):
        return self.__ac
    def setlResists(self, lResists):
        self.__lResists = lResists
    def getlResists(self):
        return self.__lResists
    def hasLairAction(self):
        return self.__lairAction
    def isEnemy(self):
        return self.__enemy
    def hasLegAction(self):
        return True if self.__legActions else False
    def getLegAction(self, name):
        lIdx = -1
        lList = [l["name"].lower() for l in self.__legActions]
        if name in lList:
            lIdx = lList.index(name)
        if lIdx != -1:
            return self.__legActions[lIdx]
        return {}

    def toDict(self):
        actions = [action.toDict() for action in self.__actions]
        return {
            "name" : self.__name,
            "cr" : self.__cr,
            "creatureType" : self.__creatureType,
            "stats": [str(self.getStat(stat)) for stat in
                          ["STR", "DEX", "CON", "INT", "WIS", "CHA"]],
            "hp" : str(self.getHP()),
            "maxHP" : str(self.getMaxHP()),
            "ac" : str(self.__ac),
            "saveProfs": [str(self.getSaveProf(stat)) for stat in
                      ["STR", "DEX", "CON", "INT", "WIS", "CHA"]],
            "lResists" : self.__lResists,
            "damResists" : self.getDamResistances(),
            "damImmunes" : self.getDamImmunities(),
            "damVulns" : self.getDamVulnerabilities(),
            "conImmunes" : self.getConImmunities(),
            "activeCons" : self.getActiveConditions(),
            "activeStatusEffects" : self.getActiveStatusEffects(),
            "magicResist" : self.__magicResist,
            "lairAction" : self.__lairAction,
            "enemy": self.__enemy,
            "actions" : actions,
            "legActions" : self.__legActions,
            "spellInfo" : self.__spellInfo
        }
