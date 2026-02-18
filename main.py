from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

from fastapi import FastAPI, APIRouter

from database import get_db
from routers.auth import router as auth_router
from routers.gambling_seasons import router as gambling_season_router
from routers.parlays import router as parlays_router
from routers.picks import router as pick_router
from routers.vetoes import router as veto_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(gambling_season_router)
app.include_router(parlays_router)
app.include_router(pick_router)
app.include_router(veto_router)