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
    print("[db_access] init_indexes start")
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
    print("[db_access] init_indexes complete")


async def get_encounter_by_eid(eid: str):
    print(f"[db_access] get_encounter_by_eid eid={eid}")
    return await encounterDb.find_one({"eid": eid})

async def getUserByGoogleSub(googleSub: str):
    return await userDb.find_one({
        "auth_provider": "google",
        "google_sub": googleSub
    })

async def deleteEncounterByEid(eid: str, username: str):
    print(f"[db_access] deleteEncounterByEid eid={eid} username={username}")
    userResult = await userDb.update_one(
        {"username": username},
        {"$pull": {"encounter_ids": eid}},
    )
    encounterResult = await encounterDb.delete_one({"eid": eid})
    print(
        f"[db_access] deleteEncounterByEid user_modified={userResult.modified_count} "
        f"encounter_deleted={encounterResult.deleted_count}"
    )
    return userResult.modified_count > 0, encounterResult.deleted_count > 0


async def deletePlayerByCid(cid: str, username: str):
    print(f"[db_access] deletePlayerByCid cid={cid} username={username}")
    userResult = await userDb.update_one(
        {"username": username},
        {"$pull": {"player_ids": cid}},
    )
    playerResult = await playerDb.delete_one({"stats.cid": cid})
    print(
        f"[db_access] deletePlayerByCid user_modified={userResult.modified_count} "
        f"player_deleted={playerResult.deleted_count}"
    )
    return userResult.modified_count > 0, playerResult.deleted_count > 0


async def get_player_by_cid(cid: str):
    print(f"[db_access] get_player_by_cid cid={cid}")
    return await playerDb.find_one({"stats.cid": cid})


async def get_user_by_username(username: str):
    print(f"[db_access] get_user_by_username username={username}")
    return await userDb.find_one({"username": username})


async def getUserByGoogleSub(google_sub: str):
    print(f"[db_access] getUserByGoogleSub google_sub={google_sub}")
    return await userDb.find_one({"google_sub": google_sub})


async def upsert_encounter_dict(encounter_dict: dict):
    print(f"[db_access] upsert_encounter_dict eid={encounter_dict.get('eid')}")
    return await encounterDb.replace_one(
        {"eid": encounter_dict["eid"]},
        encounter_dict,
        upsert=True,
    )


async def upsert_player_dict(player_dict: dict):
    print(f"[db_access] upsert_player_dict cid={player_dict.get('stats', {}).get('cid')}")
    return await playerDb.replace_one(
        {"stats.cid": player_dict["stats"]["cid"]},
        player_dict,
        upsert=True,
    )


async def upsert_user_dict(user_dict: dict):
    print(f"[db_access] upsert_user_dict username={user_dict.get('username')}")
    return await userDb.replace_one(
        {"username": user_dict["username"]},
        user_dict,
        upsert=True,
    )


async def find_players_by_username(username: str):
    print(f"[db_access] find_players_by_username username={username}")
    userData = await get_user_by_username(username)
    if not userData:
        return playerDb.find({"stats.cid": {"$in": []}}, {"_id": 0})

    return playerDb.find(
        {"stats.cid": {"$in": userData.get("player_ids", [])}},
        {"_id": 0},
    )


async def find_encounters_by_username(username: str):
    print(f"[db_access] find_encounters_by_username username={username}")
    userData = await get_user_by_username(username)
    if not userData:
        return encounterDb.find({"eid": {"$in": []}}, {"_id": 0})

    return encounterDb.find(
        {"eid": {"$in": userData.get("encounter_ids", [])}},
        {"_id": 0},
    )


async def addEncounterToUser(username: str, eid: str):
    print(f"[db_access] addEncounterToUser username={username} eid={eid}")
    await userDb.update_one(
        {"username": username},
        {"$addToSet": {"encounter_ids": eid}},
    )


async def addPlayerToUser(username: str, cid: str):
    print(f"[db_access] addPlayerToUser username={username} cid={cid}")
    await userDb.update_one(
        {"username": username},
        {"$addToSet": {"player_ids": cid}},
    )


async def create_weapon_weight_record(record: Dict[str, Any]):
    print(f"[db_access] create_weapon_weight_record name={record.get('name')}")
    doc = _prepare_weight_doc(record, "Weapon")
    result = await weaponWeightDb.insert_one(doc)
    print(f"[db_access] create_weapon_weight_record inserted_id={result.inserted_id}")
    return result.inserted_id


