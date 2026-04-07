from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

import BackendAPI.server as server

pytestmark = pytest.mark.asyncio

class FakeUserInDB:
    def __init__(
        self,
        username="charles",
        email="charles@example.com",
        disabled=False,
        hashed_password="hashedpw",
        auth_provider="local",
        encounter_ids=None,
        player_ids=None,
        uid="uid-1",
    ):
        self.username = username
        self.email = email
        self.disabled = disabled
        self.hashed_password = hashed_password
        self.auth_provider = auth_provider
        self.encounter_ids = encounter_ids or []
        self.player_ids = player_ids or []
        self.uid = uid


@pytest.fixture
def active_user():
    return FakeUserInDB()


async def test_signup(monkeypatch):
    created_user = FakeUserInDB(
        username="newuser",
        email="newuser@example.com",
        disabled=False,
        encounter_ids=[],
        player_ids=[],
        uid="uid-new",
    )

    async def fake_create_user(user_in):
        return created_user

    monkeypatch.setattr(server, "createUser", fake_create_user)

    body = SimpleNamespace(username="newuser", email="newuser@example.com", password="pw123")
    result = await server.signup(body)

    assert result.uid == "uid-new"
    assert result.username == "newuser"
    assert result.email == "newuser@example.com"
    assert result.disabled is False

async def test_login(monkeypatch):
    user = FakeUserInDB(username="charles")

    monkeypatch.setattr(server, "cleanupExpiredRefreshSessions", lambda: None)

    async def fake_authenticate(username, password):
        assert username == "charles"
        assert password == "pw123"
        return user

    async def fake_issue_access_auth(auth_user, response):
        assert auth_user is user
        assert isinstance(response, Response)
        return {"access_token": "access-123", "token_type": "bearer"}

    monkeypatch.setattr(server, "authenticateUser", fake_authenticate)
    monkeypatch.setattr(server, "issueAccessAuth", fake_issue_access_auth)

    form = SimpleNamespace(username="charles", password="pw123")
    response = Response()

    result = await server.login(response, form)

    assert result == {"access_token": "access-123", "token_type": "bearer"}

async def test_auth_google_existing_user(monkeypatch):
    monkeypatch.setattr(server, "GOOGLE_CLIENT_ID", "client-id-123")

    def fake_verify_oauth2_token(id_token, request, client_id):
        assert id_token == "google-token"
        assert client_id == "client-id-123"
        return {"sub": "google-sub-1", "email": "charles@example.com"}

    async def fake_get_user_by_google_sub(google_sub):
        assert google_sub == "google-sub-1"
        return {
            "username": "charles",
            "email": "charles@example.com",
            "disabled": False,
        }

    async def fake_issue_access_auth(user, response):
        assert user["username"] == "charles"
        return {"access_token": "google-access", "token_type": "bearer"}

    monkeypatch.setattr(server.google_id_token, "verify_oauth2_token", fake_verify_oauth2_token)
    monkeypatch.setattr(server, "getUserByGoogleSub", fake_get_user_by_google_sub)
    monkeypatch.setattr(server, "issueAccessAuth", fake_issue_access_auth)

    body = SimpleNamespace(id_token="google-token")
    response = Response()

    result = await server.authGoogle(body, response)

    assert result == {"access_token": "google-access", "token_type": "bearer"}

