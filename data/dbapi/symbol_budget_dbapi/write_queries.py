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
def modify_symbol_budget(
        id: int,
        dto: ModifySymbolBudgetDTO,
        session=None,
        commit=True
):
    default_log.debug(f"inside modify_symbol_budget with modify_symbol_budget_dto={dto}")

    db = session if session else next(get_db())

    symbol_budget = db.query(SymbolBudget).filter(SymbolBudget.id == id).first()

    default_log.debug(f"Symbol budget found for symbol budget id ({id}): {symbol_budget}")

    symbol_budget.symbol = dto.symbol
    symbol_budget.time_frame = dto.time_frame

    symbol_budget.budget = dto.budget
    db.add(symbol_budget)

    if commit:
        default_log.debug(f"Committing budget update for symbol={dto.symbol} and time_frame={dto.time_frame}")
        db.commit()
    else:
        default_log.debug(f"Flushing budget update for symbol={dto.symbol} and time_frame={dto.time_frame}")
        db.flush()

    return symbol_budget.id


@dbapi_exception_handler
def delete_symbol_budget_by_id(symbol_budget_id: int, session=None, commit=True):
    default_log.debug(f"inside delete_symbol_budget_by_id with symbol_budget_id={symbol_budget_id}")

    db = session if session else next(get_db())

    existing_symbol_budget = db.query(SymbolBudget).filter(
        SymbolBudget.id == symbol_budget_id
    ).first()

    default_log.debug(f"deleting symbol budget={existing_symbol_budget} having id={symbol_budget_id}")

    db.delete(existing_symbol_budget)

    if commit:
        default_log.debug(f"Committing deletion of existing symbol budget having id={symbol_budget_id}")
        db.commit()
    else:
        default_log.debug(f"Flushing deletion of existing symbol budget having id={symbol_budget_id}")
        db.flush()
    
    return True
