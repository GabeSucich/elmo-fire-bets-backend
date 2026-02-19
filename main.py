from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

import asyncio
from fastapi import FastAPI, APIRouter, Request, HTTPException

from database import get_db
from routers.auth import router as auth_router
from routers.gambling_seasons import router as gambling_season_router
from routers.parlays import router as parlays_router
from routers.picks import router as pick_router
from routers.vetoes import router as veto_router

app = FastAPI()

# fast_url_snippets = [
#     "login",
#     "gambling_seasons"
# ]

# error_post_url_snippets = [

# ]

# @app.middleware("http")
# async def add_delay(request: Request, call_next):
#     response = await call_next(request)
#     if not any(snippet in request.url.path for snippet in fast_url_snippets):
#         await asyncio.sleep(1)
#     if any(snippet in request.url.path and request.method == "POST" for snippet in error_post_url_snippets):
#         return HTTPException(status_code=500, detail="This is the error we want to see!")
#     return response

app.include_router(auth_router)
app.include_router(gambling_season_router)
app.include_router(parlays_router)
app.include_router(pick_router)
app.include_router(veto_router)