import random
import threading

import pytz

from config import default_log, sandbox_mode, no_of_candles_to_consider, \
    instrument_tokens_map, buffer_for_entry_trade, buffer_for_tp_trade, initial_start_range, initial_end_range, \
    max_retries, trade1_loss_percent, trade2_loss_percent, trade3_loss_percent, indices_list, \
    provide_ticker_data, symbol_tokens_map, use_truedata, use_global_feed, buffer_for_indices_entry_trade, \
    buffer_for_indices_tp_trade, extension1_threshold_percent, extension2_threshold_percent
from typing import Optional

import time as tm
from datetime import datetime, timedelta
import pandas as pd
import math

from api.event_management.dtos.check_events_dto import CheckEventsDTO
from data.dbapi.symbol_budget_dbapi.read_queries import get_all_symbol_budgets
from data.dbapi.thread_details_dbapi.dtos.event_thread_details_dto import EventThreadDetailsDTO
from data.dbapi.thread_details_dbapi.read_queries import get_all_incomplete_thread_details
from data.dbapi.thread_details_dbapi.write_queries import add_thread_event_details, update_thread_event_details
from data.dbapi.timeframe_budgets_dbapi.read_queries import get_all_timeframe_budgets
from data.enums.budget_part import BudgetPart
from data.enums.configuration import Configuration
from data.enums.signal_type import SignalType
from data.enums.trades import Trades
from external_services.zerodha.zerodha_orders import place_zerodha_order_with_stop_loss, \
    place_zerodha_order_with_take_profit, update_zerodha_order_with_stop_loss, update_zerodha_order_with_take_profit, \
    get_kite_account_api, place_zerodha_order, get_historical_data, cancel_order, get_indices_symbol_for_trade, \
    get_status_of_zerodha_order, get_zerodha_order_details, round_value, get_instrument_token_for_symbol
from external_services.zerodha.zerodha_ticks_service import get_candlestick_data_using_ticker
from logic.zerodha_integration_management.dtos.event_details_dto import EventDetailsDTO
from logic.zerodha_integration_management.dtos.restart_event_dto import RestartEventDTO
from logic.zerodha_integration_management.dtos.timeframe_budget_and_trades_details_dto import \
    TimeframeBudgetAndTradesDetailsDTO
from logic.zerodha_integration_management.dtos.timeframe_budget_details_dto import TimeframeBudgetDetailsDTO
from logic.zerodha_integration_management.dtos.tp_details_dto import TPDetailsDTO
from logic.zerodha_integration_management.dtos.trades_to_make_dto import TradesToMakeDTO
from standard_responses.dbapi_exception_response import DBApiExceptionResponse

# kite = get_kite_account_api()
symbol_stop_loss_details = dict()
indices_proxy_dictionary = dict()

budget_dict = dict()
timeframe_budget_dict = dict()


def round_to_nearest_multiplier(number, multiplier):
    default_log.debug(f"inside round_to_nearest_multiplier with number={number} and multiplier={multiplier}")
    # Calculate the nearest multiple of the multiplier
    nearest_multiple = math.floor(round((number / multiplier), 0)) * multiplier

    # Check if the number is within a difference of positive 10
    if abs(number - nearest_multiple) <= 10:
        # If yes, round to the nearest multiple
        default_log.debug(f"Returning {nearest_multiple} as the nearest multiple for multiplier={multiplier} and "
                          f"number={number}")
        return nearest_multiple
    else:
        # Otherwise, keep the original number
        default_log.debug(f"Returning {number} as the nearest multiple for multiplier={multiplier} and "
                          f"number={number}")
        return number


def place_indices_market_order(
        indice_symbol: str,
        quantity: int,
        signal_type: SignalType,
        entry_price: Optional[float] = None
):
    # global kite
    kite = get_kite_account_api()
    default_log.debug(f"Inside place_market_order with indices_symbol={indice_symbol} "
                      f"with quantity={quantity} and signal_type={signal_type} and entry_price={entry_price}")

    if sandbox_mode:
        order_id = place_zerodha_order(
            kite,
            trading_symbol=indice_symbol,
            transaction_type=signal_type,
            quantity=quantity,
            average_price=entry_price,
            exchange="NFO"
        )
    else:
        order_id = place_zerodha_order(
            kite,
            trading_symbol=indice_symbol,
            transaction_type=signal_type,
            quantity=quantity,
            exchange="NFO"
        )

    if order_id is None:
        default_log.debug(f"An error occurred while placing MARKET order for indices_symbol={indice_symbol} with "
                          f"signal_type={signal_type} having quantity as "
                          f"{quantity}")
        return None

    default_log.debug(f"MARKET order placed for indices symbol={indice_symbol} with "
                      f"signal_type={signal_type} having quantity as "
                      f"{quantity}. Order ID: {order_id}")

    while True:
        zerodha_order_status = get_status_of_zerodha_order(kite, order_id)
        default_log.debug(f"Zerodha order status for MARKET order having id={order_id} is "
                          f"{zerodha_order_status} for indices_symbol={indice_symbol} ")

        if zerodha_order_status == "COMPLETE":
            default_log.debug(f"For the indices_symbol={indice_symbol} the "
                              f"status of order_id: {order_id} is COMPLETE")
            return order_id

        if zerodha_order_status == "REJECTED":
            default_log.debug(f"MARKET Order has been REJECTED having id={order_id} "
                              f"for indices_symbol={indice_symbol} ")
            return None
        tm.sleep(2)  # sleep for 2 seconds


def store_sl_details_of_active_trade(symbol: str, signal_type: SignalType, stop_loss: float, time_frame: int):
    default_log.debug(f"inside store_sl_details_of_active_trade for symbol={symbol} having "
                      f"signal_type={signal_type}, time_frame={time_frame} and stop_loss={stop_loss}")
    global symbol_stop_loss_details

    # Check whether if symbol stop loss details already present
    key = (symbol, signal_type)

    symbol_stop_loss = symbol_stop_loss_details.get(key, None)
    if symbol_stop_loss is None:
        default_log.debug(f"Adding stop loss ({stop_loss}) for symbol ({symbol}) and time_frame ({time_frame}) "
                          f"for signal_type={signal_type}")

        symbol_stop_loss_details[key] = {time_frame: stop_loss}
    else:
        # Update the stop loss value of the symbol
        if symbol_stop_loss.get(time_frame, None) is None:
            default_log.debug(f"Adding stop loss ({stop_loss}) for time_frame={time_frame} and key={key}")
            symbol_stop_loss_details[key][time_frame] = stop_loss
        else:
            old_stop_loss = symbol_stop_loss_details[key][time_frame]
            default_log.debug(f"Updating the stop loss of symbol ({symbol}) having "
                              f"time_frame={time_frame} and signal_type ({signal_type}) "
                              f"from {old_stop_loss} to {stop_loss} ")

            symbol_stop_loss_details[key][time_frame] = stop_loss


def store_all_timeframe_budget(reset: bool = False):
    global timeframe_budget_dict

    # Reset the timeframe_budget_dict and re-initialize it
    if reset:
        timeframe_budget_dict = {}

    # fetch the budget
    timeframe_budgets = get_all_timeframe_budgets()

    """
    timeframe_budget_dict = 
    {
        timeframe: [
            TimeframeBudgetDetailsDTO(
                budget=BudgetPart,
                no_of_trades=Trades,
                start_range=int,
                end_range=int,
            ),
        ]
    }
    """

    default_log.debug(f"Storing all timeframe budgets ({timeframe_budgets}) to timeframe_budget dictionary")

    if len(timeframe_budgets) == 0:
        # If no timeframe budget details found
        timeframe_budget_dict['basic'] = TimeframeBudgetDetailsDTO(
            budget=BudgetPart.FULL_BUDGET,
            no_of_trades=Trades.ALL_3_TRADES,
        )
        return

    for timeframe_budget in timeframe_budgets:
        if timeframe_budget.time_frame is None:
            key = 'default'
            existing_timeframe_budget = timeframe_budget_dict.get(key, None)
            if existing_timeframe_budget is None:
                timeframe_budget_dict[key] = [
                    TimeframeBudgetDetailsDTO(
                        budget=timeframe_budget.budget,
                        no_of_trades=timeframe_budget.trades,
                        start_range=timeframe_budget.start_range,
                        end_range=timeframe_budget.end_range
                    )
                ]
            else:
                existing_timeframe_budget.append(
                    TimeframeBudgetDetailsDTO(
                        budget=timeframe_budget.budget,
                        no_of_trades=timeframe_budget.trades,
                        start_range=timeframe_budget.start_range,
                        end_range=timeframe_budget.end_range,
                    )
                )
        else:
            key = timeframe_budget.time_frame

            existing_timeframe_budget = timeframe_budget_dict.get(key, None)
            if existing_timeframe_budget is None:
                timeframe_budget_dict[key] = [
                    TimeframeBudgetDetailsDTO(
                        budget=timeframe_budget.budget,
                        no_of_trades=timeframe_budget.trades,
                        start_range=timeframe_budget.start_range,
                        end_range=timeframe_budget.end_range
                    )
                ]
            else:
                existing_timeframe_budget.append(
                    TimeframeBudgetDetailsDTO(
                        budget=timeframe_budget.budget,
                        no_of_trades=timeframe_budget.trades,
                        start_range=timeframe_budget.start_range,
                        end_range=timeframe_budget.end_range,
                    )
                )
    return


def get_budget_and_no_of_trade_details(
        budget: float,
        close_price: float,
        dto: EventDetailsDTO
) -> TimeframeBudgetAndTradesDetailsDTO:
    def calculate_points_range(highest_point: float, lowest_point: float):
        default_log.debug(f"inside calculate_points_range with highest_point={highest_point} and "
                          f"lowest_point={lowest_point}")

        return abs(highest_point - lowest_point)

    global timeframe_budget_dict
    default_log.debug(f"inside get_budget_and_no_of_trade_details with budget={budget}, close_price={close_price} and "
                      f"dto={dto}")

    timeframe_budget_and_trades_details_dto = TimeframeBudgetAndTradesDetailsDTO()

    # Check under which range the budget will lie
    points_range = calculate_points_range(dto.highest_point, dto.lowest_point)
    # time_frame = dto.time_frame
    # if time_frame is None:
    #     key = 'default'
    #     timeframe_budgets = timeframe_budget_dict.get(key, None)
    #     if timeframe_budgets is None:
    #         key = 'basic'
    #         timeframe_budgets = timeframe_budget_dict.get(key)
    #         timeframe_budget_and_trades_details_dto.budget = timeframe_budgets.budget
    #         trades_to_make_dto = TradesToMakeDTO(
    #             entry_trade=True,
    #             extension1_trade=True,
    #             extension2_trade=True
    #         )
    #         timeframe_budget_and_trades_details_dto.trades_to_make = trades_to_make_dto
    #         return timeframe_budget_and_trades_details_dto
    # else:
    key = dto.time_frame
    timeframe_budgets = timeframe_budget_dict.get(key, None)
    if timeframe_budgets is None:
        key = 'default'
        timeframe_budgets = timeframe_budget_dict.get(key, None)
        if timeframe_budgets is None:
            key = 'basic'
            timeframe_budgets = timeframe_budget_dict.get(key)
            timeframe_budget_and_trades_details_dto.budget = timeframe_budgets.budget
            trades_to_make_dto = TradesToMakeDTO(
                entry_trade=True,
                extension1_trade=True,
                extension2_trade=True
            )
            timeframe_budget_and_trades_details_dto.trades_to_make = trades_to_make_dto

    target_timeframe_budget = None
    for timeframe_budget in timeframe_budgets:
        start_range_percent_price = (timeframe_budget.start_range / 100) * close_price
        end_range_percent_price = (timeframe_budget.end_range / 100) * close_price

        # start_range * current_price (close_price)/100 (sl-entry) timeframe_budget.end_range * current_price (close_price)/100
        # start_range * current_price (close_price)/100 point_range timeframe_budget.end_range * current_price (close_price)/100

        if start_range_percent_price <= points_range < end_range_percent_price:
            default_log.debug(f"Target time frame budget found={timeframe_budget} having "
                              f"trades={timeframe_budget.no_of_trades} and budget={timeframe_budget.budget}")

            target_timeframe_budget = timeframe_budget
            break
        elif points_range > end_range_percent_price:
            default_log.debug(f"Target time frame budget found={timeframe_budget} having "
                              f"trades={timeframe_budget.no_of_trades} and budget={timeframe_budget.budget}")

            target_timeframe_budget = timeframe_budget
            break

    budget_part = target_timeframe_budget.budget

    if budget_part == BudgetPart.FULL_BUDGET:
        timeframe_budget_and_trades_details_dto.budget = budget
    elif budget_part == BudgetPart.TWO_THIRD_BUDGET:
        timeframe_budget_and_trades_details_dto.budget = 2 * (budget / 3)
    elif budget_part == BudgetPart.ONE_THIRD_BUDGET:
        timeframe_budget_and_trades_details_dto.budget = 1 * (budget / 3)
    else:
        timeframe_budget_and_trades_details_dto.budget = 0

    # Decide the no of trades
    trades_to_make_dto = TradesToMakeDTO(
        entry_trade=False,
        extension1_trade=False,
        extension2_trade=False
    )

    if target_timeframe_budget.no_of_trades == Trades.NO_TRADE:
        timeframe_budget_and_trades_details_dto.trades_to_make = trades_to_make_dto
        return timeframe_budget_and_trades_details_dto

    if target_timeframe_budget.no_of_trades == Trades.LAST_TRADE:
        trades_to_make_dto.extension2_trade = True

    if target_timeframe_budget.no_of_trades == Trades.FIRST_2_TRADES:
        trades_to_make_dto.extension1_trade = True
        trades_to_make_dto.entry_trade = True
        trades_to_make_dto.extension2_trade = False

    if target_timeframe_budget.no_of_trades == Trades.ALL_3_TRADES:
        trades_to_make_dto.extension1_trade = True
        trades_to_make_dto.entry_trade = True
        trades_to_make_dto.extension2_trade = True

    timeframe_budget_and_trades_details_dto.trades_to_make = trades_to_make_dto
    default_log.debug(f"returning timeframe_budget_and_trades_details_dto for symbol={dto.symbol} and "
                      f"timeframe={dto.time_frame}: {timeframe_budget_and_trades_details_dto}")
    return timeframe_budget_and_trades_details_dto


def do_update_of_sl_values(
        timeframe: int,
        entry_price: float,
        close_price: float,
        signal_type: SignalType,
        symbol: str
) -> tuple[bool, float]:
    """
        1 -> 1, SELL, AXIS
        3 -> SL => 1 (50% condition) time after that don't update SL

    """
    global symbol_stop_loss_details
    default_log.debug(f"inside do_update_of_sl_values with symbol={symbol}, time_frame={timeframe} and "
                      f"signal_type={signal_type} with symbol_stop_loss_details={symbol_stop_loss_details}")

    # Fetch the stop loss of the (symbol, signal_type) key from symbol_stop_loss_details
    key = (symbol, signal_type)
    symbol_stop_loss_time_frames_with_stop_loss = symbol_stop_loss_details.get(key, None)

    update_sl = False  # keep track if sl needs to be updated
    sl_value_to_update_to = 0  # value to be updated to
    if symbol_stop_loss_time_frames_with_stop_loss is None:
        default_log.debug("Not updating SL value as no symbol_stop_loss_time_frames_with_stop_loss found "
                          f"for key={key} and time_frame={timeframe}")
        return update_sl, sl_value_to_update_to

    # Fetch the time_frames
    time_frames_of_symbol = symbol_stop_loss_time_frames_with_stop_loss.keys()
    default_log.debug(f"Timeframes fetched for symbol={symbol} having time_frame={timeframe} from "
                      f"symbol_stop_loss_details={symbol_stop_loss_details}: {time_frames_of_symbol}")

    # New Flow of SL extension
    # Calculate current SL value multiplied by x1.5 and check if any of the previous SL value obtained is between the
    # entry SL value and x1.5 SL value if yes then use the SL of the previous SL trade

    # Now get the just biggest timeframe than the current timeframe
    # Filter numbers that are greater than the target
    bigger_timeframes = [time_frame for time_frame in time_frames_of_symbol if time_frame > timeframe]

    # Check if any bigger timeframes found
    if len(bigger_timeframes) == 0:
        default_log.debug(f"No bigger timeframes than {timeframe} found from {time_frames_of_symbol}")
        return update_sl, sl_value_to_update_to

    # Get all timeframe:sl value dictionaries that are just bigger than the current timeframe
    bigger_timeframe_with_sl_values_list = [
        {sl_timeframe: sl_value} for sl_timeframe, sl_value in symbol_stop_loss_time_frames_with_stop_loss.items()
        if sl_timeframe in bigger_timeframes
    ]

    default_log.debug(
        f"bigger_timeframe_with_sl_values_list={bigger_timeframe_with_sl_values_list} for symbol={symbol} "
        f"and timeframe={timeframe} with key={key}")

    current_timeframe_sl_value = symbol_stop_loss_time_frames_with_stop_loss[timeframe]
    times_multiplied_sl = current_timeframe_sl_value * 1.5

    start_threshold = (initial_start_range / 100) * close_price
    end_threshold = (initial_end_range / 100) * close_price

    sl_and_entry_price_difference = current_timeframe_sl_value - entry_price

    default_log.debug(f"Initially for symbol={symbol} and timeframe={timeframe} and signal_type={signal_type}. "
                      f"The start_threshold={start_threshold} (initial_start_range {initial_start_range}/100 "
                      f"* close_price {close_price}) and end_threshold={end_threshold} "
                      f"(initial_end_range {initial_end_range}/100 * close_price {close_price}) and "
                      f"sl_and_entry_price_difference={sl_and_entry_price_difference}")

    for timeframe_sl_dict in bigger_timeframe_with_sl_values_list:
        time_frame, timeframe_sl_value = list(timeframe_sl_dict.items())[0]

        # Check if timeframe_sl_value is between current_timeframe_sl_value and times_multiplied_sl
        if current_timeframe_sl_value < timeframe_sl_value < times_multiplied_sl:

            # Check if SL value is going above threshold
            # start_range * current_price (close_price)/100 (sl-entry) timeframe_budget.end_range *
            # current_price (close_price)/100
            sl_and_entry_price_difference = timeframe_sl_value - entry_price
            if start_threshold < sl_and_entry_price_difference < end_threshold:
                default_log.debug(f"Need to update the SL value of current sl timeframe ({timeframe}) having key="
                                  f"{key} from {current_timeframe_sl_value} to {timeframe_sl_value} of sl timeframe "
                                  f"({time_frame}) having key={key}")

                update_sl = True
                sl_value_to_update_to = timeframe_sl_value

                default_log.debug(
                    f"Extending the stop loss value of symbol={symbol} having time_frame={timeframe} and key="
                    f"{key} from {current_timeframe_sl_value} to {sl_value_to_update_to}")

                return update_sl, sl_value_to_update_to
            else:

                default_log.debug(f"Can update SL of key={key} from {current_timeframe_sl_value} to "
                                  f"{timeframe_sl_value}. But, won't do it as the condition "
                                  f"(start_threshold [{start_threshold}] < sl_and_entry_price_difference "
                                  f"[{sl_and_entry_price_difference}] < end_threshold [{end_threshold}]) is not "
                                  f"satisfied when sl is update from {current_timeframe_sl_value} to "
                                  f"{timeframe_sl_value} ")

    return update_sl, sl_value_to_update_to

    # Find the first bigger number
    # just_bigger_timeframe_than_current_timeframe = min(bigger_timeframes)
    #
    # # Get the just bigger timeframe stop loss value and update the sl value of the current timeframe symbol
    # default_log.debug(f"Bigger time_frame ({just_bigger_timeframe_than_current_timeframe}) found that is just bigger "
    #                   f"than current timeframe={timeframe} for symbol={symbol} and signal_type={signal_type}")
    #
    # # Get the stop loss value of the just bigger timeframe
    # stop_loss_of_just_bigger_timeframe = symbol_stop_loss_time_frames_with_stop_loss.get(
    #     just_bigger_timeframe_than_current_timeframe
    # )
    #
    # default_log.debug(f"Stop Loss of just_bigger_timeframe_than_current_timeframe "
    #                   f"({just_bigger_timeframe_than_current_timeframe}) for symbol={symbol} and "
    #                   f"signal_type={signal_type} is {stop_loss_of_just_bigger_timeframe}")
    # update_sl = True
    # default_log.debug(f"Extending the stop loss value of symbol={symbol} having time_frame={timeframe} to "
    #                   f"{stop_loss_of_just_bigger_timeframe}")
    # sl_value_to_update_to = stop_loss_of_just_bigger_timeframe
    # return update_sl, sl_value_to_update_to


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


