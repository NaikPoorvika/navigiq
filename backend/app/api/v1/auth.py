"""Authentication (section 70): register, login, refresh, logout, /me,
account deletion. Anonymous plans are adopted by the account on sign-in when
the browser sends its session id."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    api_error, auth_limiter, client_key, current_user, get_db, session_id,
)
from app.config import settings
from app.core.security import create_access_token, verify_password
from app.crud import crud_user
from app.models.user import User
from app.schemas.user import (
    DeleteAccountRequest, LoginRequest, RefreshRequest, TokenPair, UserCreate, UserResponse,
)
from app.services.planning.store import claim_session_plans

router = APIRouter()


async def _tokens(db: AsyncSession, user: User) -> TokenPair:
    refresh = await crud_user.issue_refresh_token(db, user.id)
    return TokenPair(access_token=create_access_token(user.id), refresh_token=refresh,
                     expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                     user=UserResponse.model_validate(user))


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, request: Request, db: AsyncSession = Depends(get_db),
                   sid: str | None = Depends(session_id)) -> TokenPair:
    auth_limiter.check(client_key(request))
    if await crud_user.get_user_by_email(db, body.email):
        raise api_error(status.HTTP_409_CONFLICT, "EMAIL_TAKEN",
                        "an account with this email already exists")
    user = await crud_user.create_user(db, body)
    if sid:
        await claim_session_plans(db, sid, user.id)
    return await _tokens(db, user)


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db),
                sid: str | None = Depends(session_id)) -> TokenPair:
    auth_limiter.check(client_key(request))
    user = await crud_user.authenticate_user(db, body.email, body.password)
    if user is None or not user.is_active:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS",
                        "incorrect email or password")
    claim = sid or body.session_id
    if claim:
        await claim_session_plans(db, claim, user.id)
    return await _tokens(db, user)


@router.post("/login/access-token")
async def login_form(request: Request, form: OAuth2PasswordRequestForm = Depends(),
                     db: AsyncSession = Depends(get_db)) -> dict:
    """OAuth2 password flow (kept for API tooling / the OpenAPI Authorize button)."""
    auth_limiter.check(client_key(request))
    user = await crud_user.authenticate_user(db, form.username, form.password)
    if user is None or not user.is_active:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS",
                        "incorrect email or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, request: Request,
                  db: AsyncSession = Depends(get_db)) -> TokenPair:
    auth_limiter.check(client_key(request))
    try:
        user, new_refresh = await crud_user.rotate_refresh_token(db, body.refresh_token)
    except crud_user.RefreshError as exc:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "REFRESH_INVALID", str(exc))
    return TokenPair(access_token=create_access_token(user.id), refresh_token=new_refresh,
                     expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                     user=UserResponse.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> None:
    await crud_user.revoke_refresh_token(db, body.refresh_token)


me_router = APIRouter()


@me_router.get("", response_model=UserResponse)
async def me(user: User = Depends(current_user)) -> User:
    return user


@me_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(body: DeleteAccountRequest, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)) -> None:
    if not verify_password(body.password, user.hashed_password):
        raise api_error(status.HTTP_403_FORBIDDEN, "INVALID_CREDENTIALS", "password is incorrect")
    await crud_user.delete_user(db, user)
