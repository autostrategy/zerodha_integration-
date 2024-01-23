from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from data.enums.configuration import Configuration
from data.enums.signal_type import SignalType


class EventThreadDetailsDTO(BaseModel):
    alert_time: Optional[datetime]
    symbol: Optional[str]
    time_frame: Optional[str]
    signal_type: Optional[SignalType]
    configuration_type: Optional[Configuration]
    signal_candle_high: Optional[float]
    adjusted_high: Optional[float]
    signal_candle_low: Optional[float]
    adjusted_low: Optional[float]
    event1_occur_time: Optional[datetime]
    event2_breakpoint: Optional[float]
    event2_occur_time: Optional[datetime]
    event3_occur_time: Optional[datetime]
    lowest_point: Optional[float]
    highest_point: Optional[float]
    tp_value: Optional[float]
    tp_datetime: Optional[datetime]
    sl_value: Optional[float]
    sl_datetime: Optional[datetime]
    signal_trade_order_id: Optional[str]
    tp_order_id: Optional[str]
    sl_order_id: Optional[str]
    is_completed: Optional[bool]
    description: Optional[str]
    entry_price: Optional[float]
    trade1_quantity: Optional[int]
    extension_quantity: Optional[int]
    extension1_order_id: Optional[str]
    extension2_order_id: Optional[str]
    extension1_quantity: Optional[int]
    extension2_quantity: Optional[int]
