from pydantic import BaseModel
from typing import Optional

from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades


class ModifyBudgetSettingDTO(BaseModel):
    symbol: Optional[str]
    timeframe_budget_id: int
    time_frame: Optional[str]
    trades: Trades
    budget_utilization: int
    start_range: int
    end_range: int
