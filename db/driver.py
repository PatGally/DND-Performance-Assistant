import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.server_api import ServerApi


class Driver:
    def __init__(self):
        self._client = None
        self._db = None
        load_dotenv(".env")
        env = os.getenv("ENV", "development").lower()

        if env == "production":
            load_dotenv(".env.production", override=False)
            mongo_uri = os.getenv("MONGO_PROD_URI")
            db_name = os.getenv("MONGO_PROD_DB_NAME", "dndpa")
        else:
            load_dotenv(".env.development", override=False)
            mongo_uri = os.getenv("MONGO_URI")
            db_name = os.getenv("MONGO_DB_NAME", "dndpa")

        if not mongo_uri:
            raise RuntimeError(f"MongoDB URI not found for ENV={env}")

        self._uri = mongo_uri
        self._db_name = db_name
        self._env = env

    def connect(self):
        if self._client is None:
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