from fastapi import APIRouter
from pydantic import BaseModel

from models import SlateType

router = APIRouter(prefix="/slate_types", tags=["SlateTypes"])

class ListSlateTypesResponseData(BaseModel):
    slate_types: list[SlateType]

@router.get("/", operation_id="list_slate_types", response_model=ListSlateTypesResponseData)
async def list_slate_types():
    return ListSlateTypesResponseData(
        slate_types=list(SlateType)
    )