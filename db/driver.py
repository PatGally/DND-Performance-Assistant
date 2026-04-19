import os
import urllib.parse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.server_api import ServerApi


class Driver:
    def __init__(self):
        self._client = None
        self._db = None

        env = os.getenv("ENV", "development").lower()

        if env == "production":
            username = os.getenv("MONGO_PROD_USER")
            raw_password = os.getenv("MONGO_PROD_PASS")
        else:
            username = os.getenv("MONGO_USER")
            raw_password = os.getenv("MONGO_PASS")

        db_name = os.getenv("MONGO_DB_NAME", "dndpa")

        if not username or not raw_password:
            raise RuntimeError(f"MongoDB credentials not found for ENV={env}")

        password = urllib.parse.quote_plus(raw_password)

        self._uri = (
            f"mongodb+srv://{username}:{password}"
            f"@cluster0.dcn6d.mongodb.net/?appName=Cluster0"
        )
        self._db_name = db_name
        self._env = env

    def connect(self):
        if self._client is None:
            print(f"[mongo] ENV={self._env}, DB={self._db_name}")
            self._client = AsyncIOMotorClient(
                self._uri,
                server_api=ServerApi("1"),
            )
        return self._client

    def get_db(self):
        if self._db is None:
            self._db = self.connect()[self._db_name]
        return self._db

    def get_collection(self, name: str):
        return self.get_db()[name]