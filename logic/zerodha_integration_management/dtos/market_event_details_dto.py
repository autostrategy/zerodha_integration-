from pydantic import BaseModel
from datetime import datetime
from data.enums.signal_type import SignalType
from logic.zerodha_integration_management.dtos.event_details_dto import EventDetailsDTO


class MarketEventDetailsDTO(BaseModel):
    symbol: str
    time_of_candle_formation: datetime
    time_frame: str
    signal_type: SignalType
    events: list[EventDetailsDTO]
