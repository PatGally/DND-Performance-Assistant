class SimulationRequestsAPI:
    def __init__(self):
        self.__key = -1

    def incrementNextTurn(self):
        #Increments the current turn in the initiative
        #Automatically executes pre-turn effects of the creature whose turn it now is.
        pass

    def sendNewState(self):
        #Sends new encounter state back into the front end
        pass
