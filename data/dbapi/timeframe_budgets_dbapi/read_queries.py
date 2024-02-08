from typing import Optional

from config import default_log
from data.db.init_db import get_db
from data.enums.budget_part import BudgetPart
from data.enums.trades import Trades
from decorators.handle_generic_exception import dbapi_exception_handler
from data.models.timeframe_budgets import TimeframeBudgets


@dbapi_exception_handler
def get_timeframe_budget_by_id(timeframe_budget_id, session=None, close_session=True):
    default_log.debug(f"inside get_timeframe_budget_by_id with id={timeframe_budget_id}")

    db = session if session else next(get_db())

    timeframe_budget = db.query(TimeframeBudgets).filter(TimeframeBudgets.id == timeframe_budget_id).first()

    default_log.debug(f"returning timeframe budget for timeframe_budget_id={timeframe_budget_id}")
    return timeframe_budget


@dbapi_exception_handler
def find_timeframe_budget_details_by_timeframe(timeframe: Optional[str] = None, session=None, close_session=True):
    default_log.debug(f"inside find_timeframe_budget_details_by_timeframe with timeframe={timeframe}")

    db = session if session else next(get_db())

    timeframe_budget = db.query(TimeframeBudgets).filter(TimeframeBudgets.timeframe == timeframe).all()

    default_log.debug(f"Total {len(timeframe_budget)} returned for timeframe={timeframe}")

    return timeframe_budget


@dbapi_exception_handler
def get_budget_setting_by_timeframe_trades_and_budget_utilization(
        timeframe: str,
        trades: Trades,
        budget_utilization: int,
        symbol: Optional[str] = None,
        session=None,
        close_session=True
):
    default_log.debug(f"inside get_budget_setting_by_timeframe_trades_and_budget_utilization with "
                      f"timeframe={timeframe}, trades={trades} and budget_utilization={budget_utilization} "
                      f"with symbol={symbol}")

    db = session if session else next(get_db())

    if symbol is None:
        budget_setting = db.query(TimeframeBudgets).filter(
            TimeframeBudgets.symbol.is_(None),
            TimeframeBudgets.time_frame == timeframe,
            TimeframeBudgets.trades == trades,
            TimeframeBudgets.budget == budget_utilization
        ).first()
    else:
        budget_setting = db.query(TimeframeBudgets).filter(
            TimeframeBudgets.symbol == symbol,
            TimeframeBudgets.time_frame == timeframe,
            TimeframeBudgets.trades == trades,
            TimeframeBudgets.budget == budget_utilization
        ).first()

    default_log.debug(f"Returning budget_setting={budget_setting} for timeframe={timeframe}, trades={trades} and "
                      f"budget_utilization={budget_utilization}")

    return budget_setting


@dbapi_exception_handler
def get_all_timeframe_budgets(session=None, close_session=True):
    default_log.debug("inside get_all_timeframe_budgets")

    db = session if session else next(get_db())

    timeframe_budget = db.query(TimeframeBudgets).group_by(
        TimeframeBudgets.symbol,
        TimeframeBudgets.time_frame,
        TimeframeBudgets.id,
        TimeframeBudgets.budget,
        TimeframeBudgets.trades,
        TimeframeBudgets.start_range,
        TimeframeBudgets.end_range
    ).order_by(
        TimeframeBudgets.id.asc()
    ).all()

    default_log.debug(f"Total {len(timeframe_budget)} returned")

    return timeframe_budget