async def create_spell_weight_record(record: Dict[str, Any]):
    print(f"[db_access] create_spell_weight_record spellname={record.get('spellname')}")
    doc = _prepare_weight_doc(record, "Spell")
    result = await spellWeightDb.insert_one(doc)
    print(f"[db_access] create_spell_weight_record inserted_id={result.inserted_id}")
    return result.inserted_id


async def create_monaction_weight_record(record: Dict[str, Any]):
    print(f"[db_access] create_monaction_weight_record name={record.get('name')}")
    doc = _prepare_weight_doc(record, "MonAction")
    result = await monActionWeightDb.insert_one(doc)
    print(f"[db_access] create_monaction_weight_record inserted_id={result.inserted_id}")
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
    print(
        f"[db_access] finalize_weapon_weight_record id={record_id} "
        f"label={label} residual={residual}"
    )
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

    result = await weaponWeightDb.update_one(
        {"_id": _coerce_object_id(record_id)},
        {"$set": update_doc},
    )
    print(f"[db_access] finalize_weapon_weight_record modified_count={result.modified_count}")
    return result


async def finalize_spell_weight_record(
    record_id: Any,
    *,
    predicted_weight: float,
    label: float,
    residual: float,
    model_version: Optional[str] = None,
    outcome_snapshot: Optional[Dict[str, Any]] = None,
):
    print(
        f"[db_access] finalize_spell_weight_record id={record_id} "
        f"label={label} residual={residual}"
    )
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

    result = await spellWeightDb.update_one(
        {"_id": _coerce_object_id(record_id)},
        {"$set": update_doc},
    )
    print(f"[db_access] finalize_spell_weight_record modified_count={result.modified_count}")
    return result


async def finalize_monaction_weight_record(
    record_id: Any,
    *,
    predicted_weight: float,
    label: float,
    residual: float,
    model_version: Optional[str] = None,
    outcome_snapshot: Optional[Dict[str, Any]] = None,
):
    print(
        f"[db_access] finalize_monaction_weight_record id={record_id} "
        f"label={label} residual={residual}"
    )
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

    result = await monActionWeightDb.update_one(
        {"_id": _coerce_object_id(record_id)},
        {"$set": update_doc},
    )
    print(f"[db_access] finalize_monaction_weight_record modified_count={result.modified_count}")
    return result


async def get_weapon_weight_training_batch(limit: int = 1000):
    print(f"[db_access] get_weapon_weight_training_batch limit={limit}")
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
    print(f"[db_access] get_spell_weight_training_batch limit={limit}")
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
    print(f"[db_access] get_monaction_weight_training_batch limit={limit}")
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
    print(f"[db_access] delete_weapon_weight_records count={len(record_ids)}")
    ids = [_coerce_object_id(rid) for rid in record_ids]
    return await weaponWeightDb.delete_many({"_id": {"$in": ids}})


async def delete_spell_weight_records(record_ids: List[Any]):
    print(f"[db_access] delete_spell_weight_records count={len(record_ids)}")
    ids = [_coerce_object_id(rid) for rid in record_ids]
    return await spellWeightDb.delete_many({"_id": {"$in": ids}})


async def delete_monaction_weight_records(record_ids: List[Any]):
    print(f"[db_access] delete_monaction_weight_records count={len(record_ids)}")
    ids = [_coerce_object_id(rid) for rid in record_ids]
    return await monActionWeightDb.delete_many({"_id": {"$in": ids}})

async def delete_weapon_weight_records_by_ids(ids: List[Any]):
    if not ids:
        class EmptyDeleteResult:
            deleted_count = 0
        return EmptyDeleteResult()

    return await weaponWeightDb.delete_many({"_id": {"$in": ids}})

async def delete_spell_weight_records_by_ids(ids: List[Any]):
    if not ids:
        class EmptyDeleteResult:
            deleted_count = 0
        return EmptyDeleteResult()

    return await spellWeightDb.delete_many({"_id": {"$in": ids}})


async def delete_monaction_weight_records_by_ids(ids: List[Any]):
    if not ids:
        class EmptyDeleteResult:
            deleted_count = 0
        return EmptyDeleteResult()

    return await monActionWeightDb.delete_many({"_id": {"$in": ids}})