import json
import logging
import os
from typing import Union, List, Optional, Any
import uuid
from fastapi.middleware.cors import CORSMiddleware

from logs.loggingConfig import setupLogging
from BackendAPI.models import ActionRequest, Monster, Player, Encounter, Spell, Weapon, MonAction
from BackendAPI.models.DNDClasses import Barbarian, Bard, Cleric, Druid, Fighter, Paladin, Sorcerer

from dotenv import load_dotenv
import main
from fastapi import FastAPI, Request, Depends, HTTPException, status, Response
from fastapi.params import Cookie
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import time
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from pathlib import Path
from .models.UserAuth import (Token, TokenData, UserCreate,
                             UserInDB, UserPublic, ChangePasswordRequest, SetDisabledRequest, GoogleAuthRequest)

setupLogging()
logger = logging.getLogger("backend")
load_dotenv()

#USER VALIDATION
ACCESS_SECRET_KEY = os.getenv("ACCESS_SECRET_KEY")
REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 30))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth/refresh"
USERS_PATH = Path("CoreEngine/data/user_list.json")
REFRESH_STORE_PATH = Path("CoreEngine/data/refresh_store.json")
ORIGINS = [os.getenv("ORIGIN1"), os.getenv("ORIGIN2")]

def load_user_db() -> dict:
    if not USERS_PATH.exists():
        return {}
    return json.loads(USERS_PATH.read_text(encoding="utf-8"))
def save_user_db(db: dict) -> None:
    tmp = USERS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=2), encoding="utf-8")
    tmp.replace(USERS_PATH)
user_db = load_user_db()

app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], #DELETE, PUT, etc
    allow_headers=["*"], #Specific requests from specific sources.
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    logger.info("Incoming request: %s %s", request.method, request.url.path)
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        "Completed request: %s %s Status=%s Duration=%.4fs",request.method,request.url.path,response.status_code,duration)

    return response

ENCOUNTER_LIST = []
def refresh():
    with open("CoreEngine/data/encounter_list.json", "r") as rf: #TODO: DB pull here
        global ENCOUNTER_LIST
        ENCOUNTER_LIST = json.load(rf)
refresh()
AnyPlayer = Union[Fighter, Barbarian, Bard, Cleric, Druid, Paladin, Sorcerer]

def isPlayer(creature):
    if isinstance(creature, dict):
        if creature.get("stats", {}):
            return True
        else:
            return False
    elif isinstance(creature, Monster):
        return True
    else:
        return False
@app.get("/encounter/{eid}/creature/{cid}/position")
def getCreaturePosition(eid : str, cid : str):
    creature = getCreature(eid, cid)
    if isinstance(creature.get("stats", {}), dict):
        return creature.get("stats").get("position", [0, 0])
    return creature.get("position", [0, 0])
@app.get("/encounter/{eid}/creature/{cid}/actions", response_model = List[Union[Weapon, Spell, MonAction]])
def getCreatureActions(eid : str, cid : str):
    creature = getCreature(eid, cid)
    if isPlayer(creature):
        spells = creature.get("spells", [])
        weapons = creature.get("weapons", [])
        return weapons + spells
    actions = creature.get("actions", [])
    if creature.get("spellInfo", {}):
        actions += creature.get("spellInfo").get("spells", [])
    return actions
@app.get("/encounter/{eid}/creature/{cid}", response_model=Union[AnyPlayer, Monster])
def getCreature(eid : str, cid : str):
    enc = getEncounter(eid)
    creatures = enc.get("players", []) + enc.get("monsters", [])
    cids = []
    for creature in creatures:
        if isPlayer(creature):
            foundcid = creature.get("stats", {}).get("cid", "")
        else:
            foundcid = creature.get("cid", "")
        cids.append(foundcid)
    try:
        creatureIdx = cids.index(cid)
    except:
        raise ValueError(f"{cid} not a recognized creature.")
    return creatures[creatureIdx]