def store_all_symbol_budget(reset: bool = False):
    global budget_dict

    if reset:
        budget_dict = {}

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

    # candle_time = dto.time_of_candle_formation
    # candle_time = candle_time.astimezone(pytz.timezone("Asia/Kolkata"))

    # Get the wait time
    # wait_time = get_wait_time(candle_time, time_frame=int(dto.time_frame_in_minutes))
    # default_log.debug(f"Wait time for symbol={dto.symbol} having time_frame={dto.time_frame_in_minutes} and "
    #                   f"candle_time={dto.time_of_candle_formation} is {wait_time} "
    #                   f"seconds")
    symbol = dto.symbol
    inst_token = instrument_tokens_map[dto.symbol]

    exchange = "NFO" if symbol in indices_list else "NSE"
    if inst_token is None:
        inst_token = get_instrument_token_for_symbol(symbol, exchange)
        default_log.debug(f"instrument token received for symbol={symbol} and exchange={exchange}: "
                          f"{inst_token}")

    time_frame = dto.time_frame_in_minutes
    signal_type = dto.signal_type
    configuration = Configuration.HIGH if dto.signal_type == SignalType.BUY else Configuration.LOW

    # Create and start a thread for each symbol
    if signal_type == SignalType.BUY:
        thread = threading.Thread(target=start_market_logging_for_buy,
                                  args=(symbol, time_frame, inst_token, 2, configuration))
        thread.start()
    else:
        thread = threading.Thread(target=start_market_logging_for_sell,
                                  args=(symbol, time_frame, inst_token, 2, configuration))
        thread.start()

    # Let the threads run independently
    return None


# Used initially to get the initial data and later used again and again
def get_zerodha_data(
        instrument_token: int,
        market_symbol: str,
        interval: str,
        from_date: datetime = None,
        is_restart: bool = False
):
    kite = get_kite_account_api()
    for attempt in range(max_retries):
        default_log.debug("inside get_zerodha_data with "
                          f"instrument_token={instrument_token} "
                          f"market_symbol={market_symbol} "
                          f"from_date={from_date} "
                          f"interval={interval} "
                          f"is_restart={is_restart} ")

        market_symbol = ""

        # for k, v in instrument_tokens_map.items():
        #     if v == instrument_token:
        #         market_symbol = k

        if interval == "minute":
            time_frame = 1
        else:
            time_frame = int(interval.split('minute')[0])

        if from_date is not None:
            current_timestamp = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
            to_timestamp = from_date.astimezone(pytz.timezone("Asia/Kolkata")) + timedelta(minutes=time_frame)

            if to_timestamp >= current_timestamp:
                default_log.debug(f"Stopping receiving of historical data and starting to get the tick data as "
                                  f"to_timestamp ({to_timestamp}) >= current_timestamp ({current_timestamp})")

                is_restart = False
                from_date = None

        current_datetime = None
        if is_restart:
            current_datetime = from_date.astimezone(pytz.timezone("Asia/Kolkata")) + timedelta(minutes=time_frame)
            current_datetime = current_datetime.astimezone(pytz.timezone("Asia/Kolkata"))
            # if (not use_truedata) or (not use_global_feed):
            #     current_datetime = from_date.astimezone(pytz.timezone("Asia/Kolkata")) + timedelta(minutes=time_frame)
            #     from_date = from_date.astimezone(pytz.timezone("Asia/Kolkata"))
            #     if current_datetime > datetime.now().astimezone(pytz.timezone("Asia/Kolkata")):
            #         # Calculate the wait time to be added to get the nearest datetime
            #         wait_time = get_wait_time(from_date, time_frame)
            #         current_datetime = from_date + timedelta(seconds=wait_time)
            # else:
            #     current_datetime = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))
        # else:
        #     current_datetime = datetime.now().astimezone(pytz.timezone("Asia/Kolkata")) + timedelta(
        #         minutes=(time_frame * 3))
        #     from_date = from_date - timedelta(minutes=(time_frame * 3))

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

        if use_truedata or use_global_feed:
            data['time'] = zerodha_historical_data['timestamp']
        else:
            data['time'] = zerodha_historical_data['date']

        return data

    default_log.debug(f"Max retries reached. Unable to get Zerodha historical data.")
    return None


# Used again and again for consecutive data
def get_next_data(
        is_restart: bool,
        timeframe: str,
        instrument_token: int,
        interval: str,
        from_timestamp: datetime = None
):
    default_log.debug(f"inside get_next_data with "
                      f"is_restart={is_restart} "
                      f"timeframe={timeframe} "
                      f"instrument_token={instrument_token} "
                      f"interval={interval} "
                      f"from_timestamp={from_timestamp} "
                      f"and symbol={symbol_tokens_map[instrument_token]}")
    symbol = symbol_tokens_map[instrument_token]

    if is_restart:
        # wait_time = get_wait_time(timestamp, int(timeframe))
        wait_time = 2
        default_log.debug(f"Waiting for {wait_time} seconds before fetching next candle data for "
                          f"symbol={symbol} and time_frame={timeframe}")
        tm.sleep(wait_time)

        from_date = from_timestamp
        to_date = from_timestamp + timedelta(minutes=int(timeframe))
        to_date = to_date.astimezone(pytz.timezone("Asia/Kolkata"))

        # Fetch new candle data
        data = get_zerodha_data(
            instrument_token=instrument_token,
            market_symbol=symbol,
            from_date=from_date,
            interval=interval,
            is_restart=is_restart
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol}, from {from_date} to {to_date}"
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
            market_symbol=symbol,
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

        timestamp = candle_data["time"]
        # Get the H1 data
        if current_candle_high > event_data_dto.high_1:
            default_log.debug(f"Highest Point (H1) found at={timestamp} "
                              f"H1={current_candle_high}")

            event_data_dto.high_1 = current_candle_high

        # To Calculate the TP data
        sl_minus_h1 = event_data_dto.sl_value - event_data_dto.high_1

        h1_minus_h = event_data_dto.high_1 - h

        greatest = max(h1_minus_h, sl_minus_h1)

        tp_val = (event_data_dto.entry_price - greatest)

        # update tp value
        if event_data_dto.symbol not in indices_list:
            default_log.debug(f"For TP value for symbol={event_data_dto.symbol} and "
                              f"timeframe={event_data_dto.time_frame} at timestamp={timestamp} calculating TP value "
                              f"by subtracting extra percent buffer of {buffer_for_tp_trade}")

            # Calculate TP with buffer
            tp_with_buffer = tp_val - (tp_val * buffer_for_tp_trade)
        else:
            default_log.debug(f"For TP value for symbol={event_data_dto.symbol} and "
                              f"timeframe={event_data_dto.time_frame} at timestamp={timestamp} calculating TP value "
                              f"by subtracting extra percent buffer of {buffer_for_indices_tp_trade}")

            # Calculate TP with buffer
            tp_with_buffer = tp_val - (tp_val * buffer_for_indices_tp_trade)

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

        tp_with_buffer = tp_val - (tp_val * buffer_for_tp_trade)

    tp_details = TPDetailsDTO(
        timestamp=candle_data["time"],
        tp_value=tp_val,
        low_1=event_data_dto.low_1,
        high_1=event_data_dto.high_1,
        sl_value=event_data_dto.sl_value,
        low=l,
        high=h,
        entry_price=event_data_dto.entry_price,
        greatest_price=greatest,
        tp_buffer_percent=buffer_for_tp_trade,
        tp_with_buffer=tp_with_buffer
    )

    event_data_dto.tp_values.append(tp_details)

    return event_data_dto


