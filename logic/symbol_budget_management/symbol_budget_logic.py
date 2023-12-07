from config import default_log
from data.dbapi.symbol_budget_dbapi.dtos.add_symbol_budget_dto import AddSymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.dtos.modify_symbol_budget_dto import ModifySymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.write_queries import modify_symbol_budget, add_symbol_budget
from standard_responses.dbapi_exception_response import DBApiExceptionResponse


def add_symbol_budget_data(dto: list[AddSymbolBudgetDTO]):
    default_log.debug(f"inside add_symbol_budget_data with dto={dto}")

    for symbol_budget in dto:
        symbol_budget_id = add_symbol_budget(symbol_budget)

        if type(symbol_budget_id) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while adding the symbol budget ({symbol_budget.budget}) "
                              f"for symbol={symbol_budget.symbol} and time_frame={symbol_budget.time_frame}")
            return False

        default_log.debug(f"Added new symbol budget ({symbol_budget.budget}) for "
                          f"symbol={symbol_budget.symbol} and time_frame={symbol_budget.time_frame}")

    return True


def update_symbol_budget_data(dto: ModifySymbolBudgetDTO):
    default_log.debug(f"update_symbol_budget_data with update_symbol_budget_dto={dto}")

    symbol_budget_id = modify_symbol_budget(dto)

    if type(symbol_budget_id) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while modifying the symbol budget ({dto.budget}) for symbol={dto.symbol} "
                          f"and time_frame={dto.time_frame}")
        return False

    default_log.debug(f"Updated symbol budget for symbol={dto.symbol} and time_frame={dto.time_frame} to "
                      f"{dto.budget}")

    return True
