"""Sign-up and profile validation. No database needed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.schemas.user import DeleteAccountRequest, ProfileUpdate, UserRegister, UserResponse  # noqa: E402


def test_signup_rejects_is_superuser():
    """The hole this fixes: anyone could register as an administrator."""
    with pytest.raises(ValidationError):
        UserRegister(email="a@b.co", password="secret123", is_superuser=True)


def test_signup_rejects_is_active():
    with pytest.raises(ValidationError):
        UserRegister(email="a@b.co", password="secret123", is_active=False)


def test_email_is_normalised():
    assert UserRegister(email="  Priya@Example.COM ", password="secret123").email == "priya@example.com"


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "@b.co", "a b@c.co"])
def test_invalid_email_rejected(email):
    with pytest.raises(ValidationError):
        UserRegister(email=email, password="secret123")


@pytest.mark.parametrize("password", ["short1", "lettersonly", "12345678"])
def test_weak_password_rejected(password):
    with pytest.raises(ValidationError):
        UserRegister(email="a@b.co", password=password)


def test_password_over_72_bytes_rejected():
    """bcrypt reads only 72 bytes; 30 x 3-byte characters is 90 bytes."""
    with pytest.raises(ValidationError):
        UserRegister(email="a@b.co", password="a1" + "ಕ" * 30)


def test_profile_update_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ProfileUpdate(is_superuser=True)


def test_profile_update_tracks_only_sent_fields():
    p = ProfileUpdate(vegetarian=True)
    assert p.model_fields_set == {"vegetarian"}


def test_response_fills_missing_profile_values():
    class Row:
        id = "5b7c7b0e-5f55-4e0a-9a2e-2d6f4b1f6c11"
        email = "a@b.co"
        is_active = True
        is_superuser = False
        display_name = None
        home_name = None
        home_lat = None
        home_lon = None
        interests = None
        vegetarian = None

    r = UserResponse.model_validate(Row())
    assert r.interests == [] and r.vegetarian is False


def test_delete_needs_a_password():
    with pytest.raises(ValidationError):
        DeleteAccountRequest(password="")


def test_delete_rejects_extra_fields():
    with pytest.raises(ValidationError):
        DeleteAccountRequest(password="secret123", user_id="someone-else")
