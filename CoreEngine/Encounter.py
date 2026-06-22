class Encounter:
    def __init__(self, name, date, eid, mapData):
        self.__name = name
        self.__date = date
        self.__eid = eid
        self.__mapData = mapData
        self.__completed = False
        self.__initiative = []
        self.__monsters = []
        self.__players = []
        self.__results = []
        self.__initiative = []

    def getEID(self):
        return self.__eid
    def setMapData(self, mapData):
        self.__mapData = mapData
    def getMapData(self):
        return self.__mapData

    def setCreaturePosition(self, cid, newPos):
        creature = self.getPlayerByCID(cid)
        creature = self.getMonsterByCID(cid) if not creature else creature
        mapData = self.getMapData()
        tokens = mapData["layers"]["creatureTokens"]
        creatureToken = [t for t in tokens if t["cid"] == cid]
        creature.setPosition(newPos)
        creatureToken["position"] = newPos


    def setComplete(self, complete):
        self.__completed = complete
    def isComplete(self):
        return self.__completed

    def setName(self, name):
        self.__name = name
    def getName(self):
        return self.__name

    def setDate(self, date):
        self.__date = date
    def getDate(self):
        return self.__date

    def addPlayer(self, player):
        self.__players.append(player)
    def getPlayer(self, i):
        return self.__players[i]
    def getPlayerByCID(self, cid):
        for player in self.__players:
            if player.getCID() == cid:
                return player
    def playerSize(self):
        return len(self.__players)
    def setPlayer(self, i, player):
        self.__players[i] = player

    def addMonster(self, monster):
        self.__monsters.append(monster)
    def removeMonster(self, monsterName):
        for mIdx, monster in enumerate(self.__monsters):
            if monster.getName().lower() == monsterName.lower():
                del self.__monsters[mIdx]
                return True
        return False
    def getMonster(self, idx):
        return self.__monsters[idx]
    def getMonsterByCID(self, cid):
        for monster in self.__monsters:
            if monster.getCID() == cid:
                return monster
    def monsterSize(self):
        return len(self.__monsters)
    def setMonster(self, i, monster):
        self.__monsters[i] = monster

    def addResult(self, result):
        self.__results.append(result)
    def getResultByIdx(self, idx):
        return self.__results[idx]
    def getResultByID(self, resultID):
        for resultSet in self.__results:
            #Returns first instance of that result - the main instance.
            if isinstance(resultSet, list):
                for result in resultSet:
                    if result["resultID"] == resultID:
                        return result
            else:
                if "resultID" in resultSet and resultSet["resultID"] == resultID:
                    return resultSet
        return None
    def resultSize(self):
        return len(self.__results)

    def getInitiative(self):
        return self.__initiative
    def addInitiative(self, creature):
        self.__initiative.append(creature)
    def setInitiative(self, initiative):
        self.__initiative = [creature for creature in initiative]
