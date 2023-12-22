from pydantic import BaseModel
from typing import Optional

from logic.zerodha_integration_management.dtos.trades_to_make_dto import TradesToMakeDTO


class TimeframeBudgetAndTradesDetailsDTO(BaseModel):
    budget: Optional[float]
    trades_to_make: Optional[TradesToMakeDTO]
