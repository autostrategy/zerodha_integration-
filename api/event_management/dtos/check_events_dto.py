import pytz

from config import default_log
from datetime import datetime
from pydantic import BaseModel, validator

from data.enums.signal_type import SignalType
from data.enums.configuration import Configuration


class CheckEventsDTO(BaseModel):
    symbol: str
    time_of_candle_formation: datetime
    time_frame_in_minutes: str
    signal_type: SignalType

    @validator("time_frame_in_minutes")
    def validate_time_frame_in_minutes(cls, time_frame_in_minutes, **kwargs):
        default_log.debug(f"inside validate_time_frame_in_minutes(time_frame_in_minutes={time_frame_in_minutes})")

        valid_time_frames = ['1', '3', '5', '10', '15', '30', '60']

        if time_frame_in_minutes not in valid_time_frames:
            default_log.debug(f"Invalid timeframe value supplied={time_frame_in_minutes}")
            raise ValueError(f"Invalid timeframe value (values must be = {valid_time_frames})")

        return time_frame_in_minutes
