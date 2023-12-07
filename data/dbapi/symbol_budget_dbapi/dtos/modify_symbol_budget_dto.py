from pydantic import BaseModel
from typing import Optional


class ModifySymbolBudgetDTO(BaseModel):
    symbol: str
    time_frame: Optional[str]
    budget: float
