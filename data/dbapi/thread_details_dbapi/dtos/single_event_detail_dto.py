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
    trade_status: str
