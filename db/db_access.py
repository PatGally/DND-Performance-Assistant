from typing import Optional

from BackendAPI.models.UserAuth import UserInDB
from db.driver import Driver

driver = Driver()
encounterDb = driver.get_collection("encounters")
playerDb = driver.get_collection("players")
userDb = driver.get_collection("users")

DEFAULT_USER_FIELDS = {
    "hashed_password": None,
    "auth_provider": "local",
    "google_sub": None,
    "disabled": False,
    "encounter_ids": [],
    "player_ids": []
}

async def init_indexes():
    await encounterDb.create_index("eid", unique=True)
    await playerDb.create_index("stats.cid", unique=True)
    await userDb.create_index("username", unique=True)

async def get_encounter_by_eid(eid: str):
    return await encounterDb.find_one({"eid": eid})

async def get_player_by_cid(cid: str):
    return await playerDb.find_one({"stats.cid": cid})

async def get_user_by_username(username: str):
    return await userDb.find_one({"username": username})

async def getUserByGoogleSub(googleSub: str):
    return await userDb.find_one({
        "auth_provider": "google",
        "google_sub": googleSub
    })

async def upsert_encounter_dict(encounter_dict: dict):
    return await encounterDb.replace_one(
        {"eid": encounter_dict["eid"]},
        encounter_dict,
        upsert=True,
    )

async def upsert_player_dict(player_dict: dict):
    return await playerDb.replace_one(
        {"cid": player_dict["stats"]["cid"]},
        player_dict,
        upsert=True,
    )

async def upsert_user_dict(user_dict: dict):
    return await userDb.replace_one(
        {"username": user_dict["username"]},
        user_dict,
        upsert=True,
    )

async def find_players_by_username(username: str):
    userData = await get_user_by_username(username)
    if not userData:
        return playerDb.find({"stats.cid": {"$in": []}}, {"_id": 0})

    return playerDb.find(
        {"stats.cid": {"$in": userData.get("player_ids", [])}},
        {"_id": 0}
    )

async def find_encounters_by_username(username: str):
    userData = await get_user_by_username(username)
    if not userData:
        return encounterDb.find({"eid": {"$in": []}})
    return encounterDb.find(
        {"eid" : {"$in": userData.get("encounter_ids", [])}},
        {"_id": 0}
    )

async def addEncounterToUser(username, eid):
    await userDb.update_one(
        {"username": username},
        {"$addToSet": {"encounter_ids": eid}}
    )

async def addPlayerToUser(username, cid):
    await userDb.update_one(
        {"username": username},
        {"$addToSet": {"player_ids": cid}}
    )