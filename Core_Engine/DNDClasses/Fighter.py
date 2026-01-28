from Core_Engine.Player import Player

class Fighter(Player):
    def __init__(self, name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                 activeStatusEffects, activeConditions):
        super().__init__(name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                         activeStatusEffects, activeConditions)
        self.__abilities = [
            {
                "name" : "Second Wind",
                "lvl" : 1,
                "charge" : "1",
                "action" : {
                    "self": True,
                    "number": 1,
                    "rolls": {
                        "rollType": "autoHit",
                        "saveType": "none",
                        "halfSave": False,
                        "damage": "1d4",
                        "damageMod": "spellMod"
                    },
                    "damType": [
                        "healing"
                    ],
                    "conditions": [],
                    "statusEffect": [],
                    "lingEffect": {},
                    "extraEffect": {},
                    "lingSave": {},
                    "scaling": "1d4",
                    "specialNotes": [],
                    "actionCost": "bonus action"
                }
            },
            {
                "name" : "Action Surge",
                "lvl" : 2,
                "ability" : "extraAction",
                "charge" : "1",
                "recharge" : "shortRest"
            },
            {
                "name": "Extra attack",
                "lvl": "5",
                "total": 2,
                "split": [],
             },
            {
                "name": "Extra attack",
                "lvl": "11",
                "total": 3,
                "split": []
            },
            {
                "name": "Extra attack",
                "lvl": "20",
                "total": 4,
                "split": []
            },
        ]

    def getAbilities(self):
        if self.getLevel() < 1:
            return None
        elif self.getLevel() < 2:
            return self.__abilities[0]
        elif self.getLevel() < 5:
            return self.__abilities[0:2]
        elif self.getLevel() < 11:
            return self.__abilities[0:3]
        elif self.getLevel() < 20:
            return self.__abilities[0:4]
        else:
            return self.__abilities