@app.post("/encounter/{eid}/creature")
def addtoEncounter(eid : str, creature : Union[AnyPlayer, Player, Monster]):
    encounter = getEncounter(eid)
    if isPlayer(creature):
        encounter.get("players", []).append(creature)
        pass
    else:
        encounter.get("monsters", []).append(creature)
    main.saveEncounter(main.loadEncounter(encounter))
    refresh()
    return {"verification" : "true"}
@app.get("/encounter/{eid}/state/maplink")
def getMapLink(eid : str):
    enc = getEncounter(eid)
    maplink = enc.get("maplink", None)
    return maplink
@app.get("/encounter/{eid}/state")
def getEncounter(eid : str):
    for encounter in ENCOUNTER_LIST:
        db_eid = encounter.get("eid", None)
        if eid == db_eid:
            logger.info(f"{eid} found!")
            return encounter
    logger.info(f"{eid} not found!")
@app.get("/encounter/{eid}/recommendation/{cid}")
def actionRecommendation(eid : str, cid : str):
    #Returns a list of all possible actions a given creature can perform, ordered by the rankings of best to worst.
    encounter = main.loadEncounter(getEncounter(eid))
    initiative = main.setActiveInitiative(encounter)
    players = [encounter.getPlayer(i) for i in range(encounter.playerSize())]
    playercids = [player.getCID().lower() for player in players]
    if cid.lower() in playercids:
        player = players[playercids.index(cid.lower())]
        rankings = main.playerTurn(player, initiative)
        return rankings
    else:
        monsters = [encounter.getMonster(i) for i in range(encounter.monsterSize())]
        monstercids = [monster.getCID().lower() for monster in monsters]
        if cid.lower() in monstercids:
            monster = monsters[monstercids.index(cid.lower())]
            rankings = main.monsterTurn(monster, initiative)
            logger.info("Rankings for %s: %s", eid, rankings)
            return rankings
@app.get("/uuid")
def getUUID():
    my_uuid_object = uuid.uuid4()
    my_uuid_string = str(my_uuid_object)
    logger.info(my_uuid_string)
    return my_uuid_string

@app.get("/encounter/{eid}/initiative/nextturn")
def getNextTurn(eid : str):
    encounter = main.loadEncounter(getEncounter(eid))
    initiative = encounter.getInitiative()
    for i, turn in enumerate(initiative):
        if turn["currentTurn"]:
            logger.info("currentTurn creature: " + turn["name"])
            turn["currentTurn"] = False
            if i == len(initiative) - 1:
                initiative[0]["currentTurn"] = True
                logger.info("New currentTurnCreature: " + initiative[0]["name"])
            else:
                initiative[i + 1]["currentTurn"] = True
                logger.info("New currentTurnCreature: " + initiative[i + 1]["name"])
            break
    currentCreature = {}
    for creature in initiative:
        #Add creature statblock to their associated turn
        #SHALLOW COPY OF MONSTER/PLAYER OBJECTS - Changes to creature["Statblock"] affect associated object in encounter
        if creature["turnType"] == "Player":
            for i in range(encounter.playerSize()):
                if creature["name"].lower() == encounter.getPlayer(i).getName().lower():
                    currentCreature = encounter.getPlayer(i)
                    break
        elif creature["turnType"] == "Monster":
            for i in range(encounter.monsterSize()):
                if creature["name"].lower() == encounter.getMonster(i).getName().lower():
                    currentCreature = encounter.getMonster(i)
                    break
    preEffects = []
    appendTurnCountResID = []
    refreshFlag = False
    for effect in currentCreature.getActiveStatusEffects():
        if effect["name"].lower() in ["lingsave", "lingeffect"]:
            preEffects.append(effect)

            # Deals with 1Turn shenanigans
            resultIDs = effect["effect"]["resultID"]
            resultIDs = main.ensureList(resultIDs)
            for i, resultID in enumerate(resultIDs):
                if resultID != -1:
                    result = encounter.getResultByID(resultID)
                    if "turnCount" in result and "turnCap" in result:
                        if int(result["turnCount"]) >= int(result["turnCap"]):
                            main.endSpellEffect(effect, i, currentCreature, main.setActiveInitiative(encounter))
                        else:
                            result["turnCount"] += 1
                            appendTurnCountResID.append(resultID)
                        refreshFlag = True

    main.saveEncounter(encounter)
    refresh()
    preEffects = {"preEffects" : preEffects, "refresh" : refreshFlag}
    logger.info(f"preEffects: {preEffects}")
    return preEffects
