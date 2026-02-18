from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    GamblingSeasonState, 
    GamblingSeason as GamblingSeasonModel, 
    Gambler as GamblerModel, 
    User as UserModel
)

class Gambler(BaseModel):
    id: int
    user_id: int
    first_name: str
    last_name: str

    @classmethod
    async def from_model(cls, gambler: GamblerModel, model: GamblerModel):
        return cls(
            id=model.id, 
            user_id=model.user_id, 
            first_name=model.user.first_name, 
            last_name=model.user.last_name
        )

class GamblingSeason(BaseModel):
    id: int
    name: str
    year: int
    state: GamblingSeasonState

class GamblerSeason(BaseModel):
    gambler: Gambler
    gambling_season: GamblingSeason
