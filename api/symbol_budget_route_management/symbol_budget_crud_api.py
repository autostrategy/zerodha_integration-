from fastapi import APIRouter, Request

from config import default_log
from data.dbapi.symbol_budget_dbapi.dtos.add_symbol_budget_dto import AddSymbolBudgetDTO
from data.dbapi.symbol_budget_dbapi.dtos.modify_symbol_budget_dto import ModifySymbolBudgetDTO
from decorators.handle_generic_exception import frontend_api_generic_exception
from logic.symbol_budget_management.symbol_budget_logic import add_symbol_budget_data, update_symbol_budget_data
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

    response = update_symbol_budget_data(dto)

    if not response:
        default_log.debug(f"An error occurred while updating symbol budget with dto={dto}")
        return standard_json_response(error=True, message="An error occurred while adding symbol budget", data={})

    default_log.debug(f"Added symbol budget with dto={dto}")
    return standard_json_response(error=False, message="Updated symbol budget", data={})
