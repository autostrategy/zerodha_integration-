from data.db.init_db import ModelBase
from sqlalchemy import Column, Integer, String, Enum, Float

from data.enums.trades import Trades


class TimeframeBudgets(ModelBase):
    __tablename__ = "timeframe_budgets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    symbol = Column(String)
    time_frame = Column(String)
    trades = Column(Enum(Trades))
    budget = Column(Integer)
    start_range = Column(Float)
    end_range = Column(Float)
