from CoreEngine import Player

class Cleric(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions)

        self.__turnUndeadCharges = 1
        self.__abilties = [
            {
                "name" : "Turn Undead",
                "lvl" : "2",
                "action" : {
                    "name" : "Turn Undead",
                    "desc" : "",
                    "number" : "-2",
                    "actionRange" : "30",
                    "shape" : "circle",
                    "rolls": {
                        "rollType": "save",
                        "saveType": "wisdom",
                        "halfSave": "false",
                        "damage": "",
                        "damageMod": ""
                    },
                    "damType": [],
                    "conditions": ["Frightened"],
                    "statusEffect": [],
                    "lingEffect": {},
                    "extraEffect": {},
                    "lingSave": {},
                    "actionCost" : {},
                    "specialNotes": ["undeadOnly"]
                }
            },
            {
                "name": "Destroy Undead",
                "lvl": "5",
                "action": {
                    "name": "Destroy Undead",
                    "desc": "",
                    "number": "-2",
                    "actionRange": "30",
                    "shape": "circle",
                    "rolls": {
                        "rollType": "save",
                        "saveType": "wisdom",
                        "halfSave": "false",
                        "damage": "",
                        "damageMod": ""
                    },
                    "damType": [],
                    "conditions": ["Dead"],
                    "statusEffect": [],
                    "lingEffect": {},
                    "extraEffect": {},
                    "lingSave": {},
                    "actionCost": {},
                    "specialNotes": ["undeadOnly", "crCap"]
                }
            }
        ]
        self.__destroyUndeadCap = self.setUndeadCap()

    def setUndeadCap(self):
        if self.getLevel() < 5:
            return 0
        elif self.getLevel() < 11:
            return .5
        elif self.getLevel() < 14:
            return 2
        elif self.getLevel() < 17:
            return 3
        else:
            return 4

    def useTurnUndead(self):
        self.__turnUndeadCharges = 0
    def resetTurnUndead(self):
        self.__turnUndeadCharges = 1