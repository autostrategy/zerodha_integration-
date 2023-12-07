from data.db.init_db import ModelBase
from sqlalchemy import Column, Integer, String, Float


class SymbolBudget(ModelBase):
    __tablename__ = "symbol_budget"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    symbol = Column(String)
    time_frame = Column(String)
    budget = Column(Float)
