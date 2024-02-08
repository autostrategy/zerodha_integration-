from pydantic import BaseModel
from typing import Optional

from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades


class AddBudgetSettingDTO(BaseModel):
    symbol: Optional[str]  # if nothing passed then it is assumed as ALL STOCKS
    time_frame: Optional[str]
    trades: Trades
    budget_utilization: int
    start_range: int
    end_range: int
