from pydantic import BaseModel

from .data import GamblingSeason

class GetUserGamblingSeasonsResponseData(BaseModel):
    seasons: list[GamblingSeason]