from typing import Optional, Literal
from pydantic import BaseModel, Field, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str
class TokenData(BaseModel):
    username : str or None = None
class UserPublic(BaseModel):
    # what you return outward (safe)
    uid : str
    username: str
    email: EmailStr | None = None
    full_name: str | None = None
    disabled: bool = False
class UserCreate(BaseModel):
    # what you accept on signup
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)
    email: EmailStr | None = None
    full_name: Optional[str | None] = None
class UserInDB(UserPublic):
    #local account only
    hashed_password: Optional[str | None] = None

    #gates password-only behavior
    auth_provider: Literal["local", "google"] = "local"

    #Google's stable subject id
    google_sub: Optional[str | None] = None
class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)
class SetDisabledRequest(BaseModel):
    disabled: bool
class GoogleAuthRequest(BaseModel):
    id_token: str = Field(..., min_length=10)