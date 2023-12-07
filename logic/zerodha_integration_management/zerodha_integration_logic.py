import random
import threading

import pytz

from config import default_log, config_threshold_percent, sandbox_mode, no_of_candles_to_consider, \
    instrument_tokens_map, \
    max_retries, trade1_loss_percent, trade2_loss_percent, max_trades, trade3_loss_percent, indices_list, \
    provide_ticker_data, symbol_tokens_map, use_truedata
from typing import Optional

import time as tm
from datetime import datetime, timedelta
import pandas as pd

from api.event_management.dtos.check_events_dto import CheckEventsDTO
from data.dbapi.symbol_budget_dbapi.read_queries import get_all_symbol_budgets
from data.dbapi.thread_details_dbapi.dtos.event_thread_details_dto import EventThreadDetailsDTO
from data.dbapi.thread_details_dbapi.read_queries import get_all_incomplete_thread_details
from data.dbapi.thread_details_dbapi.write_queries import add_thread_event_details, update_thread_event_details
from data.enums.configuration import Configuration
from data.enums.signal_type import SignalType
from external_services.zerodha.zerodha_orders import place_zerodha_order_with_stop_loss, \
    place_zerodha_order_with_take_profit, update_zerodha_order_with_stop_loss, update_zerodha_order_with_take_profit, \
    get_kite_account_api, place_zerodha_order, get_historical_data, cancel_order, get_indices_symbol_for_trade, \
    get_status_of_zerodha_order, get_zerodha_order_details, round_value
from external_services.zerodha.zerodha_ticks_service import get_candlestick_data_using_ticker
from logic.zerodha_integration_management.dtos.event_details_dto import EventDetailsDTO
from logic.zerodha_integration_management.dtos.restart_event_dto import RestartEventDTO
from logic.zerodha_integration_management.dtos.tp_details_dto import TPDetailsDTO
from standard_responses.dbapi_exception_response import DBApiExceptionResponse

kite = get_kite_account_api()
symbol_event_details = dict()

budget_dict = dict()


def manage_symbol_sl_events(key):
    global symbol_event_details
    default_log.debug(f"inside manage_symbol_sl_events with key={key} and "
                      f"symbol_event_details: {symbol_event_details}")

    while True:
        # Check the status of event_detail_dto for the key
        event_data_dto = symbol_event_details.get(key)

        if (event_data_dto.tp_order_status == "COMPLETED") or (event_data_dto.sl_order_status == "COMPLETED"):
            # Remove the event_data_dto for the key
            default_log.debug(f"TP/SL order is completed so removing event data dto of "
                              f"symbol={event_data_dto.symbol} having time_frame={event_data_dto.time_frame} "
                              f"event_data_dto={event_data_dto}")
            symbol_event_details[key] = None
            break

        tm.sleep(2)  # sleep for 2 seconds


def check_sl_values(event_data_dto: EventDetailsDTO, event1_candle_signal_type: SignalType):
    global symbol_event_details
    default_log.debug(f"inside check_sl_values with event_data_dto={event_data_dto} and "
                      f"symbol_event_details={symbol_event_details} ")

    # Check if event details are present for the symbol and direction
    symbol = event_data_dto.symbol
    key = (symbol, event1_candle_signal_type)

    symbol_event_detail = symbol_event_details.get(key, None)

    if symbol_event_detail is None:
        # Newly trade has been placed
        symbol_event_details[key] = event_data_dto
        # Check the symbol event_data_dto tp and sl order status
        # if tp and sl order status is completed the make symbol_event_details[key] = None
        symbol_sl_management_thread = threading.Thread(target=manage_symbol_sl_events, args=(key,))
        symbol_sl_management_thread.start()
        return event_data_dto
    else:
        # Check if existing SL timestamp is greater than current SL timestamp
        existing_sl_timestamp = int(symbol_event_detail.time_frame)
        current_sl_timestamp = int(event_data_dto.time_frame)

        if current_sl_timestamp > existing_sl_timestamp:
            default_log.debug(f"Not updating current stop loss value as existing stop loss timestamp "
                              f"({existing_sl_timestamp}) < current stop loss timestamp ({current_sl_timestamp})")
            symbol_event_details[key] = event_data_dto
            return event_data_dto
        # Existing trade details found
        existing_trade_sl_value = symbol_event_detail.sl_value

        # According to event1_candle_signal_type decide which SL value to send
        current_sl_value = event_data_dto.sl_value
        if event1_candle_signal_type == SignalType.BUY:
            if existing_trade_sl_value > current_sl_value:
                default_log.debug(f"For symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} the SL value ({current_sl_value}) < "
                                  f"the SL ({existing_trade_sl_value}) of symbol={symbol_event_detail.symbol} having "
                                  f"timeframe={symbol_event_detail.time_frame}")

                event_data_dto.sl_value = existing_trade_sl_value

                symbol_event_details[key] = event_data_dto

            else:
                default_log.debug(f"For symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} the SL value ({current_sl_value}) not less "
                                  f"than the SL ({existing_trade_sl_value}) of symbol={symbol_event_detail.symbol} "
                                  f"having timeframe={symbol_event_detail.time_frame}")

        else:
            if existing_trade_sl_value < current_sl_value:
                default_log.debug(f"For symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} the SL value ({current_sl_value}) > "
                                  f"the SL ({existing_trade_sl_value}) of symbol={symbol_event_detail.symbol} having "
                                  f"timeframe={symbol_event_detail.time_frame}")

                event_data_dto.sl_value = existing_trade_sl_value

                symbol_event_details[key] = event_data_dto

            else:
                default_log.debug(f"For symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} the SL value ({current_sl_value}) not greater than "
                                  f"the SL ({existing_trade_sl_value}) of symbol={symbol_event_detail.symbol} having "
                                  f"timeframe={symbol_event_detail.time_frame}")

        return event_data_dto


def get_interval_from_timeframe(time_frame: str):
    default_log.debug(f"inside get_interval_from_timeframe with time_frame={time_frame}")

    interval = time_frame + 'minute'
    if interval == '1minute':
        interval = 'minute'

    return interval


def get_wait_time(start_time: datetime, time_frame: int):
    default_log.debug(f"inside get_wait_time(start_time={start_time}, time_frame={time_frame})")

    # Calculate the time remaining until the next occurrence
    time_difference = time_frame - (start_time.minute % time_frame)
    if time_difference == time_frame:
        time_difference = 0  # If the current time is already aligned, no need to wait

    # Calculate the wait time in seconds
    wait_time = (time_difference * 60) - start_time.second

    # If the wait time is negative, adjust it to move to the next timeframe
    if wait_time < 0:
        wait_time += time_frame * 60

    return wait_time


def fetch_symbol_budget(symbol: str, time_frame: str):
    global budget_dict
    default_log.debug(f"inside fetch_symbol_budget with symbol={symbol} and "
                      f"time_frame={time_frame}")

    key = (symbol, time_frame)
    budget = budget_dict.get(key, None)

    if budget is None:
        key = (symbol, 'default')
        budget = budget_dict.get(key, None)

    if budget is None:
        key = ('default', symbol)
        budget = budget_dict.get(key, None)

    if budget is None:
        key = ('default', 'default')
        budget = budget_dict.get(key, None)

    default_log.debug(f"Returning budget={budget} for symbol={symbol} and time_frame={time_frame}")

    return budget


def store_all_symbol_budget():
    global budget_dict

    # fetch the budget
    symbol_budgets = get_all_symbol_budgets()

    default_log.debug(f"Storing all symbol budgets ({symbol_budgets}) to symbol_budget dictionary")
    for symbol_budget in symbol_budgets:
        if (symbol_budget.time_frame is None) and (symbol_budget.symbol is None):
            key = ('default', 'default')
            budget_dict[key] = symbol_budget.budget
        elif symbol_budget.time_frame is None:
            key = (symbol_budget.symbol, 'default')  # time_frame would be default
            budget_dict[key] = symbol_budget.budget
        elif symbol_budget.symbol is None:
            key = ('default', symbol_budget.time_frame)  # symbol will be default
            budget_dict[key] = symbol_budget.budget
        else:
            key = (symbol_budget.symbol, symbol_budget.time_frame)
            budget_dict[key] = symbol_budget.budget


def log_event_trigger(dto: CheckEventsDTO):
    """
    Logic:
    1. For each symbol create a thread that will run the function after certain timeframe.
    2. If the time_of_candle_formation is given as 6:02 and the timeframe is given as '5 minutes'
    then the thread should start at 6:05 and not at 6:02
    3. If the time_of_candle_formation is given as 6:03 and the timeframe is given as '10 minutes'
    then the thread should start at 6:10 and not at 6:03
    """

    candle_time = dto.time_of_candle_formation
    candle_time = candle_time.astimezone(pytz.timezone("Asia/Kolkata"))

    # Get the wait time
    wait_time = get_wait_time(candle_time, time_frame=int(dto.time_frame_in_minutes))
    default_log.debug(f"Wait time for symbol={dto.symbol} having time_frame={dto.time_frame_in_minutes} and "
                      f"candle_time={dto.time_of_candle_formation} is {wait_time} "
                      f"seconds")
    symbol = dto.symbol
    inst_token = instrument_tokens_map[dto.symbol]
    time_frame = dto.time_frame_in_minutes
    signal_type = dto.signal_type
    configuration = dto.configuration

    # Create and start a thread for each symbol
    if signal_type == SignalType.BUY:
        thread = threading.Thread(target=start_market_logging_for_buy,
                                  args=(symbol, time_frame, inst_token, wait_time, configuration))
        thread.start()
    else:
        thread = threading.Thread(target=start_market_logging_for_sell,
                                  args=(symbol, time_frame, inst_token, wait_time, configuration))
        thread.start()

    # Let the threads run independently
    return None


def get_zerodha_data(
        instrument_token: int,
        interval: str,
        from_date: datetime = None,
        is_restart: bool = False
):
    for attempt in range(max_retries):
        default_log.debug("inside get_zerodha_data with "
                          f"instrument_token={instrument_token} "
                          f"from_date={from_date} "
                          f"interval={interval} "
                          f"is_restart={is_restart} ")

        market_symbol = ""

        for k, v in instrument_tokens_map.items():
            if v == instrument_token:
                market_symbol = k

        if interval == "minute":
            time_frame = 1
        else:
            time_frame = int(interval.split('minute')[0])

        if is_restart:
            if not use_truedata:
                current_datetime = from_date.astimezone(pytz.timezone("Asia/Kolkata")) + timedelta(minutes=time_frame)
                from_date = from_date.astimezone(pytz.timezone("Asia/Kolkata"))
                if current_datetime > datetime.now().astimezone(pytz.timezone("Asia/Kolkata")):
                    # Calculate the wait time to be added to get the nearest datetime
                    wait_time = get_wait_time(from_date, time_frame)
                    current_datetime = from_date + timedelta(seconds=wait_time)
            else:
                current_datetime = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))
        else:
            current_datetime = datetime.now().astimezone(pytz.timezone("Asia/Kolkata")) + timedelta(
                minutes=(time_frame * 3))
            from_date = from_date - timedelta(minutes=(time_frame * 3))

            # Round up to the nearest o'clock for current_datetime
            # current_datetime = current_datetime.replace(second=0, microsecond=0, minute=0)
            # current_datetime = current_datetime + timedelta(hours=2)
            #
            # # Round down to the previous o'clock for from_date
            # from_date = from_date.replace(second=0, microsecond=0, minute=0)
            # from_date = from_date - timedelta(hours=2)

        if sandbox_mode:

            kite_historical_data = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=current_datetime,
                interval=interval
            )

            default_log.debug(
                f"Historical Data returned: {kite_historical_data} for market_symbol={market_symbol} "
                f"from {from_date} to {current_datetime} and "
                f"interval={interval} ")

        elif provide_ticker_data:
            kite_historical_data = get_candlestick_data_using_ticker(
                interval=str(time_frame),
                symbol=market_symbol
            )

            if len(kite_historical_data) == 0:
                default_log.debug(f"Kite Ticker data not found for symbol={market_symbol} and "
                                  f"interval={interval}")
                seconds_to_sleep = random.choice([1, 2, 3])
                default_log.debug(f"sleeping {seconds_to_sleep} second/s to retry fetching of data")
                tm.sleep(seconds_to_sleep)
                continue

            zerodha_historical_data = pd.DataFrame(kite_historical_data)

            data = pd.DataFrame()

            data['open'] = zerodha_historical_data['open']
            data['high'] = zerodha_historical_data['high']
            data['low'] = zerodha_historical_data['low']
            data['close'] = zerodha_historical_data['close']
            data['time'] = zerodha_historical_data['date']

            return data

        else:

            kite_historical_data = get_historical_data(
                kite_connect=kite,
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=current_datetime,
                interval=interval
            )

            default_log.debug(
                f"Historical Data returned: {kite_historical_data} for market_symbol={market_symbol} "
                f"from {from_date} to {current_datetime} and "
                f"interval={interval} ")

        if len(kite_historical_data) == 0:
            default_log.debug(
                f"No data returned for market_symbol={market_symbol}, from {from_date} to {current_datetime}")
            default_log.debug(f"Attempt {attempt + 1}/{max_retries} failed")
            # tm.sleep(1 + attempt * 0.2)
            seconds_to_sleep = random.choice([1, 2, 3])
            default_log.debug(f"sleeping {seconds_to_sleep} second/s to retry fetching of data")
            tm.sleep(seconds_to_sleep)
            continue

        zerodha_historical_data = pd.DataFrame(kite_historical_data)

        data = pd.DataFrame()

        data['open'] = zerodha_historical_data['open']
        data['high'] = zerodha_historical_data['high']
        data['low'] = zerodha_historical_data['low']
        data['close'] = zerodha_historical_data['close']

        if use_truedata:
            data['time'] = zerodha_historical_data['timestamp']
        else:
            data['time'] = zerodha_historical_data['date']

        return data

    default_log.debug(f"Max retries reached. Unable to get Zerodha historical data.")
    return None


