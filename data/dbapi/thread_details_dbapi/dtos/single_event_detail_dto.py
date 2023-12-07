from typing import Optional
from datetime import datetime
from pydantic import BaseModel

from data.dbapi.thread_details_dbapi.dtos.event_detail_dto import EventDetailDTO


class SingleEventDetailDTO(BaseModel):
    date_time: datetime
    symbol: str
    time_frame: str
    event_one: EventDetailDTO
    event_two: EventDetailDTO
    event_three: EventDetailDTO
    take_profit: Optional[float]
    stop_loss: Optional[float]
    quantity: Optional[int]
    extension_quantity_one: Optional[int]
    extension_quantity_two: Optional[int]
    trade_status: str