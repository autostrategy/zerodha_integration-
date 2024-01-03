from pydantic import BaseModel
from typing import Optional


class ModifySymbolBudgetDTO(BaseModel):
    symbol_budget_id: int
    symbol: Optional[str]
    time_frame: Optional[str]
    budget: float