def get_next_data(
        is_restart: bool,
        timeframe: str,
        instrument_token: int,
        interval: str,
        timestamp=None
):
    default_log.debug(f"inside get_next_data with "
                      f"is_restart={is_restart} "
                      f"timeframe={timeframe} "
                      f"instrument_token={instrument_token} "
                      f"interval={interval} "
                      f"timestamp={timestamp} "
                      f"and symbol={symbol_tokens_map[instrument_token]}")
    symbol = symbol_tokens_map[instrument_token]
    if is_restart:
        # wait_time = get_wait_time(timestamp, int(timeframe))
        wait_time = 2
        default_log.debug(f"Waiting for {wait_time} seconds before fetching next candle data for "
                          f"symbol={symbol} and time_frame={timeframe}")
        tm.sleep(wait_time)

        current_time = timestamp + timedelta(minutes=int(timeframe))

        # Fetch new candle data
        data = get_zerodha_data(
            instrument_token=instrument_token,
            from_date=current_time,
            interval=interval,
            is_restart=is_restart
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={current_time} "
                              f"and timeframe={timeframe}")
            return None

        return data
    else:
        # Calculate the wait time required for fetching the next candle
        # wait_time = get_wait_time(datetime.now().astimezone(pytz.timezone("Asia/Kolkata")), int(timeframe))
        wait_time = 2
        default_log.debug(f"Waiting for {wait_time} seconds before fetching next candle data for "
                          f"symbol={symbol} and time_frame={timeframe}")
        tm.sleep(wait_time)

        current_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))

        # Fetch new candle data
        data = get_zerodha_data(
            instrument_token=instrument_token,
            from_date=current_time,
            interval=interval
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={current_time} "
                              f"and timeframe={timeframe}")
            return None

        return data


def calculate_tp(candle_data, event_data_dto: EventDetailsDTO, event1_signal_type: SignalType):
    default_log.debug(f"inside calculate_tp_and_sl with candle_data={candle_data} "
                      f"and event_data_dto={event_data_dto} with "
                      f"signal_type={event1_signal_type}")
    h = event_data_dto.event1_candle_high if event_data_dto.adjusted_high is None else event_data_dto.adjusted_high
    l = event_data_dto.event1_candle_low if event_data_dto.adjusted_low is None else event_data_dto.adjusted_low

    if event1_signal_type == SignalType.BUY:
        current_candle_high = candle_data["high"]
        # Set the H1 data
        event_data_dto.high_1 = current_candle_high if event_data_dto.high_1 is None else event_data_dto.high_1

        # Get the H1 data
        if current_candle_high > event_data_dto.high_1:
            timestamp = candle_data["time"]
            default_log.debug(f"Highest Point (H1) found at={timestamp} "
                              f"H1={current_candle_high}")

            event_data_dto.high_1 = current_candle_high

        # To Calculate the TP data
        sl_minus_h1 = event_data_dto.sl_value - event_data_dto.high_1

        h1_minus_h = event_data_dto.high_1 - h

        greatest = max(h1_minus_h, sl_minus_h1)

        tp_val = (event_data_dto.entry_price - greatest)

        greatest = -greatest

    else:
        # event1_signal_type == SELL
        # Set the L1 data
        current_candle_low = candle_data["low"]
        event_data_dto.low_1 = current_candle_low if event_data_dto.low_1 is None else event_data_dto.low_1

        # Get the L1 data
        if current_candle_low < event_data_dto.low_1:
            timestamp = candle_data["time"]
            default_log.debug(f"Lowest Point (L1) found at={timestamp} "
                              f"H1={current_candle_low}")

            event_data_dto.low_1 = current_candle_low

        # To Calculate the TP data
        l1_minus_sl = event_data_dto.low_1 - event_data_dto.sl_value

        l_minus_l1 = l - event_data_dto.low_1

        greatest = max(l1_minus_sl, l_minus_l1)

        tp_val = (event_data_dto.entry_price + greatest)

    tp_details = TPDetailsDTO(
        timestamp=candle_data["time"],
        tp_value=tp_val,
        low_1=event_data_dto.low_1,
        high_1=event_data_dto.high_1,
        sl_value=event_data_dto.sl_value,
        low=l,
        high=h,
        entry_price=event_data_dto.entry_price,
        greatest_price=greatest
    )

    event_data_dto.tp_values.append(tp_details)

    return event_data_dto


