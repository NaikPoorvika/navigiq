import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# Shared properties
class UserBase(BaseModel):
    email: str
    is_active: bool = True
    is_superuser: bool = False


class UserCreate(UserBase):
    """INTERNAL - built by the server. Never accepted from the public API:
    it carries is_superuser, and a client must not be able to set that."""
    password: str


class UserRegister(BaseModel):
    """Public sign-up: email and password ONLY.

    extra="forbid" rejects any other field, so a request carrying
    is_superuser or is_active fails loudly instead of being honoured.
    """
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        v = v.strip().lower()   # one account per address, whatever the case
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("password")
    @classmethod
    def password_rules(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("Use at least one letter and one number.")
        # bcrypt reads only the first 72 BYTES - a longer password would be
        # silently truncated, so refuse it instead.
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password is too long.")
        return v


class HomeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lat: float
    lon: float


class ProfileUpdate(BaseModel):
    """PATCH /auth/users/me - only the fields sent are changed."""
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=80)
    home: HomeIn | None = None
    interests: list[str] | None = Field(default=None, max_length=20)
    vegetarian: bool | None = None


class DeleteAccountRequest(BaseModel):
    """Deleting an account is permanent, so the password is asked for again -
    a signed-in device left unattended must not be enough."""
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=72)


# Properties to return via API
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    is_active: bool = True
    is_superuser: bool = False
    display_name: str | None = None
    home_name: str | None = None
    home_lat: float | None = None
    home_lon: float | None = None
    interests: list[str] = []
    vegetarian: bool = False

    @field_validator("interests", mode="before")
    @classmethod
    def none_to_empty(cls, v):
        return v or []

    @field_validator("vegetarian", mode="before")
    @classmethod
    def none_to_false(cls, v):
        return bool(v)
