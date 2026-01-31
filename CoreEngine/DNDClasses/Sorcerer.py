from CoreEngine import Player
class Sorcerer(Player):
    def __init__(self, lvl, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions)
        self.__sorceryPoints = 0
        self.__className = "Sorcerer"
        self.__lvl = lvl
        self.setPoints()
        self.__metamagics = [
            {
                "name" : "Careful Spell",
                "cost" : "1",
                "ability" : "autosuccess",
                "numTarget" : "CHA",
                "attribute" : ["ALL save"]
            },
            {
                "name" : "Distant Spell",
                "cost" : "1",
                "ability" : "range *2",
                "numTarget" : "1",
                "attribute" : ["attack rolls for"]
            },
            {
                "name" : "Empowered Spell",
                "cost" : "1",
                "ability" : "reroll",
                "numTarget" : "CHA",
                "attribute" : ["ALL damage"]
            },
            {
                "name" : "Heightened Spell",
                "cost" : "3",
                "ability" : "disadvantage",
                "numTarget" : "1",
                "attribute" : ["ALL save"]
            },
            {
                "name" : "Quickened Spell",
                "cost" : "2",
                "ability" : "action -> bonus action",
                "numTarget" : "1",
                "attribute" : ["ALL spells"]
            },
            {
                "name" : "Seeking Spell",
                "cost" : "2",
                "ability" : "reroll",
                "numTarget" : "1",
                "attribute" : ["ALL attack rolls"]
            },
            {
                "name" : "Transmuted Spell",
                "cost" : "1",
                "ability" : "damType -> damType",
                "numTarget" : "1",
                "attribute" : ["ALL spells"]
            },
            {
                "name" : "Twinned Spell",
                "cost" : "spellLvl",
                "ability" : "numTarget *2",
                "numTarget" : "1",
                "attribute" : ["ALL spells"],
                "specialNotes" : ["numTarget=1 required"]
            }
        ]
        self.__chosenMetamagics = []

    def setPoints(self):
        if self.__lvl > 1:
            self.__sorceryPoints = self.__lvl
        else:
            self.__sorceryPoints = 0
    def regainPoints(self, amt):
        self.__sorceryPoints += amt
    def usePoints(self, amt):
        self.__sorceryPoints -= amt

    def displayMetamagics(self):
        return [m["name"] for m in self.__metamagics]
    def chooseMetaMagic(self, choice):
        reject = False
        if self.__lvl < 2:
            reject = True
        elif self.__lvl < 10:
            if len(self.__chosenMetamagics) >= 2:
                reject = True
        elif self.__lvl < 17:
            if len(self.__chosenMetamagics) >= 3:
                reject = True
        elif self.__lvl < 21:
            if len(self.__chosenMetamagics) >= 4:
                reject = True
        else:
            reject = True
        if reject:
            return False

        choiceIdx = [m["name"].lower() for m in self.__metamagics].index(choice.lower())
        if choice.lower() not in [m["name"].lower() for m in self.__chosenMetamagics]:
            self.__chosenMetamagics.append(self.__metamagics[choiceIdx])
            return True
        return False #Already added!

    def executeMetaMagic(self, choiceIdx): #TODO
        pass