def trade_logic_sell(
        symbol: str, timeframe: str, candle_data: pd.DataFrame,
        data_dictionary: dict[tuple[str, str], Optional[EventDetailsDTO]],
        configuration: Configuration = Configuration.LOW
) -> tuple[EventDetailsDTO, dict[tuple[str, str], Optional[EventDetailsDTO]]]:
    """
    Checking of EVENTS
    EVENT 1: Buy Signal Candle formed
    EVENT 2: When a candle low goes below L - (H - L)
    EVENT 3: When a candle high goes above Signal candle Low
    ============ When EVENT 1 candle is BUY check events according to EVENT 1 BUY candle ===============

    ========== Values for TP and SL according to SELL ========
    SL = ENTRY PRICE + (highest point - Event 1 candle Low)

    H1: Highest Point after EVENT 3 has occurred
    GREATEST_VALUE = MAX{(H1 - H[Signal Candle High]), (SL - H1)}
    TP = ENTRY PRICE - GREATEST_VALUE
    """

    key = (symbol, timeframe)

    event_data_dto = data_dictionary.get(key, False)

    if event_data_dto:
        # Check if candle timestamp is greater than the event1_occur_time
        # Check if candle minute is greater than the current event1_occur_time
        current_candle_low = candle_data["low"]
        current_candle_high = candle_data["high"]
        timestamp = candle_data["time"]

        # Get the lowest and highest point
        if event_data_dto.event3_occur_time is None:
            current_highest_point = event_data_dto.highest_point if event_data_dto.highest_point is not None else current_candle_high
            if current_candle_high >= current_highest_point:
                default_log.debug(f"Highest point found higher than {current_highest_point} i.e. {current_candle_high} "
                                  f"at {timestamp}")
                event_data_dto.highest_point = current_candle_high
            current_lowest_point = event_data_dto.lowest_point if event_data_dto.lowest_point is not None else current_candle_low
            if current_candle_low <= current_lowest_point:
                default_log.debug(f"Lowest point found lower than {current_lowest_point} = {current_candle_low} "
                                  f"at {timestamp}")
                event_data_dto.lowest_point = current_candle_low

        if (timestamp.hour == event_data_dto.event1_occur_time.hour and
                timestamp.minute == event_data_dto.event1_occur_time.minute):
            # Update the high and low accordingly
            default_log.debug(f"Current Timestamp ({timestamp}) is equal to Event 1 occur time "
                              f"({event_data_dto.event1_occur_time}) for symbol={event_data_dto.symbol} and "
                              f"time_frame={event_data_dto.time_frame} so updating the high and low of event1_candle "
                              f"and also calculating new event2_breakpoint")

            event_data_dto.event1_candle_high = current_candle_high
            event_data_dto.event1_candle_low = current_candle_low

            # Update the event2_breakpoint
            event_data_dto.event2_occur_breakpoint = candle_data["low"] - (candle_data["high"] - candle_data["low"])

            data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        # Check for AL condition
        # If event 3 occurs before event 2
        if event_data_dto.event2_occur_time is None:

            if timestamp.hour < event_data_dto.event1_occur_time.hour or \
                    (timestamp.hour == event_data_dto.event1_occur_time.hour and
                     timestamp.minute <= event_data_dto.event1_occur_time.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
                                  f"({event_data_dto.event1_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            event1_candle_high = event_data_dto.event1_candle_high
            event1_candle_low = event_data_dto.event1_candle_low

            if current_candle_high > event1_candle_high:
                default_log.debug(f"Adjusted HIGH condition occurred at timestamp={timestamp} as "
                                  f"current_candle_low ({current_candle_high}) > buy_candle_high ({event1_candle_high})")

                # The condition for a sell signal in the "HIGH" configuration has been met
                # You can add your sell signal logic here

                # For example, update event_data_dto or perform other actions for a sell signal
                event_data_dto.adjusted_high = current_candle_high

                # Update the event2_occur_breakpoint for the sell signal
                event_data_dto.event2_occur_breakpoint = event_data_dto.event1_candle_low - (
                        event_data_dto.adjusted_high - event_data_dto.event1_candle_low)

                event_data_dto.previous_timestamp = timestamp
                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

        # The event 1 has already happened
        # Check for event 2
        if event_data_dto.event2_occur_time is None:
            previous_timestamp = event_data_dto.previous_timestamp

            if timestamp.hour < previous_timestamp.hour or \
                    (timestamp.hour == previous_timestamp.hour and
                     timestamp.minute <= previous_timestamp.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Previous time "
                                  f"({previous_timestamp}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            event2_occurring_breakpoint = event_data_dto.event2_occur_breakpoint
            if current_candle_low < event2_occurring_breakpoint:
                default_log.debug(
                    f"Event 2 occurred as at timestamp={timestamp}"
                    f"Candle Low={current_candle_low} < Buy Candle Event 2 occurring breakpoint={event2_occurring_breakpoint}")

                event_data_dto.event2_occur_time = timestamp

                data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        # Check for event 3
        if (event_data_dto.event3_occur_time is None) and (event_data_dto.event2_occur_time is not None):

            if timestamp.hour < event_data_dto.event2_occur_time.hour or \
                    (timestamp.hour == event_data_dto.event2_occur_time.hour and
                     timestamp.minute <= event_data_dto.event2_occur_time.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 2 occur time "
                                  f"({event_data_dto.event2_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            sell_candle_high = event_data_dto.event1_candle_high if event_data_dto.adjusted_high is None else event_data_dto.adjusted_high
            sell_candle_low = event_data_dto.event1_candle_low if event_data_dto.adjusted_low is None else event_data_dto.adjusted_low
            timestamp = candle_data["time"]

            # candle_high_to_check = sell_candle_high if configuration == Configuration.HIGH else sell_candle_low
            candle_high_to_check = sell_candle_low

            if current_candle_high > candle_high_to_check:
                event_data_dto.entry_price = current_candle_high
                event_data_dto.event3_occur_time = timestamp

                # Calculate SL
                # value_to_add_for_stop_loss_entry_price = (
                #         event_data_dto.highest_point - event_data_dto.event1_candle_low)

                value_to_add_for_stop_loss_entry_price = (
                        event_data_dto.highest_point - event_data_dto.lowest_point)

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low

                # Add height of event1_candle to the SL value as buffer
                sl_value = event_data_dto.entry_price + value_to_add_for_stop_loss_entry_price + event1_candle_height

                event_data_dto.value_to_add_for_stop_loss_entry_price = value_to_add_for_stop_loss_entry_price

                event_data_dto.sl_value = sl_value

                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.BUY)

                data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        if (event_data_dto.event2_occur_time is not None) and (
                event_data_dto.event3_occur_time is not None):

            current_timestamp = candle_data['time']
            previous_tp_timestamp = event_data_dto.tp_values[-1].timestamp

            if current_timestamp.hour < previous_tp_timestamp.hour or \
                    (current_timestamp.hour == previous_tp_timestamp.hour and
                     current_timestamp.minute < previous_tp_timestamp.minute):
                default_log.debug(f"Current Timestamp ({current_timestamp}) is earlier than previous TP timestamp "
                                  f"({previous_tp_timestamp}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            elif (current_timestamp.hour == previous_tp_timestamp.hour and
                  current_timestamp.minute < previous_tp_timestamp.minute):
                default_log.debug(f"Current Timestamp ({current_timestamp}) is EQUAL to previous TP timestamp "
                                  f"({previous_tp_timestamp}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.BUY)
            else:
                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.BUY)

            data_dictionary[key] = event_data_dto

        return event_data_dto, data_dictionary

    else:
        # New DTO has to be prepared
        timestamp = candle_data["time"]
        event2_occur_breakpoint = candle_data["low"] - (candle_data["high"] - candle_data["low"])
        dto = EventDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            event1_occur_time=timestamp,
            event1_candle_high=candle_data["high"],
            event1_candle_low=candle_data["low"],
            highest_point=candle_data["high"],
            lowest_point=candle_data["low"],
            event2_occur_breakpoint=event2_occur_breakpoint,
            previous_timestamp=timestamp
        )

        data_dictionary[key] = dto

        return dto, data_dictionary


def trade_logic_buy(
        symbol: str,
        timeframe: str,
        candle_data: pd.DataFrame,
        data_dictionary: dict[tuple[str, str], Optional[EventDetailsDTO]],
        configuration: Configuration = Configuration.HIGH
) -> tuple[EventDetailsDTO, dict[tuple[str, str], Optional[EventDetailsDTO]]]:
    """
    Checking of EVENTS
    EVENT 1: SELL Signal Candle formed
    EVENT 2: When a candle goes above H + (H - L)
    EVENT 3: When a candle low goes below Signal candle high
    ===== Check conditions when event 1 candle is SELL =====

    ==== Calculate SL and TP values for BUY ====
    SL = ENTRY PRICE - (H - lowest point)

    L1: Lowest point after EVENT 3 has occurred

    GREATEST_VALUE = MAX{(L1 - L[Signal Candle Low]), (SL - L1)}
    TP = ENTRY PRICE + GREATEST_VALUE
    """

    key = (symbol, timeframe)

    event_data_dto = data_dictionary.get(key, False)

    default_log.debug(f"Candle Data={candle_data}")

    if event_data_dto:
        current_candle_low = candle_data["low"]
        current_candle_high = candle_data["high"]
        timestamp = candle_data["time"]

        # Getting the highest and lowest point
        if event_data_dto.event3_occur_time is None:
            # Get the lowest point
            current_lowest_point = event_data_dto.lowest_point if event_data_dto.lowest_point else current_candle_low
            if current_candle_low <= current_lowest_point:
                default_log.debug(f"Lowest point found lower than {current_lowest_point} = {current_candle_low} "
                                  f"at {timestamp}")
                event_data_dto.lowest_point = current_candle_low

            current_highest_point = event_data_dto.highest_point if event_data_dto.highest_point else current_candle_high
            if current_candle_high >= current_highest_point:
                default_log.debug(f"Highest point found higher than {current_highest_point} i.e. {current_candle_high} "
                                  f"at {timestamp}")
                event_data_dto.highest_point = current_candle_high

        if (timestamp.hour == event_data_dto.event1_occur_time.hour and
                timestamp.minute == event_data_dto.event1_occur_time.minute):
            # Update the high and low accordingly
            default_log.debug(f"Current Timestamp ({timestamp}) is EQUAL to Event 1 occur time "
                              f"({event_data_dto.event1_occur_time}) for symbol={event_data_dto.symbol} and "
                              f"time_frame={event_data_dto.time_frame} so updating the high and low of event1_candle")

            event_data_dto.event1_candle_high = current_candle_high
            event_data_dto.event1_candle_low = current_candle_low

            # Update the event2_occur_breakpoint
            event_data_dto.event2_occur_breakpoint = candle_data["high"] + (candle_data["high"] - candle_data["low"])

        # Check for AL condition
        # If event 3 occurs before event 2
        if event_data_dto.event2_occur_time is None:

            if timestamp.hour < event_data_dto.event1_occur_time.hour or \
                    (timestamp.hour == event_data_dto.event1_occur_time.hour and
                     timestamp.minute <= event_data_dto.event1_occur_time.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
                                  f"({event_data_dto.event1_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            buy_candle_high = event_data_dto.event1_candle_high
            buy_candle_low = event_data_dto.event1_candle_low

            if current_candle_low < buy_candle_low:
                default_log.debug(f"Adjusted LOW condition occurred at timestamp={timestamp} as "
                                  f"current_candle_low ({current_candle_low}) < buy_candle_high ({buy_candle_high})")

                event_data_dto.adjusted_low = current_candle_low

                # Update the event2_occur_breakpoint
                event_data_dto.event2_occur_breakpoint = event_data_dto.event1_candle_high + (
                        event_data_dto.event1_candle_high - event_data_dto.adjusted_low)

                event_data_dto.previous_timestamp = timestamp

                data_dictionary[key] = event_data_dto
                return event_data_dto, data_dictionary

        # The event 1 has already happened
        # Check for event 2
        if event_data_dto.event2_occur_time is None:
            previous_timestamp = event_data_dto.previous_timestamp

            if timestamp.hour < previous_timestamp.hour or \
                    (timestamp.hour == previous_timestamp.hour and
                     timestamp.minute <= previous_timestamp.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Previous time "
                                  f"({previous_timestamp}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            event2_occurring_breakpoint = event_data_dto.event2_occur_breakpoint
            if current_candle_high > event2_occurring_breakpoint:
                default_log.debug(f"Event 2 occurred as Current Candle High={current_candle_high} > "
                                  f"event2_occurring_breakpoint={event2_occurring_breakpoint} at timestamp={timestamp}")

                event_data_dto.event2_occur_time = timestamp

                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

        # Check for event 3
        if (event_data_dto.event3_occur_time is None) and (event_data_dto.event2_occur_time is not None):

            if timestamp.hour < event_data_dto.event2_occur_time.hour or \
                    (timestamp.hour == event_data_dto.event2_occur_time.hour and
                     timestamp.minute <= event_data_dto.event2_occur_time.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 2 occur time "
                                  f"({event_data_dto.event2_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            buy_candle_high = event_data_dto.event1_candle_high if event_data_dto.adjusted_high is None else event_data_dto.adjusted_high
            buy_candle_low = event_data_dto.event1_candle_low if event_data_dto.adjusted_low is None else event_data_dto.adjusted_low
            timestamp = candle_data["time"]

            # candle_low_to_check = buy_candle_high if configuration == Configuration.HIGH else buy_candle_low
            candle_low_to_check = buy_candle_high

            if current_candle_low < candle_low_to_check:
                default_log.debug(f"Event 3 occurred as Current Candle Low={current_candle_low} < "
                                  f"candle_low_to_check={candle_low_to_check}")
                event_data_dto.entry_price = current_candle_low

                # value_to_add_for_stop_loss_entry_price = -(
                #         event_data_dto.event1_candle_high - event_data_dto.lowest_point)

                value_to_add_for_stop_loss_entry_price = -(
                        event_data_dto.highest_point - event_data_dto.lowest_point)

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low

                # Subtract event1 candle height from the sl value as buffer
                sl_value = event_data_dto.entry_price + value_to_add_for_stop_loss_entry_price - event1_candle_height

                event_data_dto.value_to_add_for_stop_loss_entry_price = value_to_add_for_stop_loss_entry_price

                event_data_dto.sl_value = sl_value

                event_data_dto.event3_occur_time = timestamp

                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.SELL)

                data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        if (event_data_dto.event2_occur_time is not None) and (event_data_dto.event3_occur_time is not None):
            # Check if current candle timestamp equal or less than previous tp value timestamp

            current_timestamp = candle_data['time']
            previous_tp_timestamp = event_data_dto.tp_values[-1].timestamp

            if current_timestamp.hour < previous_tp_timestamp.hour or \
                    (current_timestamp.hour == previous_tp_timestamp.hour and
                     current_timestamp.minute < previous_tp_timestamp.minute):
                default_log.debug(f"Current Timestamp ({current_timestamp}) is earlier than previous TP timestamp "
                                  f"({previous_tp_timestamp}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                return event_data_dto, data_dictionary

            elif (current_timestamp.hour == previous_tp_timestamp.hour and
                  current_timestamp.minute < previous_tp_timestamp.minute):
                default_log.debug(f"Current Timestamp ({current_timestamp}) is EQUAL to previous TP timestamp "
                                  f"({previous_tp_timestamp}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")
                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.SELL)
            else:
                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.SELL)

            data_dictionary[key] = event_data_dto

        return event_data_dto, data_dictionary

    else:
        # New DTO has to be prepared
        timestamp = candle_data["time"]
        event2_occur_breakpoint = candle_data["high"] + (candle_data["high"] - candle_data["low"])
        dto = EventDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            event1_occur_time=timestamp,
            event1_candle_high=candle_data["high"],
            event1_candle_low=candle_data["low"],
            lowest_point=candle_data["low"],
            highest_point=candle_data["high"],
            event2_occur_breakpoint=event2_occur_breakpoint,
            previous_timestamp=timestamp
        )

        data_dictionary[key] = dto

        return dto, data_dictionary


def update_tp_and_sl_status(event_data_dto: EventDetailsDTO, data_dictionary):
    default_log.debug(f"inside update_tp_and_sl_status with event_data_dto={event_data_dto}")

    symbol = event_data_dto.symbol
    time_frame = event_data_dto.time_frame

    key = (symbol, time_frame)
    while True:
        dto = data_dictionary.get(key)

        tp_order_id = dto.tp_order_id
        sl_order_id = dto.sl_order_id

        default_log.debug(f"Getting status of tp_order_id={tp_order_id} and "
                          f"sl_order_id={sl_order_id}")
        tp_order_details = kite.order_history(tp_order_id)
        sl_order_details = kite.order_history(sl_order_id)

        tp_order_status = tp_order_details[-1].get("status", None)
        sl_order_status = sl_order_details[-1].get("status", None)

        event_data_dto.tp_order_status = tp_order_status
        event_data_dto.sl_order_status = sl_order_status

        default_log.debug(f"Status of tp_order_id={tp_order_id} is {tp_order_status} and "
                          f"sl_order_id={sl_order_id} is {tp_order_status}")

        if (tp_order_status is not None) and (tp_order_status == "COMPLETE"):
            default_log.debug(f"TP Hit of symbol={symbol} at "
                              f"time={datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))}")

            default_log.debug(f"Cancelling SL trade order with id={tp_order_id} as TP is hit")
            cancel_order(kite, sl_order_id)

            dto.tp_order_status = tp_order_status
            dto.tp_candle_time = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))

            data_dictionary[key] = dto
            break

        if (sl_order_status is not None) and (sl_order_status == "COMPLETE"):
            default_log.debug(f"SL Hit of symbol={symbol} at "
                              f"time={datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))}")

            default_log.debug(f"Cancelling TP trade order with id={tp_order_id} as SL is hit")
            cancel_order(kite, tp_order_id)

            dto.sl_order_status = sl_order_status
            dto.sl_candle_time = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))

            data_dictionary[key] = dto
            break

        dto.sl_order_status = sl_order_status
        dto.tp_order_status = tp_order_status
        data_dictionary[key] = dto

        tm.sleep(2)  # sleep for 2 second before fetching order history data


