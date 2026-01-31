from CoreEngine import Player

class Barbarian(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions)
        self.__rageCharges = self.calcRageCharges()
        self.__isRaging = False
        self.__abilities = [
            {
                "name" : "Rage",
                "lvl" : "1",
                "action" : {
                    "action": {
                        "name": "Rage",
                        "desc": "",
                        "actionRange": "",
                        "numTarget": "0",
                        "shape": "",
                        "rolls": {
                            "rollType": "autoHit",
                            "saveType": "",
                            "halfSave": "",
                            "saveDC": "",
                            "damage": "",
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
                                    "attribute": ["STR save"],
                                    "resultID": []
                                },
                            },
                            {
                                "name": "Resistance",
                                "effect": {
                                    "damage": "/2",
                                    "attribute": ["bludgeoning", "piercing", "slashing"]
                                }
                            },
                            {
                                "name": "Buff",
                                "effect": {
                                    "roll": "3",
                                    "attribute": [
                                        "ALL damage"
                                    ]
                                }
                            },
                        ],
                        "lingEffect": {},
                        "extraEffect": {},
                        "lingSave": {},

                        "actionCost": "free action",
                        "recharge": [],
                        "specialNotes": [],
                        "extraDamage": []
                    }
                }
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
                            "rollType": "autoHit",
                            "saveType": "",
                            "halfSave": "",
                            "saveDC": "",
                            "damage": "",
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
            {
                "name": "Extra Attack",
                "lvl": "5",
                "total": "2",
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

    def getAbilities(self):
        if self.getLevel() < 1:
            return None
        elif self.getLevel() < 2:
            return self.__abilities[0]
        elif self.getLevel() < 5:
            return self.__abilities[0:2]
        else:
            return self.__abilities

    def getRageCharges(self):
        return self.__rageCharges

    def toggleRage(self):
        if not self.__isRaging:
            if self.__rageCharges> 0:
                self.__isRaging = True
                self.__rageCharges -= 1
            else:
                return False
        else:
            self.__isRaging = False
            return True
