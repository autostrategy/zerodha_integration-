from typing import Optional
from config import default_log
from data.db.init_db import get_db
from decorators.handle_generic_exception import dbapi_exception_handler
from data.models.timeframe_budgets import TimeframeBudgets


@dbapi_exception_handler
def find_timeframe_budget_details_by_timeframe(timeframe: Optional[str] = None, session=None, close_session=True):
    default_log.debug(f"inside find_timeframe_budget_details_by_timeframe with timeframe={timeframe}")

    db = session if session else next(get_db())

    timeframe_budget = db.query(TimeframeBudgets).filter(TimeframeBudgets.timeframe == timeframe).all()

    default_log.debug(f"Total {len(timeframe_budget)} returned for timeframe={timeframe}")

    return timeframe_budget


@dbapi_exception_handler
def get_all_timeframe_budgets(session=None, close_session=True):
    default_log.debug("inside get_all_timeframe_budgets")

    db = session if session else next(get_db())

    timeframe_budget = db.query(TimeframeBudgets).all()

    default_log.debug(f"Total {len(timeframe_budget)} returned")

    return timeframe_budget