def place_initial_zerodha_trades(
        event_data_dto: EventDetailsDTO,
        data_dictionary,
        signal_type: SignalType,
        candle_data,
        symbol: str,
        indices_symbol: str = None
):
    default_log.debug(f"inside place_zerodha_trades with event_data_dto={event_data_dto} and "
                      f"signal_type={signal_type} for symbol={symbol} and indices_symbol={indices_symbol}")

    entry_price = event_data_dto.entry_price
    entry_sl_value = event_data_dto.sl_value

    default_log.debug(f"Entry Price = {entry_price} and Entry SL value = {entry_sl_value} for "
                      f"symbol={symbol} and indices_symbol={indices_symbol}")

    loss_budget = fetch_symbol_budget(symbol, event_data_dto.time_frame)
    loss_percent = loss_budget * trade1_loss_percent

    trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
    # Round off trade1_quantity to 0 decimal places and convert to int
    trade1_quantity = int(round(trade1_quantity, 0))

    default_log.debug(f"Creating MARKET order for trading_symbol={symbol} "
                      f"transaction_type={signal_type} and quantity={trade1_quantity} "
                      f"at timestamp={candle_data['time']} with event1_occur_time={event_data_dto.event1_occur_time} "
                      f"and event3_occur_time={event_data_dto.event3_occur_time} and "
                      f"indices_symbol={indices_symbol}")

    # Start trade
    if sandbox_mode:
        entry_trade_order_id = place_zerodha_order(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=signal_type,
            quantity=trade1_quantity if indices_symbol is None else 50,
            exchange="NSE" if indices_symbol is None else "NFO",
            average_price=event_data_dto.entry_price
        )
    else:
        entry_trade_order_id = place_zerodha_order(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=signal_type,
            quantity=trade1_quantity if indices_symbol is None else 50,
            exchange="NSE" if indices_symbol is None else "NFO"
        )

    if entry_trade_order_id is None:
        default_log.debug(
            f"An error has occurred while placing MARKET order for symbol={symbol} and "
            f"event_data_dto={event_data_dto}")
        return None

    event_data_dto.entry_trade_order_id = entry_trade_order_id

    default_log.debug(f"[{signal_type.name}] Signal Trade order placed for symbol={symbol} at {candle_data['time']} "
                      f"signal_trade_order_id={entry_trade_order_id} "
                      f"and indices_symbol={indices_symbol}")

    while True:
        zerodha_order_status = get_status_of_zerodha_order(kite, entry_trade_order_id)
        default_log.debug(f"Zerodha order status for MARKET order having id={entry_trade_order_id} is "
                          f"{zerodha_order_status} for symbol={symbol} and "
                          f"indices_symbol={indices_symbol}")

        if zerodha_order_status == "COMPLETE":
            # Now get the fill price when order was completed and then calculate the take profit
            zerodha_market_order_details = get_zerodha_order_details(kite, entry_trade_order_id)

            if zerodha_market_order_details is None:
                default_log.debug(f"An error occurred while fetching Zerodha MARKET order details for "
                                  f"id={entry_trade_order_id} for symbol={symbol} and "
                                  f"indices_symbol={indices_symbol}")
                return None

            fill_price = zerodha_market_order_details['average_price']
            default_log.debug(f"Fill price of zerodha market order having id={entry_trade_order_id} is "
                              f"fill_price={fill_price} for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")

            greatest_price = event_data_dto.tp_values[-1].greatest_price
            old_take_profit = event_data_dto.tp_values[-1].tp_value

            take_profit_updated = fill_price + greatest_price

            default_log.debug(f"Updating old TP value={old_take_profit} to {take_profit_updated} for "
                              f"MARKET order id={entry_trade_order_id} for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")

            # Now update the take profit and entry price
            event_data_dto.tp_values[-1].tp_value = take_profit_updated

            # Now update entry price
            old_entry_price = event_data_dto.entry_price
            new_entry_price = fill_price
            default_log.debug(f"Updating old Entry Price of={old_entry_price} to {new_entry_price} "
                              f"for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")
            event_data_dto.entry_price = new_entry_price

            if indices_symbol is not None:
                old_sl_value = event_data_dto.sl_value
                new_sl_value = event_data_dto.entry_price + event_data_dto.value_to_add_for_stop_loss_entry_price

                default_log.debug(f"Updating old SL Value of={old_sl_value} to {new_sl_value} "
                                  f"for symbol={symbol} and "
                                  f"indices_symbol={indices_symbol}")
                event_data_dto.sl_value = new_sl_value

            break

        if zerodha_order_status == "REJECTED":
            default_log.debug(f"MARKET Order has been REJECTED having id={entry_trade_order_id} "
                              f"for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")
            return None
        tm.sleep(2)  # sleep for 2 seconds

    stop_loss = event_data_dto.sl_value
    take_profit = event_data_dto.tp_values[-1].tp_value
    default_log.debug(
        f"Entering the Market with stop_loss_value={stop_loss} and take_profit_value={take_profit} "
        f"and quantity={trade1_quantity} for symbol={symbol} and indices_symbol={indices_symbol}")

    tp_transaction_type = sl_transaction_type = SignalType.SELL if signal_type == SignalType.BUY else SignalType.BUY

    # round off the price of stop loss
    formatted_value = round_value(
        symbol=symbol if indices_symbol is None else indices_symbol,
        price=stop_loss,
        exchange="NSE" if indices_symbol is None else "NFO"
    )
    stop_loss = formatted_value

    event_data_dto.sl_value = stop_loss

    # round off the price of take profit
    formatted_value = round_value(
        symbol=symbol if indices_symbol is None else indices_symbol,
        price=take_profit,
        exchange="NSE" if indices_symbol is None else "NFO"
    )

    take_profit = formatted_value

    event_data_dto.tp_values[-1].tp_value = take_profit

    # Continue with creating a TP and SL trade
    default_log.debug(f"Placing SL order for entry_trade_order_id={entry_trade_order_id} for "
                      f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                      f"with quantity={trade1_quantity} and stop_loss={stop_loss} ")

    if sandbox_mode:
        # Place a ZERODHA order with stop loss
        sl_order_id = place_zerodha_order_with_stop_loss(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=sl_transaction_type,
            quantity=trade1_quantity if indices_symbol is None else 50,
            stop_loss=stop_loss,
            exchange="NSE" if indices_symbol is None else "NFO"
        )
    else:
        # Place a ZERODHA order with stop loss
        sl_order_id = place_zerodha_order_with_stop_loss(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=sl_transaction_type,
            quantity=trade1_quantity if indices_symbol is None else 50,
            stop_loss=stop_loss,
            exchange="NSE" if indices_symbol is None else "NFO"
        )

    if sl_order_id is None:
        default_log.debug(f"An error occurred while placing SL order for "
                          f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                          f"with quantity={trade1_quantity} and stop_loss={stop_loss} and "
                          f"indices_symbol={indices_symbol} ")
    else:
        default_log.debug(f"Placed SL order with id={sl_order_id} "
                          f"for entry_trade_order_id={entry_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                          f"with quantity={trade1_quantity} and stop_loss={stop_loss} "
                          f"indices_symbol={indices_symbol} ")

        event_data_dto.sl_order_id = sl_order_id

    default_log.debug(f"Placing TP order for signal_order_id={entry_trade_order_id} for "
                      f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                      f"with quantity={trade1_quantity} and take_profit={take_profit} ")

    # Place a ZERODHA order with take profit
    if sandbox_mode:
        tp_order_id = place_zerodha_order_with_take_profit(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=tp_transaction_type,
            quantity=trade1_quantity if indices_symbol is None else 50,
            take_profit=take_profit,
            exchange="NSE" if indices_symbol is None else "NFO"
        )
    else:
        tp_order_id = place_zerodha_order_with_take_profit(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=tp_transaction_type,
            quantity=trade1_quantity if indices_symbol is None else 50,
            take_profit=take_profit,
            exchange="NSE" if indices_symbol is None else "NFO"
        )

    if tp_order_id is None:
        default_log.debug(f"An error occurred while placing TP order for "
                          f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                          f"with quantity={trade1_quantity} and stop_loss={stop_loss} ")
    else:
        default_log.debug(f"Placed TP order with id={sl_order_id} "
                          f"for entry_trade_order_id={entry_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                          f"with quantity={trade1_quantity} and stop_loss={stop_loss} "
                          f"indices_symbol={indices_symbol} ")

        event_data_dto.tp_order_id = tp_order_id

    thread = threading.Thread(target=update_tp_and_sl_status, args=(event_data_dto, data_dictionary))
    thread.start()

    event_data_dto.trade1_quantity = trade1_quantity if indices_symbol is None else 50
    return event_data_dto


def place_extension_zerodha_trades(
        event_data_dto: EventDetailsDTO,
        signal_type: SignalType,
        candle_data,
        extension_quantity: float,
        symbol: str,
        multiplier: int,
        exchange: str = "NSE",
        indices_symbol: str = None
):
    default_log.debug(f"inside place_extension_zerodha_trades with event_data_dto={event_data_dto} and "
                      f"signal_type={signal_type} for symbol={symbol} and exchange={exchange} with "
                      f"multiplier={multiplier}")

    # Round off extension quantity to 0 decimal places and convert to int
    extension_quantity = int(round(extension_quantity, 0))

    default_log.debug(f"[EXTENSION] Creating MARKET order for trading_symbol={symbol} "
                      f"transaction_type={signal_type} and extension_quantity={extension_quantity} "
                      f"at timestamp={candle_data['time']} with event1_occur_time={event_data_dto.event1_occur_time} "
                      f"and event3_occur_time={event_data_dto.event3_occur_time} and "
                      f"indices_symbol={indices_symbol}")

    sl_order_id = event_data_dto.sl_order_id
    tp_order_id = event_data_dto.tp_order_id

    # Start trade
    if sandbox_mode:
        average_price = candle_data['low'] if signal_type == SignalType.SELL else candle_data['high']
        extension_trade_order_id = place_zerodha_order(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=signal_type,
            quantity=extension_quantity if indices_symbol is None else 50,
            exchange="NSE" if indices_symbol is None else "NFO",
            average_price=average_price
        )
    else:
        extension_trade_order_id = place_zerodha_order(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=signal_type,
            quantity=extension_quantity if indices_symbol is None else 50,
            exchange="NSE" if indices_symbol is None else "NFO"
        )

    if extension_trade_order_id is None:
        default_log.debug(
            f"An error has occurred while placing MARKET order for symbol={symbol} and "
            f"event_data_dto={event_data_dto}")
        return None

    if event_data_dto.extension1_trade_order_id is None:
        event_data_dto.extension1_trade_order_id = extension_trade_order_id
    else:
        event_data_dto.extension2_trade_order_id = extension_trade_order_id

    default_log.debug(f"[{signal_type.name}] Signal Trade order placed for symbol={symbol} at {candle_data['time']} "
                      f"extension_quantity={extension_quantity} "
                      f"and indices_symbol={indices_symbol}")

    while True:
        zerodha_order_status = get_status_of_zerodha_order(kite, extension_trade_order_id)
        default_log.debug(f"[EXTENSION] Zerodha order status for MARKET order having id={extension_trade_order_id} is "
                          f"{zerodha_order_status} for symbol={symbol} and "
                          f"indices_symbol={indices_symbol}")

        if zerodha_order_status == "COMPLETE":
            default_log.debug(f"[EXTENSION] Extension trade with id={extension_trade_order_id} status is "
                              f"COMPLETE")
            zerodha_market_order_details = get_zerodha_order_details(kite, extension_trade_order_id)

            if zerodha_market_order_details is None:
                default_log.debug(f"[EXTENSION] An error occurred while fetching Zerodha MARKET order details for "
                                  f"id={extension_trade_order_id} for symbol={symbol} and "
                                  f"indices_symbol={indices_symbol}")
                return None

            fill_price = zerodha_market_order_details['average_price']
            default_log.debug(f"[EXTENSION] Fill price of zerodha market order having id={extension_trade_order_id} is "
                              f"fill_price={fill_price} for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")
            if event_data_dto.extension1_entry_price is None:
                event_data_dto.extension1_entry_price = fill_price
            else:
                event_data_dto.extension2_entry_price = fill_price
            break

        if zerodha_order_status == "REJECTED":
            default_log.debug(f"[EXTENSION] Extension MARKET order with id={extension_trade_order_id} is REJECTED "
                              f"for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")
            return None

        tm.sleep(2)  # sleep for 2 seconds

    previous_extension_quantity = event_data_dto.extension_quantity if event_data_dto.extension_quantity else 0
    tp_quantity = sl_quantity = event_data_dto.trade1_quantity + (extension_quantity * multiplier) + previous_extension_quantity
    default_log.debug(
        f"[EXTENSION] Entering the Market with "
        f"quantity={extension_quantity} for symbol={symbol} "
        f"and tp_quantity={tp_quantity} and sl_quantity={sl_quantity} and "
        f"trade1_quantity={event_data_dto.trade1_quantity}")

    tp_transaction_type = sl_transaction_type = SignalType.SELL if SignalType.BUY else SignalType.BUY

    # Continue with updating TP and SL trade
    default_log.debug(f"[EXTENSION] Updating SL order for extension_trade_order_id={extension_trade_order_id} for "
                      f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                      f"with quantity={sl_quantity} "
                      f"exchange={exchange}")

    # Update a ZERODHA order with stop loss quantity
    if sandbox_mode:
        sl_order_id = update_zerodha_order_with_stop_loss(
            kite=kite,
            zerodha_order_id=sl_order_id,
            trade_quantity=sl_quantity if indices_symbol is None else 50,
            quantity=sl_quantity if indices_symbol is None else 50,
            transaction_type=sl_transaction_type,
            trading_symbol=symbol,
            candle_high=candle_data['high'],
            candle_low=candle_data['low'],
            exchange=exchange
        )
    else:
        sl_order_id = update_zerodha_order_with_stop_loss(
            kite=kite,
            zerodha_order_id=sl_order_id,
            trade_quantity=sl_quantity if indices_symbol is None else 50,
            quantity=sl_quantity if indices_symbol is None else 50,
            trading_symbol=symbol,
            transaction_type=sl_transaction_type,
            exchange=exchange
        )

    if sl_order_id is None:
        default_log.debug(f"[EXTENSION] An error occurred while placing SL order for "
                          f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                          f"with quantity={sl_quantity} and "
                          f"indices_symbol={indices_symbol} ")
    else:
        default_log.debug(f"[EXTENSION] Placed SL order with id={sl_order_id} "
                          f"for extension_trade_order_id={extension_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                          f"with quantity={sl_quantity} "
                          f"indices_symbol={indices_symbol} and exchange={exchange}")

        event_data_dto.sl_order_id = sl_order_id

    default_log.debug(f"[EXTENSION] Placing TP order for extension_trade_order_id={extension_trade_order_id} for "
                      f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                      f"with quantity={tp_quantity} and "
                      f"exchange={exchange}")

    # Update a ZERODHA order with take profit
    if sandbox_mode:
        tp_order_id = update_zerodha_order_with_take_profit(
            kite=kite,
            zerodha_order_id=tp_order_id,
            transaction_type=tp_transaction_type,
            trade_quantity=tp_quantity if indices_symbol is None else 50,
            quantity=tp_quantity if indices_symbol is None else 50,
            trading_symbol=symbol,
            candle_high=candle_data['high'],
            candle_low=candle_data['low'],
            exchange=exchange
        )
    else:
        tp_order_id = update_zerodha_order_with_take_profit(
            kite=kite,
            zerodha_order_id=tp_order_id,
            transaction_type=tp_transaction_type,
            trade_quantity=tp_quantity if indices_symbol is None else 50,
            quantity=tp_quantity if indices_symbol is None else 50,
            trading_symbol=symbol,
            exchange=exchange
        )

    if tp_order_id is None:
        default_log.debug(f"[EXTENSION] An error occurred while updating TP order for "
                          f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                          f"with quantity={tp_quantity} "
                          f"exchange={exchange}")
    else:
        default_log.debug(f"[EXTENSION] Updated TP order with id={sl_order_id} "
                          f"for extension_trade_order_id={extension_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                          f"with quantity={tp_quantity} "
                          f"indices_symbol={indices_symbol} and exchange={exchange}")

        event_data_dto.tp_order_id = tp_order_id

    if event_data_dto.extension1_quantity is None:
        default_log.debug(f"Updating Extension 1 quantity to {tp_quantity}")
        event_data_dto.extension1_quantity = (extension_quantity * multiplier)
    else:
        default_log.debug(f"Updating Extension 2 quantity to {tp_quantity}")
        event_data_dto.extension2_quantity = (extension_quantity * multiplier)

    event_data_dto.extension_quantity = tp_quantity

    return event_data_dto


