import math

from .Spell import Spell
from .Stats import Stats
from .Weapon import Weapon


class Player(Stats):
    def __init__(self, name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns, activeStatusEffects, activeConditions):
        super().__init__(stats, damImmunes, damResists, damVulns, conImmunities, activeStatusEffects, activeConditions)
        self.__name = name
        self.__class_type = class_type.lower()
        self.__level = level
        self.setMaxHP(self.__calcHP())
        if hp == -1:
            self.setHP(self.getMaxHP())
        else:
            self.setHP(hp)
        self.__profBonus = self.calcProfBonus()
        self.__spellMod = self.calcSpellMod()
        self.__dc = None
        self.__calcDC()
        self.__ac = ac
        self.__weapons = []
        self.__spells = []

    def __calcHP(self):
        hitDieType = self.__calcHitDie()
        health = hitDieType + self.getMod("CON")
        avg = math.ceil((hitDieType + 1) / 2)
        for i in range(0, self.__level):
            health += avg + self.getMod("CON")
        return health
    def __calcHitDie(self):
        if self.__class_type == "sorcerer" or self.__class_type == "wizard":
            return 6
        if (self.__class_type == "druid" or self.__class_type == "cleric" or self.__class_type == "warlock" or self.__class_type == "artificer"
                or self.__class_type == "bard" or self.__class_type == "monk" or self.__class_type == "rogue"):
            return 8
        if self.__class_type == "fighter" or self.__class_type == "paladin" or self.__class_type == "ranger":
            return 10
        if self.__class_type == "barbarian":
            return 12

    def addWeapon(self, name, statType, diceNum, diceType, damageType, weaponStat):
        weapon = Weapon(name, statType, diceNum, diceType, damageType, weaponStat)
        self.__weapons.append(weapon)
    def removeWeapon(self, name):
        for weapon in self.__weapons:
            if name == weapon.getName():
                self.__weapons.remove(weapon)
        #Removes every instance of a given weapon.
    def findWeapon(self, name):
        i = 0
        found = False
        while not found and i < len(self.__weapons):
            if self.__weapons[i].getName().lower() == name.lower():
                found = True
            else:
                i += 1
        return i if found else -1
    def getWeapon(self, idx):
        return self.__weapons[idx]
    def getWeaponLength(self):
        return len(self.__weapons)

    def addSpell(self, name, lvl, selfTarget,
                 numTarget, rollType, saveType, halfSave, damageMod, diceNum, diceType,
                 damType, conditions, statusEffects, lingEffects, extraEffect, lingSaves,
                 scaling, specialNotes):
        self.__spells.append(Spell(name, lvl, selfTarget,
                 numTarget, rollType, saveType, halfSave, damageMod, diceNum, diceType,
                 damType, conditions, statusEffects, lingEffects, extraEffect, lingSaves,
                 scaling, specialNotes))
    def removeSpell(self, name):
        for spell in self.__spells:
            if name == spell.getName():
                self.__spells.remove(spell)
        #Removes every instance of a given spell.
    def findSpell(self, name):
        i = 0
        found = False
        while not found and i < len(self.__spells):
            if self.__spells[i].getName().lower() == name.lower():
                found = True
            else:
                i += 1
        return i
    def getSpell(self, idx):
        return self.__spells[idx]
    def getSpellByName(self, name):
        for spell in self.__spells:
            if spell.getName().lower() == name.lower():
                return spell
    def getSpellLength(self):
        return len(self.__spells)

    def __getModByClass(self):
        modifier = 0
        class_to_modifier = {
            'bard': 'CHA',
            'paladin': 'CHA',
            'sorcerer': 'CHA',
            'warlock': 'CHA',
            'wizard': 'INT',
            'artificer': 'INT',
            'cleric': 'WIS',
            'druid': 'WIS',
            'ranger': 'WIS',
        }
        for type in class_to_modifier.keys():
            if type == self.__class_type.lower():
                modifier = self.getMod(class_to_modifier[type])

        return modifier
    def calcSpellMod(self):
        mod = self.__getModByClass()
        spellMod = self.__profBonus + mod

        return spellMod
    def __calcDC(self):
        modifier = self.__getModByClass()
        self.__dc = 8 + self.__profBonus + modifier
    def setClass(self, class_type):
        class_list = ["Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk",
                      "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard", "Artificer"]
        if class_type in class_list:
            self.__class_type = class_type
    def getClass(self):
        return self.__class_type
    def calcProfBonus(self):
        if 21 > self.__level > 0:
            return math.ceil(self.__level / 4) + 1
    def getProfBonus(self):
        return self.__profBonus
    def setLevel(self, level):
        self.__level = level
        self.__profBonus = self.calcProfBonus()
        self.__calcDC()
    def getLevel(self):
        return self.__level
    def getDC(self):
        return self.__dc
    def getAC(self):
        return self.__ac
    def getSpellMod(self):
        return self.__spellMod
    def setName(self, name):
        self.__name = name
    def getName(self):
        return self.__name
