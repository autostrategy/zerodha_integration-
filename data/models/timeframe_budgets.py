from data.db.init_db import ModelBase
from sqlalchemy import Column, Integer, String, Float, Enum

from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades


class TimeframeBudgets(ModelBase):
    __tablename__ = "timeframe_budgets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    time_frame = Column(String)
    trades = Column(Enum(Trades))
    budget = Column(Enum(BudgetPart))
    start_range = Column(Integer)
    end_range = Column(Integer)
