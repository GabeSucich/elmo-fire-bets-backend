import asyncio
import datetime

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from fastapi_login import LoginManager
from utils.auth import verify_password
from database import async_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from passlib.hash import bcrypt

from models import User, Gambler
from utils.env_vars import EnvVarName, load_env_var

# fastapi-login defaults to a 15 minute token, which logged people out mid-session.
# This is a private league app, not a bank: a long session is the right trade, and the
# client re-authenticates from stored credentials when a token does finally lapse.
TOKEN_LIFETIME = datetime.timedelta(days=30)

manager = LoginManager(
    load_env_var(EnvVarName.SECRET),
    token_url="/auth/login",
    default_expiry=TOKEN_LIFETIME,
)

router = APIRouter(tags=["Auth"])

@manager.user_loader()
async def load_user(username: str):
    for attempt in range(3):
        try:
            async with async_session() as db:
                user_query = await db.execute(
                    select(User)
                    .where(User.username == username)
                    .options(
                        selectinload(User.gamblers)
                        .selectinload(Gambler.gambling_season)
                    )
                )
                user: User | None = user_query.scalar_one_or_none()
                if user is None:
                    raise HTTPException(status_code=500, detail="Username was not recognized")
                return user
        except HTTPException:
            raise
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(2)

class LoginRequestData(BaseModel):
    username: str
    password: str

class LoginResponseData(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    token: str

@router.post("/login", operation_id="login", response_model=LoginResponseData)
async def login(data: LoginRequestData) -> LoginResponseData:
    user = await load_user(data.username)
    if not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = manager.create_access_token(data={"sub": user.username}, expires=TOKEN_LIFETIME)
    return LoginResponseData(user_id=user.id, first_name=user.first_name, last_name=user.last_name, token=token)
            