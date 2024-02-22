from pydantic import BaseModel
from typing import Optional

from data.enums.trades import Trades


class TimeframeBudgetDetailsDTO(BaseModel):
    budget: int
    no_of_trades: Trades
    start_range: Optional[float]
    end_range: Optional[float]
    