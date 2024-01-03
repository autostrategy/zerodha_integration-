from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder

from api.symbol_budget_route_management.dtos.add_budget_setting_dto import AddBudgetSettingDTO
from api.symbol_budget_route_management.dtos.modify_budget_setting_dto import ModifyBudgetSettingDTO
from config import default_log
from data.dbapi.symbol_budget_dbapi.dtos.add_symbol_budget_dto import AddSymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.dtos.modify_symbol_budget_dto import ModifySymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.read_queries import get_symbol_budget_by_id
from data.dbapi.timeframe_budgets_dbapi.read_queries import get_timeframe_budget_by_id
from decorators.handle_generic_exception import frontend_api_generic_exception
from logic.budget_setting_management.budget_setting_logic import add_budget_setting, modify_budget_setting, \
    get_all_timeframe_budget_logic
from logic.symbol_budget_management.symbol_budget_logic import add_symbol_budget_data, update_symbol_budget_data, \
    get_all_symbol_budget_logic
from standard_responses.standard_json_response import standard_json_response


symbol_budget_router = APIRouter(prefix='/budget', tags=['budget'])


@symbol_budget_router.post("/add-budget")
@frontend_api_generic_exception
def add_symbol_budget_route(
        request: Request,
        dto: list[AddSymbolBudgetDTO]
):
    default_log.debug(f"inside /add-budget api route with add_symbol_budget_dto={dto}")

    response = add_symbol_budget_data(dto)

    if not response:
        default_log.debug(f"An error occurred while adding symbol budget with dto={dto}")
        return standard_json_response(error=True, message="An error occurred while adding symbol budget", data={})

    default_log.debug(f"Added symbol budget with dto={dto}")
    return standard_json_response(error=False, message="Added symbol budget", data={})


@symbol_budget_router.put("/modify-budget")
def modify_symbol_budget_route(
        request: Request,
        dto: ModifySymbolBudgetDTO
):
    default_log.debug(f"inside /modify-budget api route with modify_symbol_budget_dto={dto}")

    # Check whether the symbol budget exists
    symbol_budget = get_symbol_budget_by_id(dto.symbol_budget_id)

    if symbol_budget is None:
        default_log.debug(f"Symbol budget not found for id={dto.symbol_budget_id}")
        return standard_json_response(error=True, message="Symbol Budget details not found", data={})

    response = update_symbol_budget_data(dto)

    if not response:
        default_log.debug(f"An error occurred while updating symbol budget with dto={dto}")
        return standard_json_response(error=True, message="An error occurred while adding symbol budget", data={})

    default_log.debug(f"Added symbol budget with dto={dto}")
    return standard_json_response(error=False, message="Updated symbol budget", data={})


@symbol_budget_router.get("/get-all-symbol-budget")
def get_all_budget_setting_route(
        request: Request
):
    default_log.debug(f"inside GET /get-all-symbol-budget")

    response = get_all_symbol_budget_logic()

    if response is None:
        default_log.debug("An error occurred while getting all symbol budget")
        return standard_json_response(error=True, message="An error occurred while getting all symbol budget", data={})

    default_log.debug(f"Fetched all budget_settings = {response}")
    return standard_json_response(error=False, message="ok", data=jsonable_encoder(response))


@symbol_budget_router.post("/add-budget-setting")
def add_budget_setting_route(
        request: Request,
        dto: list[AddBudgetSettingDTO]
):
    default_log.debug(f"inside /add-budget-setting route with dto={dto}")

    response = add_budget_setting(dto)

    if not response:
        default_log.debug(f"An error occurred while adding budget setting with dto={dto}")
        return standard_json_response(error=True, message="An error occurred while adding budget setting", data={})

    default_log.debug(f"Added symbol budget with dto={dto}")
    return standard_json_response(error=False, message="Added budget setting", data={})


@symbol_budget_router.put("/modify-budget-setting")
def add_budget_setting_route(
        request: Request,
        dto: ModifyBudgetSettingDTO
):
    default_log.debug(f"inside /modify-budget-setting route with dto={dto}")

    timeframe_budget = get_timeframe_budget_by_id(dto.timeframe_budget_id)

    if timeframe_budget is None:
        default_log.debug(f"Timeframe Budget not found for id={dto.timeframe_budget_id}")
        return standard_json_response(error=True, message="Timeframe Budget not found", data={})

    response = modify_budget_setting(dto)

    if not response:
        default_log.debug(f"An error occurred while modifying budget setting with dto={dto}")
        return standard_json_response(error=True, message="An error occurred while modifying budget setting", data={})

    default_log.debug(f"Added symbol budget with dto={dto}")
    return standard_json_response(error=False, message="Modified budget setting", data={})


@symbol_budget_router.get("/get-all-budget-setting")
def get_all_budget_setting_route(
        request: Request
):
    default_log.debug(f"inside GET /get-all-symbol-budget")

    response = get_all_timeframe_budget_logic()

    if response is None:
        default_log.debug("An error occurred while getting all symbol budget")
        return standard_json_response(error=True, message="An error occurred while getting all symbol budget", data={})

    default_log.debug(f"Fetched all budget_settings = {response}")
    return standard_json_response(error=False, message="ok", data=jsonable_encoder(response))
