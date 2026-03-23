from CoreEngine import Player

class Paladin(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions, cid, position, spellSlots, layOnHandsPool=None):
        super().__init__(name, stats, saveProfs, ac, hp, class_type,
                         level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions,
                         cid, position, spellSlots)

        self.__layOnHandsPool = 5 * self.getLevel() if layOnHandsPool is None else layOnHandsPool
        self.__auraRange = 10 if self.getLevel() < 18 else 30
        self.__maxSmiteDieNum = 5
        self.__abilities = [
            {
                "name" : "Divine Smite",
                "lvl" : "2",
                "action" : {
                    "spellname": "Divine Smite",
                    "classes": [],
                    "level": "1",
                    "targeting": [
                        {
                            "self": "true",
                            "number": "1",
                            "rolls": {
                                "rollType": "onHit",
                                "saveType": "none",
                                "halfSave": "false",
                                "damage": "2d8",
                                "damageMod": ""
                            },
                            "damType": [
                                "radiant"
                            ],
                            "conditions": [],
                            "statusEffect": [],
                            "lingEffect": {},
                            "extraEffect": {},
                            "lingSave": {},
                            "scaling": "1d8",
                            "specialNotes": [],
                            "actionCost": "action"
                        }
                    ]
                },
            },
            {
                "name": "Extra attack",
                "lvl": "5",
                "total": "2",
                "split": []
            },
            {
                "name" : "Aura of Protection",
                "lvl" : "6",
                "action" : {
                    "name" : "Aura of Protection",
                    "desc" : "",
                    "number" : "-2",
                    "actionRange" : "10",
                    "shape" : "circle",
                    "rolls": {
                        "rollType": "autoHit",
                        "saveType": "",
                        "halfSave": "",
                        "saveDC": "",
                        "damage": "",
                        "damageMod": ""
                    },
                    "damType": ["healing"],
                    "conditions": [],
                    "statusEffect": [
                        {
                            "name": "Buff",
                            "effect": {
                                "roll": "3",
                                "attribute": ["ALL save"]
                            }
                        }
                    ],
                    "lingEffect": {},
                    "extraEffect": {},
                    "lingSave": {},
                    "recharge" : {},
                    "actionCost" : "free action",
                    "specialNotes": ["1Turn"]
                }
            },
            {
                "name" : "Aura of Courage",
                "lvl" : "10",
                "action" : {
                        "name": "Aura of Courage",
                        "desc": "",
                        "number": "-2",
                        "actionRange": "10",
                        "shape": "circle",
                        "rolls": {
                            "rollType": "autoHit",
                            "saveType": "",
                            "halfSave": "",
                            "saveDC": "",
                            "damage": "",
                            "damageMod": ""
                        },
                        "damType": ["healing"],
                        "conditions": ["Frightened IMMUNE"],
                        "statusEffect": [],
                        "lingEffect": {},
                        "extraEffect": {},
                        "lingSave": {},
                        "recharge": {},
                        "actionCost": "free action",
                        "specialNotes": ["1Turn"]
                }
            }
        ]

    def useLayOnHands(self, amt):
        if amt > self.__layOnHandsPool:
            amt -= self.__layOnHandsPool
            self.__layOnHandsPool = 0
        else:
            self.__layOnHandsPool -= amt
    def resetLayOnHands(self):
        self.__layOnHandsPool = 5 * self.getLevel()

    def getLayOnHandsPool(self):
        return self.__layOnHandsPool