from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.schemas.token import TokenPayload
from app.crud.crud_user import get_user_by_email

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"/api/v1/auth/login/access-token"
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(reusable_oauth2)
) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"]
        )
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = await get_user_by_email(db, email=token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

# Planning works signed out. When a token IS sent, the plan is saved to that
# account; auto_error=False means a missing token is not an error here.
optional_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login/access-token", auto_error=False
)


async def get_optional_user(
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(optional_oauth2),
) -> User | None:
    """The signed-in user, or None. A bad token is ignored rather than
    refused - a stale token must not stop someone planning a trip."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError):
        return None
    user = await get_user_by_email(db, email=token_data.sub)
    return user if user and user.is_active else None
