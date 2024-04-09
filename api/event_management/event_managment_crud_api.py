import threading
from datetime import datetime, date
import io
import pandas as pd

import pytz
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.encoders import jsonable_encoder

from api.event_management.dtos.check_events_dto import CheckEventsDTO
from config import default_log, time_stamps, instrument_tokens_map, stop_trade_time
from decorators.handle_generic_exception import frontend_api_generic_exception
from external_services.global_datafeed.get_data import download_tick_data_for_symbols, start_backtesting, \
    get_use_simulation_status, get_global_data_feed_connection_status, get_backtesting_status
from logic.live_trades_logic.get_live_trades_logic import get_live_trades_details
from logic.zerodha_integration_management.get_event_details_logic import get_all_event_details
from logic.zerodha_integration_management.zerodha_integration_logic import log_event_trigger
from standard_responses.standard_json_response import standard_json_response


event_router = APIRouter(prefix='/event', tags=['event'])


@event_router.get('/global-data-feed-connection-status')
@frontend_api_generic_exception
def get_global_data_feed_connection_status_api_route(request: Request):
    default_log.debug(f"inside /global-data-feed-connection-status")

    global_data_feed_connection_status = get_global_data_feed_connection_status()

    default_log.debug(f"Current Global Data Feed connection status => {global_data_feed_connection_status}")

    return standard_json_response(
        error=False,
        message="ok",
        data={
            'connection_status': global_data_feed_connection_status
        }
    )


@event_router.post("/add-event-check")
@frontend_api_generic_exception
def check_event_triggers(
    request: Request,
    dto: CheckEventsDTO
):
    default_log.debug(f"inside /add-event-check with dto={dto}")

    try:
        use_simulation_status = get_use_simulation_status()
        # if (not use_simulation_status) and (not datetime.now() > stop_trade_time):
        # if not use_simulation_status:
            # default_log.debug(f"As use_simulation_status is = {use_simulation_status} and current datetime "
            #                   f"({datetime.now()}) < stop_trade_time ({stop_trade_time}) so starting live tracking")
        ist_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
        default_log.debug(f"Starting logging of events of dto={dto} and alert_time={ist_datetime}")
        log_event_trigger(dto, ist_datetime)
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

    if datetime.now() > stop_trade_time:
        default_log.debug(f"Not starting event checking as current_datetime ({datetime.now()}) > stop_trade_time "
                          f"({stop_trade_time})")
        return standard_json_response(
            error=True,
            message="Not starting event checking as current time is stop trade time",
            data={}
        )

    try:
        for sym, token in instrument_tokens_map.items():
            for timestamp in time_stamps:
                buy_dto = CheckEventsDTO(
                    symbol=sym,
                    time_frame_in_minutes=timestamp,
                    signal_type="1",  # BUY
                )

                ist_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                default_log.debug(f"Starting logging of events of dto={buy_dto} and alert_time={ist_datetime}")
                log_event_trigger(buy_dto, ist_datetime)
                default_log.debug(f"Started logging for BUY signal with dto = {buy_dto}")

                sell_dto = CheckEventsDTO(
                    symbol=sym,
                    time_frame_in_minutes=timestamp,
                    signal_type="2",  # SELL
                )

                ist_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                default_log.debug(f"Starting logging of events of dto={sell_dto} and alert_time={ist_datetime}")
                log_event_trigger(sell_dto, ist_datetime)
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
        columns_missing = [col for col in columns_to_check if col not in data_df.columns]
        if len(columns_missing) > 0:
            default_log.debug(f"The following columns {columns_missing} are missing from the dataframe having columns "
                              f"({data_df.columns})")
            return standard_json_response(
                error=True,
                message=f"The following columns are missing: {columns_missing}",
                data={}
            )

        start_backtesting(backtesting_data_df_filename)
    except Exception as e:
        default_log.debug(f"An error occurred while reading file. Error: {e}")
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


@event_router.get("/backtesting-status")
@frontend_api_generic_exception
def get_backtesting_status_route(
        request: Request
):
    default_log.debug(f"inside /backtesting-status")

    backtesting_status = get_backtesting_status()

    default_log.debug(f"backtesting_status retrieved={backtesting_status}")

    return standard_json_response(error=False, message="ok", data={'backtesting_status': backtesting_status})


@event_router.get("/live-trades")
@frontend_api_generic_exception
def get_live_trades_route(request: Request):
    default_log.debug(f"inside /live-trades")

    live_trades = get_live_trades_details()

    if live_trades is None:
        default_log.debug(f"An error occurred while getting live trades details")
        return standard_json_response(
            error=True,
            message="An error occurred while getting live trades details",
            data={}
        )

    default_log.debug(f"{len(live_trades)} Live Trades Details returned: {live_trades}")
    return standard_json_response(
        error=False,
        message="ok",
        data=jsonable_encoder(live_trades)
    )
