from pydantic import BaseModel
from typing import Optional

from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades


class AddBudgetSettingDTO(BaseModel):
    time_frame: Optional[str]
    trades: Trades
    budget_utilization: BudgetPart
    start_range: int
    end_range: int
