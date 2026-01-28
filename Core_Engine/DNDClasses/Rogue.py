from Core_Engine.Player import Player

class Rogue(Player):
    def __init__(self, lvl, name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                 activeStatusEffects, activeConditions):
        super().__init__(name, stats, ac, hp, class_type, level, conImmunities, damImmunes, damResists, damVulns,
                         activeStatusEffects, activeConditions)
        self.__abilities = [
            {
                "name" : "Sneak Attack",
                "lvl" : 1,
                "scaling" : "1d6 PER2",
                "specialNotes" : ["needsAdvantage"]
            },
            {
                "name" : "Cunning Action",
                "lvl" : 2,
                "action" : [
                    {
                        "spellname": "Hide",
                        "targeting": [
                            {
                                "self": True,
                                "number": 0,
                                "rolls": {
                                    "rollType": "autoHit",
                                    "saveType": "none",
                                    "halfSave": True,
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
                                "actionCost": "bonus action",
                                "specialNotes": [
                                    "1Turn"
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "name" : "Slippery Mind",
                "lvl" : 15,
                "ability" : "Proficiency",
                "attribute" : ["WIS save"]
            },
            {
                "name" : "Elusive",
                "lvl" : 18,
                "ability" : "neutrality",
                "attribute" : ["attack rolls against"],
            }
        ]

    def getAbilities(self):
        if self.getLevel() < 1:
            return None
        elif self.getLevel() < 2:
            return self.__abilities[0]
        elif self.getLevel() < 15:
            return self.__abilities[0:2]
        elif self.getLevel() < 18:
            return self.__abilities[0:3]
        else:
            return self.__abilities