def update_zerodha_stop_loss_order(event_data_dto: EventDetailsDTO, indices_symbol: str = None,
                                   candle_high: float = None, candle_low: float = None):
    default_log.debug(f"inside update_zerodha_stop_loss_order for symbol={event_data_dto.symbol} "
                      f"and timeframe={event_data_dto.time_frame} and indices_symbol={indices_symbol}"
                      f"and with event_data_dto={event_data_dto} and candle_high={candle_high} and "
                      f"candle_low={candle_low}")

    sl_value = event_data_dto.sl_value
    symbol = event_data_dto.symbol

    # round off the price of stop loss
    formatted_value = round_value(
        symbol=symbol if indices_symbol is None else indices_symbol,
        price=sl_value,
        exchange="NSE" if indices_symbol is None else "NFO"
    )
    stop_loss = formatted_value

    event_data_dto.sl_value = stop_loss

    quantity = event_data_dto.trade1_quantity if event_data_dto.extension_quantity is None else event_data_dto.extension_quantity
    if sandbox_mode:
        default_log.debug(f"Updating Zerodha SL order with id={event_data_dto.sl_order_id} having market order "
                          f"id={event_data_dto.entry_trade_order_id} stop_loss to {stop_loss}")

        sl_order_id = update_zerodha_order_with_stop_loss(
            kite=kite,
            zerodha_order_id=event_data_dto.sl_order_id,
            transaction_type=SignalType.SELL,
            exchange="NSE" if indices_symbol is None else "NFO",
            stop_loss=stop_loss,
            trading_symbol=symbol,
            candle_high=candle_high,
            candle_low=candle_low
        )
    else:
        default_log.debug(f"Updating Zerodha SL order with id={event_data_dto.sl_order_id} having market order "
                          f"id={event_data_dto.entry_trade_order_id} stop_loss to {stop_loss}")

        sl_order_id = update_zerodha_order_with_stop_loss(
            kite=kite,
            zerodha_order_id=event_data_dto.sl_order_id,
            transaction_type=SignalType.SELL,
            trade_quantity=quantity,
            exchange="NSE" if indices_symbol is None else "NFO",
            stop_loss=stop_loss,
            trading_symbol=symbol
        )

    if sl_order_id is None:
        default_log.debug(f"An error occurred while updating SL order for "
                          f"trading_symbol={symbol}, having transaction_type as {SignalType.SELL} "
                          f"having quantity={event_data_dto.trade1_quantity} with stop_loss={stop_loss} ")
    else:
        default_log.debug(
            f"Updated SL order with ID: {sl_order_id} with stop_loss={stop_loss} "
            f"for symbol={symbol} and indices_symbol={indices_symbol}")

        event_data_dto.sl_order_id = sl_order_id

    return event_data_dto


