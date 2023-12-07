from pydantic import BaseModel
from typing import Optional


class AddSymbolBudgetDTO(BaseModel):
    symbol: Optional[str]
    time_frame: Optional[str]
    budget: float