def trade_logic_sell(
        symbol: str, timeframe: str, candle_data: pd.DataFrame,
        data_dictionary: dict[tuple[str, str], Optional[EventDetailsDTO]]
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

        # Check for AH condition
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

            candle_high = event_data_dto.adjusted_high if event_data_dto.adjusted_high is not None else event1_candle_high
            if current_candle_high > candle_high:
                default_log.debug(f"Adjusted HIGH condition occurred at timestamp={timestamp} as "
                                  f"current_candle_high ({current_candle_high}) > candle_high ({candle_high}) "
                                  f"for symbol={symbol} having timeframe={timeframe}")

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
            # Check whether the adjusted_high has traced more than the candle length, if yes then stop tracking
            if event_data_dto.adjusted_high is not None:
                adjusted_difference = event_data_dto.adjusted_high - event_data_dto.event1_candle_high

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = event1_candle_height

                if adjusted_difference > event_data_dto.candle_length:
                    default_log.debug(f"The adjusted_high difference={adjusted_difference} has gone above "
                                      f"by more than the candle_length={event_data_dto.candle_length} so stopping "
                                      f"tracking of the events for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.stop_tracking_further_events = True
                    return event_data_dto, data_dictionary

            # Commented out this as if adjusted low or high occurred then check for event 2 on that only candle and
            # don't wait for the next candle to check the event 2 occur timestamp
            # if timestamp.hour < previous_timestamp.hour or \
            #         (timestamp.hour == previous_timestamp.hour and
            #          timestamp.minute <= previous_timestamp.minute):
            #     default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Previous time "
            #                       f"({previous_timestamp}) for symbol={event_data_dto.symbol} and "
            #                       f"time_frame={event_data_dto.time_frame}")
            #     return event_data_dto, data_dictionary

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
            if event_data_dto.symbol not in indices_list:
                default_log.debug(f"Subtracting a buffer percent ({buffer_for_entry_trade}) from the sell_candle_low "
                                  f"({sell_candle_low}) as the breakpoint for event 3 for symbol={event_data_dto.symbol} "
                                  f"and time_frame={event_data_dto.time_frame}")

                candle_high_to_check = sell_candle_low - (sell_candle_low * buffer_for_entry_trade)
                event_data_dto.event3_occur_breakpoint = candle_high_to_check
            else:
                default_log.debug(f"Subtracting a buffer percent ({buffer_for_indices_entry_trade}) "
                                  f"from the sell_candle_low ({sell_candle_low}) as the breakpoint for "
                                  f"event 3 for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")

                candle_high_to_check = sell_candle_low - (sell_candle_low * buffer_for_indices_entry_trade)
                event_data_dto.event3_occur_breakpoint = candle_high_to_check

            if current_candle_high > candle_high_to_check:
                default_log.debug(f"Event 3 occurred for symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} at timestamp={timestamp}")
                default_log.debug(f"Event 3 occurred as Current Candle High={current_candle_high} > "
                                  f"candle_high_to_check={candle_high_to_check}")
                event_data_dto.entry_price = current_candle_high
                event_data_dto.event3_occur_time = timestamp

                # Calculate SL
                # value_to_add_for_stop_loss_entry_price = (
                #         event_data_dto.highest_point - event_data_dto.event1_candle_low)

                value_to_add_for_stop_loss_entry_price = (
                        event_data_dto.highest_point - event_data_dto.lowest_point)

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = event1_candle_height

                # Add height of event1_candle to the SL value as buffer
                sl_value = event_data_dto.entry_price + value_to_add_for_stop_loss_entry_price

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
            previous_timestamp=timestamp,
            stop_tracking_further_events=False
        )

        data_dictionary[key] = dto

        return dto, data_dictionary


def trade_logic_buy(
        symbol: str,
        timeframe: str,
        candle_data: pd.DataFrame,
        data_dictionary: dict[tuple[str, str], Optional[EventDetailsDTO]]
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

            candle_low = event_data_dto.adjusted_low if event_data_dto.adjusted_low is not None else buy_candle_low
            if current_candle_low < candle_low:
                default_log.debug(f"Adjusted LOW condition occurred at timestamp={timestamp} as "
                                  f"current_candle_low ({current_candle_low}) < candle_low ({candle_low}) "
                                  f"for symbol={symbol} having timeframe={timeframe}")

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

            # Check whether the adjusted_low has traced more than the candle length, if yes then stop tracking
            if event_data_dto.adjusted_low is not None:
                adjusted_difference = event_data_dto.event1_candle_low - event_data_dto.adjusted_low

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = event1_candle_height

                if adjusted_difference > event_data_dto.candle_length:
                    default_log.debug(f"The adjusted_low_difference={adjusted_difference} has gone below "
                                      f"by more than the candle_length={event_data_dto.candle_length} so stopping "
                                      f"tracking of the events for symbol={symbol} and time_frame={timeframe}")
                    event_data_dto.stop_tracking_further_events = True
                    return event_data_dto, data_dictionary

            # Commented out this as if adjusted low or high occurred then check for event 2 on that only candle and
            # don't wait for the next candle to check the event 2 occur timestamp
            # if timestamp.hour < previous_timestamp.hour or \
            #         (timestamp.hour == previous_timestamp.hour and
            #          timestamp.minute <= previous_timestamp.minute):
            #     default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Previous time "
            #                       f"({previous_timestamp}) for symbol={event_data_dto.symbol} and "
            #                       f"time_frame={event_data_dto.time_frame}")
            #     return event_data_dto, data_dictionary

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
            if event_data_dto.symbol not in indices_list:
                default_log.debug(f"Adding a buffer percent ({buffer_for_entry_trade}) to the buy_candle_high "
                                  f"({buy_candle_high}) as the breakpoint for event 3 for symbol={event_data_dto.symbol} "
                                  f"and time_frame={event_data_dto.time_frame}")

                candle_low_to_check = buy_candle_high + (buy_candle_high * buffer_for_entry_trade)
                event_data_dto.event3_occur_breakpoint = candle_low_to_check
            else:
                default_log.debug(f"Adding a buffer percent ({buffer_for_indices_entry_trade}) to the buy_candle_high "
                                  f"({buy_candle_high}) as the breakpoint for event 3 for symbol={event_data_dto.symbol} "
                                  f"and time_frame={event_data_dto.time_frame}")

                candle_low_to_check = buy_candle_high + (buy_candle_high * buffer_for_indices_entry_trade)
                event_data_dto.event3_occur_breakpoint = candle_low_to_check

            if current_candle_low < candle_low_to_check:
                default_log.debug(f"Event 3 occurred for symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} at timestamp={timestamp}")
                default_log.debug(f"Event 3 occurred as Current Candle Low={current_candle_low} < "
                                  f"candle_low_to_check={candle_low_to_check}")
                event_data_dto.entry_price = current_candle_low

                # value_to_add_for_stop_loss_entry_price = -(
                #         event_data_dto.event1_candle_high - event_data_dto.lowest_point)

                value_to_add_for_stop_loss_entry_price = -(
                        event_data_dto.highest_point - event_data_dto.lowest_point)

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = -event1_candle_height

                # Subtract event1 candle height from the sl value as buffer only while creating SL-M order
                sl_value = event_data_dto.entry_price + value_to_add_for_stop_loss_entry_price

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
            previous_timestamp=timestamp,
            stop_tracking_further_events=False
        )

        data_dictionary[key] = dto

        return dto, data_dictionary


def update_tp_and_sl_status(event_data_dto: EventDetailsDTO, data_dictionary):
    kite = get_kite_account_api()
    default_log.debug(f"inside update_tp_and_sl_status with event_data_dto={event_data_dto}")

    symbol = event_data_dto.symbol
    time_frame = event_data_dto.time_frame

    key = (symbol, time_frame)
    while True:
        dto = data_dictionary.get(key)

        tp_order_id = dto.tp_order_id
        sl_order_id = dto.sl_order_id

        default_log.debug(f"Getting status of tp_order_id={tp_order_id} and "
                          f"sl_order_id={sl_order_id} of symbol={symbol} having timeframe={time_frame}")
        tp_order_details = kite.order_history(tp_order_id)
        sl_order_details = kite.order_history(sl_order_id)

        tp_order_status = tp_order_details[-1].get("status", None)
        sl_order_status = sl_order_details[-1].get("status", None)

        event_data_dto.tp_order_status = tp_order_status
        event_data_dto.sl_order_status = sl_order_status

        default_log.debug(f"Status of tp_order_id={tp_order_id} is {tp_order_status} and "
                          f"sl_order_id={sl_order_id} is {tp_order_status} for symbol={symbol} having timeframe="
                          f"{time_frame}")

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
        loss_budget: float,
        indices_symbol: str = None,
        extra_extension: bool = False
) -> tuple[EventDetailsDTO, bool]:
    default_log.debug(f"inside place_zerodha_trades with event_data_dto={event_data_dto} and "
                      f"signal_type={signal_type} for symbol={symbol} and indices_symbol={indices_symbol} and "
                      f"loss_budget={loss_budget} and extra_extension status={extra_extension}")
    kite = get_kite_account_api()
    entry_price = event_data_dto.entry_price
    entry_sl_value = event_data_dto.sl_value

    default_log.debug(f"Entry Price = {entry_price} and Entry SL value = {entry_sl_value} for "
                      f"symbol={symbol} and indices_symbol={indices_symbol}")

    loss_percent = loss_budget * trade1_loss_percent

    trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
    # Round off trade1_quantity to 0 decimal places and convert to int
    trade1_quantity = int(round(trade1_quantity, 0))

    if not extra_extension:
        default_log.debug(f"Creating MARKET order for trading_symbol={symbol} "
                          f"transaction_type={signal_type} and quantity={trade1_quantity} "
                          f"at timestamp={candle_data['time']} with event1_occur_time={event_data_dto.event1_occur_time} "
                          f"and event3_occur_time={event_data_dto.event3_occur_time} and "
                          f"indices_symbol={indices_symbol}")
    else:
        default_log.debug(f"[BEYOND EXTENSION] Creating MARKET order for trading_symbol={symbol} "
                          f"transaction_type={signal_type} and quantity={event_data_dto.extension_quantity} "
                          f"at timestamp={candle_data['time']} with event1_occur_time={event_data_dto.event1_occur_time} "
                          f"and event3_occur_time={event_data_dto.event3_occur_time} and "
                          f"indices_symbol={indices_symbol}")

    event_data_dto.trade1_quantity = trade1_quantity
    extra_extension_quantity = event_data_dto.extension_quantity

    # Start trade
    if sandbox_mode:
        entry_trade_order_id = place_zerodha_order(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=signal_type,
            quantity=trade1_quantity if not extra_extension else extra_extension_quantity,
            exchange="NSE",
            average_price=event_data_dto.entry_price
        )
    else:
        entry_trade_order_id = place_zerodha_order(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=signal_type,
            quantity=trade1_quantity if not extra_extension else extra_extension_quantity,
            exchange="NSE"
        )

    if entry_trade_order_id is None:
        if not extra_extension:
            default_log.debug(
                f"An error has occurred while placing MARKET order for symbol={symbol} having timeframe="
                f"{event_data_dto.time_frame} and "
                f"event_data_dto={event_data_dto}")
        else:
            default_log.debug(
                f"[BEYOND EXTENSION] An error has occurred while placing MARKET order for symbol={symbol} "
                f"having timeframe={event_data_dto.time_frame} and "
                f"event_data_dto={event_data_dto}")
        return event_data_dto, True

    event_data_dto.entry_trade_order_id = entry_trade_order_id

    if not extra_extension:
        default_log.debug(
            f"[{signal_type.name}] Signal Trade order placed for symbol={symbol} at {candle_data['time']} "
            f"signal_trade_order_id={entry_trade_order_id} "
            f"and indices_symbol={indices_symbol}")
    else:
        default_log.debug(
            f"[BEYOND EXTENSION] [{signal_type.name}] Signal Trade order placed for symbol={symbol} at "
            f"{candle_data['time']} signal_trade_order_id={entry_trade_order_id} "
            f"and indices_symbol={indices_symbol}")

    while True:
        zerodha_order_status = get_status_of_zerodha_order(kite, entry_trade_order_id)
        default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                          f"Zerodha order status for MARKET order having id={entry_trade_order_id} is "
                          f"{zerodha_order_status} for symbol={symbol} and "
                          f"indices_symbol={indices_symbol}")

        if zerodha_order_status == "COMPLETE":
            # Now get the fill price when order was completed and then calculate the take profit
            zerodha_market_order_details = get_zerodha_order_details(kite, entry_trade_order_id)

            if zerodha_market_order_details is None:
                default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                                  f"An error occurred while fetching Zerodha MARKET order details for "
                                  f"id={entry_trade_order_id} for symbol={symbol} and "
                                  f"indices_symbol={indices_symbol}")
                return event_data_dto, True

            fill_price = zerodha_market_order_details['average_price']
            default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                              f"Fill price of zerodha market order having id={entry_trade_order_id} is "
                              f"fill_price={fill_price} for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")

            greatest_price = event_data_dto.tp_values[-1].greatest_price
            old_take_profit = event_data_dto.tp_values[-1].tp_with_buffer

            # tp_direction = 1 if signal_type == SignalType.BUY else -1  # +1 if tp order is SELL and -1 if tp is BUY
            take_profit_updated = fill_price + greatest_price

            default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                              f"Updating old TP value={old_take_profit} to {take_profit_updated} for "
                              f"MARKET order id={entry_trade_order_id} for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")

            take_profit_with_buffer = take_profit_updated - (take_profit_updated * buffer_for_tp_trade)

            default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                              f"Updating old TP (by adding/subtracting buffer of [{buffer_for_tp_trade}]) "
                              f"value={take_profit_updated} to {take_profit_with_buffer} for "
                              f"MARKET order id={entry_trade_order_id} for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")

            # Now update the take profit and entry price
            # event_data_dto.tp_values[-1].tp_value = take_profit_updated
            event_data_dto.tp_values[-1].tp_with_buffer = take_profit_with_buffer

            # Now update entry price
            old_entry_price = event_data_dto.entry_price
            new_entry_price = fill_price
            default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                              f"Updating old Entry Price of={old_entry_price} to {new_entry_price} "
                              f"for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")
            event_data_dto.entry_price = new_entry_price

            # if indices_symbol is not None:
            old_sl_value = event_data_dto.sl_value
            new_sl_value = event_data_dto.entry_price + event_data_dto.value_to_add_for_stop_loss_entry_price

            default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                              f"Updating old SL Value of={old_sl_value} to {new_sl_value} "
                              f"for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")
            event_data_dto.sl_value = new_sl_value

            break

        if zerodha_order_status == "REJECTED":
            default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                              f"MARKET Order has been REJECTED having id={entry_trade_order_id} "
                              f"for symbol={symbol} and "
                              f"indices_symbol={indices_symbol}")
            return event_data_dto, True
        tm.sleep(2)  # sleep for 2 seconds

    default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                      f"Adding buffer of {event_data_dto.candle_length} to the stop loss ({event_data_dto.sl_value}) ="
                      f" {event_data_dto.sl_value + event_data_dto.candle_length}")
    stop_loss = event_data_dto.sl_value + event_data_dto.candle_length

    take_profit = event_data_dto.tp_values[-1].tp_with_buffer
    default_log.debug(
        f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
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

    default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                      f"Formatted SL value for symbol={event_data_dto.symbol} and timeframe = "
                      f"{event_data_dto.time_frame} is {stop_loss}")

    # event_data_dto.sl_value = stop_loss

    # round off the price of take profit
    formatted_value = round_value(
        symbol=symbol if indices_symbol is None else indices_symbol,
        price=take_profit,
        exchange="NSE" if indices_symbol is None else "NFO"
    )

    take_profit = formatted_value

    event_data_dto.tp_values[-1].tp_with_buffer = take_profit
    # event_data_dto.tp_values[-1].tp_value = take_profit  # commented out as tp value should not be updated

    # Continue with creating a TP and SL trade
    default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                      f"Placing SL order for entry_trade_order_id={entry_trade_order_id} for "
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
        default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                          f"An error occurred while placing SL order for "
                          f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                          f"with quantity={trade1_quantity} and stop_loss={stop_loss} and "
                          f"indices_symbol={indices_symbol} ")
    else:
        default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                          f"Placed SL order with id={sl_order_id} "
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
        default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                          f"An error occurred while placing TP order for "
                          f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                          f"with quantity={trade1_quantity} and stop_loss={stop_loss} ")
    else:
        default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
                          f"Placed TP order with id={sl_order_id} "
                          f"for entry_trade_order_id={entry_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                          f"with quantity={trade1_quantity} and stop_loss={stop_loss} "
                          f"indices_symbol={indices_symbol} ")

        event_data_dto.tp_order_id = tp_order_id

    thread = threading.Thread(target=update_tp_and_sl_status, args=(event_data_dto, data_dictionary))
    thread.start()

    return event_data_dto, False


