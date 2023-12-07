from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class EventDetailDTO(BaseModel):
    time: Optional[datetime]
    event1_candle_high: Optional[float]
    event1_candle_low: Optional[float]
    adjusted_high: Optional[float]
    adjusted_low: Optional[float]
    event2_breakpoint: Optional[float]
    entry_price: Optional[float]