@app.get("/encounter/{eid}/initiative/currentturn")
def getTurn(eid : str):
    encounter = getEncounter(eid)
    initiative = encounter.get("initiative", [])
    for turn in initiative:
        if turn["currentTurn"]:
            return turn["name"]
    return {"error" : "no turns in initiative!"}
@app.get("/encounter/{eid}/initiative")
def getInitiative(eid : str):
    enc = getEncounter(eid)
    return enc.get("initiative", [])
@app.post("/encounter")
def postEncounter(encounter : Encounter):
    ENCOUNTER_LIST.append(encounter.model_dump(mode="json", by_alias=True))
    with open("CoreEngine/data/encounter_list.json", "w") as wf:
        json.dump(ENCOUNTER_LIST, wf, indent=4)
    refresh()
    return dict(verification="true")

@app.get("/dashboard/{eid}/packet")
def getEncounterMiniData(eid : str):
    encounter = getEncounter(eid)
    players = encounter.get("players", [])
    monsters = encounter.get("monsters", [])
    logger.info(players)
    logger.info(monsters)
    p_packet = [{"name" : player.get("stats").get("name"), "level" : player.get("stats").get("level"),
               "characterClass" : player.get("stats").get("characterClass")} for player in players]
    m_packet = [{"name" : monster.get("name"), "cr" : monster.get("cr"), "size" : monster.get("size")} for monster in monsters]
    return {"players" : p_packet, "monsters" : m_packet}
@app.get("/dashboard/players")
def getPlayers():
    with open("CoreEngine/data/player_list.json", "r") as pf:
        player_list = json.load(pf)
    return player_list
@app.get("/dashboard/weapons")
def getWeapons():
    with open("CoreEngine/data/weapons_list.json", "r") as wf:
        weapon_list = json.load(wf)
    return weapon_list
@app.get("/dashboard/player/availablespells")
def getSpells(classid : str, level : int):
    import math
    with open("CoreEngine/data/spell_list.json", "r") as sf:
        spellData = json.load(sf)
    relevantSpellData = []
    playerCap = -1
    if classid == "cleric" or classid == "sorcerer" or classid == "wizard" or classid == "bard" or classid == "druid" or classid == "warlock":
        playerCap = math.ceil(level / 2)  # Full casters
    elif (classid == "artificer" or classid == "paladin"
          or classid == "ranger"):
        playerCap = math.ceil(level / 3)  # Half casters
    for spell in spellData:
        if spell["level"] <= playerCap:
            found = False
            i = 0
            while not found and i < len(spell["classes"]):
                if classid.lower() == spell["classes"][i].lower():
                    relevantSpellData.append(spell)
                    found = True
                else:
                    i += 1
    logger.info("Spell data from get spells: %s", relevantSpellData)
    return relevantSpellData
@app.get("/dashboard/encounters")
def getEncounterPacket():
    return [{"name" : enc.get("name"), "date" : enc.get("date"), "eid" : enc.get("eid"), "completed" : enc.get("completed")} for enc in ENCOUNTER_LIST]
