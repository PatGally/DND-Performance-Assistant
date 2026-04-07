import os
import urllib.parse
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.server_api import ServerApi


class Driver:
    _client = None
    _db = None

    def __init__(self):
        load_dotenv()

        username = os.getenv("MONGO_USER")
        raw_password = os.getenv("MONGO_PASS")
        db_name = os.getenv("MONGO_DB_NAME", "dndpa")

        if not username or not raw_password:
            raise RuntimeError("MongoDB credentials not found")

        password = urllib.parse.quote_plus(raw_password)

        self._uri = (
            f"mongodb+srv://{username}:{password}"
            "@cluster0.dcn6d.mongodb.net/?appName=Cluster0"
        )
        self._db_name = db_name

    def connect(self):
        if Driver._client is None:
            Driver._client = AsyncIOMotorClient(self._uri, server_api=ServerApi("1"))
        return Driver._client

    def get_db(self):
        if Driver._db is None:
            Driver._db = self.connect()[self._db_name]
        return Driver._db

    def get_collection(self, name: str):
        return self.get_db()[name]