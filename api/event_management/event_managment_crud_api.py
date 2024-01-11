import threading
from datetime import datetime, date
import io
import pandas as pd

import pytz
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.encoders import jsonable_encoder

from api.event_management.dtos.check_events_dto import CheckEventsDTO
from config import default_log, time_stamps, instrument_tokens_map
from data.enums.configuration import Configuration
from data.enums.signal_type import SignalType
from decorators.handle_generic_exception import frontend_api_generic_exception
from external_services.global_datafeed.get_data import download_tick_data_for_symbols, start_backtesting
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


@event_router.post("/add-csv-for-backtesting")
def add_csv_for_backtesting(
    request: Request,
    backtesting_data_date: date,
    file: UploadFile = File(...)
):
    default_log.debug(f"inside /add-csv-for-backtesting")
    columns_to_check = ['Symbol', 'Timeframe', 'Alert Type', 'Alert Time']

    # Read and store the CSV file upload
    try:
        contents = file.file.read()
        data_df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        backtesting_data_df_filename = f"backtest_data_{backtesting_data_date}.csv"

        data_df.to_csv(backtesting_data_df_filename, index=False)

        # Check if proper columns are present
        columns_missing = [col for col in data_df.columns if col not in columns_to_check]
        if len(columns_missing) > 0:
            default_log.debug(f"The following columns are missing from the dataframe having columns ({data_df.columns})"
                              f"={columns_missing}")
            return standard_json_response(
                error=True,
                message=f"The following columns are missing: {columns_missing}",
                data={}
            )

        start_backtesting(backtesting_data_df_filename)
    except Exception as e:
        return standard_json_response(
            error=True, 
            message="Error occurred while reading file",
            data={}
        )
    
    # Get all symbols from the data_df 'Symbol' columns
    symbols = data_df['Symbol'].unique().tolist()
    
    # Download the tick data for the date for the symbols
    threading.Thread(target=download_tick_data_for_symbols, args=(backtesting_data_date, symbols)).start()

    return standard_json_response(error=False, message="ok", data={})