async def test_auth_refresh(monkeypatch):
    monkeypatch.setattr(server, "REFRESH_TOKEN_EXPIRE_DAYS", 30)
    monkeypatch.setattr(server, "COOKIE_SECURE", False)
    monkeypatch.setattr(server, "COOKIE_SAMESITE", "lax")
    monkeypatch.setattr(server, "REFRESH_COOKIE_NAME", "refresh_token")
    monkeypatch.setattr(server, "REFRESH_COOKIE_PATH", "/auth")

    def fake_jwt_decode(token, secret, algorithms):
        if token == "old-refresh":
            return {"type": "refresh", "sub": "charles", "jti": "old-jti"}
        if token == "new-refresh-token":
            return {"type": "refresh", "sub": "charles", "jti": "new-jti", "exp": 9999999999}
        raise AssertionError("Unexpected token decode")

    monkeypatch.setattr(server.jwt, "decode", fake_jwt_decode)
    monkeypatch.setattr(server, "hasRefreshSession", lambda username, jti: username == "charles" and jti == "old-jti")
    monkeypatch.setattr(server, "createAccessToken", lambda subject: "new-access-token")
    monkeypatch.setattr(server, "createRefreshToken", lambda subject: ("new-refresh-token", "new-jti"))
    monkeypatch.setattr(server, "replaceRefreshSession", lambda username, oldJti, newJti, newExp: True)

    response = Response()
    result = await server.refreshToken(response, "old-refresh")

    assert result == {"access_token": "new-access-token", "token_type": "bearer"}

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "refresh_token=new-refresh-token" in set_cookie_header
    assert "HttpOnly" in set_cookie_header

async def test_auth_logout(monkeypatch):
    monkeypatch.setattr(server, "REFRESH_COOKIE_NAME", "refresh_token")
    monkeypatch.setattr(server, "REFRESH_COOKIE_PATH", "/auth")

    def fake_jwt_decode(token, secret, algorithms):
        assert token == "refresh-token"
        return {"type": "refresh", "sub": "charles", "jti": "jti-1"}

    revoked = {}

    def fake_revoke(username, jti):
        revoked["username"] = username
        revoked["jti"] = jti

    monkeypatch.setattr(server.jwt, "decode", fake_jwt_decode)
    monkeypatch.setattr(server, "revokeRefreshSession", fake_revoke)

    response = Response()
    result = await server.logout(response, "refresh-token")

    assert result == {"detail": "logged out"}
    assert revoked == {"username": "charles", "jti": "jti-1"}

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header or "expires=" in set_cookie_header.lower()

async def test_change_password(monkeypatch, active_user):
    monkeypatch.setattr(server, "verifyPassword", lambda plain, hashed: plain == "oldpw" and hashed == "hashedpw")
    monkeypatch.setattr(server, "getPasswordHash", lambda pw: f"hashed::{pw}")

    async def fake_get_user_by_username(username):
        assert username == "charles"
        return {
            "username": "charles",
            "email": "charles@example.com",
            "disabled": False,
            "hashed_password": "hashedpw",
            "auth_provider": "local",
            "encounter_ids": [],
            "player_ids": [],
            "uid": "uid-1",
        }

    saved = {}

    async def fake_upsert_user_dict(user_data):
        saved["user_data"] = user_data

    monkeypatch.setattr(server, "get_user_by_username", fake_get_user_by_username)
    monkeypatch.setattr(server, "upsert_user_dict", fake_upsert_user_dict)

    body = SimpleNamespace(current_password="oldpw", new_password="newpw")
    result = await server.changePassword(body, active_user)

    assert result == {"detail": "Password changed successfully"}
    assert saved["user_data"]["hashed_password"] == "hashed::newpw"

async def test_set_disabled(monkeypatch, active_user):
    async def fake_get_user_by_username(username):
        assert username == "charles"
        return {
            "username": "charles",
            "email": "charles@example.com",
            "disabled": False,
            "hashed_password": "hashedpw",
            "auth_provider": "local",
            "encounter_ids": [],
            "player_ids": [],
            "uid": "uid-1",
        }

    saved = {}

    async def fake_upsert_user_dict(user_data):
        saved["user_data"] = user_data

    monkeypatch.setattr(server, "get_user_by_username", fake_get_user_by_username)
    monkeypatch.setattr(server, "upsert_user_dict", fake_upsert_user_dict)

    body = SimpleNamespace(disabled=True)
    result = await server.setDisabled(body, active_user)

    assert result == {"detail": "Disabled user"}
    assert saved["user_data"]["disabled"] is True