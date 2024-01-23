from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class RestartEventDTO(BaseModel):
    thread_id: int
    symbol: str
    time_frame: str
    alert_time: Optional[datetime]
    candle_high: Optional[float]
    candle_low: Optional[float]
    adjusted_high: Optional[float]
    adjusted_low: Optional[float]
    event1_occur_time: Optional[datetime]
    event2_breakpoint: Optional[float]
    event2_occur_time: Optional[datetime]
    event3_occur_time: Optional[datetime]
    lowest_point: Optional[float]
    highest_point: Optional[float]
    sl_value: Optional[float]
    tp_value: Optional[float]
    signal_trade_order_id: Optional[str]
    tp_order_id: Optional[str]
    sl_order_id: Optional[str]
    entry_price: Optional[float]
    trade1_quantity: Optional[int]
    extension_quantity: Optional[int]
    extension1_order_id: Optional[str]
    extension2_order_id: Optional[str]
    extension1_quantity: Optional[int]
    extension2_quantity: Optional[int]