def place_extension_zerodha_trades(
        event_data_dto: EventDetailsDTO,
        signal_type: SignalType,
        candle_data,
        extension_quantity: float,
        symbol: str,
        multiplier: int,
        extension_no: int,
        exchange: str = "NSE",
        indices_symbol: str = None
) -> tuple[EventDetailsDTO, bool]:
    default_log.debug(f"inside place_extension_zerodha_trades with event_data_dto={event_data_dto} and "
                      f"signal_type={signal_type} for symbol={symbol} and exchange={exchange} with "
                      f"multiplier={multiplier} and extension no={extension_no}")

    kite = get_kite_account_api()

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
            quantity=extension_quantity,
            exchange="NSE",
            average_price=average_price
        )
    else:
        extension_trade_order_id = place_zerodha_order(
            kite=kite,
            trading_symbol=symbol if indices_symbol is None else indices_symbol,
            transaction_type=signal_type,
            quantity=extension_quantity,
            exchange="NSE"
        )

    # Calculate the quantity for the extension tp and sl order update
    if event_data_dto.trade1_quantity is None:
        default_log.debug(f"Setting Trade 1 quantity as 0 as trade1_quantity={event_data_dto.trade1_quantity}")
        event_data_dto.trade1_quantity = 0

    event_data_dto.extension_quantity = event_data_dto.trade1_quantity if event_data_dto.extension_quantity is None else event_data_dto.extension_quantity

    # [LOGIC] if extension_quantity is None: extension_quantity = dto.trade1_quantity
    # tp_sl_quantity = extension_quantity + extension
    # 1st Extension: extension_quantity = trade1_quantity = 4 =>
    # 4 + 6 = 10 (extension_quantity=10) = extension1_quantity

    # 2nd Extension: 10 + 3 = 13 = extension2_quantity = extension_quantity

    # [LOGIC] trade1_quantity + extension1_quantity + extension2_quantity + extension
    # 1st Extension: 4 + 0 + 0 + 6 = 10 (extension1_quantity = 10)

    # 2nd Extension: 4 + 10 + 0 + 3 =
    # 4 + 0 + 6 = 10 => extension_quantity
    # 4 + 10 + 3

    # tp_quantity = sl_quantity = event_data_dto.trade1_quantity + (
    #         extension_quantity * multiplier) + previous_extension_quantity

    tp_quantity = sl_quantity = event_data_dto.extension_quantity + extension_quantity

    if event_data_dto.extension1_quantity is None:
        default_log.debug(f"Updating Extension 1 quantity to {tp_quantity}")
        event_data_dto.extension1_quantity = extension_quantity
    else:
        default_log.debug(f"Updating Extension 2 quantity to {tp_quantity}")
        event_data_dto.extension2_quantity = extension_quantity

    event_data_dto.extension_quantity = tp_quantity

    if extension_trade_order_id is None:
        default_log.debug(
            f"An error has occurred while placing MARKET order for symbol={symbol} and "
            f"event_data_dto={event_data_dto}")

        return event_data_dto, True

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
                return event_data_dto, True

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

            if event_data_dto.trade1_quantity is None:
                default_log.debug(f"[EXTENSION order has been rejected] Setting Trade 1 quantity as 0 as "
                                  f"trade1_quantity={event_data_dto.trade1_quantity}")
                event_data_dto.trade1_quantity = 0

            event_data_dto.extension_quantity = event_data_dto.trade1_quantity if event_data_dto.extension_quantity is None else event_data_dto.extension_quantity

            return event_data_dto, True

        tm.sleep(2)  # sleep for 2 seconds

    default_log.debug(
        f"[EXTENSION] Updating the SL and LIMIT with "
        f"quantity={extension_quantity} for symbol={symbol} "
        f"and tp_quantity={tp_quantity} and sl_quantity={sl_quantity} and "
        f"trade1_quantity={event_data_dto.trade1_quantity}")

    tp_transaction_type = sl_transaction_type = SignalType.SELL if SignalType.BUY else SignalType.BUY

    # if tp and sl trades are not made at all then create one else update the existing TP and SL trades
    if (tp_order_id is None) and (sl_order_id is None):

        # Get the direction that would be used if fill price needs to be subtracted or not
        direction = -1 if signal_type == SignalType.SELL else 1

        # Check whether which extension trade is this and accordingly using the config threshold
        if extension_no == 1:
            default_log.debug(f"[EXTENSION] As it is extension no {extension_no} trade so will be using "
                              f"{extension1_threshold_percent} as threshold percent [EXTENSION 1]")

            extension1_fill_price = event_data_dto.extension1_entry_price
            pseudo_entry_trade_fill_price = extension1_fill_price + (direction * extension1_threshold_percent)
            default_log.debug(
                f"[EXTENSION] Pseudo Entry Trade fill price calculated as={pseudo_entry_trade_fill_price} "
                f"as extension1_fill_price={extension1_fill_price}, direction={direction} and "
                f"extension1_threshold_percent={extension1_threshold_percent}")
        else:
            default_log.debug(f"[EXTENSION] As it is extension no {extension_no} trade so will be using "
                              f"{extension2_threshold_percent} as threshold percent [EXTENSION 2]")

            extension2_fill_price = event_data_dto.extension2_entry_price
            pseudo_entry_trade_fill_price = extension2_fill_price + (direction * extension2_threshold_percent)
            default_log.debug(
                f"[EXTENSION] Pseudo Entry Trade fill price calculated as={pseudo_entry_trade_fill_price} "
                f"as extension2_fill_price={extension2_fill_price}, direction={direction} and "
                f"extension2_threshold_percent={extension2_threshold_percent}")

        # Calculate Stop Loss and Take Profit
        # For take profit use take profit with buffer

        # Do it
        greatest_price = event_data_dto.tp_values[-1].greatest_price
        old_take_profit = event_data_dto.tp_values[-1].tp_with_buffer

        # tp_direction = 1 if signal_type == SignalType.BUY else -1  # +1 if tp order is SELL and -1 if tp is BUY
        take_profit_updated = fill_price + greatest_price

        default_log.debug(f"[EXTENSION] Updating old TP value={old_take_profit} to {take_profit_updated} for "
                          f"MARKET order id={extension_trade_order_id} for symbol={symbol} and "
                          f"indices_symbol={indices_symbol}")

        take_profit_with_buffer = take_profit_updated - (take_profit_updated * buffer_for_tp_trade)

        default_log.debug(f"[EXTENSION] Updating old TP (by adding/subtracting buffer of [{buffer_for_tp_trade}]) "
                          f"value={take_profit_updated} to {take_profit_with_buffer} for "
                          f"MARKET order id={extension_trade_order_id} for symbol={symbol} and "
                          f"indices_symbol={indices_symbol}")

        # Now update the take profit and entry price
        # event_data_dto.tp_values[-1].tp_value = take_profit_updated
        event_data_dto.tp_values[-1].tp_with_buffer = take_profit_with_buffer

        # Now update entry price
        old_entry_price = event_data_dto.entry_price
        new_entry_price = fill_price
        default_log.debug(f"[EXTENSION] Updating old Entry Price of={old_entry_price} to {new_entry_price} "
                          f"for symbol={symbol} and "
                          f"indices_symbol={indices_symbol}")
        event_data_dto.entry_price = new_entry_price

        # if indices_symbol is not None:
        old_sl_value = event_data_dto.sl_value
        new_sl_value = event_data_dto.entry_price + event_data_dto.value_to_add_for_stop_loss_entry_price

        default_log.debug(f"[EXTENSION] Updating old SL Value of={old_sl_value} to {new_sl_value} "
                          f"for symbol={symbol} and "
                          f"indices_symbol={indices_symbol}")
        event_data_dto.sl_value = new_sl_value

        # Create TP and SL trade

        # Adding a buffer of candle length to the stop loss
        default_log.debug(f"[EXTENSION] Adding buffer of {event_data_dto.candle_length} to the stop loss "
                          f"({event_data_dto.sl_value}) = {event_data_dto.sl_value + event_data_dto.candle_length}")
        stop_loss = event_data_dto.sl_value + event_data_dto.candle_length

        # Rounding of STOP LOSS and TAKE PROFIT to its tick size
        # round off the price of stop loss
        formatted_value = round_value(
            symbol=symbol if indices_symbol is None else indices_symbol,
            price=stop_loss,
            exchange="NSE" if indices_symbol is None else "NFO"
        )
        stop_loss = formatted_value

        default_log.debug(f"[EXTENSION] Formatted SL value for symbol={event_data_dto.symbol} and timeframe = "
                          f"{event_data_dto.time_frame} is {stop_loss}")

        take_profit = event_data_dto.tp_values[-1].tp_with_buffer

        # round off the price of take profit
        formatted_value = round_value(
            symbol=symbol if indices_symbol is None else indices_symbol,
            price=take_profit,
            exchange="NSE" if indices_symbol is None else "NFO"
        )

        take_profit = formatted_value

        default_log.debug(f"[EXTENSION] Formatted TP value for symbol={event_data_dto.symbol} and timeframe = "
                          f"{event_data_dto.time_frame} is {take_profit}")

        default_log.debug(f"[EXTENSION] Placing SL order for extension_trade_order_id={extension_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                          f"with quantity={sl_quantity} and stop_loss={stop_loss}"
                          f"exchange={exchange}")

        if sandbox_mode:
            sl_order_id = place_zerodha_order_with_stop_loss(
                kite=kite,
                quantity=sl_quantity,
                transaction_type=sl_transaction_type,
                trading_symbol=symbol,
                stop_loss=stop_loss,
                exchange=exchange
            )
        else:
            sl_order_id = place_zerodha_order_with_stop_loss(
                kite=kite,
                quantity=sl_quantity,
                trading_symbol=symbol,
                transaction_type=sl_transaction_type,
                stop_loss=stop_loss,
                exchange=exchange
            )

        if sl_order_id is None:
            default_log.debug(f"[EXTENSION] An error occurred while placing SL order for "
                              f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                              f"with quantity={sl_quantity} and stop_loss={stop_loss} and "
                              f"indices_symbol={indices_symbol} ")
        else:
            default_log.debug(f"[EXTENSION] Placed SL order with id={sl_order_id} "
                              f"for extension_trade_order_id={extension_trade_order_id} for "
                              f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                              f"with quantity={sl_quantity} and stop_loss={stop_loss}"
                              f"indices_symbol={indices_symbol} and exchange={exchange}")

            event_data_dto.sl_order_id = sl_order_id

        default_log.debug(f"[EXTENSION] Placing TP order for extension_trade_order_id={extension_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                          f"with quantity={tp_quantity} and "
                          f"exchange={exchange}")

        # Update a ZERODHA order with take profit
        if sandbox_mode:
            tp_order_id = place_zerodha_order_with_take_profit(
                kite=kite,
                transaction_type=tp_transaction_type,
                quantity=tp_quantity,
                trading_symbol=symbol,
                take_profit=take_profit,
                exchange=exchange
            )
        else:
            tp_order_id = place_zerodha_order_with_take_profit(
                kite=kite,
                transaction_type=tp_transaction_type,
                quantity=tp_quantity,
                trading_symbol=symbol,
                take_profit=take_profit,
                exchange=exchange
            )

        if tp_order_id is None:
            default_log.debug(f"[EXTENSION] An error occurred while placing TP order for "
                              f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                              f"with quantity={tp_quantity} and take_profit={take_profit} and"
                              f"exchange={exchange}")
        else:
            default_log.debug(f"[EXTENSION] Updated TP order with id={sl_order_id} "
                              f"for extension_trade_order_id={extension_trade_order_id} for "
                              f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
                              f"with quantity={tp_quantity}  and take_profit={take_profit} and "
                              f"indices_symbol={indices_symbol} and exchange={exchange}")

            event_data_dto.tp_order_id = tp_order_id

        return event_data_dto, False

    # Continue with updating TP and SL trade
    default_log.debug(f"[EXTENSION] Updating SL order for extension_trade_order_id={extension_trade_order_id} for "
                      f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                      f"with quantity={sl_quantity} "
                      f"exchange={exchange}")

    # Add stop loss and take profit while updating the SL-M and LIMIT order
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
        default_log.debug(f"[EXTENSION] Updated SL order with id={sl_order_id} "
                          f"for extension_trade_order_id={extension_trade_order_id} for "
                          f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
                          f"with quantity={sl_quantity} "
                          f"indices_symbol={indices_symbol} and exchange={exchange}")

        event_data_dto.sl_order_id = sl_order_id

    default_log.debug(f"[EXTENSION] Updating TP order for extension_trade_order_id={extension_trade_order_id} for "
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

    return event_data_dto, False


def update_zerodha_stop_loss_order(event_data_dto: EventDetailsDTO, indices_symbol: str = None,
                                   candle_high: float = None, candle_low: float = None):
    kite = get_kite_account_api()
    default_log.debug(f"inside update_zerodha_stop_loss_order for symbol={event_data_dto.symbol} "
                      f"and timeframe={event_data_dto.time_frame} and indices_symbol={indices_symbol}"
                      f"and with event_data_dto={event_data_dto} and candle_high={candle_high} and "
                      f"candle_low={candle_low} and stop_loss={event_data_dto.sl_value} and "
                      f"buffer={event_data_dto.candle_length}")

    default_log.debug(f"Updating SL value of symbol={event_data_dto.symbol} and timeframe={event_data_dto.time_frame} "
                      f"from {event_data_dto.sl_value} to {event_data_dto.sl_value + event_data_dto.candle_length} "
                      f"by adding buffer of {event_data_dto.candle_length}")

    sl_value = event_data_dto.sl_value + event_data_dto.candle_length
    symbol = event_data_dto.symbol

    # round off the price of stop loss
    formatted_value = round_value(
        symbol=symbol if indices_symbol is None else indices_symbol,
        price=sl_value,
        exchange="NSE" if indices_symbol is None else "NFO"
    )
    stop_loss = formatted_value

    # event_data_dto.sl_value = stop_loss

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
    kite = get_kite_account_api()
    default_log.debug("inside start_market_logging_for_buy with "
                      f"symbol={symbol}, timeframe={timeframe}, instrument_token={instrument_token} "
                      f"wait_time={wait_time} and configuration={configuration} "
                      f"restart_dto={restart_dto}")

    data_dictionary = {}
    wait_time = 2  # as ticker data is being used now
    use_current_candle = False

    interval = get_interval_from_timeframe(timeframe)

    key = (symbol, timeframe)
    trades_made = 0

    is_restart = False
    extension_diff = None

    sl_order_id = None
    tp_order_id = None
    signal_trade_order_id = None

    tried_creating_entry_order = False
    tried_creating_extension1_order = False
    tried_creating_extension2_order = False

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
        lowest_point = restart_dto.lowest_point

        sl_value = restart_dto.sl_value
        candle_high = restart_dto.candle_high
        candle_low = restart_dto.candle_low
        candle_length = candle_high - candle_low
        adjusted_high = restart_dto.adjusted_high
        adjusted_low = restart_dto.adjusted_low

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
                market_symbol=symbol,
                interval=interval,
                is_restart=True
            )

            event_details_dto = EventDetailsDTO(
                event1_occur_time=event1_occur_time,
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_high=candle_high,
                event1_candle_low=candle_low,
                candle_length=candle_length,
                event2_occur_breakpoint=event2_breakpoint,
                adjusted_high=adjusted_high,
                adjusted_low=adjusted_low,
                stop_tracking_further_events=False
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event1_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

            # event1_candle_high = data.iloc[-1]["high"]
            # event1_candle_low = data.iloc[-1]["low"]

            # event_details_dto.event1_candle_high = event1_candle_high
            # event_details_dto.event1_candle_low = event1_candle_low

            data_dictionary[key] = event_details_dto

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
                candle_length=candle_length,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                highest_point=highest_point,
                lowest_point=lowest_point,
                sl_value=sl_value,
                stop_tracking_further_events=False
            )

            data_dictionary[key] = event_details_dto

            # Fetch the data
            data = get_zerodha_data(
                from_date=event2_occur_time,
                market_symbol=symbol,
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
                market_symbol=symbol,
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

            value_to_add_for_stop_loss_entry_price = (highest_point - lowest_point)

            event_details_dto = EventDetailsDTO(
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_high=candle_high,
                event1_candle_low=candle_low,
                candle_length=candle_length,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                event3_occur_time=event3_occur_time,
                highest_point=highest_point,
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
                extension2_quantity=extension2_quantity,
                value_to_add_for_stop_loss_entry_price=value_to_add_for_stop_loss_entry_price,
                stop_tracking_further_events=False
            )

            data_dictionary[key] = event_details_dto

            # Set the trades made value depending on the extension trade
            trades_made = 0
            if signal_trade_order_id is not None:
                trades_made += 1
                tried_creating_entry_order = True

            if extension1_order_id is not None:
                trades_made += 1
                tried_creating_extension1_order = True

            if extension2_order_id is not None:
                trades_made += 1
                tried_creating_extension2_order = True

            # Start checking the status of the TP and SL order
            if tp_order_id is not None or sl_order_id is not None:
                thread = threading.Thread(target=update_tp_and_sl_status, args=(event_details_dto, data_dictionary))
                thread.start()
    else:
        # Not restarted flow
        tm.sleep(wait_time)
        current_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))

        # Fetch candle data
        data = get_zerodha_data(
            instrument_token=instrument_token,
            market_symbol=symbol,
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

    sl_got_extended = False

    initial_close_price = None

    indices_quantity_multiplier = 50 if symbol == "NIFTY" else 45

    while True:
        # defining loss budget
        loss_budget = fetch_symbol_budget(symbol, timeframe)

        timestamp = data.iloc[-1]['time']
        if prev_timestamp is None:
            prev_timestamp = timestamp

        # This Flow skips first Candle
        # if not is_restart:
        #     if not use_current_candle:  # use_current_candle = True and is_restart = False (not True and not False) => False and True => False
        #         if current_time is None:
        #             current_time = data.iloc[-1]["time"]
        #
        #         next_time = data.iloc[-1]["time"]
        #         default_log.debug(f"Current Time ({current_time}) and Next Time ({next_time}) for symbol={symbol} "
        #                           f"having timeframe={timeframe}")
        #         # next_time = 13:55
        #         # current_time = 13:50
        #         # 55 <= 50 False
        #         if next_time.minute <= current_time.minute:
        #             data = get_next_data(
        #                 is_restart=is_restart,
        #                 timeframe=timeframe,
        #                 instrument_token=instrument_token,
        #                 interval=interval,
        #                 from_timestamp=data.iloc[-1]["time"]
        #             )
        #
        #             if data is None:
        #                 default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                                   f"and timeframe={timeframe}")
        #                 break
        #             continue
        #         else:
        #             use_current_candle = True
        #
        #             data = get_next_data(
        #                 is_restart=is_restart,
        #                 timeframe=timeframe,
        #                 instrument_token=instrument_token,
        #                 interval=interval,
        #                 from_timestamp=data.iloc[-1]["time"]
        #             )
        #
        #             if data is None:
        #                 default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                                   f"and timeframe={timeframe}")
        #                 break
        #             continue

        dto, data_dictionary = trade_logic_sell(symbol, timeframe, data.iloc[-1], data_dictionary)
        dto.current_candle_low = data.iloc[-1]["low"]
        dto.current_candle_high = data.iloc[-1]["high"]

        # Adding a check of if stop_tracking_further_events is True then break out and mark thread as completed
        if dto.stop_tracking_further_events:
            default_log.debug(f"Stopping tracking of further events for symbol={symbol} having timeframe={timeframe} "
                              f"as stop_tracking_further_events={dto.stop_tracking_further_events}")
            break

        # This part prevents the thread_details to be committed till next candle (after event 1) is formed
        # Commented it out
        # if timestamp.hour < dto.event1_occur_time.hour or \
        #         (timestamp.hour == dto.event1_occur_time.hour and
        #          timestamp.minute <= dto.event1_occur_time.minute):
        #     default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
        #                       f"({dto.event1_occur_time}) for symbol={dto.symbol} and "
        #                       f"time_frame={dto.time_frame}")
        #
        #     data = get_next_data(
        #         is_restart=is_restart,
        #         timeframe=timeframe,
        #         instrument_token=instrument_token,
        #         interval=interval,
        #         from_timestamp=data.iloc[-1]["time"]
        #     )
        #
        #     if data is None:
        #         default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                           f"and timeframe={timeframe}")
        #         break
        #
        #     continue

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
                    from_timestamp=data.iloc[-1]["time"]
                )

                if data is None:
                    default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                                      f"and timeframe={timeframe}")
                    break

                continue

        if dto.event3_occur_time is None:
            if candles_checked > no_of_candles_to_consider:
                if (dto.event2_occur_time is None) and (dto.event3_occur_time is None):
                    default_log.debug(f"Event 2 not occurred for symbol={symbol} having timeframe={timeframe} "
                                      f"as checked {no_of_candles_to_consider} candles for the event 2 so stopping "
                                      f"tracking of further events")
                    data_not_found = True
                    break
                elif (dto.event2_occur_time is not None) \
                        and (dto.event3_occur_time is None):
                    default_log.debug(f"Event 3 not occurred for symbol={symbol} having timeframe={timeframe} "
                                      f"as checked {no_of_candles_to_consider} candles after event 2"
                                      f"for the event 3 so stopping tracking of further events")
                    data_not_found = True
                    break
                else:
                    candles_checked = 0
            else:
                default_log.debug(f"Candles Checked ({candles_checked}) is not greater than No of candle to "
                                  f"consider ({no_of_candles_to_consider})")
                if prev_timestamp.hour < timestamp.hour or \
                        (prev_timestamp.hour == timestamp.hour and
                         prev_timestamp.minute <= timestamp.minute):
                    default_log.debug(f"Previous Timestamp ({prev_timestamp}) is earlier than Current Timestamp "
                                      f"({timestamp}) for symbol={dto.symbol} and "
                                      f"time_frame={dto.time_frame}")

                    if prev_timestamp.hour == timestamp.hour:
                        time_difference = abs(int(prev_timestamp.minute - timestamp.minute))
                    else:
                        time_difference = abs(int((60 - prev_timestamp.minute) - timestamp.minute))

                    if time_difference >= int(timeframe):
                        default_log.debug(f"Time difference ({time_difference}) >= Timeframe ({int(timeframe)})")
                        prev_timestamp = timestamp
                        candles_checked += 1
                else:
                    default_log.debug(f"Previous Timestamp ({prev_timestamp}) is not earlier than "
                                      f"Current Timestamp ({timestamp}) for symbol={symbol} and time_frame={timeframe}")
                    candles_checked += 1
                    prev_timestamp = timestamp

        if (dto.event2_occur_time is not None) and (dto.event3_occur_time is not None):

            # find out how many trades needs to be made and the budget to be used
            # get the initial close price
            if initial_close_price is None:
                initial_close_price = data.iloc[-1]["close"]

            # if trades_details_dto is None:

            close_price = initial_close_price
            trades_details_dto = get_budget_and_no_of_trade_details(
                budget=loss_budget,
                close_price=close_price,
                dto=dto
            )

            default_log.debug(f"Budget and Trade details retrieved for symbol={symbol} "
                              f"and time_frame={dto.time_frame} having close_price={close_price}: "
                              f"{trades_details_dto}")

            if (not trades_details_dto.trades_to_make.entry_trade) and \
                    (not trades_details_dto.trades_to_make.extension1_trade) and \
                    (not trades_details_dto.trades_to_make.extension2_trade):
                default_log.debug(f"No TRADES are to be made for symbol={symbol} and time_frame={timeframe}")
                break

            # Find out how many trades would be made
            maximum_trades_to_make = 0
            if trades_details_dto.trades_to_make.entry_trade:
                default_log.debug(f"Make Entry Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
            else:
                # if first trade should not be made then increment trades_made by 1 (for checking of condition of
                # extension 1 and extension 2 trade)
                tried_creating_entry_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension1_trade:
                default_log.debug(f"Make Extension 1 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
            else:
                tried_creating_extension1_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension2_trade:
                default_log.debug(f"Make Extension 2 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1

            if symbol in indices_list:
                # Getting the indices symbol for the index symbol
                default_log.debug(f"Getting indices symbol as trading symbol={symbol} is in "
                                  f"indices_list={indices_list} with entry price={entry_price} ")

                if indices_symbol is None:
                    default_log.debug(f"Getting indices symbol for symbol={symbol}, price={dto.entry_price} "
                                      f"and for transaction_type={SignalType.SELL}")
                    indices_symbol = get_indices_symbol_for_trade(trading_symbol=symbol, price=dto.entry_price,
                                                                  transaction_type=SignalType.SELL)

                    if indices_symbol is None:
                        default_log.debug(
                            f"Cannot find indices symbol for symbol={symbol} and time_frame={timeframe} with "
                            f"transaction_type={SignalType.SELL}")
                        break

                    default_log.debug(f"Indices symbol retrieved={indices_symbol}")

            if indices_symbol is not None:
                candle_high = data.iloc[-1]["high"]
                candle_low = data.iloc[-1]["low"]

                default_log.debug(f"Indices symbol ({indices_symbol}) is present so only will place MARKET orders and "
                                  f"not LIMIT and SL-M orders with current_candle_high={candle_high} and "
                                  f"current_candle_low={candle_low}")

                # Placing the entry MARKET order trade
                if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
                        not tried_creating_entry_order:

                    # Calculate trade 1 quantity
                    entry_sl_value = dto.sl_value
                    entry_price = dto.entry_price
                    loss_percent = loss_budget * trade1_loss_percent

                    default_log.debug(f"[For indices_symbol={indices_symbol}] Entry Price={entry_price} and "
                                      f"Entry SL value={entry_sl_value}")

                    trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
                    trade1_quantity = int(round(trade1_quantity, 0))

                    default_log.debug(f"Rounding off trade1_quantity ({trade1_quantity}) to the "
                                      f"indices_quantity_multiplier ({indices_quantity_multiplier}) for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                    trade1_quantity = round_to_nearest_multiplier(trade1_quantity,
                                                                  indices_quantity_multiplier)

                    default_log.debug(f"After rounding off trade1_quantity to {trade1_quantity} using "
                                      f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
                    make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                    if (trade1_quantity > 0) and (
                            (trade1_quantity % indices_quantity_multiplier) != 0) and make_entry_trade:
                        default_log.debug(
                            f"As trade1_quantity ({trade1_quantity}) is not divisible by indices_quantity_"
                            f"multiplier ({indices_quantity_multiplier}) so skipping placing MARKET "
                            f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
                            f"timeframe={timeframe}")
                        dto.trade1_quantity = trade1_quantity
                        tried_creating_entry_order = True
                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'
                    else:
                        quantity = trade1_quantity
                        # quantity = 50 if symbol == "NIFTY" else 45
                        entry_trade_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.BUY,
                            quantity=quantity
                        )

                        tried_creating_entry_order = True

                        if entry_trade_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")
                        else:
                            dto.entry_trade_order_id = entry_trade_order_id

                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'

                        dto.trade1_quantity = quantity

                if dto.entry_trade_order_id or dto.extension1_trade_order_id or dto.extension2_trade_order_id:
                    # Check TP hit or not only if order has been placed
                    tp_value = dto.tp_values[-1].tp_value
                    sl_value = dto.sl_value + dto.candle_length  # added buffer

                    quantity = dto.extension_quantity if dto.extension_quantity is not None else dto.trade1_quantity

                    if candle_low <= tp_value:
                        default_log.debug(f"Current Candle Low ({candle_low}) <= TP value ({tp_value}) for indices_"
                                          f"symbol={indices_symbol} and time_frame={timeframe}. So placing MARKET order "
                                          f"with quantity={quantity} and signal_type={SignalType.BUY}")

                        tp_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity
                        )

                        if tp_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (LIMIT) MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")

                        dto.tp_order_id = tp_order_id
                        dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.tp_hit = True
                        data_not_found = False
                        dto.tp_order_status = 'COMPLETE'
                        break

                    # Check SL hit or not
                    elif candle_high >= sl_value:
                        default_log.debug(
                            f"Current Candle High ({candle_high}) >= SL value ({sl_value}) for indices_symbol="
                            f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
                            f"quantity={quantity} and signal_type={SignalType.BUY}")

                        sl_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity
                        )

                        if sl_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (SL-M) MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")

                        dto.sl_order_id = sl_order_id
                        dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.sl_hit = True
                        data_not_found = False
                        dto.sl_order_status = 'COMPLETE'
                        break

            default_log.debug(f"Storing SL value of symbol={symbol}, timeframe={timeframe}, "
                              f"signal_type={SignalType.SELL} having stop_loss={dto.sl_value}")

            store_sl_details_of_active_trade(
                symbol=symbol,
                signal_type=SignalType.BUY,
                stop_loss=dto.sl_value,
                time_frame=int(timeframe)
            )

            if extension_diff is None:
                default_log.debug(f"Extension Difference = Entry Price ({dto.entry_price}) - SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
                    (indices_symbol is None) and not tried_creating_entry_order:
                # Check the SL increase condition
                entry_price = dto.entry_price

                event_data_dto, error_occurred = place_initial_zerodha_trades(
                    event_data_dto=dto,
                    data_dictionary=data_dictionary,
                    signal_type=SignalType.SELL,
                    candle_data=data.iloc[-1],
                    symbol=symbol,
                    loss_budget=loss_budget,
                    indices_symbol=indices_symbol
                )

                if error_occurred:
                    default_log.debug(f"An error occurred while placing MARKET order for symbol={symbol} and "
                                      f"indices_symbol={indices_symbol} and event_data_dto={dto}")

                tried_creating_entry_order = True
                dto = event_data_dto
                trades_made += 1

                # Updating the extension difference
                default_log.debug(f"[UPDATING] Extension Difference = Entry Price ({dto.entry_price}) - "
                                  f"SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if not trades_details_dto.trades_to_make.entry_trade:
                dto.trade1_quantity = 0

            if (dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.tp_order_id is not None) and \
                    (indices_symbol is None):
                take_profit = dto.tp_values[-1].tp_with_buffer

                # round off the price of take profit
                formatted_value = round_value(
                    symbol=symbol if indices_symbol is None else indices_symbol,
                    price=take_profit,
                    exchange="NSE" if indices_symbol is None else "NFO"
                )
                take_profit = formatted_value

                # dto.tp_values[-1].tp_value = take_profit
                dto.tp_values[-1].tp_with_buffer = take_profit
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

                # Condition 1 [EXTENSION OF SL]
                # Check the SL increase condition
                entry_price = dto.entry_price
                current_candle_high = data.iloc[-1]["high"]
                current_candle_close = data.iloc[-1]["close"]

                # Check for condition of entry price
                # if ((entry_price + ((dto.sl_value - entry_price) / 2)) <= current_candle_high) and not sl_got_extended:
                #     default_log.debug(f"[EXTENSION OF SL] For symbol={symbol} and time_frame={dto.time_frame} "
                #                       f"Entry Price ({entry_price}) + [[SL value ({dto.sl_value}) - "
                #                       f"Entry Price ({entry_price})] / 2] "
                #                       f"<= Current Candle High ({current_candle_high})")

                do_update, stop_loss_to_update_to = do_update_of_sl_values(
                    timeframe=int(dto.time_frame),
                    signal_type=SignalType.BUY,
                    symbol=symbol,
                    entry_price=entry_price,
                    close_price=current_candle_close
                )

                if do_update and not sl_got_extended:
                    default_log.debug(f"[EXTENSION OF SL] Updating stop loss of symbol={symbol} with "
                                      f"time_frame={dto.time_frame} and "
                                      f"event1_candle signal_type={SignalType.BUY} from {dto.sl_value} to "
                                      f"{stop_loss_to_update_to}")

                    dto.sl_value = stop_loss_to_update_to
                    sl_got_extended = True

                    if indices_symbol is None:
                        # Only updating SL order when indices symbol is None
                        # as for indices symbol SL-M order is not placed
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

                # Condition 2
                # Check condition of updating Stop Loss according to average price
                average_entry_price = dto.entry_price
                if dto.extension1_trade_order_id is not None:
                    average_entry_price = (dto.entry_price + dto.extension1_entry_price) / 2

                if dto.extension2_trade_order_id is not None:
                    average_entry_price = (
                                                      dto.entry_price + dto.extension1_entry_price + dto.extension2_entry_price) / 3

                current_candle_close = data.iloc[-1]["close"]

                if (average_entry_price - current_candle_close) > ((dto.sl_value - average_entry_price) * 0.8):
                    default_log.debug(f"Satisfied condition for updating SL according to average entry price as "
                                      f"[Average Entry Price ({average_entry_price}) - Current Candle close "
                                      f"({current_candle_close})] > "
                                      f"[SL value ({dto.sl_value}) - Average Entry Price ({average_entry_price})] * 0.8")
                    dto.sl_value = average_entry_price

                    if indices_symbol is None:
                        # Only updating SL order when indices symbol is None
                        # as for indices symbol SL-M order is not placed
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
            if (extension_diff is not None) and (trades_made < maximum_trades_to_make) and \
                    ((dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])
                     and (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])) and \
                    (trades_details_dto.trades_to_make.extension1_trade or
                     trades_details_dto.trades_to_make.extension2_trade):

                default_log.debug(f"Extension Diff={extension_diff}, trades_made={trades_made}, "
                                  f"TP Order status={dto.tp_order_status} with id={dto.tp_order_id} and "
                                  f"SL Order status={dto.sl_order_status} with id={dto.sl_order_id} ")

                extension_time_stamp = data.iloc[-1]["time"]
                candle_high_price = data.iloc[-1]["high"]

                default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                  f"and candle_high_price = {candle_high_price} at timestamp = {extension_time_stamp}")

                entry_price_difference = abs(dto.sl_value - candle_high_price)

                if tried_creating_extension1_order and trades_details_dto.trades_to_make.extension1_trade:
                    default_log.debug(f"Extension 1 trade has been made as Extension 1 Trade order id="
                                      f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                                      f"{tried_creating_extension1_order} and Make extension 1 trade status="
                                      f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 2 "
                                      f"trade threshold percent={extension2_threshold_percent}")
                    threshold_percent = extension2_threshold_percent
                else:
                    default_log.debug(f"Extension 1 trade has not been made as Extension 1 Trade order id="
                                      f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                                      f"{tried_creating_extension1_order} and Make extension 1 trade status="
                                      f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 1 "
                                      f"trade threshold percent={extension1_threshold_percent}")
                    threshold_percent = extension1_threshold_percent

                # threshold = extension_diff * (config_threshold_percent * trades_made)
                threshold = extension_diff * threshold_percent

                default_log.debug(
                    f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                    f"at timestamp = {extension_time_stamp} and "
                    f"candle_high_price={candle_high_price} ")

                if entry_price_difference >= threshold:
                    default_log.debug(
                        f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
                        f"and SL value = {dto.sl_value} "
                        f"and candle_high_price = {candle_high_price} "
                        f"at timestamp = {extension_time_stamp} "
                        f"Entry Price Difference {entry_price_difference} >= "
                        f"Threshold {threshold}")

                    # If first extension trade is already done placing second extension trade
                    if (trades_made == 2) and tried_creating_extension1_order and (not tried_creating_extension2_order):
                        # If first two trades were placed then check if third trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension2_trade:
                            tried_creating_extension2_order = True
                            loss_percent = loss_budget * trade3_loss_percent
                            # loss_percent = trade3_loss_percent
                            default_log.debug(
                                f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference

                            if indices_symbol is not None:

                                total_quantity = extension_quantity
                                make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                                make_extension1_trade = trades_details_dto.trades_to_make.extension1_trade

                                dto.extension2_quantity = int(round(total_quantity, 0))
                                if (dto.entry_trade_order_id is None) and make_entry_trade:
                                    total_quantity += dto.trade1_quantity
                                if (dto.extension1_trade_order_id is None) and make_extension1_trade:
                                    total_quantity += dto.extension1_quantity if dto.extension1_quantity is not None else 0

                                total_quantity = int(round(total_quantity, 0))
                                default_log.debug(
                                    f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
                                    f"indices_quantity_multiplier ({indices_quantity_multiplier}) for "
                                    f"symbol={symbol}"
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                total_quantity = round_to_nearest_multiplier(total_quantity,
                                                                             indices_quantity_multiplier)

                                default_log.debug(
                                    f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
                                    f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0):
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 2 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier})")
                                    dto.extension_quantity = total_quantity
                                else:
                                    default_log.debug(
                                        f"Creating EXTENSION indices MARKET order with quantity=50 for "
                                        f"indices_symbol={indices_symbol} and time_frame={timeframe}")

                                    if dto.extension_quantity is None:
                                        dto.extension_quantity = 0

                                    extension2_quantity = total_quantity
                                    extension_quantity_for_indices_symbol = dto.extension_quantity + extension2_quantity

                                    extension_order_id = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=extension_quantity_for_indices_symbol,
                                        entry_price=dto.entry_price
                                    )

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION MARKET order for symbol={indices_symbol} and "
                                            f"and event_data_dto={dto} and extension2_quantity={extension2_quantity}"
                                            f"extension_quantity={extension_quantity_for_indices_symbol} "
                                            f"and trade1_quantity={dto.trade1_quantity}")
                                    else:
                                        dto.extension2_trade_order_id = extension_order_id

                                    # dto.extension2_quantity = extension2_quantity
                                    dto.extension_quantity = extension_quantity_for_indices_symbol
                                    trades_made += 1

                                # Mark TP and SL order status as OPEN as TP and SL order won't be placed for
                                # indices trade
                                dto.tp_order_status = 'OPEN'
                                dto.sl_order_status = 'OPEN'

                            else:
                                event_data_dto, error_occurred = place_extension_zerodha_trades(
                                    event_data_dto=dto,
                                    signal_type=SignalType.BUY,
                                    candle_data=data.iloc[-1],
                                    extension_quantity=extension_quantity if indices_symbol is None else 50,
                                    symbol=symbol,
                                    indices_symbol=indices_symbol,
                                    multiplier=trades_made,
                                    extension_no=2,
                                    exchange="NSE" if indices_symbol is None else "NFO"
                                )

                                if error_occurred:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} "
                                        f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
                                        f"extension_quantity={extension_quantity} and "
                                        f"trade1_quantity={dto.trade1_quantity}")

                                trades_made += 1
                                dto = event_data_dto
                        else:
                            default_log.debug(
                                f"[EXTENSION] Not placing Extension 2 trade has extension 2 trade "
                                f"condition is {trades_details_dto.trades_to_make.extension2_trade}")

                    # Making Extension 1 trade
                    elif tried_creating_entry_order and (not tried_creating_extension1_order):
                        # If first trade was placed then check if second trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension1_trade:
                            tried_creating_extension1_order = True
                            loss_percent = loss_budget * trade2_loss_percent
                            # loss_percent = trade2_loss_percent
                            default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference

                            if indices_symbol is not None:

                                total_quantity = extension_quantity
                                make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                                make_extension2_trade = trades_details_dto.trades_to_make.extension2_trade

                                dto.extension1_quantity = int(round(total_quantity, 0))
                                if (dto.entry_trade_order_id is None) and make_entry_trade:
                                    total_quantity += dto.trade1_quantity

                                total_quantity = int(round(total_quantity, 0))
                                default_log.debug(
                                    f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
                                    f"indices_quantity_multiplier ({indices_quantity_multiplier}) "
                                    f"for symbol={symbol} and indices_symbol={indices_symbol} "
                                    f"having time_frame={timeframe}")

                                total_quantity = round_to_nearest_multiplier(total_quantity,
                                                                             indices_quantity_multiplier)

                                default_log.debug(
                                    f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
                                    f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0):
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier}). "
                                        f"Also extension 2 trade won't be made as make_extension2_trade="
                                        f"{make_extension2_trade}")

                                    dto.extension_quantity = total_quantity

                                    if not make_extension2_trade:
                                        default_log.debug(f"Not making Extension 2 trade as make_extension2_trade="
                                                          f"{make_extension2_trade} and quantity ({total_quantity}) is "
                                                          f"not a multiplier of {indices_quantity_multiplier}")
                                        break
                                else:
                                    default_log.debug(
                                        f"Creating EXTENSION indices MARKET order with quantity=50 for "
                                        f"indices_symbol={indices_symbol} and time_frame={timeframe}")

                                    if dto.extension_quantity is None:
                                        dto.extension_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0

                                    extension1_quantity = total_quantity

                                    extension_quantity_for_indices_symbol = dto.extension_quantity + extension1_quantity

                                    extension_order_id = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=extension_quantity_for_indices_symbol,
                                        entry_price=dto.entry_price
                                    )

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION MARKET order for symbol={indices_symbol} and "
                                            f"and event_data_dto={dto} and "
                                            f"extension_quantity={extension_quantity_for_indices_symbol} "
                                            f"and trade1_quantity={dto.trade1_quantity}")
                                    else:
                                        dto.extension1_trade_order_id = extension_order_id

                                    trades_made += 1
                                    dto.extension1_quantity = extension1_quantity
                                    dto.extension_quantity = extension_quantity_for_indices_symbol

                                dto.sl_order_status = 'OPEN'
                                dto.tp_order_status = 'OPEN'

                            else:
                                event_data_dto, error_occurred = place_extension_zerodha_trades(
                                    event_data_dto=dto,
                                    signal_type=SignalType.SELL,
                                    candle_data=data.iloc[-1],
                                    extension_quantity=extension_quantity if indices_symbol is None else 50,
                                    symbol=symbol,
                                    indices_symbol=indices_symbol,
                                    multiplier=trades_made,
                                    extension_no=1,
                                    exchange="NSE" if indices_symbol is None else "NFO"
                                )

                                tried_creating_extension1_order = True

                                if error_occurred:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} "
                                        f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
                                        f"extension_quantity={extension_quantity} and "
                                        f"trade1_quantity={dto.trade1_quantity}")

                                dto = event_data_dto
                                trades_made += 1
                        else:
                            default_log.debug(
                                f"[EXTENSION] Not placing Extension 1 trade has extension 1 trade "
                                f"condition is {trades_details_dto.trades_to_make.extension1_trade}")
                else:
                    default_log.debug(
                        f"Extension Trade condition not met as values: extension_diff={extension_diff} "
                        f"trades_made={trades_made}, threshold_percent={threshold_percent} "
                        f"entry_price={entry_price} and sl_value={dto.sl_value} "
                        f"and entry_price_difference: {entry_price_difference} < threshold: {threshold} "
                        f"and symbol={symbol} and indices_symbol={indices_symbol} and "
                        f"Make Extension 1 trade={trades_details_dto.trades_to_make.extension1_trade} "
                        f"and Make Extension 2 trade={trades_details_dto.trades_to_make.extension2_trade} ")

            # Extra Trade placing logic
            # Place extra trade if candle high goes ABOVE by a threshold value

            # Ententions would be checked only if TP and SL order not completed
            # if (extension_diff is not None) and (trades_made < maximum_trades_to_make) and \
            #         ((dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])
            #          and (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])) and \
            #         (trades_details_dto.trades_to_make.extension1_trade or
            #          trades_details_dto.trades_to_make.extension2_trade):
            #
            #     default_log.debug(f"Extension Diff={extension_diff}, trades_made={trades_made}, "
            #                       f"TP Order status={dto.tp_order_status} with id={dto.tp_order_id} and "
            #                       f"SL Order status={dto.sl_order_status} with id={dto.sl_order_id} ")
            #
            #     # threshold = extension_diff * (1 + (config_threshold_percent * trades_made))
            #
            #     extension_time_stamp = data.iloc[-1]["time"]
            #     candle_high_price = data.iloc[-1]["high"]
            #
            #     default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
            #                       f"and candle_high_price = {candle_high_price} at timestamp = {extension_time_stamp}")
            #
            #     entry_price_difference = abs(dto.sl_value - candle_high_price)
            #
            #     if tried_creating_extension1_order and trades_details_dto.trades_to_make.extension1_trade:
            #         default_log.debug(f"Extension 1 trade has been made as Extension 1 Trade order id="
            #                           f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
            #                           f"{tried_creating_extension1_order} and Make extension 1 trade status="
            #                           f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 2 "
            #                           f"trade threshold percent={extension2_threshold_percent}")
            #         threshold_percent = extension2_threshold_percent
            #     else:
            #         default_log.debug(f"Extension 1 trade has not been made as Extension 1 Trade order id="
            #                           f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
            #                           f"{tried_creating_extension1_order} and Make extension 1 trade status="
            #                           f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 1 "
            #                           f"trade threshold percent={extension1_threshold_percent}")
            #         threshold_percent = extension1_threshold_percent
            #
            #     # threshold = extension_diff * (config_threshold_percent * trades_made)
            #     threshold = extension_diff * threshold_percent
            #
            #     # If second trade is already done
            #     if trades_made == 2:
            #         if trades_details_dto.trades_to_make.extension2_trade:
            #             loss_percent = loss_budget * trade3_loss_percent
            #             default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")
            #
            #             extension_quantity = loss_percent / entry_price_difference
            #             default_log.debug(
            #                 f"Extension quantity = Loss percent ({loss_percent}) / "
            #                 f"Entry Price Difference ({entry_price_difference})")
            #
            #             if entry_price_difference >= threshold:
            #                 tried_creating_extension2_order = True
            #                 default_log.debug(
            #                     f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
            #                     f"and SL value = {dto.sl_value} and candle_high_price={candle_high_price} "
            #                     f"at timestamp = {extension_time_stamp} "
            #                     f"Entry Price Difference {entry_price_difference} >= "
            #                     f"Threshold {threshold} with extension_quantity={extension_quantity}")
            #
            #                 if indices_symbol is not None:
            #
            #                     total_quantity = extension_quantity
            #                     make_entry_trade = trades_details_dto.trades_to_make.entry_trade
            #                     make_extension1_trade = trades_details_dto.trades_to_make.extension1_trade
            #
            #                     if (dto.entry_trade_order_id is None) and make_entry_trade:
            #                         total_quantity += dto.trade1_quantity
            #                     if (dto.extension1_trade_order_id is None) and make_extension1_trade:
            #                         total_quantity += dto.extension1_quantity if dto.extension1_quantity is not None else 0
            #
            #                     total_quantity = int(round(total_quantity, 0))
            #                     default_log.debug(f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
            #                                       f"indices_quantity_multiplier ({indices_quantity_multiplier}) for "
            #                                       f"symbol={symbol} and indices_symbol={indices_symbol} "
            #                                       f"having time_frame={timeframe}")
            #
            #                     total_quantity = round_to_nearest_multiplier(total_quantity,
            #                                                                  indices_quantity_multiplier)
            #
            #                     default_log.debug(
            #                         f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
            #                         f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
            #                         f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
            #
            #                     if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0):
            #                         default_log.debug(
            #                             f"Avoiding placing EXTENSION 2 indices trade for symbol={symbol}, "
            #                             f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
            #                             f"the total_quantity ({total_quantity}) is not divisible by "
            #                             f"indices_quantity_multiplier ({indices_quantity_multiplier})")
            #
            #                     default_log.debug(f"Creating EXTENSION 2 indices MARKET order with "
            #                                       f"quantity={total_quantity} for "
            #                                       f"indices_symbol={indices_symbol} and time_frame={timeframe}")
            #
            #                     if dto.extension_quantity is None:
            #                         dto.extension_quantity = 0
            #
            #                     extension2_quantity = total_quantity
            #
            #                     extension_quantity_for_indices_symbol = dto.extension_quantity + extension2_quantity
            #
            #                     extension_order_id = place_indices_market_order(
            #                         indice_symbol=indices_symbol,
            #                         signal_type=SignalType.BUY,
            #                         quantity=extension_quantity_for_indices_symbol
            #                     )
            #
            #                     if extension_order_id is None:
            #                         default_log.debug(
            #                             f"An error occurred while placing EXTENSION MARKET order for "
            #                             f"symbol={indices_symbol} and event_data_dto={dto} and "
            #                             f"extension_quantity={extension_quantity_for_indices_symbol} "
            #                             f"and trade1_quantity={dto.trade1_quantity} and "
            #                             f"extension2_quantity={extension2_quantity}")
            #
            #                         return None
            #
            #                     dto.extension2_trade_order_id = extension_order_id
            #                     dto.extension_quantity = extension_quantity_for_indices_symbol
            #                     dto.extension2_quantity = extension2_quantity
            #                     dto.tp_order_status = 'OPEN'
            #                     dto.sl_order_status = 'OPEN'
            #                     trades_made += 1
            #                 else:
            #                     event_data_dto, error_occurred = place_extension_zerodha_trades(
            #                         event_data_dto=dto,
            #                         signal_type=SignalType.SELL,
            #                         candle_data=data.iloc[-1],
            #                         extension_quantity=extension_quantity if indices_symbol is None else 50,
            #                         symbol=symbol,
            #                         indices_symbol=indices_symbol,
            #                         multiplier=trades_made,
            #                         exchange="NSE" if indices_symbol is None else "NFO"
            #                     )
            #
            #                     if error_occurred:
            #                         default_log.debug(
            #                             f"An error occurred while placing EXTENSION 2 MARKET order for symbol={symbol} "
            #                             f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
            #                             f"extension_quantity={extension_quantity} and "
            #                             f"trade1_quantity={dto.trade1_quantity}")
            #
            #                         return None
            #
            #                     dto = event_data_dto
            #                     trades_made += 1
            #             else:
            #                 default_log.debug(f"[EXTENSION] Not placing Extension 2 trade has extension 2 trade making "
            #                                   f"condition is {trades_details_dto.trades_to_make.extension2_trade}")
            #
            #     # If only first trade is made so try making extension 1 trade
            #     else:
            #         if trades_details_dto.trades_to_make.extension1_trade:
            #             loss_percent = loss_budget * trade2_loss_percent
            #             default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")
            #
            #             extension_quantity = loss_percent / entry_price_difference
            #             default_log.debug(
            #                 f"Extension quantity = Loss percent ({loss_percent}) / "
            #                 f"Entry Price Difference ({entry_price_difference})")
            #
            #             if (entry_price_difference >= threshold) and not tried_creating_extension1_order:
            #                 tried_creating_extension1_order = True
            #                 default_log.debug(
            #                     f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
            #                     f"and SL value = {dto.sl_value} and candle_high_price={candle_high_price} "
            #                     f"at timestamp = {extension_time_stamp} "
            #                     f"Entry Price Difference {entry_price_difference} >= "
            #                     f"Threshold {threshold} with extension_quantity={extension_quantity} and "
            #                     f"tried_creating_extension1_order={tried_creating_extension1_order}")
            #
            #                 if indices_symbol is not None:
            #
            #                     total_quantity = extension_quantity
            #                     make_entry_trade = trades_details_dto.trades_to_make.entry_trade
            #                     make_extension2_trade = trades_details_dto.trades_to_make.extension2_trade
            #
            #                     if (dto.entry_trade_order_id is None) and make_entry_trade:
            #                         total_quantity += dto.trade1_quantity
            #
            #                     total_quantity = int(round(total_quantity, 0))
            #                     default_log.debug(f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
            #                                       f"indices_quantity_multiplier ({indices_quantity_multiplier}) for symbol={symbol} "
            #                                       f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
            #
            #                     total_quantity = round_to_nearest_multiplier(total_quantity,
            #                                                                  indices_quantity_multiplier)
            #
            #                     default_log.debug(
            #                         f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
            #                         f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
            #                         f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
            #
            #                     if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0) and \
            #                             not make_extension2_trade:
            #                         default_log.debug(
            #                             f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
            #                             f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
            #                             f"the total_quantity ({total_quantity}) is not divisible by "
            #                             f"indices_quantity_multiplier ({indices_quantity_multiplier}). "
            #                             f"Also extension 2 trade won't be made as make_extension2_trade="
            #                             f"{make_extension2_trade}")
            #
            #                     default_log.debug(f"Creating EXTENSION indices MARKET order with quantity=50 for "
            #                                       f"indices_symbol={indices_symbol} and time_frame={timeframe}")
            #
            #                     dto.extension_quantity = dto.trade1_quantity
            #                     extension1_quantity = total_quantity
            #
            #                     extension_quantity_for_indices_symbol = dto.extension_quantity + extension1_quantity
            #
            #                     extension_order_id = place_indices_market_order(
            #                         indice_symbol=indices_symbol,
            #                         signal_type=SignalType.BUY,
            #                         quantity=extension_quantity_for_indices_symbol,
            #                         entry_price=dto.entry_price
            #                     )
            #
            #                     tried_creating_extension1_order = True
            #
            #                     if extension_order_id is None:
            #                         default_log.debug(
            #                             f"An error occurred while placing EXTENSION MARKET order for symbol={indices_symbol} and "
            #                             f"and event_data_dto={dto} and extension1_quantity={extension1_quantity}"
            #                             f"extension_quantity={extension_quantity} and trade1_quantity={dto.trade1_quantity}")
            #                     else:
            #                         dto.extension1_trade_order_id = extension_order_id
            #                         dto.tp_order_status = 'OPEN'
            #                         dto.sl_order_status = 'OPEN'
            #
            #                     dto.extension_quantity = extension_quantity_for_indices_symbol
            #                     dto.extension1_quantity = extension1_quantity
            #                     trades_made += 1
            #                 else:
            #                     event_data_dto, error_occurred = place_extension_zerodha_trades(
            #                         event_data_dto=dto,
            #                         signal_type=SignalType.SELL,
            #                         candle_data=data.iloc[-1],
            #                         extension_quantity=extension_quantity if indices_symbol is None else 50,
            #                         symbol=symbol,
            #                         indices_symbol=indices_symbol,
            #                         multiplier=trades_made,
            #                         exchange="NSE" if indices_symbol is None else "NFO"
            #                     )
            #                     tried_creating_extension1_order = True
            #                     if error_occurred:
            #                         default_log.debug(
            #                             f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} and "
            #                             f"indices_symbol={indices_symbol} and event_data_dto={dto} and "
            #                             f"extension_quantity={extension_quantity} and trade1_quantity={dto.trade1_quantity}")
            #
            #                     dto = event_data_dto
            #                     trades_made += 1
            #             else:
            #                 default_log.debug(f"[EXTENSION] Not placing Extension 1 trade has extension 1 trade "
            #                                   f"condition is {trades_details_dto.trades_to_make.extension1_trade}. "
            #                                   f"Entry Price Difference={entry_price_difference} and "
            #                                   f"Threshold={threshold}")
            # else:
            #     default_log.debug(f"[EXTENSION] Not placing EXTENSION trade as tp_order_status={dto.tp_order_status} "
            #                       f"sl_order_status={dto.sl_order_status} trades_made={trades_made} and "
            #                       f"maximum_trades_to_make={maximum_trades_to_make} Make Extension 1 trade status="
            #                       f"{trades_details_dto.trades_to_make.extension1_trade} Make Extension 2 trade "
            #                       f"status={trades_details_dto.trades_to_make.extension2_trade} and extension_diff="
            #                       f"{extension_diff}")

            # Check if tried creating market order, extension1 order and extension2 order. If yes then create a MARKET
            # order with only SL-M order and LIMIT order
            if (tried_creating_entry_order and tried_creating_extension1_order and tried_creating_extension2_order) \
                    and (dto.entry_trade_order_id is None and dto.extension1_trade_order_id is None and
                         dto.extension2_trade_order_id is None):
                default_log.debug(f"For symbol={symbol} having timeframe={timeframe} there has been a attempt to "
                                  f"create entry order (as tried_creating_entry_order={tried_creating_entry_order}) "
                                  f"and to create extension1_order (as tried_creating_extension1_order="
                                  f"{tried_creating_extension1_order}) and to create extension2_order (as "
                                  f"tried_creating_extension2_order={tried_creating_extension2_order}). But Failed to "
                                  f"create these orders as Entry Trade order id={dto.entry_trade_order_id}, "
                                  f"Extension 1 order id={dto.extension1_trade_order_id} and Extension 2 order id="
                                  f"{dto.extension2_trade_order_id}. So will create a MARKET order and SL-M order only "
                                  f"with stop_loss={dto.sl_value} with quantity={dto.extension_quantity}")

                if indices_symbol is not None:
                    # Place only MARKET order

                    # For the quantity: Round off the extension quantity to the lower closest multiplier of
                    # indices_multiplier
                    # Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) * Indices Multiplier

                    default_log.debug(f"[BEYOND EXTENSION] Rounding down the extension quantity "
                                      f"{dto.extension_quantity} to nearest multiplier of indices "
                                      f"{indices_quantity_multiplier} using the formula: "
                                      f"Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) "
                                      f"* Indices")
                    rounded_down_extension_quantity = math.floor(
                        dto.extension_quantity / indices_quantity_multiplier) * indices_quantity_multiplier
                    default_log.debug(f"[BEYOND EXTENSION] Rounded down extension quantity "
                                      f"{dto.extension_quantity} to nearest multiplier of indices "
                                      f"{indices_quantity_multiplier} using the formula: "
                                      f"Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) "
                                      f"* Indices => {rounded_down_extension_quantity}")
                    dto.extension_quantity = rounded_down_extension_quantity

                    extension_indices_market_order_id = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        quantity=dto.extension_quantity,
                        signal_type=SignalType.BUY,
                        entry_price=dto.entry_price
                    )

                    if extension_indices_market_order_id is None:
                        default_log.debug(f"[BEYOND EXTENSION] An error occurred while placing BEYOND Extension Trade "
                                          f"for indices_symbol={indices_symbol} having time_frame={timeframe}")
                        break

                    default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                      f"id={extension_indices_market_order_id} for symbol={symbol} having time_frame="
                                      f"{timeframe} with quantity={dto.extension_quantity}")

                    dto.entry_trade_order_id = extension_indices_market_order_id
                    dto.sl_order_status = 'OPEN'
                    dto.tp_order_status = 'OPEN'
                else:
                    event_data_dto, error_occurred = place_initial_zerodha_trades(
                        event_data_dto=dto,
                        data_dictionary=data_dictionary,
                        signal_type=SignalType.BUY,
                        candle_data=data.iloc[-1],
                        symbol=symbol,
                        loss_budget=0,
                        indices_symbol=indices_symbol,
                        extra_extension=True
                    )

                    if error_occurred:
                        default_log.debug(f"[BEYOND EXTENSION] Error occurred while placing Extra Extension Order for "
                                          f"symbol={symbol} having timeframe={dto.time_frame} with "
                                          f"quantity={dto.extension_quantity} and stop_loss={dto.sl_value}")
                        break

                    default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                      f"id={event_data_dto.entry_trade_order_id} for symbol={symbol} having "
                                      f"time_frame={timeframe} with quantity={dto.extension_quantity}")

                    dto = event_data_dto

        data_dictionary[key] = dto
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
            default_log.debug(f"TP/SL HIT for symbol={symbol} and timeframe={timeframe}")
            break

        # When server is stopped and all orders are CANCELLED
        if (dto.sl_order_status == "CANCELLED") and (dto.tp_order_status == "CANCELLED"):
            default_log.debug(f"The TP and SL order has been CANCELLED for symbol={symbol} and time_frame={timeframe} "
                              f"TP order status={dto.tp_order_status} and SL order status={dto.sl_order_status}")
            break

        data = get_next_data(
            is_restart=is_restart,
            timeframe=timeframe,
            instrument_token=instrument_token,
            interval=interval,
            from_timestamp=data.iloc[-1]["time"]
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                              f"and timeframe={timeframe}")
            return None

    # if dto is not None:
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
    kite = get_kite_account_api()
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

    tried_creating_entry_order = False
    tried_creating_extension1_order = False
    tried_creating_extension2_order = False

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
        lowest_point = restart_dto.lowest_point

        sl_value = restart_dto.sl_value

        candle_high = restart_dto.candle_high
        candle_low = restart_dto.candle_low
        candle_length = candle_high - candle_low

        adjusted_high = restart_dto.adjusted_high
        adjusted_low = restart_dto.adjusted_low

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

            event_details_dto = EventDetailsDTO(
                event1_occur_time=event1_occur_time,
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_high=candle_high,
                event1_candle_low=candle_low,
                candle_length=candle_length,
                event2_occur_breakpoint=event2_breakpoint,
                adjusted_high=adjusted_high,
                adjusted_low=adjusted_low,
                stop_tracking_further_events=False
            )

            data_dictionary[key] = event_details_dto

            data = get_zerodha_data(
                from_date=event1_occur_time,
                instrument_token=instrument_token,
                market_symbol=symbol,
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
                candle_length=candle_length,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                highest_point=highest_point,
                lowest_point=lowest_point,
                sl_value=sl_value,
                stop_tracking_further_events=False
            )

            # Fetch the data
            data = get_zerodha_data(
                from_date=event2_occur_time,
                instrument_token=instrument_token,
                market_symbol=symbol,
                interval=interval,
                is_restart=True
            )

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event2_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

            # event1_candle_high = data.iloc[-1]["high"]
            # event1_candle_low = data.iloc[-1]["low"]
            #
            # event_details_dto.event1_candle_high = event1_candle_high
            # event_details_dto.event1_candle_low = event1_candle_low

            data_dictionary[key] = event_details_dto
        else:
            # Event 3 has been completed but tp or sl has not been hit yet Start the thread from event 3 timestamp
            # Provide the following: EVENT1_OCCUR_TIME, LOWEST_POINT, SL_VALUE, EVENT2_BREAKPOINT, EVENT2_OCCUR_TIME,
            # EVENT3_OCCUR_TIME, TP VALUE

            tp_value = restart_dto.tp_value

            # Fetch data
            data = get_zerodha_data(
                from_date=event3_occur_time,
                instrument_token=instrument_token,
                market_symbol=symbol,
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

            value_to_add_for_stop_loss_entry_price = -(highest_point - lowest_point)

            event_details_dto = EventDetailsDTO(
                symbol=symbol,
                time_frame=time_frame,
                event1_candle_high=candle_high,
                event1_candle_low=candle_low,
                candle_length=candle_length,
                event1_occur_time=event1_occur_time,
                event2_breakpoint=event2_breakpoint,
                event2_occur_time=event2_occur_time,
                event3_occur_time=event3_occur_time,
                highest_point=highest_point,
                lowest_point=lowest_point,
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
                extension2_quantity=extension2_quantity,
                value_to_add_for_stop_loss_entry_price=value_to_add_for_stop_loss_entry_price,
                stop_tracking_further_events=False
            )

            data_dictionary[key] = event_details_dto

            # Set the trades made value depending on the extension trade
            trades_made = 0
            if signal_trade_order_id is not None:
                trades_made += 1
                tried_creating_entry_order = True

            if extension1_order_id is not None:
                trades_made += 1
                tried_creating_extension1_order = True

            if extension2_order_id is not None:
                trades_made += 1
                tried_creating_extension2_order = True

            # Start checking the status of the TP and SL order
            if (tp_order_id is not None) and (sl_order_id is not None):
                thread = threading.Thread(target=update_tp_and_sl_status, args=(event_details_dto, data_dictionary))
                thread.start()
    else:
        # Non restart flow
        tm.sleep(wait_time)
        current_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))

        # Fetch candle data
        data = get_zerodha_data(
            instrument_token=instrument_token,
            market_symbol=symbol,
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
    dto = None

    trades_details_dto = None
    temp_current_time = None
    sl_got_extended = False
    maximum_trades_to_make = 0

    initial_close_price = None

    indices_quantity_multiplier = 50 if symbol == "NIFTY" else 45

    while True:
        # Defining loss budget
        loss_budget = fetch_symbol_budget(symbol, timeframe)

        timestamp = data.iloc[-1]['time']
        if prev_timestamp is None:
            prev_timestamp = timestamp

        # This Flow skips first Candle
        # if not is_restart:
        #     if not use_current_candle:
        #         if temp_current_time is None:
        #             temp_current_time = data.iloc[-1]["time"]
        #
        #         next_time = data.iloc[-1]["time"]
        #         default_log.debug(f"Current Time ({temp_current_time}) and Next Time ({next_time}) for symbol={symbol} "
        #                           f"having timeframe={timeframe}")
        #         if next_time.minute <= temp_current_time.minute:
        #             data = get_next_data(
        #                 is_restart=is_restart,
        #                 timeframe=timeframe,
        #                 instrument_token=instrument_token,
        #                 interval=interval,
        #                 from_timestamp=data.iloc[-1]["time"]
        #             )
        #
        #             if data is None:
        #                 default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                                   f"and timeframe={timeframe}")
        #                 break
        #             continue
        #         else:
        #             use_current_candle = True
        #
        #             data = get_next_data(
        #                 is_restart=is_restart,
        #                 timeframe=timeframe,
        #                 instrument_token=instrument_token,
        #                 interval=interval,
        #                 from_timestamp=data.iloc[-1]["time"]
        #             )
        #
        #             if data is None:
        #                 default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                                   f"and timeframe={timeframe}")
        #                 break
        #             continue

        dto, data_dictionary = trade_logic_buy(symbol, timeframe, data.iloc[-1], data_dictionary)
        dto.current_candle_low = data.iloc[-1]["low"]
        dto.current_candle_high = data.iloc[-1]["high"]

        # Adding a check of if stop_tracking_further_events is True then break out and mark thread as completed
        if dto.stop_tracking_further_events:
            default_log.debug(f"Stopping tracking of further events for symbol={symbol} having timeframe={timeframe} "
                              f"as stop_tracking_further_events={dto.stop_tracking_further_events}")
            break

        # This part prevents the thread_details to be committed till next candle (after event 1) is formed
        # Commented it out
        # if timestamp.hour < dto.event1_occur_time.hour or \
        #         (timestamp.hour == dto.event1_occur_time.hour and
        #          timestamp.minute <= dto.event1_occur_time.minute):
        #     default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
        #                       f"({dto.event1_occur_time}) for symbol={dto.symbol} and "
        #                       f"time_frame={dto.time_frame}")
        #
        #     data = get_next_data(
        #         is_restart=is_restart,
        #         timeframe=timeframe,
        #         instrument_token=instrument_token,
        #         interval=interval,
        #         from_timestamp=data.iloc[-1]["time"]
        #     )
        #
        #     if data is None:
        #         default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
        #                           f"and timeframe={timeframe}")
        #         break
        #
        #     continue

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
                    from_timestamp=data.iloc[-1]["time"]
                )

                if data is None:
                    default_log.debug(f"No data received from ZERODHA for symbol={symbol} "
                                      f"and timeframe={timeframe}")
                    break

                continue

        if dto.event3_occur_time is None:
            if candles_checked > no_of_candles_to_consider:
                if (dto.event2_occur_time is None) and (dto.event3_occur_time is None):
                    default_log.debug(f"Event 2 not occurred for symbol={symbol} having timeframe={timeframe} "
                                      f"as checked {no_of_candles_to_consider} candles for the event 2 so stopping "
                                      f"tracking of further events")
                    data_not_found = True
                    break
                elif (dto.event2_occur_time is not None) \
                        and (dto.event3_occur_time is None):
                    default_log.debug(f"Event 3 not occurred for symbol={symbol} having timeframe={timeframe} "
                                      f"as checked {no_of_candles_to_consider} candles after event 2"
                                      f"for the event 3 so stopping tracking of further events")
                    data_not_found = True
                    break
                else:
                    candles_checked = 0
            else:
                default_log.debug(f"Candles Checked ({candles_checked}) is not greater than No of candle to "
                                  f"consider ({no_of_candles_to_consider})")
                if prev_timestamp.hour < timestamp.hour or \
                        (prev_timestamp.hour == timestamp.hour and
                         prev_timestamp.minute <= timestamp.minute):
                    default_log.debug(f"Previous Timestamp ({prev_timestamp}) is earlier than Current Timestamp "
                                      f"({timestamp}) for symbol={dto.symbol} and "
                                      f"time_frame={dto.time_frame}")

                    if prev_timestamp.hour == timestamp.hour:
                        time_difference = abs(int(prev_timestamp.minute - timestamp.minute))
                    else:
                        time_difference = abs(int((60 - prev_timestamp.minute) - timestamp.minute))

                    if time_difference >= int(timeframe):
                        default_log.debug(f"Time difference ({time_difference}) == Timeframe ({int(timeframe)})")
                        prev_timestamp = timestamp
                        candles_checked += 1
                else:
                    default_log.debug(f"Previous Timestamp ({prev_timestamp}) is not earlier than "
                                      f"Current Timestamp ({timestamp}) for symbol={symbol} and time_frame={timeframe}")
                    candles_checked += 1
                    prev_timestamp = timestamp

        current_timestamp = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
        # if (dto.event2_occur_time is not None) and (dto.event3_occur_time is not None) \
        #         and timestamp >= current_timestamp:

        if (dto.event2_occur_time is not None) and (dto.event3_occur_time is not None):

            # find out how many trades needs to be made and the budget to be used
            # get the initial close price
            if initial_close_price is None:
                initial_close_price = data.iloc[-1]["close"]

            # if trades_details_dto is None:

            close_price = initial_close_price
            trades_details_dto = get_budget_and_no_of_trade_details(
                budget=loss_budget,
                close_price=close_price,
                dto=dto
            )

            default_log.debug(f"Budget and Trade details retrieved for symbol={symbol} "
                              f"and time_frame={dto.time_frame} having close_price={close_price}: "
                              f"{trades_details_dto}")

            if (not trades_details_dto.trades_to_make.entry_trade) and \
                    (not trades_details_dto.trades_to_make.extension1_trade) and \
                    (not trades_details_dto.trades_to_make.extension2_trade):
                default_log.debug(f"No TRADES are to be made for symbol={symbol} and time_frame={timeframe}")
                break

            # Find out how many trades would be made
            maximum_trades_to_make = 0
            if trades_details_dto.trades_to_make.entry_trade:
                default_log.debug(f"Make Entry Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
            else:
                tried_creating_entry_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension1_trade:
                default_log.debug(f"Make Extension 1 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
            else:
                tried_creating_extension1_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension2_trade:
                default_log.debug(f"Make Extension 2 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1

            if symbol in indices_list:
                default_log.debug(f"Getting indices symbol as trading symbol={symbol} is in "
                                  f"indices_list={indices_list} with entry price={entry_price} "
                                  f"and transaction type as {SignalType.SELL}")
                if indices_symbol is None:
                    default_log.debug(f"Getting indices symbol for symbol={symbol}, price={dto.entry_price} "
                                      f"and for transaction_type={SignalType.SELL}")
                    indices_symbol = get_indices_symbol_for_trade(
                        trading_symbol=symbol,
                        price=dto.entry_price,
                        transaction_type=SignalType.SELL
                    )

                    if indices_symbol is None:
                        default_log.debug(f"Cannot find indices symbol for symbol={symbol} and time_frame={timeframe} "
                                          f"with transaction_type={SignalType.SELL}")
                        break

            if indices_symbol is not None:
                candle_high = data.iloc[-1]["high"]
                candle_low = data.iloc[-1]["low"]

                default_log.debug(f"Indices symbol ({indices_symbol}) is present so only will place MARKET orders and "
                                  f"not LIMIT and SL-M orders with current_candle_high={candle_high} and "
                                  f"current_candle_low={candle_low}")

                if (dto.entry_trade_order_id is None) and not tried_creating_entry_order:

                    # Calculate trade 1 quantity
                    entry_sl_value = dto.sl_value
                    entry_price = dto.entry_price
                    loss_percent = loss_budget * trade1_loss_percent

                    default_log.debug(f"[For indices_symbol={indices_symbol}] Entry Price={entry_price} and "
                                      f"Entry SL value={entry_sl_value}")

                    trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
                    trade1_quantity = int(round(trade1_quantity, 0))

                    default_log.debug(f"Rounding off trade1_quantity ({trade1_quantity}) to the "
                                      f"indices_quantity_multiplier ({indices_quantity_multiplier}) for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                    trade1_quantity = round_to_nearest_multiplier(trade1_quantity, indices_quantity_multiplier)

                    default_log.debug(f"After rounding off trade1_quantity to {trade1_quantity} using "
                                      f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                    make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                    if (trade1_quantity > 0) and (
                            (trade1_quantity % indices_quantity_multiplier) != 0) and make_entry_trade:
                        default_log.debug(
                            f"As trade1_quantity ({trade1_quantity}) is not divisible by indices_quantity_"
                            f"multiplier ({indices_quantity_multiplier}) so skipping placing MARKET "
                            f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
                            f"timeframe={timeframe}")
                        dto.trade1_quantity = trade1_quantity
                        tried_creating_entry_order = True
                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'
                    else:
                        quantity = trade1_quantity
                        # quantity = 50 if symbol == "NIFTY" else 45
                        default_log.debug(f"Placing MARKET order for indices_symbol={indices_symbol} and time_frame="
                                          f"{timeframe} with quantity={quantity}")

                        entry_trade_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.BUY,
                            quantity=quantity,
                            entry_price=dto.entry_price
                        )

                        if entry_trade_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.BUY}")

                            tried_creating_entry_order = True
                        else:
                            dto.entry_trade_order_id = entry_trade_order_id

                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'
                        dto.trade1_quantity = quantity

                if dto.entry_trade_order_id or dto.extension1_trade_order_id or dto.extension2_trade_order_id:
                    # Check TP hit or not
                    tp_value = dto.tp_values[-1].tp_value
                    sl_value = dto.sl_value + dto.candle_length
                    tp_quantity = sl_quantity = dto.extension_quantity if dto.extension_quantity is not None else dto.trade1_quantity

                    if candle_high >= tp_value:
                        default_log.debug(
                            f"Current Candle High ({candle_high}) >= TP value ({tp_value}) for indices_symbol="
                            f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
                            f"quantity={tp_quantity} and signal_type={SignalType.SELL}")

                        tp_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=tp_quantity,
                            entry_price=dto.entry_price
                        )

                        if tp_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing MARKET (LIMIT) order for indices symbol={indices_symbol} "
                                f"with quantity={tp_quantity} with signal_type={SignalType.SELL}")

                        dto.tp_order_id = tp_order_id
                        dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.tp_hit = True
                        dto.tp_order_status = 'COMPLETE'
                        break

                    # Check SL-M hit or not
                    elif candle_low <= sl_value:
                        default_log.debug(
                            f"Current Candle Low ({candle_high}) <= SL value ({sl_value}) for indices_symbol="
                            f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
                            f"quantity={sl_quantity} and signal_type={SignalType.SELL}")

                        sl_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=sl_quantity,
                            entry_price=dto.entry_price
                        )

                        if sl_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing MARKET (SL-M) order for indices symbol={indices_symbol} "
                                f"with quantity={sl_quantity} with signal_type={SignalType.SELL}")

                        dto.sl_order_id = sl_order_id
                        dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.sl_hit = True
                        dto.sl_order_status = 'COMPLETE'
                        break

            default_log.debug(f"Storing SL value of symbol={symbol}, timeframe={timeframe}, "
                              f"signal_type={SignalType.BUY} having stop_loss={dto.sl_value}")

            store_sl_details_of_active_trade(
                symbol=symbol,
                signal_type=SignalType.SELL,
                stop_loss=dto.sl_value,
                time_frame=int(timeframe)
            )

            if extension_diff is None:
                default_log.debug(f"Extension Difference = Entry Price ({dto.entry_price}) - SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
                    (indices_symbol is None) and not tried_creating_entry_order:
                entry_price = dto.entry_price

                event_data_dto, error_occurred = place_initial_zerodha_trades(
                    event_data_dto=dto,
                    data_dictionary=data_dictionary,  # used for tracking tp and sl order status
                    signal_type=SignalType.BUY,
                    candle_data=data.iloc[-1],
                    symbol=symbol,
                    loss_budget=loss_budget,
                    indices_symbol=indices_symbol
                )

                tried_creating_entry_order = True
                if error_occurred:
                    default_log.debug(f"An error occurred while placing MARKET order for symbol={symbol} and "
                                      f"indices_symbol={indices_symbol} and event_data_dto={dto}")

                dto = event_data_dto
                trades_made += 1

                default_log.debug(f"[UPDATING] Extension Difference = Entry Price ({dto.entry_price}) "
                                  f"- SL Value ({dto.sl_value})")
                extension_diff = abs(dto.entry_price - dto.sl_value)

            if not trades_details_dto.trades_to_make.entry_trade:
                dto.trade1_quantity = 0

            if (dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.tp_order_id is not None) and \
                    (indices_symbol is None):
                take_profit = dto.tp_values[-1].tp_with_buffer

                # round off the price of take profit
                formatted_value = round_value(
                    symbol=symbol if indices_symbol is None else indices_symbol,
                    price=take_profit,
                    exchange="NSE" if indices_symbol is None else "NFO"
                )
                take_profit = formatted_value

                # dto.tp_values[-1].tp_value = take_profit
                dto.tp_values[-1].tp_with_buffer = take_profit
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
                current_candle_low = data.iloc[-1]["low"]
                current_candle_close = data.iloc[-1]["close"]

                # if ((entry_price - ((entry_price - dto.sl_value) / 2)) >= current_candle_low) and not sl_got_extended:
                #     default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
                #                       f"Entry Price ({entry_price}) - [Entry Price ({entry_price}) - "
                #                       f"SL value ({dto.sl_value})] >= Current Candle Low ({current_candle_low})")

                do_update, stop_loss_to_update_to = do_update_of_sl_values(
                    timeframe=int(dto.time_frame),
                    signal_type=SignalType.SELL,
                    symbol=symbol,
                    entry_price=entry_price,
                    close_price=current_candle_close
                )

                if do_update and not sl_got_extended:
                    default_log.debug(f"[EXTENSION OF SL] Updating stop loss of symbol={symbol} with "
                                      f"time_frame={dto.time_frame} and "
                                      f"event1_candle signal_type={SignalType.SELL} from {dto.sl_value} to "
                                      f"{stop_loss_to_update_to}")
                    dto.sl_value = stop_loss_to_update_to
                    sl_got_extended = True

                    if indices_symbol is None:
                        # Only updating SL order when indices symbol is None
                        # as for indices symbol SL-M order is not placed
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

                # Condition 2
                # Check condition of updating Stop Loss according to average price
                average_entry_price = dto.entry_price
                if dto.extension1_trade_order_id is not None:
                    average_entry_price = (dto.entry_price + dto.extension1_entry_price) / 2

                if dto.extension2_trade_order_id is not None:
                    average_entry_price = (
                                                      dto.entry_price + dto.extension1_entry_price + dto.extension2_entry_price) / 3

                current_candle_close = data.iloc[-1]["close"]

                if (current_candle_close - average_entry_price) > ((average_entry_price - dto.sl_value) * 0.8):
                    default_log.debug(f"Satisfied condition for updating SL according to average entry price as "
                                      f"[Current Candle close ({current_candle_close}) - "
                                      f"Average Entry Price ({average_entry_price})] > "
                                      f"[Average Entry Price ({average_entry_price}) - SL value ({dto.sl_value})]")
                    dto.sl_value = average_entry_price

                    if indices_symbol is None:
                        # Only updating SL order when indices symbol is None
                        # as for indices symbol SL-M order is not placed
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
            if (extension_diff is not None) and (trades_made < maximum_trades_to_make) and \
                    ((dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])
                     and (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])) and \
                    (trades_details_dto.trades_to_make.extension1_trade or
                     trades_details_dto.trades_to_make.extension2_trade):

                default_log.debug(f"Extension Diff={extension_diff}, trades_made={trades_made}, "
                                  f"TP Order status={dto.tp_order_status} with id={dto.tp_order_id} and "
                                  f"SL Order status={dto.sl_order_status} with id={dto.sl_order_id} ")

                extension_time_stamp = data.iloc[-1]["time"]
                current_candle_low = data.iloc[-1]["low"]
                # threshold = extension_diff * (1 + (config_threshold_percent * trades_made))

                entry_price_difference = abs(dto.sl_value - current_candle_low)

                if tried_creating_extension1_order and trades_details_dto.trades_to_make.extension1_trade:
                    default_log.debug(f"Extension 1 trade has been made as Extension 1 Trade order id="
                                      f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                                      f"{tried_creating_extension1_order} and Make extension 1 trade status="
                                      f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 2 "
                                      f"trade threshold percent={extension2_threshold_percent}")
                    threshold_percent = extension2_threshold_percent
                else:
                    default_log.debug(f"Extension 1 trade has not been made as Extension 1 Trade order id="
                                      f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                                      f"{tried_creating_extension1_order} and Make extension 1 trade status="
                                      f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 1 "
                                      f"trade threshold percent={extension1_threshold_percent}")
                    threshold_percent = extension1_threshold_percent

                # threshold = extension_diff * (config_threshold_percent * trades_made)
                threshold = extension_diff * threshold_percent

                default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                  f"at timestamp = {extension_time_stamp} and "
                                  f"current_candle_low={current_candle_low} ")

                if entry_price_difference >= threshold:
                    default_log.debug(f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
                                      f"and SL value = {dto.sl_value} "
                                      f"and current_candle_low = {current_candle_low} "
                                      f"at timestamp = {extension_time_stamp} "
                                      f"Entry Price Difference {entry_price_difference} >= "
                                      f"Threshold {threshold}")

                    # If first extension trade is already done placing second extension trade
                    if (trades_made == 2) and tried_creating_extension1_order and (not tried_creating_extension2_order):
                        # If first two trades were placed then check if third trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension2_trade:
                            tried_creating_extension2_order = True
                            loss_percent = loss_budget * trade3_loss_percent
                            # loss_percent = trade3_loss_percent
                            default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference

                            if indices_symbol is not None:

                                total_quantity = extension_quantity
                                make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                                make_extension1_trade = trades_details_dto.trades_to_make.extension1_trade

                                dto.extension2_quantity = int(round(total_quantity, 0))
                                if (dto.entry_trade_order_id is None) and make_entry_trade:
                                    total_quantity += dto.trade1_quantity
                                if (dto.extension1_trade_order_id is None) and make_extension1_trade:
                                    total_quantity += dto.extension1_quantity if dto.extension1_quantity is not None else 0

                                total_quantity = int(round(total_quantity, 0))
                                default_log.debug(f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
                                                  f"indices_quantity_multiplier ({indices_quantity_multiplier}) for "
                                                  f"symbol={symbol}"
                                                  f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                total_quantity = round_to_nearest_multiplier(total_quantity,
                                                                             indices_quantity_multiplier)

                                default_log.debug(
                                    f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
                                    f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0):
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 2 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier})")
                                    dto.extension_quantity = total_quantity
                                else:
                                    default_log.debug(f"Creating EXTENSION indices MARKET order with quantity=50 for "
                                                      f"indices_symbol={indices_symbol} and time_frame={timeframe}")

                                    if dto.extension_quantity is None:
                                        dto.extension_quantity = 0

                                    extension2_quantity = total_quantity
                                    extension_quantity_for_indices_symbol = dto.extension_quantity + extension2_quantity

                                    extension_order_id = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=extension_quantity_for_indices_symbol,
                                        entry_price=dto.entry_price
                                    )

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION MARKET order for "
                                            f"symbol={indices_symbol} and "
                                            f"and event_data_dto={dto} and extension2_quantity={extension2_quantity}"
                                            f"extension_quantity={extension_quantity_for_indices_symbol} "
                                            f"and trade1_quantity={dto.trade1_quantity}")
                                    else:
                                        dto.extension2_trade_order_id = extension_order_id

                                    # dto.extension2_quantity = extension2_quantity
                                    dto.extension_quantity = extension_quantity_for_indices_symbol
                                    trades_made += 1

                                dto.tp_order_status = 'OPEN'
                                dto.sl_order_status = 'OPEN'

                            else:
                                event_data_dto, error_occurred = place_extension_zerodha_trades(
                                    event_data_dto=dto,
                                    signal_type=SignalType.BUY,
                                    candle_data=data.iloc[-1],
                                    extension_quantity=extension_quantity if indices_symbol is None else 50,
                                    symbol=symbol,
                                    indices_symbol=indices_symbol,
                                    multiplier=trades_made,
                                    extension_no=2,
                                    exchange="NSE" if indices_symbol is None else "NFO"
                                )

                                if error_occurred:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} and "
                                        f"indices_symbol={indices_symbol} and event_data_dto={dto} and "
                                        f"extension_quantity={extension_quantity} and trade1_quantity={dto.trade1_quantity}")
                                    return None

                                trades_made += 1
                                dto = event_data_dto
                        else:
                            default_log.debug(f"[EXTENSION] Not placing Extension 2 trade has extension 2 trade "
                                              f"condition is {trades_details_dto.trades_to_make.extension2_trade}")

                    # If only first trade is made
                    elif tried_creating_entry_order and (not tried_creating_extension1_order):
                        # If first trade was placed then check if second trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension1_trade:
                            tried_creating_extension1_order = True
                            loss_percent = loss_budget * trade2_loss_percent
                            # loss_percent = trade2_loss_percent
                            default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference

                            if indices_symbol is not None:

                                total_quantity = extension_quantity
                                make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                                make_extension2_trade = trades_details_dto.trades_to_make.extension2_trade

                                dto.extension1_quantity = int(round(total_quantity, 0))
                                if (dto.entry_trade_order_id is None) and make_entry_trade:
                                    total_quantity += dto.trade1_quantity

                                total_quantity = int(round(total_quantity, 0))
                                default_log.debug(f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
                                                  f"indices_quantity_multiplier ({indices_quantity_multiplier}) "
                                                  f"for symbol={symbol} and indices_symbol={indices_symbol} "
                                                  f"having time_frame={timeframe}")

                                total_quantity = round_to_nearest_multiplier(total_quantity,
                                                                             indices_quantity_multiplier)

                                default_log.debug(
                                    f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
                                    f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0):
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier}). "
                                        f"Also extension 2 trade won't be made as make_extension2_trade="
                                        f"{make_extension2_trade}")

                                    dto.extension_quantity = total_quantity

                                    if not make_extension2_trade:
                                        default_log.debug(f"Not making Extension 2 trade as make_extension2_trade="
                                                          f"{make_extension2_trade} and quantity ({total_quantity}) is "
                                                          f"not a multiplier of {indices_quantity_multiplier}")
                                        break
                                else:
                                    default_log.debug(f"Creating EXTENSION indices MARKET order with quantity=50 for "
                                                      f"indices_symbol={indices_symbol} and time_frame={timeframe}")

                                    if dto.extension_quantity is None:
                                        dto.extension_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0

                                    extension1_quantity = total_quantity
                                    extension_quantity_for_indices_symbol = dto.extension_quantity + extension1_quantity

                                    extension_order_id = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=extension_quantity_for_indices_symbol,
                                        entry_price=dto.entry_price
                                    )

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION MARKET order for "
                                            f"symbol={indices_symbol} and event_data_dto={dto} and "
                                            f"extension_quantity={extension_quantity_for_indices_symbol} "
                                            f"and trade1_quantity={dto.trade1_quantity}")
                                    else:
                                        dto.extension1_trade_order_id = extension_order_id

                                    trades_made += 1
                                    dto.extension1_quantity = extension1_quantity
                                    dto.extension_quantity = extension_quantity_for_indices_symbol

                                dto.tp_order_status = 'OPEN'
                                dto.sl_order_status = 'OPEN'
                            else:
                                event_data_dto, error_occurred = place_extension_zerodha_trades(
                                    event_data_dto=dto,
                                    signal_type=SignalType.BUY,
                                    candle_data=data.iloc[-1],
                                    extension_quantity=extension_quantity if indices_symbol is None else 50,
                                    symbol=symbol,
                                    indices_symbol=indices_symbol,
                                    multiplier=trades_made,
                                    extension_no=1,
                                    exchange="NSE" if indices_symbol is None else "NFO"
                                )

                                tried_creating_extension1_order = True

                                if error_occurred:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} "
                                        f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
                                        f"extension_quantity={extension_quantity} and "
                                        f"trade1_quantity={dto.trade1_quantity}")

                                dto = event_data_dto
                                trades_made += 1
                        else:
                            default_log.debug(f"[EXTENSION] Not placing Extension 1 trade has extension 1 trade "
                                              f"condition is {trades_details_dto.trades_to_make.extension1_trade}")
                else:
                    default_log.debug(
                        f"Extension Trade condition not met as values: extension_diff={extension_diff} "
                        f"trades_made={trades_made}, threshold_percent={threshold_percent} "
                        f"entry_price={entry_price} and sl_value={dto.sl_value} "
                        f"and entry_price_difference: {entry_price_difference} < threshold: {threshold} "
                        f"and symbol={symbol} and indices_symbol={indices_symbol} and "
                        f"Make Extension 1 trade={trades_details_dto.trades_to_make.extension1_trade} "
                        f"and Make Extension 2 trade={trades_details_dto.trades_to_make.extension2_trade} ")

            # Check if tried creating market order, extension1 order and extension2 order. If yes then create a
            # MARKET order with only SL-M order and no LIMIT order
            if (tried_creating_entry_order and tried_creating_extension1_order and tried_creating_extension2_order) \
                    and ((dto.entry_trade_order_id is None) and (dto.extension1_trade_order_id is None) and
                         (dto.extension2_trade_order_id is None)):
                default_log.debug(
                    f"For symbol={symbol} having timeframe={timeframe} there has been a attempt to "
                    f"create entry order (as tried_creating_entry_order={tried_creating_entry_order}) "
                    f"and to create extension1_order (as tried_creating_extension1_order="
                    f"{tried_creating_extension1_order}) and to create extension2_order (as "
                    f"tried_creating_extension2_order={tried_creating_extension2_order}). But Failed to "
                    f"create these orders as Entry Trade order id={dto.entry_trade_order_id}, "
                    f"Extension 1 order id={dto.extension1_trade_order_id} and Extension 2 order id="
                    f"{dto.extension2_trade_order_id}. So will create a MARKET order and TP with SL-M order only "
                    f"with stop_loss={dto.sl_value} and take_profit={dto.tp_values[-1].tp_value} "
                    f"with quantity={dto.extension_quantity}")

                if indices_symbol is not None:
                    # Place only MARKET order

                    # For the quantity: Round off the extension quantity to the lower closest multiplier of
                    # indices_multiplier
                    # Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) * Indices Multiplier

                    default_log.debug(f"[BEYOND EXTENSION] Rounding down the extension quantity "
                                      f"{dto.extension_quantity} to nearest multiplier of indices "
                                      f"{indices_quantity_multiplier} using the formula: "
                                      f"Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) "
                                      f"* Indices")
                    rounded_down_extension_quantity = math.floor(
                        dto.extension_quantity / indices_quantity_multiplier) * indices_quantity_multiplier
                    default_log.debug(f"[BEYOND EXTENSION] Rounded down extension quantity "
                                      f"{dto.extension_quantity} to nearest multiplier of indices "
                                      f"{indices_quantity_multiplier} using the formula: "
                                      f"Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) "
                                      f"* Indices => {rounded_down_extension_quantity}")
                    dto.extension_quantity = rounded_down_extension_quantity
                    extension_indices_market_order_id = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        quantity=dto.extension_quantity,
                        signal_type=SignalType.BUY,
                        entry_price=dto.entry_price
                    )

                    if extension_indices_market_order_id is None:
                        default_log.debug(
                            f"[BEYOND EXTENSION] An error occurred while placing BEYOND Extension Trade "
                            f"for indices_symbol={indices_symbol} having time_frame={timeframe}")
                        break

                    default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                      f"id={extension_indices_market_order_id} for symbol={symbol} having "
                                      f"time_frame={timeframe} with quantity={dto.extension_quantity}")

                    dto.entry_trade_order_id = extension_indices_market_order_id
                    dto.sl_order_status = 'OPEN'
                    dto.tp_order_status = 'OPEN'
                else:
                    event_data_dto, error_occurred = place_initial_zerodha_trades(
                        event_data_dto=dto,
                        data_dictionary=data_dictionary,
                        signal_type=SignalType.SELL,
                        candle_data=data.iloc[-1],
                        symbol=symbol,
                        loss_budget=loss_budget,
                        indices_symbol=indices_symbol,
                        extra_extension=True
                    )

                    if error_occurred:
                        default_log.debug(
                            f"[BEYOND EXTENSION] Error occurred while placing Extra Extension Order for "
                            f"symbol={symbol} having timeframe={dto.time_frame} with "
                            f"quantity={dto.extension_quantity} and stop_loss={dto.sl_value}")
                        break

                    default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                      f"id={event_data_dto.entry_trade_order_id} for symbol={symbol} having "
                                      f"time_frame={timeframe} with quantity={dto.extension_quantity}")

                    dto = event_data_dto

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
            extension1_quantity=dto.extension1_quantity,
            extension2_quantity=dto.extension2_quantity,
            extension1_order_id=dto.extension1_trade_order_id,
            extension2_order_id=dto.extension2_trade_order_id
        )

        response = update_thread_event_details(update_event_thread_dto, thread_detail_id)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

        if (dto.sl_order_status == "COMPLETE") or (dto.tp_order_status == "COMPLETE"):
            default_log.debug(f"TP/SL hit for symbol={symbol} having timeframe={timeframe}")
            break

        # When server is stopped and all orders are CANCELLED
        if (dto.sl_order_status == "CANCELLED") and (dto.tp_order_status == "CANCELLED"):
            default_log.debug(
                f"The TP and SL order has been CANCELLED for symbol={symbol} and time_frame={timeframe} "
                f"TP order status={dto.tp_order_status} and SL order status={dto.sl_order_status}")
            break

        # Fetch next data
        data = get_next_data(
            is_restart=is_restart,
            timeframe=timeframe,
            instrument_token=instrument_token,
            interval=interval,
            from_timestamp=data.iloc[-1]["time"]
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
            extension1_quantity=dto.extension1_quantity,
            extension2_quantity=dto.extension2_quantity,
            extension1_order_id=dto.extension1_trade_order_id,
            extension2_order_id=dto.extension2_trade_order_id
        )

        response = update_thread_event_details(update_event_thread_dto, thread_detail_id)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while updating thread event details in database: {response.error}")
            return False

    if data_not_found:
        default_log.debug("Data not found for TP/SL")
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
    and track the tp and sl order status
    """
    default_log.debug(f"inside restart_event_threads")

    # Get all incomplete thread details
    thread_details = get_all_incomplete_thread_details()

    for thread_detail in thread_details:

        event1_occur_time = thread_detail.event1_occur_time
        event2_occur_time = thread_detail.event2_occur_time
        event3_occur_time = thread_detail.event3_occur_time

        event2_breakpoint = thread_detail.event2_breakpoint

        market_symbol = thread_detail.symbol

        candle_high = thread_detail.signal_candle_high
        candle_low = thread_detail.signal_candle_low

        lowest_point = thread_detail.lowest_point
        highest_point = thread_detail.highest_point
        sl_value = thread_detail.sl_value
        signal_type = thread_detail.signal_type

        time_frame = thread_detail.time_frame
        instrument_token = instrument_tokens_map.get(market_symbol, None)

        exchange = "NFO" if market_symbol in indices_list else "NSE"
        if instrument_token is None:
            instrument_token = get_instrument_token_for_symbol(market_symbol, exchange)
            default_log.debug(f"instrument token received for symbol={market_symbol} and exchange={exchange}: "
                              f"{instrument_token}")

        configuration_type = thread_detail.configuration_type

        signal_trade_order_id = thread_detail.signal_trade_order_id
        tp_order_id = thread_detail.tp_order_id
        sl_order_id = thread_detail.sl_order_id

        trade1_quantity = thread_detail.trade1_quantity
        entry_price = thread_detail.entry_price

        extension_quantity = thread_detail.extension_quantity
        extension1_order_id = thread_detail.extension1_order_id
        extension2_order_id = thread_detail.extension2_order_id

        extension1_quantity = thread_detail.extension1_quantity
        extension2_quantity = thread_detail.extension2_quantity

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
                sl_value=sl_value,
                adjusted_high=thread_detail.adjusted_high,
                adjusted_low=thread_detail.adjusted_high,
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
                sl_value=sl_value,
                adjusted_high=thread_detail.adjusted_high,
                adjusted_low=thread_detail.adjusted_high,
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
                entry_price=entry_price,
                extension_quantity=extension_quantity,
                extension1_order_id=extension1_order_id,
                extension2_order_id=extension2_order_id,
                signal_trade_order_id=signal_trade_order_id,
                tp_order_id=tp_order_id,
                sl_order_id=sl_order_id,
                adjusted_high=thread_detail.adjusted_high,
                adjusted_low=thread_detail.adjusted_high,
            )

            if trade1_quantity is not None:
                restart_dto.trade1_quantity = trade1_quantity

            if extension_quantity is not None:
                restart_dto.extension_quantity = int(extension_quantity)

            if extension1_quantity is not None:
                restart_dto.extension1_quantity = int(extension1_quantity)

            if extension2_quantity is not None:
                restart_dto.extension2_quantity = int(extension2_quantity)

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
