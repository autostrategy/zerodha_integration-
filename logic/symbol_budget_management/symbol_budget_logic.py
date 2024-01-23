from config import default_log
from data.dbapi.symbol_budget_dbapi.dtos.add_symbol_budget_dto import AddSymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.dtos.modify_symbol_budget_dto import ModifySymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.read_queries import get_all_symbol_budgets, \
    get_symbol_budget_by_symbol_and_timeframe
from data.dbapi.symbol_budget_dbapi.write_queries import delete_symbol_budget_by_id, modify_symbol_budget, add_symbol_budget
from logic.symbol_budget_management.dtos.add_symbol_budget_response_dto import AddSymbolBudgetResponseDTO
from logic.zerodha_integration_management.zerodha_integration_logic import store_all_symbol_budget
from standard_responses.dbapi_exception_response import DBApiExceptionResponse


def add_symbol_budget_data(dto: list[AddSymbolBudgetDTO]):
    default_log.debug(f"inside add_symbol_budget_data with dto={dto}")

    for symbol_budget in dto:
        # Check if budget setting already exists for timeframe, trades and budget_utilization
        existing_symbol_budget = get_symbol_budget_by_symbol_and_timeframe(
            symbol=symbol_budget.symbol,
            timeframe=symbol_budget.time_frame
        )

        if type(existing_symbol_budget) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while fetching symbol_budget for timeframe "
                              f"({symbol_budget.time_frame}) and symbol ({symbol_budget.symbol}). Error: "
                              f"{existing_symbol_budget.error}")
            response = AddSymbolBudgetResponseDTO(
                error=True,
                error_message="An error occurred"
            )
            return response

        if existing_symbol_budget is not None:
            default_log.debug(f"Not setting budget setting with symbol_budget={symbol_budget} "
                              f"as already symbol_budget exists for timeframe={symbol_budget.time_frame} and "
                              f"symbol={symbol_budget.symbol}")
            error_message = f"Symbol Budget of {existing_symbol_budget.budget} already exists for timeframe={symbol_budget.time_frame} for symbol={symbol_budget.symbol}"
            response = AddSymbolBudgetResponseDTO(
                error=True,
                error_message=error_message
            )
            return response

    for symbol_budget in dto:
        symbol_budget_id = add_symbol_budget(symbol_budget)

        if type(symbol_budget_id) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while adding the symbol budget ({symbol_budget.budget}) "
                              f"for symbol={symbol_budget.symbol} and time_frame={symbol_budget.time_frame}")
            response = AddSymbolBudgetResponseDTO(
                error=True,
                error_message="An error occurred"
            )
            return response

        default_log.debug(f"Added new symbol budget ({symbol_budget.budget}) for "
                          f"symbol={symbol_budget.symbol} and time_frame={symbol_budget.time_frame}")

    store_all_symbol_budget(reset=True)
    response = AddSymbolBudgetResponseDTO(
        error=False
    )
    return response


def update_symbol_budget_data(dto: ModifySymbolBudgetDTO):
    default_log.debug(f"update_symbol_budget_data with update_symbol_budget_dto={dto}")

    symbol_budget_id = modify_symbol_budget(id=dto.symbol_budget_id, dto=dto)

    if type(symbol_budget_id) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while modifying the symbol budget ({dto.budget}) for symbol={dto.symbol} "
                          f"and time_frame={dto.time_frame}")
        return False

    default_log.debug(f"Updated symbol budget for symbol={dto.symbol} and time_frame={dto.time_frame} to "
                      f"{dto.budget}")

    store_all_symbol_budget(reset=True)
    return True


def get_all_symbol_budget_logic():
    default_log.debug("inside get_all_budget_settings_logic")

    symbol_budgets = get_all_symbol_budgets()

    if type(symbol_budgets) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while get all budget settings. Error: {symbol_budgets.error}")
        return None

    default_log.debug(f"Returning {len(symbol_budgets)} symbol budgets")
    return symbol_budgets


def delete_symbol_budget_logic(symbol_budget_id: int):
    default_log.debug(f"inside delete_symbol_budget_logic with symbol_budget_id={symbol_budget_id}")

    response = delete_symbol_budget_by_id(symbol_budget_id)

    if type(response) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while deleting symbol budget having id={symbol_budget_id}. Error: "
                          f"{response.error}")
        return False

    default_log.debug(f"Deleted symbol budget having id={symbol_budget_id}")
    store_all_symbol_budget(reset=True)
    return True
