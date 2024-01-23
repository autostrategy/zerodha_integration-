from data.db.init_db import ModelBase
from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, Enum

from data.enums.configuration import Configuration
from data.enums.signal_type import SignalType


class ThreadDetails(ModelBase):
    __tablename__ = "thread_details"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    symbol = Column(String)
    time_frame = Column(String)
    signal_type = Column(Enum(SignalType))
    configuration_type = Column(Enum(Configuration))
    alert_time = Column(DateTime)
    signal_candle_high = Column(Float)
    adjusted_high = Column(Float)
    signal_candle_low = Column(Float)
    adjusted_low = Column(Float)
    event1_occur_time = Column(DateTime)
    event2_breakpoint = Column(Float)
    event2_occur_time = Column(DateTime)
    event3_occur_time = Column(DateTime)
    lowest_point = Column(Float)
    highest_point = Column(Float)
    signal_trade_order_id = Column(String)
    tp_value = Column(Float)
    tp_datetime = Column(DateTime)
    tp_order_id = Column(String)
    sl_value = Column(Float)
    sl_order_id = Column(String)
    sl_datetime = Column(DateTime)
    is_completed = Column(Boolean)
    entry_price = Column(Float)
    trade1_quantity = Column(Integer)
    extension1_order_id = Column(String)
    extension2_order_id = Column(String)
    extension_quantity = Column(Integer)
    extension1_quantity = Column(Integer)
    extension2_quantity = Column(Integer)
