from datetime import datetime

import pytz
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder

from api.event_management.dtos.check_events_dto import CheckEventsDTO
from config import default_log, time_stamps, instrument_tokens_map
from data.enums.configuration import Configuration
from data.enums.signal_type import SignalType
from decorators.handle_generic_exception import frontend_api_generic_exception
from logic.zerodha_integration_management.get_event_details_logic import get_all_event_details
from logic.zerodha_integration_management.zerodha_integration_logic import log_event_trigger
from standard_responses.standard_json_response import standard_json_response


event_router = APIRouter(prefix='/event', tags=['event'])


@event_router.post("/add-event-check")
@frontend_api_generic_exception
def check_event_triggers(
    request: Request,
    dto: CheckEventsDTO
):
    default_log.debug(f"inside /add-event-check with dto={dto}")

    try:
        log_event_trigger(dto)
        return standard_json_response(error=False, message="ok", data={})
    except Exception as e:
        default_log.debug(f"An error occurred while starting logging: {e}")
        return standard_json_response(error=True, message="Error occurred while starting trade", data={})


@event_router.get("/get-all-events")
@frontend_api_generic_exception
def get_all_events_details(
        request: Request
):
    default_log.debug("inside /get-all-events")

    event_details = get_all_event_details()

    default_log.debug(f"Returning all event details: {event_details}")

    if event_details.error:
        default_log.debug(f"An error occurred while fetching all event details: {event_details.error_message}")
        return standard_json_response(error=True, message="An error occurred while fetching all event details", data={})

    return standard_json_response(error=False, message="Ok", data=jsonable_encoder(event_details.data))


@event_router.get("/start-all-logging")
@frontend_api_generic_exception
def start_all_market_logging(
        request: Request
):
    default_log.debug(f"inside /start-all-logging")

    try:
        for sym, token in instrument_tokens_map.items():
            for timestamp in time_stamps:
                buy_dto = CheckEventsDTO(
                    symbol=sym,
                    time_of_candle_formation=datetime.now().astimezone(pytz.timezone("Asia/Kolkata")),
                    time_frame_in_minutes=timestamp,
                    signal_type=SignalType.BUY,
                    configuration=Configuration.HIGH
                )

                log_event_trigger(buy_dto)
                default_log.debug(f"Started logging for BUY signal with dto = {buy_dto}")

                sell_dto = CheckEventsDTO(
                    symbol=sym,
                    time_of_candle_formation=datetime.now().astimezone(pytz.timezone("Asia/Kolkata")),
                    time_frame_in_minutes=timestamp,
                    signal_type=SignalType.SELL,
                    configuration=Configuration.LOW
                )

                log_event_trigger(sell_dto)
                default_log.debug(f"Started logging for SELL signal with dto = {sell_dto}")

        default_log.debug("Started all logging")
        return standard_json_response(error=False, message="ok", data={})
    except Exception as e:
        default_log.debug(f"An error occurred while starting logging: {e}")
        return standard_json_response(error=True, message="An error occurred while starting logging", data={})
