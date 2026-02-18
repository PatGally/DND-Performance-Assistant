from CoreEngine import Player
class Monk(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions, cid, position):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions, cid, position)
        self.__abilities = [
            {
                "name": "Extra attack",
                "lvl": "5",
                "total": "2",
                "split": []
            },
            {
                "name" : "Purity of Body",
                "lvl" : "10",
                "ability" : [
                    {
                        "name": "Immunity",
                        "effect": {
                            "damage": "*0",
                            "attribute": ["Poisoned", "Diseased"]
                        }
                    },
                ]
            },
            {
                "name" : "Diamond Soul",
                "lvl" : "14",
                "ability" : [
                    {
                        "name": "Buff",
                        "effect": {
                            "rolls" : "Proficiency",
                            "attribute": ["ALL saves"]
                        }
                    },
                ]
            },
        ]