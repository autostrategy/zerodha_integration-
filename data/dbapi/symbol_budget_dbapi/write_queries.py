from config import default_log
from data.dbapi.symbol_budget_dbapi.dtos.add_symbol_budget_dto import AddSymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.dtos.modify_symbol_budget_dto import ModifySymbolBudgetDTO
from decorators.handle_generic_exception import dbapi_exception_handler
from data.db.init_db import get_db
from data.models.symbol_budget import SymbolBudget


@dbapi_exception_handler
def add_symbol_budget(dto: AddSymbolBudgetDTO, session=None, commit=True):
    default_log.debug(f"inside add_symbol_budget with add_symbol_budget_dto={dto}")

    db = session if session else next(get_db())

    new_symbol_budget = SymbolBudget(
        symbol=dto.symbol,
        time_frame=dto.time_frame,
        budget=dto.budget
    )

    db.add(new_symbol_budget)

    if commit:
        default_log.debug(f"Committing new budget for symbol={dto.symbol} and time_frame={dto.time_frame}")
        db.commit()
    else:
        default_log.debug(f"Flushing new budget for symbol={dto.symbol} and time_frame={dto.time_frame}")
        db.flush()

    return new_symbol_budget.id


@dbapi_exception_handler
def modify_symbol_budget(dto: ModifySymbolBudgetDTO, session=None, commit=True):
    default_log.debug(f"inside modify_symbol_budget with modify_symbol_budget_dto={dto}")

    db = session if session else next(get_db())

    symbol_budget = db.query(SymbolBudget).filter(
        SymbolBudget.symbol == dto.symbol,
        SymbolBudget.time_frame == dto.time_frame).first()

    default_log.debug(f"Symbol budget found for symbol ({dto.symbol}) and "
                      f"time_frame ({dto.time_frame}) = {symbol_budget} "
                      f"Updating the symbol budget from {symbol_budget.budget} to {dto.budget}")

    symbol_budget.budget = dto.budget

    if commit:
        default_log.debug(f"Committing budget update for symbol={dto.symbol} and time_frame={dto.time_frame}")
        db.commit()
    else:
        default_log.debug(f"Flushing budget update for symbol={dto.symbol} and time_frame={dto.time_frame}")
        db.flush()

    return symbol_budget.id
