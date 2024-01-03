from pydantic import BaseModel
from typing import Optional

from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades


class TimeFrameBudgetDTO(BaseModel):
    timeframe_budget_id: int
    time_frame: Optional[str]
    budget_utilization: BudgetPart
    trades: Trades
    start_range: Optional[int]
    end_range: Optional[int]
