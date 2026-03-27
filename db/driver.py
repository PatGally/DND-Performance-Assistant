import os
import urllib.parse
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.server_api import ServerApi


class Driver:
    _client = None

    def __init__(self):

        load_dotenv()

        username = os.getenv("MONGO_USER")
        password = urllib.parse.quote_plus(os.getenv("MONGO_PASS"))

        if not username or not password:
            raise RuntimeError("MongoDB credentials not found")

        password = urllib.parse.quote_plus(password)

        uri = (
            f"mongodb+srv://{username}:{password}"
            "@cluster0.dcn6d.mongodb.net/?appName=Cluster0"
        )

        self._uri = uri

    def connect(self):
        if Driver._client is None:
            Driver._client = AsyncIOMotorClient(self._uri, server_api=ServerApi("1"))
        return Driver._client

    def getDb(self, name):
        client = self.connect()
        return client[name]

# print(db.getDb("encounters"))