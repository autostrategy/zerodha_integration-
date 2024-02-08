from typing import Optional
from datetime import datetime
from pydantic import BaseModel

from data.dbapi.thread_details_dbapi.dtos.event_detail_dto import EventDetailDTO
from data.enums.signal_type import SignalType


class SingleEventDetailDTO(BaseModel):
    date_time: Optional[datetime]
    symbol: str
    time_frame: str
    signal_type: Optional[SignalType]
    event_one: EventDetailDTO
    event_two: EventDetailDTO
    event_three: EventDetailDTO
    take_profit: Optional[float]
    stop_loss: Optional[float]
    quantity: Optional[int]
    extension_quantity_one: Optional[int]
    extension_quantity_two: Optional[int]
    extended_sl: Optional[float]
    extended_sl_timestamp: Optional[str]
    cover_sl: Optional[float]
    cover_sl_quantity: Optional[int]
    # trade_status: str
    reverse1_trade_quantity: Optional[int]
    reverse2_trade_quantity: Optional[int]
    reverse_trade_take_profit: Optional[float]
    reverse_trade_stop_loss: Optional[float]
    reverse1_entry_price: Optional[float]
    reverse2_entry_price: Optional[float]
    trade_status: Optional[str]
