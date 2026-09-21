from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    get_password_hash, hash_token, new_family, new_refresh_token, refresh_expiry, verify_password,
)
from app.models.user import RefreshToken, User
from app.schemas.user import UserCreate

# A real bcrypt hash of a random string: comparing against it when the email
# is unknown keeps login time independent of whether the account exists.
_DUMMY_HASH = get_password_hash(uuid.uuid4().hex)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.strip().lower()))
    return result.scalars().first()


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, user_in: UserCreate) -> User:
    user = User(email=user_in.email, hashed_password=get_password_hash(user_in.password),
                display_name=user_in.display_name, is_active=True, is_superuser=False)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def issue_refresh_token(db: AsyncSession, user_id: uuid.UUID,
                              family: uuid.UUID | None = None) -> str:
    token = new_refresh_token()
    db.add(RefreshToken(user_id=user_id, token_hash=hash_token(token),
                        family_id=family or new_family(), expires_at=refresh_expiry()))
    await db.commit()
    return token


class RefreshError(Exception):
    pass


async def rotate_refresh_token(db: AsyncSession, token: str) -> tuple[User, str]:
    row = (await db.execute(select(RefreshToken).where(
        RefreshToken.token_hash == hash_token(token)).with_for_update())).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        raise RefreshError("invalid refresh token")
    if row.revoked_at is not None:
        # Reuse of a rotated token: assume theft, revoke the whole family.
        await db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id,
                                                    RefreshToken.revoked_at.is_(None))
                         .values(revoked_at=now))
        await db.commit()
        raise RefreshError("refresh token reuse detected")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise RefreshError("refresh token expired")
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise RefreshError("account unavailable")
    row.revoked_at = now
    await db.flush()
    new = await issue_refresh_token(db, user.id, row.family_id)
    return user, new


async def revoke_refresh_token(db: AsyncSession, token: str) -> None:
    row = (await db.execute(select(RefreshToken).where(
        RefreshToken.token_hash == hash_token(token)))).scalar_one_or_none()
    if row is not None:
        await db.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id,
                                                    RefreshToken.revoked_at.is_(None))
                         .values(revoked_at=datetime.now(timezone.utc)))
        await db.commit()


async def delete_user(db: AsyncSession, user: User) -> None:
    """Delete the account and everything attributed to it (FK cascades)."""
    await db.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": user.id})
    await db.commit()