def start_market_logging_for_buy(
        symbol: str,
        timeframe: str,
        instrument_token: int,
        wait_time: int,
        configuration: Configuration,
        restart_dto: RestartEventDTO = None
):
    default_log.debug("inside start_market_logging_for_buy with "
                      f"symbol={symbol}, timeframe={timeframe}, instrument_token={instrument_token} "
                      f"wait_time={wait_time} and configuration={configuration} "
                      f"restart_dto={restart_dto}")

    data_dictionary = {}
    wait_time = 2  # as ticker data is being used now
    # use_current_candle = False

    interval = get_interval_from_timeframe(timeframe)

    key = (symbol, timeframe)
    trades_made = 0

    is_restart = False
    extension_diff = None

    sl_order_id = None
    tp_order_id = None
    signal_trade_order_id = None

    if restart_dto is not None:
        is_restart = True
        default_log.debug(f"Restarting the thread with restart_dto={restart_dto}")

        thread_detail_id = restart_dto.thread_id

        event1_occur_time = restart_dto.event1_occur_time
        event2_occur_time = restart_dto.event2_occur_time
        event3_occur_time = restart_dto.event3_occur_time

        symbol = restart_dto.symbol
        time_frame = restart_dto.time_frame

        event2_breakpoint = restart_dto.event2_breakpoint
        lowest_point = restart_dto.lowest_point
        sl_value = restart_dto.sl_value
        candle_high = restart_dto.candle_high
        candle_low = restart_dto.candle_low

        entry_price = restart_dto.entry_price
        trade1_quantity = restart_dto.trade1_quantity

        extension_quantity = restart_dto.extension_quantity
        extension1_order_id = restart_dto.extension1_order_id,
        extension2_order_id = restart_dto.extension2_order_id

        extension1_quantity = restart_dto.extension1_quantity
        extension2_quantity = restart_dto.extension2_quantity

        if (event1_occur_time is not None) and (event2_occur_time is None):
            # Start the thread from event 1 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT, SL_VALUE
            data = get_zerodha_data(
                from_date=event1_occur_time,
                instrument_token=instrument_token,
                interval=interval,
                is_restart=True
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event1_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

        elif (event1_occur_time is not None) and (event2_occur_time is not None) and (event3_occur_time is None):
            # Event 2 has been completed but not event 3
            # Start the thread from event 2 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT (For BUY),
            # HIGHEST_POINT (For SELL), SL_VALUE, EVENT2_OCCUR_TIME, EVENT2_BREAKPOINT

            event_details_dto = EventDetailsDTO(
                event1_candle_high=candle_high,
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_low=candle_low,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                lowest_point=lowest_point,
                sl_value=sl_value
            )

            data_dictionary[key] = event_details_dto

            # Fetch the data
            data = get_zerodha_data(
                from_date=event2_occur_time,
                instrument_token=instrument_token,
                interval=interval,
                is_restart=True
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event2_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

        else:
            # Event 3 has been completed but tp or sl has not been hit yet Start the thread from event 3 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT, SL_VALUE, EVENT2_BREAKPOINT, EVENT2_OCCUR_TIME,
            # EVENT3_OCCUR_TIME, TP VALUE

            tp_value = restart_dto.tp_value

            # Fetch data
            data = get_zerodha_data(
                from_date=event3_occur_time,
                instrument_token=instrument_token,
                interval=interval,
                is_restart=True
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event3_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

            high_1 = data["high"]

            tp_details = TPDetailsDTO(
                entry_price=entry_price,
                timestamp=data["time"].values[-1],
                tp_value=tp_value,
                high_1=high_1,
                sl_value=sl_value,
                high=restart_dto.candle_high
            )

            event_details_dto = EventDetailsDTO(
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_high=candle_high,
                event1_candle_low=candle_low,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                event3_occur_time=event3_occur_time,
                lowest_point=lowest_point,
                high_1=high_1,
                tp_values=[tp_details],
                sl_value=sl_value,
                entry_trade_order_id=signal_trade_order_id,
                tp_order_id=tp_order_id,
                sl_order_id=sl_order_id,
                entry_price=entry_price,
                trade1_quantity=trade1_quantity if trade1_quantity is not None else None,
                extension_quantity=extension_quantity if extension_quantity is not None else None,
                extension1_order_id=extension1_order_id,
                extension2_order_id=extension2_order_id,
                extension1_quantity=extension1_quantity,
                extension2_quantity=extension2_quantity
            )

            data_dictionary[key] = event_details_dto

            # Start checking the status of the TP and SL order
            thread = threading.Thread(target=update_tp_and_sl_status, args=(event_details_dto, data_dictionary))
            thread.start()
    else:
        # Not restarted flow
        tm.sleep(wait_time)
        current_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))

        # Fetch candle data
        data = get_zerodha_data(
            instrument_token=instrument_token,
            from_date=current_time,
            interval=interval
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={current_time} "
                              f"and timeframe={timeframe}")
            return None

        # Store the current state of event in the database
        new_event_thread_dto = EventThreadDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.BUY,
            configuration_type=configuration,
            is_completed=False
        )

        response = add_thread_event_details(new_event_thread_dto)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

        thread_detail_id = response

    data_not_found = False
    candles_checked = 0
    entry_price = None

    indices_symbol = None
    prev_timestamp = None
    while True:
        timestamp = data.iloc[-1]['time']
        if prev_timestamp is None:
            prev_timestamp = timestamp
        # TODO: comment this
        # if not use_current_candle:
        #     if current_time is None:
        #         current_time = data.iloc[-1]["time"]
        #
        #     next_time = data.iloc[-1]["time"]
        #     if next_time.minute <= current_time.minute:
        #         data = get_next_data(
        #             is_restart=is_restart,
        #             timeframe=timeframe,
        #             instrument_token=instrument_token,
        #             interval=interval,
        #             timestamp=data.iloc[-1]["time"]
        #         )
        #
        #         if data is None:
        #             default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                               f"and timeframe={timeframe}")
        #             break
        #         continue
        #     else:
        #         use_current_candle = True
        #
        #         data = get_next_data(
        #             is_restart=is_restart,
        #             timeframe=timeframe,
        #             instrument_token=instrument_token,
        #             interval=interval,
        #             timestamp=data.iloc[-1]["time"]
        #         )
        #
        #         if data is None:
        #             default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                               f"and timeframe={timeframe}")
        #             break
        #         continue

        dto, data_dictionary = trade_logic_sell(symbol, timeframe, data.iloc[-1], data_dictionary, configuration)

        if timestamp.hour < dto.event1_occur_time.hour or \
                (timestamp.hour == dto.event1_occur_time.hour and
                 timestamp.minute <= dto.event1_occur_time.minute):
            default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
                              f"({dto.event1_occur_time}) for symbol={dto.symbol} and "
                              f"time_frame={dto.time_frame}")

            data = get_next_data(
                is_restart=is_restart,
                timeframe=timeframe,
                instrument_token=instrument_token,
                interval=interval,
                timestamp=data.iloc[-1]["time"]
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                                  f"and timeframe={timeframe}")
                break

            continue

        if dto.event2_occur_time is not None:
            if timestamp.hour < dto.event2_occur_time.hour or \
                    (timestamp.hour == dto.event2_occur_time.hour and
                     timestamp.minute <= dto.event2_occur_time.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier than Event 2 occur time "
                                  f"({dto.event2_occur_time}) for symbol={dto.symbol} and "
                                  f"time_frame={dto.time_frame}")

                data = get_next_data(
                    is_restart=is_restart,
                    timeframe=timeframe,
                    instrument_token=instrument_token,
                    interval=interval,
                    timestamp=data.iloc[-1]["time"]
                )

                if data is None:
                    default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                                      f"and timeframe={timeframe}")
                    break

                continue

        # todo: uncomment
        if candles_checked > no_of_candles_to_consider:
            if (dto.event2_occur_time is None) and (dto.event3_occur_time is None):
                data_not_found = True
                break
            elif (dto.event2_occur_time is not None) \
                    and (dto.event3_occur_time is None):
                data_not_found = True
                break
            else:
                candles_checked = 0
        else:
            if prev_timestamp.hour < timestamp.hour or \
                    (prev_timestamp.hour == timestamp.hour and
                     prev_timestamp.minute <= timestamp.minute):
                default_log.debug(f"Previous Timestamp ({prev_timestamp}) is earlier than Current Timestamp "
                                  f"({timestamp}) for symbol={dto.symbol} and "
                                  f"time_frame={dto.time_frame}")
            else:
                candles_checked += 1
                prev_timestamp = timestamp

        if (dto.event2_occur_time is not None) and (dto.event3_occur_time is not None):

            if extension_diff is None:
                default_log.debug(f"Extension Difference = Entry Price ({dto.entry_price}) - SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if symbol in indices_list:
                default_log.debug(f"Getting indices symbol as trading symbol={symbol} is in "
                                  f"indices_list={indices_list} with entry price={entry_price} ")
                indices_symbol = get_indices_symbol_for_trade(symbol, dto.entry_price, SignalType.BUY)

                if indices_symbol is None:
                    default_log.debug(f"No Options found for indices={symbol} with transaction type "
                                      f"{SignalType.SELL}")
                    return None
                default_log.debug(f"Indices symbol retrieved={indices_symbol}")

            if dto.entry_trade_order_id is None:
                # Check the SL increase condition
                entry_price = dto.entry_price
                current_candle_low = data.iloc[-1]["low"]

                if (entry_price - ((dto.sl_value - entry_price) / 2)) >= current_candle_low:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) - [SL value ({dto.sl_value}) - "
                                      f"Entry Price ({entry_price})] >= Current Candle Low ({current_candle_low})")
                    event_data_dto = check_sl_values(event_data_dto=dto, event1_candle_signal_type=SignalType.BUY)
                    dto = event_data_dto
                else:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) - [SL value ({dto.sl_value}) - "
                                      f"Entry Price ({entry_price})] < Current Candle Low ({current_candle_low})")

                event_data_dto = place_initial_zerodha_trades(
                    event_data_dto=dto,
                    data_dictionary=data_dictionary,
                    signal_type=SignalType.SELL,
                    candle_data=data.iloc[-1],
                    symbol=symbol,
                    indices_symbol=indices_symbol
                )

                if event_data_dto is None:
                    default_log.debug(f"An error occurred while placing MARKET order for symbol={symbol} and "
                                      f"indices_symbol={indices_symbol} and event_data_dto={dto}")

                    return None
                trades_made += 1
                dto = event_data_dto

                # Updating the extension difference
                default_log.debug(f"[UPDATING] Extension Difference = Entry Price ({dto.entry_price}) - "
                                  f"SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if (dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.tp_order_id is not None):
                take_profit = dto.tp_values[-1].tp_value

                # round off the price of take profit
                formatted_value = round_value(
                    symbol=symbol if indices_symbol is None else indices_symbol,
                    price=take_profit,
                    exchange="NSE" if indices_symbol is None else "NFO"
                )
                take_profit = formatted_value

                dto.tp_values[-1].tp_value = take_profit
                if sandbox_mode:
                    default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
                                      f"id={dto.entry_trade_order_id} take_profit to {take_profit}")

                    tp_order_id = update_zerodha_order_with_take_profit(
                        kite=kite,
                        zerodha_order_id=dto.tp_order_id,
                        transaction_type=SignalType.BUY,
                        trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
                        take_profit=take_profit,
                        candle_high=data.iloc[-1]["high"],
                        candle_low=data.iloc[-1]["low"],
                        trading_symbol=symbol,
                        exchange="NSE" if indices_symbol is None else "NFO"
                    )

                    if tp_order_id is None:
                        default_log.debug(f"An error occurred while updating TP order for "
                                          f"trading_symbol={symbol}, having transaction_type as {SignalType.SELL} "
                                          f"and take_profit={take_profit} ")
                    else:
                        default_log.debug(f"[BUY] Updated TP order with ID: {tp_order_id} with "
                                          f"take profit={take_profit} "
                                          f"for symbol={symbol} and indices_symbol={indices_symbol}")
                        dto.tp_order_id = tp_order_id

                else:
                    default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
                                      f"id={dto.entry_trade_order_id} take_profit to {take_profit}")

                    tp_order_id = update_zerodha_order_with_take_profit(
                        kite=kite,
                        zerodha_order_id=dto.tp_order_id,
                        transaction_type=SignalType.BUY,
                        trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
                        take_profit=take_profit,
                        trading_symbol=symbol,
                        exchange="NSE" if indices_symbol is None else "NFO"
                    )

                    if tp_order_id is None:
                        default_log.debug(f"An error occurred while updating TP order for "
                                          f"trading_symbol={symbol}, having transaction_type as {SignalType.SELL} "
                                          f"and take_profit={take_profit} ")
                    else:
                        default_log.debug(f"[BUY] Updated TP order with ID: {tp_order_id} with "
                                          f"take profit={take_profit} "
                                          f"for symbol={symbol} and indices_symbol={indices_symbol}")
                        dto.tp_order_id = tp_order_id

            if (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.sl_order_id is not None):

                # Condition 1
                # Check the SL increase condition
                entry_price = dto.entry_price
                current_candle_low = data.iloc[-1]["low"]

                if (entry_price - ((dto.sl_value - entry_price) / 2)) <= current_candle_low:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) - [SL value ({dto.sl_value}) - "
                                      f"Entry Price ({entry_price})] <= Current Candle Low ({current_candle_low})")
                    event_data_dto = check_sl_values(event_data_dto=dto, event1_candle_signal_type=SignalType.BUY)
                    dto = event_data_dto

                    if sandbox_mode:
                        candle_high = data.iloc[-1]["high"]
                        candle_low = data.iloc[-1]["low"]
                        event_data_dto = update_zerodha_stop_loss_order(
                            dto,
                            indices_symbol=indices_symbol,
                            candle_high=candle_high,
                            candle_low=candle_low
                        )
                        dto = event_data_dto
                    else:
                        event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                        dto = event_data_dto

                else:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) - [SL value ({dto.sl_value}) - "
                                      f"Entry Price ({entry_price})] > Current Candle Low ({current_candle_low})")

                # Condition 2
                # Check condition of updating Stop Loss according to average price
                average_entry_price = dto.entry_price
                if dto.extension1_trade_order_id is not None:
                    average_entry_price = (dto.entry_price + dto.extension1_entry_price) / 2

                if dto.extension2_trade_order_id is not None:
                    average_entry_price = (dto.entry_price + dto.extension1_entry_price + dto.extension2_entry_price) / 3

                current_candle_close = data.iloc[-1]["close"]

                if (average_entry_price - current_candle_close) > (dto.sl_value - average_entry_price):
                    default_log.debug(f"Satisfied condition for updating SL according to average entry price as "
                                      f"[Average Entry Price ({average_entry_price}) - Current Candle close "
                                      f"({current_candle_close})] >"
                                      f"[SL value ({dto.sl_value}) - Average Entry Price ({average_entry_price})]")
                    dto.sl_value = average_entry_price
                    if sandbox_mode:
                        candle_high = data.iloc[-1]["high"]
                        candle_low = data.iloc[-1]["low"]
                        event_data_dto = update_zerodha_stop_loss_order(
                            dto,
                            indices_symbol=indices_symbol,
                            candle_high=candle_high,
                            candle_low=candle_low
                        )

                        dto = event_data_dto
                    else:
                        event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                        dto = event_data_dto

            # Extra Trade placing logic
            # Place extra trade if candle high goes ABOVE by a threshold value

            # Ententions would be checked only if TP and SL order not completed
            if (extension_diff is not None) and (trades_made < max_trades) and \
                    ((dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])
                     and (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])):

                default_log.debug(f"Extension Diff={extension_diff}, trades_made={trades_made}, "
                                  f"TP Order status={dto.tp_order_status} with id={dto.tp_order_id} and "
                                  f"SL Order status={dto.sl_order_status} with id={dto.sl_order_id} ")

                # threshold = extension_diff * (1 + (config_threshold_percent * trades_made))

                extension_time_stamp = data.iloc[-1]["time"]
                candle_high_price = data.iloc[-1]["high"]

                default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                  f"at timestamp = {extension_time_stamp}")

                entry_price_difference = candle_high_price - dto.entry_price
                threshold = extension_diff * (config_threshold_percent * trades_made)

                # If second trade is already done
                if trades_made == 2:
                    loss_budget = fetch_symbol_budget(symbol, dto.time_frame)
                    loss_percent = loss_budget * trade3_loss_percent
                    # loss_percent = trade3_loss_percent
                    default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")
                # If only first trade is made
                else:
                    loss_budget = fetch_symbol_budget(symbol, dto.time_frame)
                    loss_percent = loss_budget * trade2_loss_percent
                    # loss_percent = trade2_loss_percent
                    default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                extension_quantity = loss_percent / entry_price_difference
                default_log.debug(
                    f"Extension quantity = Loss percent ({loss_percent}) / "
                    f"Entry Price Difference ({entry_price_difference})")

                if entry_price_difference >= threshold:
                    default_log.debug(f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
                                      f"and SL value = {dto.sl_value} and candle_high_price={candle_high_price} "
                                      f"at timestamp = {extension_time_stamp} "
                                      f"Entry Price Difference {entry_price_difference} >= "
                                      f"Threshold {threshold} with extension_quantity={extension_quantity}")

                    event_data_dto = place_extension_zerodha_trades(
                        event_data_dto=dto,
                        signal_type=SignalType.SELL,
                        candle_data=data.iloc[-1],
                        extension_quantity=extension_quantity if indices_symbol is None else 50,
                        symbol=symbol,
                        indices_symbol=indices_symbol,
                        multiplier=trades_made,
                        exchange="NSE" if indices_symbol is None else "NFO"
                    )

                    if event_data_dto is None:
                        default_log.debug(
                            f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} and "
                            f"indices_symbol={indices_symbol} and event_data_dto={dto} and "
                            f"extension_quantity={extension_quantity} and trade1_quantity={dto.trade1_quantity}")

                        return None

                    dto = event_data_dto
                    trades_made += 1

        default_log.debug(f"[{data['time']}] Event Details: {data_dictionary.get(key, None)}")

        # Store the current state of event in the database
        update_event_thread_dto = EventThreadDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.BUY,
            configuration_type=configuration,
            signal_candle_high=dto.event1_candle_high,
            adjusted_high=dto.adjusted_high,
            signal_candle_low=dto.event1_candle_low,
            adjusted_low=dto.adjusted_low,
            event1_occur_time=dto.event1_occur_time,
            event2_breakpoint=dto.event2_occur_breakpoint,
            event2_occur_time=dto.event2_occur_time,
            event3_occur_time=dto.event3_occur_time,
            lowest_point=dto.lowest_point,
            highest_point=dto.highest_point,
            tp_value=dto.tp_values[-1].tp_value if len(dto.tp_values) > 0 else None,
            tp_datetime=dto.tp_candle_time,
            sl_value=dto.sl_value,
            sl_order_id=dto.sl_order_id,
            tp_order_id=dto.tp_order_id,
            signal_trade_order_id=dto.entry_trade_order_id,
            sl_datetime=dto.sl_candle_time,
            is_completed=False,
            entry_price=dto.entry_price,
            trade1_quantity=int(dto.trade1_quantity) if dto.trade1_quantity is not None else None,
            extension_quantity=dto.extension_quantity,
            extension1_order_id=dto.extension1_trade_order_id,
            extension2_order_id=dto.extension2_trade_order_id,
            extension1_quantity=dto.extension1_quantity,
            extension2_quantity=dto.extension2_quantity
        )

        response = update_thread_event_details(update_event_thread_dto, thread_detail_id)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

        if (dto.sl_order_status == "COMPLETE") or (dto.tp_order_status == "COMPLETE"):
            default_log.debug(f"TP/SL HIT")
            break

        data = get_next_data(
            is_restart=is_restart,
            timeframe=timeframe,
            instrument_token=instrument_token,
            interval=interval,
            timestamp=data.iloc[-1]["time"]
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                              f"and timeframe={timeframe}")
            return None

    if dto is not None:
        # Store the current state of event in the database
        update_event_thread_dto = EventThreadDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.BUY,
            configuration_type=configuration,
            signal_candle_high=dto.event1_candle_high,
            adjusted_high=dto.adjusted_high,
            signal_candle_low=dto.event1_candle_low,
            adjusted_low=dto.adjusted_low,
            event1_occur_time=dto.event1_occur_time,
            event2_occur_time=dto.event2_occur_time,
            event3_occur_time=dto.event3_occur_time,
            lowest_point=dto.lowest_point,
            highest_point=dto.highest_point,
            tp_value=dto.tp_values[-1].tp_value if len(dto.tp_values) > 0 else None,
            tp_datetime=dto.tp_candle_time,
            tp_order_id=dto.tp_order_id,
            sl_order_id=dto.sl_order_id,
            signal_trade_order_id=dto.entry_trade_order_id,
            sl_value=dto.sl_value,
            sl_datetime=dto.sl_candle_time,
            is_completed=True,
            entry_price=dto.entry_price,
            trade1_quantity=int(dto.trade1_quantity) if dto.trade1_quantity is not None else None,
            extension_quantity=dto.extension_quantity,
            extension1_order_id=dto.extension1_trade_order_id,
            extension2_order_id=dto.extension2_trade_order_id,
            extension1_quantity=dto.extension1_quantity,
            extension2_quantity=dto.extension2_quantity
        )

        response = update_thread_event_details(update_event_thread_dto, thread_detail_id)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

    if data_not_found:
        default_log.debug("Data not found for TP/SL hit")
        default_log.debug("Thread completed")
        return False
    else:
        default_log.debug("TP/SL Hit")
        default_log.debug(f"Thread Completed")
        return True


