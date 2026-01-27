from Player import Player

class Ranger(Player):
    def __init__(self, lvl, name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                 activeStatusEffects, activeConditions):
        super().__init__(name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                         activeStatusEffects, activeConditions)
        self.__abilities = [
            {
                "name": "Extra attack",
                "lvl" : "5",
                "total": 2,
                "split": []
            },
            {
                "name" : "Vanish",
                "lvl" : "14",
                "action" :   {
                    "spellname": "Hide",
                    "targeting": [
                      {
                        "self": True,
                        "number": 0,
                        "rolls": {
                          "rollType": "autoHit",
                          "saveType": "none",
                          "halfSave": False,
                          "damage": "",
                          "damageMod": ""
                        },
                        "damType": [
                          ""
                        ],
                        "conditions": [
                          "Invisible"
                        ],
                        "statusEffect": [],
                        "lingEffect": {},
                        "extraEffect": {},
                        "lingSave": {},
                        "scaling": "",
                        "actionCost": "action",
                        "specialNotes": [
                          "1Turn"
                        ]
                      }
                    ]
                }
            }
        ]

    def getAbilities(self):
        if self.__lvl < 5:
            return None
        elif self.__lvl < 14:
            return self.__abilities[0]
        else:
            return self.__abilities