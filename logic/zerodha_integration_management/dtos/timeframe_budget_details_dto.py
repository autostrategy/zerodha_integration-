from pydantic import BaseModel
from typing import Optional

from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades


class TimeframeBudgetDetailsDTO(BaseModel):
    budget: BudgetPart
    no_of_trades: Trades
    start_range: Optional[int]
    end_range: Optional[int]
    