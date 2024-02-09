from pydantic import BaseModel
from typing import Optional

from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades


class TimeFrameBudgetDTO(BaseModel):
    timeframe_budget_id: int
    symbol: Optional[str]
    time_frame: Optional[str]
    budget_utilization: int
    trades: Trades
    start_range: Optional[float]
    end_range: Optional[float]