@app.post("/dashboard/players")
def postPlayerToPlayerList(player : Union[AnyPlayer, Player]):
    # TODO: Replace with DB call to add in.
    def addClassPassives():
        #List of classes with relevant passives:
        #Barbarian, Bard, Fighter, Monk, Paladin, Ranger, Rogue
            #List of add and forget passives (here):
                #(B)Magic Secrets, (Ro) Slippery Mind
            #Rest are on playerTurn() logic
        if playerObj.getClass().lower() == "bard":
            extraSpells = playerObj.getMagicalSecrets()
            for spell in extraSpells:
                playerObj.getMagicalSecret(spell)
                main.addChosenSpell(spell, playerObj)
        elif playerObj.getClass().lower() == "rogue":
            playerObj.setSaveProf("WIS", playerObj.getSaveProf("WIS") + playerObj.getProfBonus())
    playerJSON = player.model_dump(mode="json", by_alias=True)
    playerObj = main.getPlayerStats(playerJSON)
    main.getSavedWeapons(playerObj, playerJSON["weapons"])
    main.getSavedSpells(playerObj, playerJSON["spells"])
    addClassPassives()
    main.savePlayer(playerObj)
    return dict(verification="true")


#USER AUTH METHODS
def load_refresh_store() -> dict[str, Any]:
    if not REFRESH_STORE_PATH.exists():
        return {}
    return json.loads(REFRESH_STORE_PATH.read_text(encoding="utf-8"))
def save_refresh_store(store: dict[str, Any]) -> None:
    tmp = REFRESH_STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    tmp.replace(REFRESH_STORE_PATH)
def set_active_refresh_jti(username: str, jti: str, exp_ts: int) -> None:
    store = load_refresh_store()
    store[username] = {"jti": jti, "exp": exp_ts}
    save_refresh_store(store)
def get_active_refresh_jti(username: str) -> dict[str, Any] | None:
    store = load_refresh_store()
    return store.get(username)
def clear_active_refresh_jti(username: str) -> None:
    store = load_refresh_store()
    if username in store:
        del store[username]
        save_refresh_store(store)
def create_access_token(*, subject: str, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    now = _now_utc()
    payload = {
        "sub": subject,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, ACCESS_SECRET_KEY, algorithm=ALGORITHM)
def create_refresh_token(*, subject: str, expires_days: int = REFRESH_TOKEN_EXPIRE_DAYS) -> tuple[str, str]:
    #Returns (refresh_jwt, jti). We store the jti server-side for revocation/rotation.
    now = _now_utc()
    jti = getUUID()
    payload = {
        "sub": subject,
        "type": "refresh",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expires_days)).timestamp()),
    }
    token = jwt.encode(payload, REFRESH_SECRET_KEY, algorithm=ALGORITHM)
    return token, jti
#AUTH METHODS LOCAL
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)
def get_password_hash(password):
    return pwd_context.hash(password)
def get_user(db, username : str):
    if username in db:
        user_data = db[username]
        return UserInDB(**user_data)
def authenticate_user(db, username : str, password : str):
    user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user
