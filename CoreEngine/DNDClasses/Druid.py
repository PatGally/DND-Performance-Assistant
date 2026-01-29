from CoreEngine import Player, Monster

class Druid(Player):
    def __init__(self, name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                 damVulns, activeStatusEffects, activeConditions):
        super().__init__(name, stats, saveProfs, ac, hp, class_type, level, conImmunities, damImmunes, damResists,
                         damVulns, activeStatusEffects, activeConditions)
        self.__monster = None

    def setWildShape(self, name, cr, cType, stats, hp, maxHP, ac, saveProfs, lResists, damResists, damImmunes, damVulns,conImmunes, activeConditions, activeStatusEffects, lairAction, magicResist,enemy, actions, spellInfo, legActions):
        self.__monster = Monster(name, cr, cType, stats, hp, maxHP, ac, saveProfs, lResists, damResists, damImmunes, damVulns,conImmunes, activeConditions, activeStatusEffects, lairAction, magicResist,enemy, actions, spellInfo, legActions)

    def getWildShape(self):
        return self.__monster

