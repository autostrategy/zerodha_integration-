from api.symbol_budget_route_management.dtos.add_budget_setting_dto import AddBudgetSettingDTO
from api.symbol_budget_route_management.dtos.modify_budget_setting_dto import ModifyBudgetSettingDTO
from config import default_log
from data.db.init_db import get_db
from data.dbapi.timeframe_budgets_dbapi.read_queries import get_all_timeframe_budgets, \
    get_budget_setting_by_timeframe_trades_and_budget_utilization
from data.dbapi.timeframe_budgets_dbapi.write_queries import add_new_budget_setting, update_budget_setting, \
    delete_timeframe_budget_by_id
from logic.budget_setting_management.dtos.add_budget_setting_response_dto import AddBudgetSettingResponseDTO
from logic.budget_setting_management.dtos.timeframe_budget_dto import TimeFrameBudgetDTO
from logic.zerodha_integration_management.zerodha_integration_logic import store_all_timeframe_budget
from standard_responses.dbapi_exception_response import DBApiExceptionResponse


def add_budget_setting(dto: list[AddBudgetSettingDTO]):
    default_log.debug(f"inside add_budget_setting with dto={dto}")

    db = next(get_db())

    for budget_setting in dto:
        # Check if budget setting already exists for timeframe, trades and budget_utilization
        existing_budget_setting = get_budget_setting_by_timeframe_trades_and_budget_utilization(
            symbol=budget_setting.symbol,
            timeframe=budget_setting.time_frame,
            trades=budget_setting.trades,
            budget_utilization=budget_setting.budget_utilization,
            session=db,
            close_session=False
        )

        if type(existing_budget_setting) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while fetching budget_setting for timeframe "
                              f"({budget_setting.time_frame}), trades ({budget_setting.trades}) and "
                              f"budget_utilization ({budget_setting.budget_utilization}) and "
                              f"symbol={budget_setting.symbol}. Error: {existing_budget_setting.error}")
            response = AddBudgetSettingResponseDTO(
                error=True,
                error_message="An error occurred"
            )
            return response

        if existing_budget_setting is not None:
            default_log.debug(f"Not setting budget setting with budget_setting={budget_setting} "
                              f"as already budget_setting exists for timeframe={budget_setting.time_frame} and "
                              f"trades={budget_setting.trades} and budget_utilization="
                              f"{budget_setting.budget_utilization}")

            budget_setting_symbol = budget_setting.symbol
            if budget_setting.symbol is None:
                budget_setting_symbol = 'ALL STOCKS'

            error_message = f"Budget Setting already exists for timeframe={existing_budget_setting.time_frame} and having trades set as {existing_budget_setting.trades.name} with budget utilization as {existing_budget_setting.budget.name} for symbol {budget_setting_symbol}"
            response = AddBudgetSettingResponseDTO(
                error=True,
                error_message=error_message
            )
            db.close()
            return response

    for budget_setting in dto:
        default_log.debug(f"Setting new budget setting with budget_setting={budget_setting}")
        budget_setting_id = add_new_budget_setting(budget_setting, session=db, commit=False)

        if type(budget_setting_id) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while adding budget setting details. Error: "
                              f"{budget_setting_id.error}")

            response = AddBudgetSettingResponseDTO(
                error=True,
                error_message="An error occurred"
            )
            return response

        default_log.debug(f"Added budget_setting details to the database with id={budget_setting_id}")

    default_log.debug("Added all budget setting details to the database. Committing everything")
    db.commit()
    db.close()

    store_all_timeframe_budget(reset=True)
    response = AddBudgetSettingResponseDTO(
        error=False
    )
    return response


def modify_budget_setting(dto: ModifyBudgetSettingDTO):
    default_log.debug(f"inside modify_budget_setting with dto={dto}")

    budget_setting_id = update_budget_setting(dto=dto)  # timeframe budget

    if type(budget_setting_id) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while update budget setting details. Error: {budget_setting_id.error}")
        return False

    if not budget_setting_id:
        default_log.debug(f"Budget Setting Details not found having the following parameters of dto={dto}")
        return False

    store_all_timeframe_budget(reset=True)
    default_log.debug(f"Updated budget_setting details to the database with id={budget_setting_id}")
    return True


def get_all_timeframe_budget_logic():
    default_log.debug("inside get_all_timeframe_budget_logic")

    response = get_all_timeframe_budgets()

    if type(response) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while getting all timeframe budgets. Error: {response.error}")
        return None

    timeframe_budgets_list = []
    for timeframe_budget in response:
        tmf_budget = TimeFrameBudgetDTO(
            timeframe_budget_id=timeframe_budget.id,
            symbol=timeframe_budget.symbol,
            time_frame=timeframe_budget.time_frame,
            budget_utilization=timeframe_budget.budget,
            trades=timeframe_budget.trades,
            start_range=timeframe_budget.start_range,
            end_range=timeframe_budget.end_range
        )

        timeframe_budgets_list.append(tmf_budget)

    default_log.debug(f"Returning {len(timeframe_budgets_list)} timeframe budgets")
    return timeframe_budgets_list


def delete_timeframe_budget_logic(budget_setting_id: int):
    default_log.debug(f"inside delete_timeframe_budget_logic with budget_setting_id={budget_setting_id}")

    response = delete_timeframe_budget_by_id(budget_setting_id)

    if type(response) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while deleting timeframe budget having id={budget_setting_id}. Error: "
                          f"{response.error}")
        return False

    default_log.debug(f"Deleted timeframe budget having id={budget_setting_id}")
    store_all_timeframe_budget(reset=True)
    return True
