import json
import os

from CoreEngine import Player

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SPELL_LIST_FILE = os.path.join(BASE_DIR, "..", "data", "spell_list_NEW.json")


class Bard(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions)
        self.__bardicCharges = self.setBardicCharges()
        self.__bardicDieType = self.setDieType()
        self.__magicalSecrets = []

    def setDieType(self):
        if self.getLevel() < 5:
            return 6
        elif 5 <= self.getLevel() < 10:
            return 8
        elif 10 <= self.getLevel() < 15:
            return 10
        elif 15 <= self.getLevel() <= 20:
            return 12
    def getDieType(self):
        return self.__bardicDieType

    def setBardicCharges(self):
        if self.getMod("CHA") == 0:
            return 1
        else:
            return self.getMod("CHA")
    def getBardicCharges(self):
        return self.__bardicCharges
    def useBardicCharges(self):
        self.__bardicCharges = self.setBardicCharges() - 1
    def resetBardicCharges(self):
        if self.getMod("CHA") == 0:
            return 1
        else:
            self.__bardicCharges = self.getMod("CHA")
            return self.__bardicCharges

    def getMagicalSecret(self, magicalSecret):
        with open(SPELL_LIST_FILE, "r") as f:
            spells = json.load(f)

        for spell in spells:
            if spell["name"].lower() == magicalSecret.lower():
                return spell

        return {}
    def addMagicalSecret(self, magicalSecret):
        if self.checkMagicalSecrets():
            spell = self.getMagicalSecret(magicalSecret)
            spellName = spell["spellname"]
            spellLvl = spell["level"]

            if isinstance(spell["targeting"], list) and len(spell["targeting"]) > 1: #Multiple possible effects
                for spellTarget in spell["targeting"]:
                    newSpell = {
                        "spellname": spellTarget["targetType"],
                        "level": spellLvl,
                        "targeting": spellTarget
                    }
                    self.addMagicalSecret(newSpell) #Adds the multiple types of effects as individual spells.
            else:
                if isinstance(spell["targeting"], list):
                    targeting = spell["targeting"][0]
                else:
                    targeting = spell["targeting" ]
                selfTarget = targeting["self"]
                targetNum = targeting["number"]
                damType = targeting["damType"]
                if len(damType) == 1:
                    damType = damType[0]
                conditions = None
                if len(targeting["conditions"]) != 0:
                    conditions = targeting["conditions"]
                statusEffect = None
                if targeting["statusEffect"]:
                    statusEffect = targeting["statusEffect"]
                lingEffect = None
                if targeting["lingEffect"]:
                    lingEffect = targeting["lingEffect"]
                extraEffect = None
                if targeting["extraEffect"]:
                    extraEffect = targeting["extraEffect"]
                lingSaves = None
                if targeting["lingSave"]:
                    lingSaves = targeting["lingSave"]
                scaling = targeting["scaling"]
                specialNotes = None
                if len(targeting["specialNotes"]) != 0:
                    specialNotes = targeting["specialNotes"]
                actionCost = targeting["actionCost"]

                spellRolls = targeting["rolls"]
                rollType = spellRolls["rollType"]
                saveType = spellRolls["saveType"]
                halfSave = spellRolls["halfSave"]
                damageDice = spellRolls["damage"]
                diceNum = 0
                diceType = 0
                if damageDice != "":
                    damageDice = damageDice.split("d")
                    diceNum = int(damageDice[0])
                    diceType = int(damageDice[1])
                damageMod = 0
                if "damageMod" in spellRolls: #Accounts for schema error
                    if spellRolls["damageMod"] == "spellMod":
                        damageMod = self.getSpellMod()
                    elif spellRolls["damageMod"] != "":
                        damageMod = int(spellRolls["damageMod"])

                if spellLvl == 0:
                    # Cantrips scale at lvls 5, 11, and 17.
                    if scaling and "d" in scaling:
                        if self.getLevel() >= 5:
                            diceNum += 1
                            if self.getLevel() >= 11:
                                diceNum += 1
                                if self.getLevel() >= 17:
                                    diceNum += 1
                    elif scaling and "extraTarget" in scaling:
                        if self.getLevel() >= 5:
                            targetNum += 1
                            if self.getLevel() >= 11:
                                targetNum += 1
                                if self.getLevel() >= 17:
                                    targetNum += 1

                self.addSpell(spellName, spellLvl, selfTarget,
                                targetNum, rollType, saveType, halfSave, damageMod, diceNum, diceType,
                                damType, conditions, statusEffect, lingEffect, extraEffect, lingSaves,
                                scaling, actionCost, specialNotes)

            self.__magicalSecrets.append(spellName)
    def checkMagicalSecrets(self):
        if self.getLevel() < 10:
            if len(self.__magicalSecrets) >= 0:
                return False
        elif 10 <= self.getLevel() < 14:
            if len(self.__magicalSecrets) >= 2:
                return False
            else:
                return True
        elif 14 <= self.getLevel() < 18:
            if len(self.__magicalSecrets) >= 4:
                return False
            else:
                return True
        elif 18 <= self.getLevel() <= 20:
            if len(self.__magicalSecrets) >= 6:
                return False
            else:
                return True
        return False
