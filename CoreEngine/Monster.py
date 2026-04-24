from .MonAction import MonAction
from .Stats import Stats

class Monster(Stats):
    def __init__(self, name, cr, cType, stats, hp, maxHP, ac, saveProfs, lResists, damResists, damImmunes, damVulns,
                 conImmunes, activeConditions, activeStatusEffects, lairAction, magicResist,
                 enemy, actions, spellInfo, legActions, cid, position, size, movement):
        super().__init__(stats, saveProfs, damImmunes,
                         damResists, damVulns, conImmunes,
                         activeStatusEffects, activeConditions, cid, position)
        self.__name = name
        self.__cr = cr
        self.calcProfBonus()
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
        self.__caster = True if spellInfo.get("spells", []) else False
        self.__legActions = legActions
        self.__size = size
        self.__movement = movement

    def setName(self, name):
        self.__name = name
    def getName(self):
        return self.__name
    def setLevel(self, cr):
        self.__cr = cr
    def getLevel(self):
        return self.__cr
    def calcProfBonus(self):
        def _cr_to_float(cr_str: str) -> float:
            """'1/4' -> 0.25, '2' -> 2.0"""
            s = str(cr_str).strip()
            if "/" in s:
                num, den = s.split("/")
                return float(num) / float(den)
            return float(s)
        cr = _cr_to_float(self.__cr)
        if cr <= 4:
            pb = 2
        elif cr <= 8:
            pb = 3
        elif cr <= 12:
            pb = 4
        elif cr <= 16:
            pb = 5
        elif cr <= 20:
            pb = 6
        elif cr <= 24:
            pb = 7
        elif cr <= 28:
            pb = 8
        else:
            pb = 9
        self.__profBonus = pb
    def getProfBonus(self):
        return self.__profBonus
    def setSpellSlots(self,level, slotAmount):
        slotIndex = level -1
        spells = self.getSpellInfo()
        spells = spells.get("spellSlots", [])
        if not (0 <= slotIndex < len(spells)):
            raise ValueError("Invalid spell slot level")
        if spells[slotIndex][1] != 0:
            spells[slotIndex][0] = int(slotAmount)
            self.__spellInfo["spellSlots"] = spells

    def getSpellSlots(self):
        return self.__spellInfo.get("spellSlots", [])
    def getSpellSlot(self, lvl):
        slotIdx = int(lvl) - 1
        if self.isCaster() and "spellSlots" in self.__spellInfo and self.__spellInfo["spellSlots"]:
            return int(self.__spellInfo["spellSlots"][slotIdx][0])
        else:
            return 0

    def hasSpellSlots(self):
        return self.isCaster() and "spellSlots" in self.__spellInfo and self.__spellInfo["spellSlots"]


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

    def getSpellMod(self):
        if self.isCaster():
            statType = self.__spellInfo["type"]
            if statType:
                mod = self.getMod(statType)
                pB = self.getProfBonus()
                return mod + pB
            else:
                return 0
        else:
            return 0

    def isCaster(self):
        return self.__caster
    def getSpellInfo(self):
        if self.isCaster():
            return self.__spellInfo
    def getDC(self):
        if self.isCaster():
            return int(self.__spellInfo["DC"])
        return 8 + self.getProfBonus() + self.getMod("STR")
    def getSpellAttack(self):
        if self.isCaster():
            return int(self.__spellInfo["attackRoll"])
        return 0
    def addSpell(self, name, charges=0):
        if charges == 0:
            self.__spellInfo["spells"].append({"name" : name})
        else:
            self.__spellInfo["spells"].append({"name" : name, "charges" : charges})
    def removeSpell(self, name):
        for spell in self.__spellInfo["spells"]:
            if name.lower() == spell["name"].lower():
                self.__spellInfo["spells"].remove(spell)
        #Removes every instance of a given spell.
    def findSpell(self, name):
        i = 0
        found = False
        while not found and i < len(self.__spellInfo["spells"]):
            if self.__spellInfo["spells"][i]["name"].lower() == name.lower():
                found = True
            else:
                i += 1
        return i
    def getSpell(self, idx):
        return self.__spellInfo["spells"][idx]
    def getSpellByName(self, name):
        for spell in self.__spellInfo["spells"]:
            if spell["name"].lower() == name.lower():
                return spell
    def getSpellLength(self):
        return len(self.__spellInfo["spells"])

    def addAction(self, name, desc, selfTarget, numTarget, actionRange, shape,
                 rollType, saveType, saveDC, halfSave, damageMod, diceNum, diceType, attackBonus,
                 extraDamage, damType, conditions, statusEffects, lingEffects, extraEffect,
                 lingSaves, actionCost, recharge, specialNotes):
        self.__actions.append(MonAction(name, desc, selfTarget, numTarget, actionRange, shape,
                 rollType, saveType, saveDC, halfSave, damageMod, diceNum, diceType, attackBonus,
                 extraDamage, damType, conditions, statusEffects, lingEffects, extraEffect,
                 lingSaves, actionCost, recharge, specialNotes))
    def removeAction(self, name):
        for action in self.__actions:
            if name.lower() == action["name"].lower():
                self.__actions.remove(action)
        # Removes every instance of a given spell.
    def findAction(self, name):
        i = 0
        found = False
        while not found and i < len(self.__actions):
            if self.__actions.getName().lower() == name.lower():
                found = True
            else:
                i += 1
        return i
    def getAction(self, idx):
        return self.__actions[idx]
    def getActionByName(self, name):
        for action in self.__actions:
            if isinstance(action, MonAction):
                if action.getName().lower() == name.lower():
                    return action
            elif action["name"].lower() == name.lower():
                return action
        return None
    def getActionLength(self):
        return len(self.__actions)

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

    def getSize(self):
        return self.__size

    def setSize(self, val : str):
        self.__size = val

    def toDict(self):
        def stripSpellData(p_spellInfo):
            for i, spell in enumerate(p_spellInfo["spells"]):
                if "spellData" in spell:
                    del p_spellInfo["spells"][i]["spellData"]
            return p_spellInfo
        actions = [action.toDict() for action in self.__actions]
        spellInfo = stripSpellData(self.__spellInfo)
        return {
            "name" : self.__name,
            "cr" : self.__cr,
            "creatureType" : self.__creatureType,
            "statArray": {stat : str(self.getStat(stat)) for stat in
                          ["STR", "DEX", "CON", "INT", "WIS", "CHA"]},
            "hp" : str(self.getHP()),
            "maxhp" : str(self.getMaxHP()),
            "cid" : str(self.getCID()),
            "position" : self.getPosition(),
            "ac" : str(self.__ac),
            "saveProfs": {stat : str(self.getSaveProf(stat)) for stat in
                      ["STR", "DEX", "CON", "INT", "WIS", "CHA"]},
            "lResists" : self.__lResists,
            "damResists" : self.getDamResistances(),
            "damImmunes" : self.getDamImmunities(),
            "damVulns" : self.getDamVulnerabilities(),
            "conImmunes" : self.getConImmunes(),
            "activeCons" : self.getActiveConditions(),
            "activeStatusEffects" : self.getActiveStatusEffects(),
            "magicResist" : self.__magicResist,
            "lairAction" : self.__lairAction,
            "enemy": self.__enemy,
            "actions" : actions,
            "legActions" : self.__legActions,
            "spellInfo" : spellInfo,
            "movement" : self.__movement,
            "size" : self.__size
        }
