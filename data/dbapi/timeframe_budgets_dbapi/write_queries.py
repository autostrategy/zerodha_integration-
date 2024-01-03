from config import default_log
from data.db.init_db import get_db
from decorators.handle_generic_exception import dbapi_exception_handler
from data.models.timeframe_budgets import TimeframeBudgets
from api.symbol_budget_route_management.dtos.add_budget_setting_dto import AddBudgetSettingDTO
from api.symbol_budget_route_management.dtos.modify_budget_setting_dto import ModifyBudgetSettingDTO


@dbapi_exception_handler
def add_new_budget_setting(dto: AddBudgetSettingDTO, session=None, commit=True):
    default_log.debug(f"inside add_new_budget_setting with dto={dto}")

    db = session if session else next(get_db())

    timeframe_budget = TimeframeBudgets(
        time_frame=dto.time_frame,
        trades=dto.trades,
        budget=dto.budget_utilization,
        start_range=dto.start_range,
        end_range=dto.end_range
    )

    db.add(timeframe_budget)

    if commit:
        default_log.debug(f"Committing new time frame budget")
        db.commit()
    else:
        default_log.debug(f"Flushing new time frame budget")
        db.flush()

    return timeframe_budget.id


@dbapi_exception_handler
def update_budget_setting(
        dto: ModifyBudgetSettingDTO,
        session=None,
        commit=True
):
    default_log.debug(f"inside update_budget_setting with timeframe_budget_id={dto.timeframe_budget_id} and dto={dto}")

    db = session if session else next(get_db())

    timeframe_budget = db.query(TimeframeBudgets).filter(TimeframeBudgets.id == dto.timeframe_budget_id).first()

    if timeframe_budget is None:
        default_log.debug(f"Timeframe budget not found having time_frame={dto.time_frame}, "
                          f"budget_utilization={dto.budget_utilization} and trades={dto.trades}")
        return None

    default_log.debug(f"Timeframe budget found for timeframe_budget_id ({dto.timeframe_budget_id}): {timeframe_budget}")

    if dto.trades is not None:
        default_log.debug(f"Updating trades from {timeframe_budget.trades} to {dto.trades}")
        timeframe_budget.trades = dto.trades

    if dto.budget_utilization is not None:
        default_log.debug(f"Updating budget_utilization from {timeframe_budget.budget} to "
                          f"{dto.budget_utilization}")
        timeframe_budget.budget = dto.budget_utilization

    if dto.start_range is not None:
        default_log.debug(f"Updating start range from {timeframe_budget.start_range} to {dto.start_range}")
        timeframe_budget.start_range = dto.start_range

    if dto.end_range is not None:
        default_log.debug(f"Updating end range from {timeframe_budget.end_range} to {dto.end_range}")
        timeframe_budget.end_range = dto.end_range

    db.add(timeframe_budget)

    if commit:
        default_log.debug(f"Committing timeframe_budget update for time_frame={dto.time_frame}")
        db.commit()
    else:
        default_log.debug(f"Flushing timeframe_budget update for time_frame={dto.time_frame}")
        db.flush()

    return timeframe_budget.id
