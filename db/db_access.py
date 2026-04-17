from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from db.driver import Driver


driver = Driver()

encounterDb = driver.get_collection("encounters")
playerDb = driver.get_collection("players")
userDb = driver.get_collection("users")
weaponWeightDb = driver.get_collection("weaponweights")
spellWeightDb = driver.get_collection("spellweights")
monActionWeightDb = driver.get_collection("monactionweights")

DEFAULT_USER_FIELDS = {
    "hashed_password": None,
    "auth_provider": "local",
    "google_sub": None,
    "disabled": False,
    "encounter_ids": [],
    "player_ids": [],
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_object_id(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        return value


def _prepare_weight_doc(record: Dict[str, Any], action_family: str) -> Dict[str, Any]:
    doc = dict(record)
    doc["action_family"] = action_family

    doc.setdefault("base_weight", None)
    doc.setdefault("predicted_weight", None)
    doc.setdefault("label", None)
    doc.setdefault("residual", None)
    doc.setdefault("feature_snapshot", {})
    doc.setdefault("outcome_snapshot", None)
    doc.setdefault("encounter_id", None)
    doc.setdefault("user_id", None)
    doc.setdefault("model_version", None)

    if "created_at" not in doc or doc["created_at"] is None:
        doc["created_at"] = _utcnow()
    doc["updated_at"] = _utcnow()
    return doc


async def init_indexes():
    await encounterDb.create_index("eid", unique=True)
    await playerDb.create_index("stats.cid", unique=True)
    await userDb.create_index("username", unique=True)

    # ML collections: multiple rows per action over time, so these are not unique.
    await weaponWeightDb.create_index("name")
    await weaponWeightDb.create_index("encounter_id")
    await weaponWeightDb.create_index("user_id")
    await weaponWeightDb.create_index("created_at")

    await spellWeightDb.create_index("spellname")
    await spellWeightDb.create_index("encounter_id")
    await spellWeightDb.create_index("user_id")
    await spellWeightDb.create_index("created_at")

    await monActionWeightDb.create_index("name")
    await monActionWeightDb.create_index("encounter_id")
    await monActionWeightDb.create_index("user_id")
    await monActionWeightDb.create_index("created_at")


async def get_encounter_by_eid(eid: str):
    return await encounterDb.find_one({"eid": eid})

async def getUserByGoogleSub(googleSub: str):
    return await userDb.find_one({
        "auth_provider": "google",
        "google_sub": googleSub
    })

async def deleteEncounterByEid(eid: str, username: str):
    userResult = await userDb.update_one(
        {"username": username},
        {"$pull": {"encounter_ids": eid}},
    )
    encounterResult = await encounterDb.delete_one({"eid": eid})
    return userResult.modified_count > 0, encounterResult.deleted_count > 0


async def deletePlayerByCid(cid: str, username: str):
    userResult = await userDb.update_one(
        {"username": username},
        {"$pull": {"player_ids": cid}},
    )
    playerResult = await playerDb.delete_one({"stats.cid": cid})
    return userResult.modified_count > 0, playerResult.deleted_count > 0


async def get_player_by_cid(cid: str):
    return await playerDb.find_one({"stats.cid": cid})


async def get_user_by_username(username: str):
    return await userDb.find_one({"username": username})


async def upsert_encounter_dict(encounter_dict: dict):
    return await encounterDb.replace_one(
        {"eid": encounter_dict["eid"]},
        encounter_dict,
        upsert=True,
    )


async def upsert_player_dict(player_dict: dict):
    return await playerDb.replace_one(
        {"stats.cid": player_dict["stats"]["cid"]},
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
        {"_id": 0},
    )


async def find_encounters_by_username(username: str):
    userData = await get_user_by_username(username)
    if not userData:
        return encounterDb.find({"eid": {"$in": []}}, {"_id": 0})

    return encounterDb.find(
        {"eid": {"$in": userData.get("encounter_ids", [])}},
        {"_id": 0},
    )


async def addEncounterToUser(username: str, eid: str):
    await userDb.update_one(
        {"username": username},
        {"$addToSet": {"encounter_ids": eid}},
    )


async def addPlayerToUser(username: str, cid: str):
    await userDb.update_one(
        {"username": username},
        {"$addToSet": {"player_ids": cid}},
    )

async def create_weapon_weight_record(record: Dict[str, Any]):
    doc = _prepare_weight_doc(record, "Weapon")
    result = await weaponWeightDb.insert_one(doc)
    return result.inserted_id


async def create_spell_weight_record(record: Dict[str, Any]):
    doc = _prepare_weight_doc(record, "Spell")
    result = await spellWeightDb.insert_one(doc)
    return result.inserted_id


async def create_monaction_weight_record(record: Dict[str, Any]):
    doc = _prepare_weight_doc(record, "MonAction")
    result = await monActionWeightDb.insert_one(doc)
    return result.inserted_id

async def finalize_weapon_weight_record(
    record_id: Any,
    *,
    predicted_weight: float,
    label: float,
    residual: float,
    model_version: Optional[str] = None,
    outcome_snapshot: Optional[Dict[str, Any]] = None,
):
    update_doc = {
        "predicted_weight": float(predicted_weight),
        "label": float(label),
        "residual": float(residual),
        "updated_at": _utcnow(),
    }
    if model_version is not None:
        update_doc["model_version"] = model_version
    if outcome_snapshot is not None:
        update_doc["outcome_snapshot"] = outcome_snapshot

    return await weaponWeightDb.update_one(
        {"_id": _coerce_object_id(record_id)},
        {"$set": update_doc},
    )


async def finalize_spell_weight_record(
    record_id: Any,
    *,
    predicted_weight: float,
    label: float,
    residual: float,
    model_version: Optional[str] = None,
    outcome_snapshot: Optional[Dict[str, Any]] = None,
):
    update_doc = {
        "predicted_weight": float(predicted_weight),
        "label": float(label),
        "residual": float(residual),
        "updated_at": _utcnow(),
    }
    if model_version is not None:
        update_doc["model_version"] = model_version
    if outcome_snapshot is not None:
        update_doc["outcome_snapshot"] = outcome_snapshot

    return await spellWeightDb.update_one(
        {"_id": _coerce_object_id(record_id)},
        {"$set": update_doc},
    )


async def finalize_monaction_weight_record(
    record_id: Any,
    *,
    predicted_weight: float,
    label: float,
    residual: float,
    model_version: Optional[str] = None,
    outcome_snapshot: Optional[Dict[str, Any]] = None,
):
    update_doc = {
        "predicted_weight": float(predicted_weight),
        "label": float(label),
        "residual": float(residual),
        "updated_at": _utcnow(),
    }
    if model_version is not None:
        update_doc["model_version"] = model_version
    if outcome_snapshot is not None:
        update_doc["outcome_snapshot"] = outcome_snapshot

    return await monActionWeightDb.update_one(
        {"_id": _coerce_object_id(record_id)},
        {"$set": update_doc},
    )

async def get_weapon_weight_training_batch(limit: int = 1000):
    return weaponWeightDb.find(
        {"label": {"$ne": None}},
        {
            "_id": 1,
            "name": 1,
            "action_family": 1,
            "base_weight": 1,
            "predicted_weight": 1,
            "label": 1,
            "residual": 1,
            "feature_snapshot": 1,
            "outcome_snapshot": 1,
            "encounter_id": 1,
            "user_id": 1,
            "created_at": 1,
            "updated_at": 1,
            "model_version": 1,
        },
    ).limit(limit)


async def get_spell_weight_training_batch(limit: int = 1000):
    return spellWeightDb.find(
        {"label": {"$ne": None}},
        {
            "_id": 1,
            "spellname": 1,
            "action_family": 1,
            "base_weight": 1,
            "predicted_weight": 1,
            "label": 1,
            "residual": 1,
            "feature_snapshot": 1,
            "outcome_snapshot": 1,
            "encounter_id": 1,
            "user_id": 1,
            "created_at": 1,
            "updated_at": 1,
            "model_version": 1,
        },
    ).limit(limit)


async def get_monaction_weight_training_batch(limit: int = 1000):
    return monActionWeightDb.find(
        {"label": {"$ne": None}},
        {
            "_id": 1,
            "name": 1,
            "action_family": 1,
            "base_weight": 1,
            "predicted_weight": 1,
            "label": 1,
            "residual": 1,
            "feature_snapshot": 1,
            "outcome_snapshot": 1,
            "encounter_id": 1,
            "user_id": 1,
            "created_at": 1,
            "updated_at": 1,
            "model_version": 1,
        },
    ).limit(limit)

async def delete_weapon_weight_records(record_ids: List[Any]):
    ids = [_coerce_object_id(rid) for rid in record_ids]
    return await weaponWeightDb.delete_many({"_id": {"$in": ids}})


async def delete_spell_weight_records(record_ids: List[Any]):
    ids = [_coerce_object_id(rid) for rid in record_ids]
    return await spellWeightDb.delete_many({"_id": {"$in": ids}})


async def delete_monaction_weight_records(record_ids: List[Any]):
    ids = [_coerce_object_id(rid) for rid in record_ids]
    return await monActionWeightDb.delete_many({"_id": {"$in": ids}})


async def delete_weapon_weight_records_by_encounter(eid: str):
    return await weaponWeightDb.delete_many({"encounter_id": eid})


async def delete_spell_weight_records_by_encounter(eid: str):
    return await spellWeightDb.delete_many({"encounter_id": eid})


async def delete_monaction_weight_records_by_encounter(eid: str):
    return await monActionWeightDb.delete_many({"encounter_id": eid})
