from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Path, Request, Response, UploadFile

from app.trade.common.api import require_write
from app.trade.settings import operations
from app.trade.settings.models import BankInput, CompanyInput, CounterpartyInput, PriceInput
from app.trade.settings.repository import SQLSettings
from app.auth.deps import current_user_id

router = APIRouter(prefix="/api/trade/settings", tags=["trade-settings"])


@router.get("")
def read(request: Request, response: Response, user_id: int = Depends(current_user_id)):
    response.headers["Cache-Control"] = "private, no-store"
    return operations.read_settings(repository=SQLSettings(request.app.state.database, user_id))


@router.put("/company")
def company(command: CompanyInput, request: Request, user_id: int = Depends(require_write)):
    return operations.save_company(command, repository=SQLSettings(request.app.state.database, user_id))


@router.put("/banks/{currency}")
def bank(currency: Annotated[str, Path(pattern=r"^[A-Z]{3}$")], command: BankInput,
         request: Request, user_id: int = Depends(require_write)):
    return operations.save_bank(currency, command, repository=SQLSettings(request.app.state.database, user_id))


@router.put("/prices")
def price(command: PriceInput, request: Request, user_id: int = Depends(require_write)):
    return operations.save_price(command, repository=SQLSettings(request.app.state.database, user_id))


@router.post("/branding/{kind}")
async def branding(kind: Literal["logo", "seal"], request: Request,
                   image: Annotated[UploadFile, File()], user_id: int = Depends(require_write)):
    content = await image.read(operations.MAX_BRANDING_BYTES + 1)
    return operations.save_branding(kind, content, repository=SQLSettings(request.app.state.database, user_id),
                                    storage=request.app.state.storage)


@router.put("/counterparties")
def counterparty(command: CounterpartyInput, request: Request, user_id: int = Depends(require_write)):
    return operations.save_counterparty(command, repository=SQLSettings(request.app.state.database, user_id))