def start_market_logging_for_sell(
        symbol: str,
        timeframe: str,
        instrument_token: int,
        wait_time: int,
        configuration: Configuration,
        restart_dto: RestartEventDTO = None
):
    default_log.debug("inside start_market_logging_for_sell with "
                      f"symbol={symbol}, timeframe={timeframe}, instrument_token={instrument_token} "
                      f"wait_time={wait_time} and configuration={configuration} "
                      f"restart_dto={restart_dto}")

    data_dictionary = {}
    wait_time = 2  # as ticker data is now being used
    use_current_candle = False

    interval = get_interval_from_timeframe(timeframe)

    key = (symbol, timeframe)
    trades_made = 0
    extension_diff = None
    entry_price = None

    sl_order_id = None
    tp_order_id = None
    signal_trade_order_id = None

    is_restart = False

    if restart_dto is not None:
        is_restart = True
        default_log.debug(f"Restarting the thread with restart_dto={restart_dto}")

        thread_detail_id = restart_dto.thread_id

        event1_occur_time = restart_dto.event1_occur_time
        event2_occur_time = restart_dto.event2_occur_time
        event3_occur_time = restart_dto.event3_occur_time

        symbol = restart_dto.symbol
        time_frame = restart_dto.time_frame

        event2_breakpoint = restart_dto.event2_breakpoint
        highest_point = restart_dto.highest_point
        sl_value = restart_dto.sl_value
        candle_high = restart_dto.candle_high
        candle_low = restart_dto.candle_low

        entry_price = restart_dto.entry_price
        trade1_quantity = restart_dto.trade1_quantity

        extension_quantity = restart_dto.extension_quantity
        extension1_order_id = restart_dto.extension1_order_id
        extension2_order_id = restart_dto.extension2_order_id

        extension1_quantity = restart_dto.extension1_quantity
        extension2_quantity = restart_dto.extension2_quantity

        if (event1_occur_time is not None) and (event2_occur_time is None):
            # Start the thread from event 1 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT, SL_VALUE
            data = get_zerodha_data(
                from_date=event1_occur_time,
                instrument_token=instrument_token,
                interval=interval,
                is_restart=True
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event1_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

        elif (event1_occur_time is not None) and (event2_occur_time is not None) and (event3_occur_time is None):
            # Event 2 has been completed but not event 3
            # Start the thread from event 2 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT (For BUY),
            # HIGHEST_POINT (For SELL), SL_VALUE, EVENT2_OCCUR_TIME, EVENT2_BREAKPOINT

            event_details_dto = EventDetailsDTO(
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_high=candle_high,
                event1_candle_low=candle_low,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                highest_point=highest_point,
                sl_value=sl_value
            )

            data_dictionary[key] = event_details_dto

            # Fetch the data
            data = get_zerodha_data(
                from_date=event2_occur_time,
                instrument_token=instrument_token,
                interval=interval,
                is_restart=True
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event2_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

        else:
            # Event 3 has been completed but tp or sl has not been hit yet Start the thread from event 3 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT, SL_VALUE, EVENT2_BREAKPOINT, EVENT2_OCCUR_TIME,
            # EVENT3_OCCUR_TIME, TP VALUE

            tp_value = restart_dto.tp_value

            # Fetch data
            data = get_zerodha_data(
                from_date=event3_occur_time,
                instrument_token=instrument_token,
                interval=interval,
                is_restart=True
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event3_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

            low_1 = data.iloc[-1]["low"]

            tp_details = TPDetailsDTO(
                entry_price=entry_price,
                timestamp=data["time"].values[-1],
                tp_value=tp_value,
                low_1=low_1,
                sl_value=sl_value,
                low=restart_dto.candle_low
            )

            event_details_dto = EventDetailsDTO(
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_high=candle_high,
                event1_candle_low=candle_low,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                event3_occur_time=event3_occur_time,
                highest_point=highest_point,
                sl_value=sl_value,
                tp_values=[tp_details],
                low_1=low_1,
                entry_trade_order_id=signal_trade_order_id,
                tp_order_id=tp_order_id,
                sl_order_id=sl_order_id,
                entry_price=entry_price,
                trade1_quantity=trade1_quantity,
                extension_quantity=extension_quantity,
                extension1_order_id=extension1_order_id,
                extension2_order_id=extension2_order_id,
                extension1_quantity=extension1_quantity,
                extension2_quantity=extension2_quantity
            )

            data_dictionary[key] = event_details_dto

            # Start checking the status of the TP and SL order
            thread = threading.Thread(target=update_tp_and_sl_status, args=(event_details_dto, data_dictionary))
            thread.start()
    else:
        # Non restart flow
        tm.sleep(wait_time)
        current_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))

        # Fetch candle data
        data = get_zerodha_data(
            instrument_token=instrument_token,
            from_date=current_time,
            interval=interval
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={current_time} "
                              f"and timeframe={timeframe}")
            return None

        # Store the current state of event in the database
        new_event_thread_dto = EventThreadDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.SELL,
            configuration_type=configuration,
            is_completed=False
        )

        response = add_thread_event_details(new_event_thread_dto)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

        thread_detail_id = response

    data_not_found = False
    candles_checked = 0

    indices_symbol = None
    prev_timestamp = None
    while True:
        timestamp = data.iloc[-1]['time']
        if prev_timestamp is None:
            prev_timestamp = timestamp
        # TODO: comment this
        # if not use_current_candle:
        #     if temp_current_time is None:
        #         temp_current_time = data.iloc[-1]["time"]
        #
        #     next_time = data.iloc[-1]["time"]
        #     if next_time.minute <= temp_current_time.minute:
        #         data = get_next_data(
        #             is_restart=is_restart,
        #             timeframe=timeframe,
        #             instrument_token=instrument_token,
        #             interval=interval,
        #             timestamp=data.iloc[-1]["time"]
        #         )
        #
        #         if data is None:
        #             default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                               f"and timeframe={timeframe}")
        #             break
        #         continue
        #     else:
        #         use_current_candle = True
        #
        #         data = get_next_data(
        #             is_restart=is_restart,
        #             timeframe=timeframe,
        #             instrument_token=instrument_token,
        #             interval=interval,
        #             timestamp=data.iloc[-1]["time"]
        #         )
        #
        #         if data is None:
        #             default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                               f"and timeframe={timeframe}")
        #             break
        #         continue

        dto, data_dictionary = trade_logic_buy(symbol, timeframe, data.iloc[-1], data_dictionary, configuration)

        if timestamp.hour < dto.event1_occur_time.hour or \
                (timestamp.hour == dto.event1_occur_time.hour and
                 timestamp.minute <= dto.event1_occur_time.minute):
            default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
                              f"({dto.event1_occur_time}) for symbol={dto.symbol} and "
                              f"time_frame={dto.time_frame}")

            data = get_next_data(
                is_restart=is_restart,
                timeframe=timeframe,
                instrument_token=instrument_token,
                interval=interval,
                timestamp=data.iloc[-1]["time"]
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                                  f"and timeframe={timeframe}")
                break

            continue

        if dto.event2_occur_time is not None:
            if timestamp.hour < dto.event2_occur_time.hour or \
                    (timestamp.hour == dto.event2_occur_time.hour and
                     timestamp.minute <= dto.event2_occur_time.minute):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier than Event 2 occur time "
                                  f"({dto.event2_occur_time}) for symbol={dto.symbol} and "
                                  f"time_frame={dto.time_frame}")

                data = get_next_data(
                    is_restart=is_restart,
                    timeframe=timeframe,
                    instrument_token=instrument_token,
                    interval=interval,
                    timestamp=data.iloc[-1]["time"]
                )

                if data is None:
                    default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                                      f"and timeframe={timeframe}")
                    break

                continue
        # todo: uncomment
        if candles_checked > no_of_candles_to_consider:
            if (dto.event2_occur_time is None) and (dto.event3_occur_time is None):
                data_not_found = True
                break
            elif (dto.event2_occur_time is not None) \
                    and (dto.event3_occur_time is None):
                data_not_found = True
                break
            else:
                candles_checked = 0
        else:
            if prev_timestamp.hour < timestamp.hour or \
                    (prev_timestamp.hour == timestamp.hour and
                     prev_timestamp.minute <= timestamp.minute):
                default_log.debug(f"Previous Timestamp ({prev_timestamp}) is earlier than Current Timestamp "
                                  f"({timestamp}) for symbol={dto.symbol} and "
                                  f"time_frame={dto.time_frame}")
            else:
                candles_checked += 1
                prev_timestamp = timestamp

        if (dto.event2_occur_time is not None) and (dto.event3_occur_time is not None):

            if extension_diff is None:
                default_log.debug(f"Extension Difference = Entry Price ({dto.entry_price}) - SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if symbol in indices_list:
                default_log.debug(f"Getting indices symbol as trading symbol={symbol} is in "
                                  f"indices_list={indices_list} with entry price={entry_price} "
                                  f"and transaction type as {SignalType.BUY}")
                indices_symbol = get_indices_symbol_for_trade(symbol, dto.entry_price, SignalType.BUY)

                default_log.debug(f"Indices symbol retrieved={indices_symbol}")

            if dto.entry_trade_order_id is None:
                entry_price = dto.entry_price
                current_candle_high = data.iloc[-1]["high"]

                if (entry_price + ((entry_price - dto.sl_value) / 2)) <= current_candle_high:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) + [Entry Price ({entry_price}) - "
                                      f"SL value ({dto.sl_value})] <= Current Candle High ({current_candle_high})")
                    event_data_dto = check_sl_values(event_data_dto=dto, event1_candle_signal_type=SignalType.SELL)
                    dto = event_data_dto
                else:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) + [Entry Price ({entry_price}) - "
                                      f"SL value ({dto.sl_value})] > Current Candle High ({current_candle_high})")

                event_data_dto = place_initial_zerodha_trades(
                    event_data_dto=dto,
                    data_dictionary=data_dictionary,  # used for tracking tp and sl order status
                    signal_type=SignalType.BUY,
                    candle_data=data.iloc[-1],
                    symbol=symbol,
                    indices_symbol=indices_symbol
                )

                if event_data_dto is None:
                    default_log.debug(f"An error occurred while placing MARKET order for symbol={symbol} and "
                                      f"indices_symbol={indices_symbol} and event_data_dto={dto}")

                    return None

                dto = event_data_dto
                trades_made += 1

                default_log.debug(f"[UPDATING] Extension Difference = Entry Price ({dto.entry_price}) "
                                  f"- SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if (dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.tp_order_id is not None):
                take_profit = dto.tp_values[-1].tp_value

                # round off the price of take profit
                formatted_value = round_value(
                    symbol=symbol if indices_symbol is None else indices_symbol,
                    price=take_profit,
                    exchange="NSE" if indices_symbol is None else "NFO"
                )
                take_profit = formatted_value

                dto.tp_values[-1].tp_value = take_profit

                if sandbox_mode:
                    default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
                                      f"id={dto.entry_trade_order_id} take_profit to {take_profit}")
                    tp_order_id = update_zerodha_order_with_take_profit(
                        kite=kite,
                        zerodha_order_id=dto.tp_order_id,
                        transaction_type=SignalType.SELL,
                        trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
                        exchange="NSE" if indices_symbol is None else "NFO",
                        take_profit=take_profit,
                        trading_symbol=symbol,
                        candle_high=data.iloc[-1]['high'],
                        candle_low=data.iloc[-1]['low']
                    )
                else:
                    default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
                                      f"id={dto.entry_trade_order_id} take_profit to {take_profit}")
                    tp_order_id = update_zerodha_order_with_take_profit(
                        kite=kite,
                        zerodha_order_id=dto.tp_order_id,
                        transaction_type=SignalType.SELL,
                        trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
                        exchange="NSE" if indices_symbol is None else "NFO",
                        take_profit=take_profit,
                        trading_symbol=symbol
                    )

                if tp_order_id is None:
                    default_log.debug(f"An error occurred while updating TP order for "
                                      f"trading_symbol={symbol}, having transaction_type as {SignalType.SELL} "
                                      f"having quantity={dto.trade1_quantity} with take_profit={take_profit} ")
                else:
                    default_log.debug(
                        f"Updated TP order with ID: {tp_order_id} with take profit={take_profit} "
                        f"for symbol={symbol} and indices_symbol={indices_symbol}")

                    dto.tp_order_id = tp_order_id

            if (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.sl_order_id is not None):
                # Condition 1
                # Check the SL increase condition
                entry_price = dto.entry_price
                current_candle_high = data.iloc[-1]["high"]

                if (entry_price + ((entry_price - dto.sl_value) / 2)) <= current_candle_high:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) + [Entry Price ({entry_price}) - "
                                      f"SL value ({dto.sl_value})] <= Current Candle High ({current_candle_high})")
                    event_data_dto = check_sl_values(event_data_dto=dto, event1_candle_signal_type=SignalType.SELL)
                    dto = event_data_dto

                    if sandbox_mode:
                        candle_high = data.iloc[-1]["high"]
                        candle_low = data.iloc[-1]["low"]
                        event_data_dto = update_zerodha_stop_loss_order(
                            dto,
                            indices_symbol=indices_symbol,
                            candle_high=candle_high,
                            candle_low=candle_low
                        )
                        dto = event_data_dto
                    else:
                        event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                        dto = event_data_dto

                else:
                    default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                                      f"Entry Price ({entry_price}) + [Entry Price ({entry_price}) - "
                                      f"SL value ({dto.sl_value})] > Current Candle High ({current_candle_high})")

                # Condition 2
                # Check condition of updating Stop Loss according to average price
                average_entry_price = dto.entry_price
                if dto.extension1_trade_order_id is not None:
                    average_entry_price = (dto.entry_price + dto.extension1_entry_price) / 2

                if dto.extension2_trade_order_id is not None:
                    average_entry_price = (dto.entry_price + dto.extension1_entry_price + dto.extension2_entry_price) / 3

                current_candle_close = data.iloc[-1]["close"]

                if (current_candle_close - average_entry_price) > (average_entry_price - dto.sl_value):
                    default_log.debug(f"Satisfied condition for updating SL according to average entry price as "
                                      f"[Current Candle close ({current_candle_close}) - "
                                      f"Average Entry Price ({average_entry_price})] > "
                                      f"[Average Entry Price ({average_entry_price}) - SL value ({dto.sl_value})]")
                    dto.sl_value = average_entry_price
                    if sandbox_mode:
                        candle_high = data.iloc[-1]["high"]
                        candle_low = data.iloc[-1]["low"]
                        event_data_dto = update_zerodha_stop_loss_order(
                            dto,
                            indices_symbol=indices_symbol,
                            candle_high=candle_high,
                            candle_low=candle_low
                        )

                        dto = event_data_dto
                    else:
                        event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                        dto = event_data_dto

            # Extra Trade placing logic
            # Place extra trade if candle high goes ABOVE by a threshold value
            if (extension_diff is not None) and (trades_made < max_trades) and \
                    ((dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])
                     and (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])):

                default_log.debug(f"Extension Diff={extension_diff}, trades_made={trades_made}, "
                                  f"TP Order status={dto.tp_order_status} with id={dto.tp_order_id} and "
                                  f"SL Order status={dto.sl_order_status} with id={dto.sl_order_id} ")

                extension_time_stamp = data.iloc[-1]["time"]
                current_candle_low = data.iloc[-1]["low"]
                # threshold = extension_diff * (1 + (config_threshold_percent * trades_made))

                entry_price_difference = abs(current_candle_low - dto.entry_price)

                threshold = extension_diff * (config_threshold_percent * trades_made)

                default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                  f"at timestamp = {extension_time_stamp} and "
                                  f"current_candle_low={current_candle_low} ")

                # if entry_price_difference >= threshold:  # old condition
                if entry_price_difference >= threshold:
                    default_log.debug(f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
                                      f"and SL value = {dto.sl_value} "
                                      f"and current_candle_low = {current_candle_low} "
                                      f"at timestamp = {extension_time_stamp} "
                                      f"Entry Price Difference {entry_price_difference} >= "
                                      f"Threshold {threshold}")

                    # If second trade is already done
                    if trades_made == 2:
                        loss_budget = fetch_symbol_budget(symbol, dto.time_frame)
                        loss_percent = loss_budget * trade3_loss_percent
                        # loss_percent = trade3_loss_percent
                        default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")
                    # If only first trade is made
                    else:
                        loss_budget = fetch_symbol_budget(symbol, dto.time_frame)
                        loss_percent = loss_budget * trade2_loss_percent
                        # loss_percent = trade2_loss_percent
                        default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                    extension_quantity = loss_percent / entry_price_difference

                    event_data_dto = place_extension_zerodha_trades(
                        event_data_dto=dto,
                        signal_type=SignalType.BUY,
                        candle_data=data.iloc[-1],
                        extension_quantity=extension_quantity if indices_symbol is None else 50,
                        symbol=symbol,
                        indices_symbol=indices_symbol,
                        multiplier=trades_made,
                        exchange="NSE" if indices_symbol is None else "NFO"
                    )

                    if event_data_dto is None:
                        if event_data_dto is None:
                            default_log.debug(
                                f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} and "
                                f"indices_symbol={indices_symbol} and event_data_dto={dto} and "
                                f"extension_quantity={extension_quantity} and trade1_quantity={dto.trade1_quantity}")
                        return None
                    trades_made += 1
                    dto = event_data_dto
                else:
                    default_log.debug(
                        f"Extension Trade condition not met as values: extension_diff={extension_diff} "
                        f"trades_made={trades_made}, config_threshold_percent={config_threshold_percent} "
                        f"entry_price={entry_price} and sl_value={dto.sl_value} "
                        f"and entry_price_difference: {entry_price_difference} < threshold: {threshold} "
                        f"and symbol={symbol} and indices_symbol={indices_symbol} ")

        default_log.debug(f"[{data.iloc[-1]['time']}] Event Details: {data_dictionary.get(key, None)}")

        # Store the current state of event in the database
        update_event_thread_dto = EventThreadDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.SELL,
            configuration_type=configuration,
            signal_candle_high=dto.event1_candle_high,
            adjusted_high=dto.adjusted_high,
            signal_candle_low=dto.event1_candle_low,
            adjusted_low=dto.adjusted_low,
            event1_occur_time=dto.event1_occur_time,
            event2_breakpoint=dto.event2_occur_breakpoint,
            event2_occur_time=dto.event2_occur_time,
            event3_occur_time=dto.event3_occur_time,
            lowest_point=dto.lowest_point,
            highest_point=dto.highest_point,
            tp_value=dto.tp_values[-1].tp_value if len(dto.tp_values) > 0 else None,
            tp_datetime=dto.tp_candle_time,
            sl_value=dto.sl_value,
            sl_datetime=dto.sl_candle_time,
            sl_order_id=dto.sl_order_id,
            tp_order_id=dto.tp_order_id,
            signal_trade_order_id=dto.entry_trade_order_id,
            is_completed=False,
            entry_price=dto.entry_price,
            trade1_quantity=int(dto.trade1_quantity) if dto.trade1_quantity is not None else None,
            extension_quantity=dto.extension_quantity,
            extension1_order_id=dto.extension1_trade_order_id,
            extension2_order_id=dto.extension2_trade_order_id
        )

        response = update_thread_event_details(update_event_thread_dto, thread_detail_id)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

        if (dto.sl_order_status == "COMPLETE") or (dto.tp_order_status == "COMPLETE"):
            default_log.debug(f"TP/SL hit")
            break

        # Fetch next data
        data = get_next_data(
            is_restart=is_restart,
            timeframe=timeframe,
            instrument_token=instrument_token,
            interval=interval,
            timestamp=data.iloc[-1]["time"]
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                              f"and timeframe={timeframe}")
            break

    if dto is not None:
        # Store the current state of event in the database
        update_event_thread_dto = EventThreadDetailsDTO(
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.SELL,
            configuration_type=configuration,
            signal_candle_high=dto.event1_candle_high,
            adjusted_high=dto.adjusted_high,
            signal_candle_low=dto.event1_candle_low,
            adjusted_low=dto.adjusted_low,
            event1_occur_time=dto.event1_occur_time,
            event2_breakpoint=dto.event2_occur_breakpoint,
            event2_occur_time=dto.event2_occur_time,
            event3_occur_time=dto.event3_occur_time,
            lowest_point=dto.lowest_point,
            highest_point=dto.highest_point,
            tp_value=dto.tp_values[-1].tp_value if len(dto.tp_values) > 0 else None,
            tp_datetime=dto.tp_candle_time,
            sl_value=dto.sl_value,
            sl_datetime=dto.sl_candle_time,
            sl_order_id=dto.sl_order_id,
            tp_order_id=dto.tp_order_id,
            signal_trade_order_id=dto.entry_trade_order_id,
            is_completed=True,
            entry_price=dto.entry_price,
            trade1_quantity=int(dto.trade1_quantity) if dto.trade1_quantity is not None else None,
            extension_quantity=dto.extension_quantity,
            extension1_order_id=dto.extension1_trade_order_id,
            extension2_order_id=dto.extension2_trade_order_id
        )

        response = update_thread_event_details(update_event_thread_dto, thread_detail_id)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while updating thread event details in database: {response.error}")
            return False

    if data_not_found:
        default_log.debug("Data not found for TP/SL hit")
        default_log.debug("Thread completed")
        return False
    else:
        default_log.debug("TP/SL Hit")
        default_log.debug(f"Thread Completed")
        return True


