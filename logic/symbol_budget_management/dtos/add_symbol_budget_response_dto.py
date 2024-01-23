from pydantic import BaseModel
from typing import Optional


class AddSymbolBudgetResponseDTO(BaseModel):
    error: bool
    error_message: Optional[str]
