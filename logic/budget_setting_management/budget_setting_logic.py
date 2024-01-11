from api.symbol_budget_route_management.dtos.add_budget_setting_dto import AddBudgetSettingDTO
from api.symbol_budget_route_management.dtos.modify_budget_setting_dto import ModifyBudgetSettingDTO
from config import default_log
from data.db.init_db import get_db
from data.dbapi.timeframe_budgets_dbapi.read_queries import get_all_timeframe_budgets
from data.dbapi.timeframe_budgets_dbapi.write_queries import add_new_budget_setting, update_budget_setting
from logic.budget_setting_management.dtos.timeframe_budget_dto import TimeFrameBudgetDTO
from logic.zerodha_integration_management.zerodha_integration_logic import store_all_timeframe_budget
from standard_responses.dbapi_exception_response import DBApiExceptionResponse


def add_budget_setting(dto: list[AddBudgetSettingDTO]):
    default_log.debug(f"inside add_budget_setting with dto={dto}")

    db = next(get_db())
    for budget_setting in dto:
        budget_setting_id = add_new_budget_setting(budget_setting, session=db, commit=False)

        if type(budget_setting_id) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while adding budget setting details. Error: "
                              f"{budget_setting_id.error}")
            return False

        default_log.debug(f"Added budget_setting details to the database with id={budget_setting_id}")

    default_log.debug("Added all budget setting details to the database. Committing everything")
    db.commit()

    store_all_timeframe_budget(reset=True)

    return True


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
            time_frame=timeframe_budget.time_frame,
            budget_utilization=timeframe_budget.budget,
            trades=timeframe_budget.trades,
            start_range=timeframe_budget.start_range,
            end_range=timeframe_budget.end_range
        )

        timeframe_budgets_list.append(tmf_budget)

    default_log.debug(f"Returning {len(timeframe_budgets_list)} timeframe budgets")
    return timeframe_budgets_list