async def get_current_user(token : str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate" : "Bearer"})
    try:
        payload = jwt.decode(token, ACCESS_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise credentials_exception
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = get_user(user_db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user
async def get_current_active_user(current_user : UserInDB = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
def user_to_public(user: UserInDB) -> UserPublic:
    return UserPublic(
        uid=user.uid,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=bool(user.disabled),
    )
def create_user(db: dict, user_in: UserCreate) -> UserInDB:
    # basic uniqueness check
    if user_in.username in db:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already registered",
        )

    hashed = get_password_hash(user_in.password)

    record = {
        "uid" : getUUID(),
        "username": user_in.username,
        "email": user_in.email,
        "full_name": user_in.full_name,
        "disabled": False,
        "hashed_password": hashed,
        "auth_provider": "local",
        "google_sub": None,
    }
    db[user_in.username] = record
    save_user_db(user_db)
    return UserInDB(**record)
#AUTH METHODS GOOGLE
def find_user_by_google_sub(db: dict, google_sub: str) -> Optional[UserInDB]:
    for _, user_data in db.items():
        if user_data.get("auth_provider") == "google" and user_data.get("google_sub") == google_sub:
            return UserInDB(**user_data)
    return None
def create_google_user(db: dict, *, google_sub: str, email: str | None, full_name: str | None) -> UserInDB:
    # TODO: Refine this later; for now use "g_<sub_prefix>"
    base_username = f"g_{google_sub[:12]}"
    username = base_username
    i = 1
    while username in db:
        i += 1
        username = f"{base_username}_{i}"

    record = {
        "uid" : getUUID(),
        "username": username,
        "email": email,
        "full_name": full_name,
        "disabled": False,
        "hashed_password": None,
        "auth_provider": "google",
        "google_sub": google_sub,
    }
    db[username] = record
    save_user_db(user_db)
    return UserInDB(**record)
#AUTH HELPERS
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
async def issueAccessAuth(user, response):
    access = create_access_token(subject=user.username)
    refresh, jti = create_refresh_token(subject=user.username)

    refresh_payload = jwt.decode(refresh, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    set_active_refresh_jti(user.username, jti, refresh_payload["exp"])

    # 5) Set refresh cookie (FIX: secure should be COOKIE_SECURE)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh,
        httponly=True,
        secure=COOKIE_SECURE,  # ✅ correct
        samesite=COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS,
    )

    return {"access_token": access, "token_type": "bearer"}

#AUTH ENDPOINTS
@app.get("/users/me/", response_model=UserPublic)
async def read_users_me(current_user: UserInDB = Depends(get_current_active_user)):
    return user_to_public(current_user)
@app.post("/signup", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def signup(user_in: UserCreate):
    u_db = create_user(user_db, user_in)
    return user_to_public(u_db)
@app.post("/auth/login")
async def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(user_db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")

    return await issueAccessAuth(user, response)
@app.post("/auth/google")
async def auth_google(body: GoogleAuthRequest, response: Response):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CLIENT_ID is not configured",
        )
    try:
        claims = google_id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        )

    google_sub = claims.get("sub")
    email = claims.get("email")
    full_name = claims.get("name") or claims.get("given_name")

    if not google_sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google token missing subject",
        )
    user = find_user_by_google_sub(user_db, google_sub)
    if not user:
        user = create_google_user(user_db, google_sub=google_sub, email=email, full_name=full_name)

    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return await issueAccessAuth(user, response)
@app.post("/auth/refresh")
async def refresh_token(response: Response, refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME)):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        payload = jwt.decode(refresh_token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")

    username = payload.get("sub")
    jti = payload.get("jti")
    if not username or not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed refresh token")

    # server-side check (revocation/rotation)
    active = get_active_refresh_jti(username)
    if not active or active.get("jti") != jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    # issue new access token
    access = create_access_token(subject=username)

    # ROTATE refresh token (recommended)
    new_refresh, new_jti = create_refresh_token(subject=username)
    new_payload = jwt.decode(new_refresh, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    set_active_refresh_jti(username, new_jti, new_payload["exp"])

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=new_refresh,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS,
    )

    return {"access_token": access, "token_type": "bearer"}
@app.post("/auth/logout")
async def logout(response: Response, refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME)):
    if refresh_token:
        try:
            payload = jwt.decode(refresh_token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("type") == "refresh" and payload.get("sub"):
                clear_active_refresh_jti(payload["sub"])
        except Exception:
            pass

    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    return {"detail": "logged out"}
@app.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: ChangePasswordRequest, current_user: UserInDB = Depends(get_current_active_user)):
    if current_user.auth_provider != "local" or not current_user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account uses an external provider (e.g., Google). Password changes are not available.",
        )
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )
    new_hash = get_password_hash(body.new_password)

    # Assuming user_db is keyed by username:
    if current_user.username not in user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User record not found",
        )

    user_db[current_user.username]["hashed_password"] = new_hash

    save_user_db(user_db)
    return {"detail": "Password changed successfully"}
@app.post("/auth/set-disabled", status_code=status.HTTP_204_NO_CONTENT)
async def set_disabled(body: SetDisabledRequest, current_user: UserInDB = Depends(get_current_active_user)):
    #TODO: for now, allow self-toggle (useful for testing)
    # Later, implement admin checks.
    user_db[current_user.username]["disabled"] = bool(body.disabled)
    save_user_db(user_db)
    return {"detail": "Disabled user"}