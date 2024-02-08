from typing import Optional
from pydantic import BaseModel


class TradesToMakeDTO(BaseModel):
    entry_trade: Optional[bool] = False
    extension1_trade: Optional[bool] = False
    extension2_trade: Optional[bool] = False
    cover_sl_trade: Optional[bool] = False
