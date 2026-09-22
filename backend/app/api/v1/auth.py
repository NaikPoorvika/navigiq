from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.region import in_region
from app.core.security import create_access_token
from app.crud import crud_user
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import ProfileUpdate, UserCreate, UserRegister, UserResponse

router = APIRouter()


def _invalid(field: str, message: str) -> HTTPException:
    """Same error envelope as /plan, so the frontend handles both the same way."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error": {
            "code": "SEMANTIC_INVALID", "message": message,
            "details": {"errors": [{"field": field, "message": message}]},
        }},
    )


@router.post("/login/access-token", response_model=Token)
async def login_access_token(
    db: AsyncSession = Depends(deps.get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests."""
    user = await crud_user.authenticate_user(
        db, email=form_data.username.strip().lower(), password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return {"access_token": create_access_token(user.email), "token_type": "bearer"}


@router.post("/users", response_model=UserResponse)
async def create_user(
    *,
    db: AsyncSession = Depends(deps.get_db),
    user_in: UserRegister,
) -> Any:
    """Public sign-up. Accepts email and password ONLY - the server decides
    is_active and is_superuser. Before this, any caller could send
    is_superuser: true and make themselves an administrator."""
    if await crud_user.get_user_by_email(db, email=user_in.email):
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists.",
        )
    return await crud_user.create_user(db, user_in=UserCreate(
        email=user_in.email,
        password=user_in.password,
        is_active=True,
        is_superuser=False,
    ))


@router.get("/users/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Get current user, including their planning profile."""
    return current_user


@router.patch("/users/me", response_model=UserResponse)
async def update_my_profile(
    profile: ProfileUpdate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Update the planning profile. Only the fields sent are changed."""
    sent = profile.model_fields_set

    if "interests" in sent and profile.interests is not None:
        rows = await db.execute(text("SELECT key FROM poi_categories"))
        valid = {r[0] for r in rows}
        unknown = sorted(set(profile.interests) - valid)
        if unknown:
            raise _invalid("interests", f"Unknown interests: {', '.join(unknown)}")
        current_user.interests = list(dict.fromkeys(profile.interests))   # de-duplicate, keep order

    if "home" in sent:
        if profile.home is None:
            current_user.home_name = current_user.home_lat = current_user.home_lon = None
        else:
            if not in_region(profile.home.lat, profile.home.lon):
                raise _invalid("home", "Home must be in the Bengaluru region.")
            current_user.home_name = profile.home.name.strip()
            current_user.home_lat = profile.home.lat
            current_user.home_lon = profile.home.lon

    if "display_name" in sent:
        current_user.display_name = (profile.display_name or "").strip() or None

    if "vegetarian" in sent and profile.vegetarian is not None:
        current_user.vegetarian = profile.vegetarian

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user
