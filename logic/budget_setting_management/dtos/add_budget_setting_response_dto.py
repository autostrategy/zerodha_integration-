from pydantic import BaseModel
from typing import Optional


class AddBudgetSettingResponseDTO(BaseModel):
    error: bool
    error_message: Optional[str]
