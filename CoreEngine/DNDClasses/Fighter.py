from CoreEngine.Player import Player

class Fighter(Player):
    def __init__(self, name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                 activeStatusEffects, activeConditions):
        super().__init__(name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                         activeStatusEffects, activeConditions)
        self.__secondWindCharges = 1
        self.__actionSurgeCharges = 1
        if self.getLevel() < 5:
            self.__extraAttackAmt = 0
        elif self.getLevel() < 11:
            self.__extraAttackTotal = 2
        elif self.getLevel() < 20:
            self.__extraAttackAmt = 3
        else:
            self.__extraAttackAmt = 4
        self.__abilities = [
            {
                "name" : "Second Wind",
                "lvl" : "1",
                "charge" : "1",
                "action" : {
                    "self": "true",
                    "number": "1",
                    "rolls": {
                        "rollType": "autoHit",
                        "saveType": "none",
                        "halfSave": "false",
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
                "lvl" : "2",
                "ability" : "extraAction",
                "charge" : "1",
                "recharge" : "shortRest"
            },
            {
                "name": "Extra attack",
                "lvl": "5",
                "total": "2",
                "split": [],
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

    def useSecondWind(self):
        self.__secondWindCharges = 0
    def resetSecondWind(self):
        self.__secondWindCharges = 1

    def useActionSurge(self):
        self.__actionSurgeCharges = 0
    def resetActionSurge(self):
        self.__actionSurgeCharges = 1

