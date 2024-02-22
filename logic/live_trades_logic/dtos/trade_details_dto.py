from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from data.enums.signal_type import SignalType


class TradeDetailDTO(BaseModel):
    signal_type: Optional[SignalType]
    quantity: Optional[int]
    trade_time: Optional[datetime]
    order_id: Optional[str]
