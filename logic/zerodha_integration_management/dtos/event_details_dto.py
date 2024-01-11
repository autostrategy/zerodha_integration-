from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from logic.zerodha_integration_management.dtos.tp_details_dto import TPDetailsDTO


class EventDetailsDTO(BaseModel):
    symbol: Optional[str]
    time_frame: Optional[str]
    trade1_quantity: Optional[int]
    event1_occur_time: Optional[datetime]
    event2_occur_time: Optional[datetime]
    event3_occur_time: Optional[datetime]
    event2_occur_breakpoint: Optional[float]
    event3_occur_breakpoint: Optional[float]
    current_candle_high: Optional[float]
    current_candle_low: Optional[float]
    candle_length: Optional[float]
    highest_point: Optional[float]  # For 'SELL' part
    lowest_point: Optional[float]
    event1_candle_high: Optional[float]
    adjusted_high: Optional[float]
    event1_candle_low: Optional[float]
    adjusted_low: Optional[float]  # For 'SELL' part
    high_1: Optional[float]
    low_1: Optional[float]  # For 'SELL' part
    sl_value: Optional[float]
    tp_values: Optional[list[TPDetailsDTO]] = []
    sl_hit: bool = False
    tp_hit: bool = False
    sl_candle_time: Optional[datetime]
    tp_candle_time: Optional[datetime]
    entry_trade_order_id: Optional[str]
    sl_order_id: Optional[str]
    tp_order_id: Optional[str]
    tp_order_status: Optional[str]
    sl_order_status: Optional[str]
    entry_price: Optional[float]
    extension1_trade_order_id: Optional[str]
    extension2_trade_order_id: Optional[str]
    extension_quantity: Optional[int]
    value_to_add_for_stop_loss_entry_price: Optional[float]
    previous_timestamp: Optional[datetime]
    extension1_quantity: Optional[int]
    extension2_quantity: Optional[int]
    extension1_entry_price: Optional[float]
    extension2_entry_price: Optional[float]
    stop_tracking_further_events: Optional[bool]
