from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TPDetailsDTO(BaseModel):
    timestamp: Optional[datetime]
    tp_value: Optional[float]
    high_1: Optional[float]
    sl_value: Optional[float]
    high: Optional[float]
    low_1: Optional[float]
    low: Optional[float]
    entry_price: Optional[float]
    greatest_price: Optional[float]
    tp_buffer_percent: Optional[float]
    tp_with_buffer: Optional[float]
