from CoreEngine import Player

class Barbarian(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions)
        self.__rageCharges = self.calcRageCharges()
        self.__abilities = [
            {
                "name": "Extra Attack",
                "lvl" : "5",
                "total": 2,
            },
            {
                "name": "Reckless Attack",
                "lvl": "2",
                    "action" :{
                        "name": "Reckless Attack",
                        "desc": "",
                        "actionRange": "10",
                        "numTarget": "0",
                        "shape": "",

                        "rolls": {
                            "rollType": "autoHit",     # or "save"
                            "saveType": "",        # "STR", "CON", "DEX", etc
                            "halfSave": "",
                            "saveDC": "",
                            "damage": "",          # e.g. "2d6"
                            "attackBonus": "",
                            "damMod": ""
                        },

                        "damType": [],
                        "conditions": [],
                        "statusEffect": [
                            {
                                "name": "Advantage",
                                "effect": {
                                    "roll": "4",
                                    "attribute": ["attack rolls for"],
                                    "resultID": []
                                },
                            },
                            {
                                "name": "Advantage",
                                "effect": {
                                    "roll": "4",
                                    "attribute": ["attack rolls against"],
                                    "resultID": []
                                },
                            }
                        ],
                        "lingEffect": {},
                        "extraEffect": {},
                        "lingSave": {},

                        "actionCost": "free action",
                        "recharge": [],
                        "specialNotes": [],
                        "extraDamage": []
                    }
            },

         ]

    def calcRageCharges(self):
        if self.getLevel() >= 1 and self.getLevel() <= 2:
            return 2
        elif self.getLevel() >= 3 and self.getLevel() <= 5:
            return 3
        elif self.getLevel() >= 6 and self.getLevel() <= 11:
            return 4
        elif self.getLevel() >= 12 and self.getLevel() <= 16:
            return 5
        elif self.getLevel() >= 17 and self.getLevel() <= 19:
            return 6
        elif self.getLevel() == 20:
            return 999
        return -1
