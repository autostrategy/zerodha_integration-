from config import default_log
from decorators.handle_generic_exception import dbapi_exception_handler
from data.db.init_db import get_db
from data.models.symbol_budget import SymbolBudget


@dbapi_exception_handler
def get_symbol_budget_by_id(symbol_budget_id: int, session=None, close_session=True):
    default_log.debug(f"inside get_symbol_budget_by_id with id={symbol_budget_id}")

    db = session if session else next(get_db())

    symbol_budget = db.query(SymbolBudget).filter(SymbolBudget.id == symbol_budget_id).first()

    default_log.debug(f"Symbol budget found for id ({symbol_budget_id})={symbol_budget}")

    return symbol_budget


@dbapi_exception_handler
def get_symbol_budget(symbol: str, time_frame: str = None, session=None, close_session=True):
    default_log.debug(f"inside get_symbol_budget for symbol={symbol} and time_frame={time_frame}")

    db = session if session else next(get_db())

    symbol_budget = db.query(SymbolBudget).filter(
        SymbolBudget.symbol == symbol,
        SymbolBudget.time_frame == time_frame).first()

    default_log.debug(f"Symbol budget found for symbol ({symbol}) and time_frame ({time_frame})={symbol_budget}")

    return symbol_budget


@dbapi_exception_handler
def get_symbol_budget_by_symbol_and_timeframe(
        symbol: str,
        timeframe: str,
        session=None,
        close_session=True,
):
    default_log.debug(f"inside get_symbol_budget_by_symbol_and_timeframe with symbol={symbol} and "
                      f"timeframe={timeframe}")

    db = session if session else next(get_db())

    if symbol is None:
        symbol_budget = db.query(SymbolBudget).filter(
            SymbolBudget.symbol.is_(None),
            SymbolBudget.time_frame == timeframe
        ).first()
    else:
        symbol_budget = db.query(SymbolBudget).filter(
            SymbolBudget.symbol == symbol,
            SymbolBudget.time_frame == timeframe
        ).first()

    default_log.debug(f"Returning symbol budget={symbol_budget} for symbol={symbol} and timeframe={timeframe}")

    return symbol_budget


@dbapi_exception_handler
def get_all_symbol_budgets(session=None, close_session=True):
    default_log.debug(f"inside get_all_symbol_budget")

    db = session if session else next(get_db())

    symbol_budgets = db.query(SymbolBudget).group_by(
        SymbolBudget.time_frame,
        SymbolBudget.id,
        SymbolBudget.symbol,
        SymbolBudget.budget
    ).order_by(
        SymbolBudget.id.asc()
    ).all()

    default_log.debug(f"Returning {len(symbol_budgets)}")

    return symbol_budgets