def restart_event_threads():
    """
    Get all incomplete threads and then execute them according to the event occur times
    1. For event 1 occurred but event 2 not occurred start from event 1 timestamp
    2. For event 2 occurred and event 3 not occurred then start from event 3 timestamp
    3. For event 3 occurred but neither tp nor sl got hit then start from event 3 timestamp
    """
    default_log.debug(f"inside restart_event_threads")

    # Get all incomplete thread details
    thread_details = get_all_incomplete_thread_details()

    for thread_detail in thread_details:

        event1_occur_time = thread_detail.event1_occur_time
        event2_occur_time = thread_detail.event2_occur_time
        event3_occur_time = thread_detail.event3_occur_time

        market_symbol = thread_detail.symbol

        candle_high = thread_detail.signal_candle_high
        candle_low = thread_detail.signal_candle_low

        lowest_point = thread_detail.lowest_point
        highest_point = thread_detail.highest_point
        sl_value = thread_detail.sl_value
        signal_type = thread_detail.signal_type

        time_frame = thread_detail.time_frame
        instrument_token = instrument_tokens_map[market_symbol]
        configuration_type = thread_detail.configuration_type

        signal_trade_order_id = thread_detail.signal_trade_order_id
        tp_order_id = thread_detail.tp_order_id
        sl_order_id = thread_detail.sl_order_id

        trade1_quantity = thread_detail.trade1_quantity,
        entry_price = thread_detail.entry_price

        extension_quantity = thread_detail.extension_quantity
        extension1_order_id = thread_detail.extension1_order_id
        extension2_order_id = thread_detail.extension2_order_id

        # 1. For event 1 occurred but event 2 not occurred start from event 1 timestamp
        if (event1_occur_time is not None) and (event2_occur_time is None):
            # Start the thread from event 1 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT, SL_VALUE
            restart_dto = RestartEventDTO(
                thread_id=thread_detail.id,
                symbol=market_symbol,
                time_frame=time_frame,
                candle_high=candle_high,
                candle_low=candle_low,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=thread_detail.event2_breakpoint,
                lowest_point=lowest_point,
                highest_point=highest_point,
                sl_value=sl_value
            )

            if signal_type == SignalType.BUY:

                thread = threading.Thread(target=start_market_logging_for_buy, args=(
                    market_symbol,
                    time_frame,
                    instrument_token,
                    0,
                    configuration_type,
                    restart_dto)
                                          )

                thread.start()

            else:

                thread = threading.Thread(target=start_market_logging_for_sell, args=(
                    market_symbol,
                    time_frame,
                    instrument_token,
                    0,
                    configuration_type,
                    restart_dto)
                                          )

                thread.start()

        elif (event1_occur_time is not None) and (event2_occur_time is not None) and (event3_occur_time is None):
            # Event 2 has been completed but not event 3
            # Start the thread from event 2 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT (For BUY),
            # HIGHEST_POINT (For SELL), SL_VALUE, EVENT2_OCCUR_TIME, EVENT2_BREAKPOINT

            restart_dto = RestartEventDTO(
                thread_id=thread_detail.id,
                symbol=market_symbol,
                time_frame=time_frame,
                candle_high=candle_high,
                candle_low=candle_low,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=thread_detail.event2_breakpoint,
                event2_occur_time=thread_detail.event2_occur_time,
                lowest_point=lowest_point,
                highest_point=highest_point,
                sl_value=sl_value
            )

            if signal_type == SignalType.BUY:
                thread = threading.Thread(target=start_market_logging_for_buy, args=(
                    market_symbol,
                    time_frame,
                    instrument_token,
                    0,
                    configuration_type,
                    restart_dto)
                                          )

                thread.start()

            else:
                thread = threading.Thread(target=start_market_logging_for_sell, args=(
                    market_symbol,
                    time_frame,
                    instrument_token,
                    0,
                    configuration_type,
                    restart_dto)
                                          )

                thread.start()
        else:
            # Event 3 has been completed but tp or sl has not been hit yet Start the thread from event 3 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT, SL_VALUE, EVENT2_BREAKPOINT, EVENT2_OCCUR_TIME,
            # EVENT3_OCCUR_TIME, TP VALUE

            tp_value = thread_detail.tp_value

            restart_dto = RestartEventDTO(
                thread_id=thread_detail.id,
                symbol=market_symbol,
                time_frame=time_frame,
                candle_high=candle_high,
                candle_low=candle_low,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=thread_detail.event2_breakpoint,
                event2_occur_time=thread_detail.event2_occur_time,
                event3_occur_time=thread_detail.event3_occur_time,
                lowest_point=lowest_point,
                highest_point=highest_point,
                sl_value=sl_value,
                tp_value=tp_value,
                trade1_quantity=trade1_quantity,
                entry_price=entry_price,
                extension_quantity=extension_quantity,
                extension1_order_id=extension1_order_id,
                extension2_order_id=extension2_order_id,
                signal_trade_order_id=signal_trade_order_id,
                tp_order_id=tp_order_id,
                sl_order_id=sl_order_id,
            )

            if signal_type == SignalType.BUY:
                thread = threading.Thread(target=start_market_logging_for_buy, args=(
                    market_symbol,
                    time_frame,
                    instrument_token,
                    0,
                    configuration_type,
                    restart_dto)
                                          )

                thread.start()

            else:
                thread = threading.Thread(target=start_market_logging_for_sell, args=(
                    market_symbol,
                    time_frame,
                    instrument_token,
                    0,
                    configuration_type,
                    restart_dto)
                                          )

                thread.start()
    return None
