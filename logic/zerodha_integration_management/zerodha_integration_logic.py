import random
import threading
import time as tm
from datetime import datetime, timedelta
from typing import Optional, Union, Any

import pandas as pd
import pytz

from api.event_management.dtos.check_events_dto import CheckEventsDTO
from config import default_log, no_of_candles_to_consider, instrument_tokens_map, buffer_for_entry_trade, \
    buffer_for_tp_trade, initial_start_range, initial_end_range, max_retries, trade1_loss_percent, \
    trade2_loss_percent, trade3_loss_percent, indices_list, symbol_tokens_map, use_global_feed, \
    buffer_for_indices_entry_trade, buffer_for_indices_tp_trade, extension1_threshold_percent, \
    extension2_threshold_percent, stop_trade_time, backtest_zerodha_equity, take_reverse_trade, \
    close_indices_position_time, close_cash_trades_position_time, market_start_time, market_close_time
from data.dbapi.symbol_budget_dbapi.read_queries import get_all_symbol_budgets
from data.dbapi.thread_details_dbapi.dtos.event_thread_details_dto import EventThreadDetailsDTO
from data.dbapi.thread_details_dbapi.read_queries import get_all_incomplete_thread_details, \
    get_all_continuity_thread_details
from data.dbapi.thread_details_dbapi.write_queries import add_thread_event_details, update_thread_event_details
from data.dbapi.timeframe_budgets_dbapi.read_queries import get_all_timeframe_budgets
from data.enums.configuration import Configuration
from data.enums.signal_type import SignalType
from data.enums.trades import Trades
from external_services.global_datafeed.get_data import get_use_simulation_status
from external_services.zerodha.zerodha_orders import update_zerodha_order_with_stop_loss, get_kite_account_api, \
    place_zerodha_order, get_historical_data, cancel_order, get_indices_symbol_for_trade, \
    get_status_of_zerodha_order, get_zerodha_order_details, round_value, get_instrument_token_for_symbol, \
    get_symbol_for_instrument_token, get_zerodha_account_equity
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

zerodha_margin = backtest_zerodha_equity

latest_trade_tracking_alerts = []

# Initialize a lock
latest_trade_tracking_lock = threading.Lock()


def store_current_state_of_event(
        thread_detail_id: int,
        symbol: str,
        time_frame: str,
        signal_type: SignalType,
        trade_alert_status: str,
        configuration: Configuration,
        is_completed: bool,
        dto: EventDetailsDTO
):
    default_log.debug(f"inside store_current_state_of_event with symbol={symbol}, time_frame={time_frame}, signal_type="
                      f"{signal_type}, trade_alert_status={trade_alert_status}, configuration={configuration}, "
                      f"thread_detail_id={thread_detail_id}, is_completed={is_completed} and dto={dto}")

    # Store the current state of event in the database
    update_event_thread_dto = EventThreadDetailsDTO(
        symbol=symbol,
        time_frame=time_frame,
        signal_type=signal_type,
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
        high_1=dto.high_1,
        low_1=dto.low_1,
        tp_datetime=dto.tp_candle_time,
        sl_value=dto.sl_value,
        sl_order_id=dto.sl_order_id,
        tp_order_id=dto.tp_order_id,
        signal_trade_order_id=dto.entry_trade_order_id,
        entry_trade_datetime=dto.entry_trade_datetime,
        sl_datetime=dto.sl_candle_time,
        is_completed=is_completed,
        entry_price=dto.entry_price,
        trade1_quantity=int(dto.trade1_quantity) if dto.trade1_quantity is not None else None,
        extension_quantity=dto.extension_quantity,
        extension1_order_id=dto.extension1_trade_order_id,
        extension1_trade_datetime=dto.extension1_trade_datetime,
        extension2_order_id=dto.extension2_trade_order_id,
        extension2_trade_datetime=dto.extension2_trade_datetime,
        extension1_quantity=dto.extension1_quantity,
        extension2_quantity=dto.extension2_quantity,
        extended_sl=dto.extended_sl,
        cover_sl=dto.cover_sl,
        cover_sl_quantity=dto.cover_sl_quantity,
        cover_sl_trade_order_id=dto.cover_sl_trade_order_id,
        sl_trade_datetime=dto.sl_trade_datetime,
        reverse1_trade_quantity=dto.reverse1_trade_quantity,
        reverse2_trade_quantity=dto.reverse2_trade_quantity,
        total_reverse_trade_quantity=dto.total_reverse_trade_quantity,
        reverse1_trade_order_id=dto.reverse1_trade_order_id,
        reverse1_trade_datetime=dto.reverse1_trade_datetime,
        reverse_trade_take_profit=dto.reverse_trade_take_profit,
        reverse2_trade_order_id=dto.reverse2_trade_order_id,
        reverse2_trade_datetime=dto.reverse2_trade_datetime,
        reverse_trade_stop_loss=dto.reverse_trade_stop_loss,
        reverse_trade_tp_order_id=dto.reverse_trade_tp_order_id,
        reverse_trade_sl_order_id=dto.reverse_trade_sl_order_id,
        reverse1_entry_price=dto.reverse1_entry_price,
        reverse2_entry_price=dto.reverse2_entry_price,
        trade_alert_status=trade_alert_status,
        extended_sl_timestamp=dto.extended_sl_timestamp,
        reverse_trade_tp_order_datetime=dto.reverse_trade_tp_order_datetime,
        reverse_trade_sl_order_datetime=dto.reverse_trade_sl_order_datetime
    )

    response = update_thread_event_details(update_event_thread_dto, thread_detail_id)

    if type(response) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while storing event details for symbol={symbol} having time_frame="
                          f"{time_frame}, signal_type={signal_type}, configuration={configuration} and dto={dto}")
        return False

    return True


def reallocate_equity_after_trade(equity_to_reallocate: float):
    global zerodha_margin
    default_log.debug(f"inside reallocate_equity_after_trade with equity_to_reallocate={equity_to_reallocate} and "
                      f"current_equity={zerodha_margin}")

    zerodha_margin = zerodha_margin + equity_to_reallocate


def allocate_equity_for_trade(equity_to_allocate: float):
    global zerodha_margin
    default_log.debug(f"inside allocate_equity_for_trade with equity_to_allocate={equity_to_allocate} and "
                      f"current_equity={zerodha_margin}")

    equity_remaining = zerodha_margin - equity_to_allocate
    zerodha_margin = equity_remaining
    default_log.debug(f"Remaining Equity = Rs. {equity_remaining} after allocating {equity_to_allocate}")
    return equity_remaining


def calculate_required_budget_for_trades(
        used_percent_ratio: float,
        used_ratio_value: float,
        total_percent_ratio: float
):
    default_log.debug(f"inside calculate_required_budget_for_trades with used_percent_ratio="
                      f"{used_percent_ratio}, used_ratio_value={used_ratio_value} and "
                      f"total_percent_ratio={total_percent_ratio}")

    # Calculate total budget that will be required for the remaining trades (including EXTENSION
    # TRADES)
    # remaining_trade_percentage (y_perc) = total_percentage - trade1_loss_percent (x_perc)
    # x_perc_value = 5000 then y_perc_value = ?

    # First calculate total_value for total_percentage using the x_perc_value
    # total_percentage_amount = (total_percentage / 100) * x_perc_value

    # Now calculate y_perc_value using total_percentage_amount
    # y_perc_value = (y_perc / 100) * total_percentage_amount

    total_percentage = total_percent_ratio
    trade_loss_percent = used_percent_ratio
    budget_used = used_ratio_value

    # Calculate y_perc
    remaining_trades_percentage = total_percentage - trade_loss_percent

    # Calculate total_percentage_amount (y_perc) [TOTAL BUDGET]
    # total_percentage_amount = (total_percentage * 100) * budget_used
    total_percentage_amount = budget_used / trade_loss_percent

    # Calculate y_perc_value [% BUDGET REQUIRED FOR REMAINING TRADE FROM TOTAL BUDGET]
    remaining_trade_budget_requirement = (remaining_trades_percentage * 100) * total_percentage_amount

    # Total budget required = budget_used + remaining_trade_budget_requirement
    # [TOTAL BUDGET REQUIRED FOR CREATING REMAINING TRADES (INCLUDING CURRENT BUDGET USED)]
    total_budget_required = budget_used + remaining_trade_budget_requirement

    default_log.debug(f"Budget Required = Rs. {total_budget_required} for the remaining trades")

    return total_budget_required


def fetch_start_and_end_range(symbol: str, timeframe: str):
    global timeframe_budget_dict
    default_log.debug(f"inside fetch_start_and_end_range with symbol={symbol} and timeframe={timeframe}")

    key = (timeframe, symbol)

    start_range_percent = None
    end_range_percent = None

    if symbol in indices_list:
        timeframe_budgets = timeframe_budget_dict.get(key, None)
        if timeframe_budgets is None:
            default_log.debug(f"Timeframe Budget details not found for key={key} with symbol={symbol} and "
                              f"timeframe={timeframe}")
            return start_range_percent, end_range_percent
    else:
        key = (timeframe, 'All Stocks')
        timeframe_budgets = timeframe_budget_dict.get(key, None)
        if timeframe_budgets is None:
            default_log.debug(f"Timeframe Budget details not found for key={key} with symbol={symbol} and "
                              f"timeframe={timeframe}")

            return start_range_percent, end_range_percent

    default_log.debug(f"Timeframe budgets found for key {key} => {timeframe_budgets}")

    start_ranges = []
    end_ranges = []

    for timeframe_budget in timeframe_budgets:
        start_ranges.append(timeframe_budget.start_range)
        end_ranges.append(timeframe_budget.end_range)

    default_log.debug(f"Start {start_ranges} and End {end_ranges} Ranges Percentage found from timeframe_budgets "
                      f"{timeframe_budgets}")

    start_range_percent = min(start_ranges)
    end_range_percent = max(end_ranges)

    default_log.debug(f"Returning start_range_percent ({start_range_percent}) and end_range_percent "
                      f"({end_range_percent}) for symbol={symbol} and timeframe={timeframe}")

    return start_range_percent, end_range_percent


def set_zerodha_margin_value():
    global zerodha_margin
    default_log.debug(f"inside set_zerodha_margin_value")
    kite = get_kite_account_api()

    current_zerodha_account_equity = get_zerodha_account_equity(kite)
    default_log.debug(f"Current Zerodha equity fetched: {current_zerodha_account_equity}")

    zerodha_margin = float(current_zerodha_account_equity)

    return zerodha_margin


def get_zerodha_equity():
    global zerodha_margin
    default_log.debug(f"inside get_zerodha_equity with zerodha_margin={zerodha_margin}")

    return zerodha_margin


def round_to_nearest_multiplier(number, multiplier):
    """
    Choose between multiples of multiplier based on their distance from x.
    If the higher multiple is within threshold points of x, choose it only if the lower multiple is not within
    the threshold; otherwise, choose the lower multiple.

    Args:
        number: The number to compare against.
        multiplier: The multiplier

    Returns:
        The chosen multiple.
    """
    threshold = 24
    default_log.debug(f"inside round_to_nearest_multiplier with number={number} and multiplier={multiplier} and a "
                      f"threshold of {threshold} units")

    # Special case: if the number is exactly divisible by the multiplier
    if number % multiplier == 0:
        default_log.debug(f"As the number ({number}) is exactly divisible by the multiplier ({multiplier}), "
                          f"returning the lower multiple ({number})")
        return number

    # If the number is less than the lowest multiple of the multiplier, return the lowest multiple
    if (number < multiplier) and (multiplier == 15) and (number >= 10):
        default_log.debug(f"Number ({number}) is less than the lowest multiple of the multiplier ({multiplier}), "
                          f"returning the lowest multiple ({multiplier})")
        return multiplier

    # if multiplier is 15 then quantity should more than or equal to 10 for BANKNIFTY
    if (multiplier == 15) and (number < 10):
        default_log.debug(f"As multiplier is {multiplier} and number ({number}) is not greater than or equal to 10 "
                          f"so returning number ({number}) and won't round off the number")
        return number

    # For NIFTY
    if (number == 50) and (number > 26) and (number < multiplier):
        default_log.debug(f"As multiplier is {multiplier} and number ({number}) is greater than 26 and less than the "
                          f"multiplier ({multiplier}) so rounding off to the multiplier {multiplier} and returning")
        return multiplier

    lower_multiple = (number // multiplier) * multiplier
    higher_multiple = lower_multiple + multiplier

    lower_difference = abs(number - lower_multiple)
    higher_difference = abs(number - higher_multiple)

    # Check if the number is closer to the lower multiple within the threshold
    if lower_difference <= threshold and lower_difference < higher_difference:
        default_log.debug(f"Returning {lower_multiple} as the nearest multiple for multiplier={multiplier} and "
                          f"number={number}")
        return lower_multiple
    # Check if the number is closer to the higher multiple within the threshold
    elif higher_difference <= threshold and higher_difference < lower_difference:
        default_log.debug(f"Returning {higher_multiple} as the nearest multiple for multiplier={multiplier} and "
                          f"number={number}")
        return higher_multiple
    # If the number is not closer to either multiple within the threshold, return the lower multiple
    else:
        default_log.debug(f"Number ({number}) is not closer to either multiple within the threshold, "
                          f"returning the lower multiple ({lower_multiple}).")
        return lower_multiple


# OLD LOGIC
# def round_to_nearest_multiplier(number, multiplier):
#     """
#         Choose between multiples of multiplier based on their distance from x.
#         If the higher multiple is within threshold points of x, choose it. Otherwise, choose the lower multiple.
#
#         Args:
#             number: The number to compare against.
#             multiplier: The multiplier
#
#         Returns:
#             The chosen multiple.
#     """
#     threshold = 15
#     default_log.debug(f"inside round_to_nearest_multiplier with number={number} and multiplier={multiplier} and a "
#                       f"threshold of {threshold} units")
#
#     # Special case: if the number is exactly divisible by the multiplier
#     if number % multiplier == 0:
#         default_log.debug(f"As the number ({number}) is exactly divisible by the multiplier ({multiplier}), "
#                           f"returning the lower multiple ({number})")
#         return number
#
#     # if multiplier is 15 then quantity should more than or equal to 10
#     if (multiplier == 15) and (number < 10):
#         default_log.debug(f"As multiplier is {multiplier} and number ({number}) is not greater than or equal to 10 "
#                           f"so returning number ({number}) and won't round off the number")
#         return number
#
#     lower_multiple = (number // multiplier) * multiplier
#     higher_multiple = lower_multiple + multiplier
#
#     if abs(number - higher_multiple) <= threshold:
#         default_log.debug(f"Returning {higher_multiple} as the nearest multiple for multiplier={multiplier} and "
#                           f"number={number}")
#         return higher_multiple
#     else:
#         default_log.debug(f"Returning {lower_multiple} as the nearest multiple for multiplier={multiplier} and "
#                           f"number={number}")
#         return lower_multiple


def place_indices_market_order(
        indice_symbol: str,
        quantity: int,
        signal_type: SignalType,
        entry_price: Optional[float] = None
) -> Union[tuple[None, None], tuple[Any, Any]]:
    """
    This function returns order id and the fill price
    """
    global use_simulation
    kite = get_kite_account_api()
    default_log.debug(f"Inside place_market_order with indices_symbol={indice_symbol} "
                      f"with quantity={quantity} and signal_type={signal_type} and entry_price={entry_price}")

    use_simulation = get_use_simulation_status()
    if use_simulation:
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
        return None, None

    default_log.debug(f"MARKET order placed for indices symbol={indice_symbol} with "
                      f"signal_type={signal_type} having quantity as "
                      f"{quantity}. Order ID: {order_id}")

    while True:
        zerodha_order_status = get_status_of_zerodha_order(kite, order_id)
        default_log.debug(f"Zerodha order status for MARKET order having id={order_id} is "
                          f"{zerodha_order_status} for indices_symbol={indice_symbol} ")

        if zerodha_order_status == "COMPLETE":
            # Now get the fill price when order was completed and then calculate the take profit
            zerodha_market_order_details = get_zerodha_order_details(kite, order_id)

            if zerodha_market_order_details is None:
                default_log.debug(f"An error occurred while fetching Zerodha MARKET order details for "
                                  f"id={order_id} for symbol={indice_symbol}")
                return None, None

            fill_price = zerodha_market_order_details['average_price']
            default_log.debug(f"Fill price of zerodha market order having id={order_id} is "
                              f"fill_price={fill_price} for symbol={indice_symbol}")

            return order_id, fill_price

        if zerodha_order_status == "REJECTED":
            default_log.debug(f"MARKET Order has been REJECTED having id={order_id} "
                              f"for indices_symbol={indice_symbol} ")
            return None, None
        tm.sleep(2)  # sleep for 2 seconds


def place_market_order(
        symbol: str,
        quantity: int,
        signal_type: SignalType,
        exchange: str = "NSE",
        entry_price: Optional[float] = None
) -> Union[tuple[None, None], tuple[Any, Any]]:
    """
        This function returns order id and the fill price
    """
    global use_simulation
    kite = get_kite_account_api()
    default_log.debug(f"Inside place_market_order with symbol={symbol}, exchange={exchange} "
                      f"with quantity={quantity} and signal_type={signal_type} and entry_price={entry_price}")

    use_simulation = get_use_simulation_status()
    if use_simulation:
        order_id = place_zerodha_order(
            kite,
            trading_symbol=symbol,
            transaction_type=signal_type,
            quantity=quantity,
            average_price=entry_price,
            exchange=exchange
        )
    else:
        order_id = place_zerodha_order(
            kite,
            trading_symbol=symbol,
            transaction_type=signal_type,
            quantity=quantity,
            exchange=exchange
        )

    if order_id is None:
        default_log.debug(f"An error occurred while placing MARKET order for symbol={symbol} with "
                          f"signal_type={signal_type} having quantity as "
                          f"{quantity}")
        return None, None

    default_log.debug(f"MARKET order placed for symbol={symbol} with "
                      f"signal_type={signal_type} having quantity as "
                      f"{quantity}. Order ID: {order_id}")

    while True:
        zerodha_order_status = get_status_of_zerodha_order(kite, order_id)
        default_log.debug(f"Zerodha order status for MARKET order having id={order_id} is "
                          f"{zerodha_order_status} for symbol={symbol} ")

        if zerodha_order_status == "COMPLETE":
            default_log.debug(f"For the symbol={symbol} the "
                              f"status of order_id: {order_id} is COMPLETE")

            # Now get the fill price when order was completed and then calculate the take profit
            zerodha_market_order_details = get_zerodha_order_details(kite, order_id)

            if zerodha_market_order_details is None:
                default_log.debug(f"An error occurred while fetching Zerodha MARKET order details for "
                                  f"id={order_id} for symbol={symbol}")
                return None, None

            fill_price = zerodha_market_order_details['average_price']
            default_log.debug(f"Fill price of zerodha market order having id={order_id} is "
                              f"fill_price={fill_price} for symbol={symbol}")

            return order_id, fill_price

        if zerodha_order_status == "REJECTED":
            default_log.debug(f"MARKET Order has been REJECTED having id={order_id} "
                              f"for symbol={symbol} ")
            return None, None
        tm.sleep(2)  # sleep for 2 seconds


def remove_sl_details_of_completed_trade(
        symbol: str,
        signal_type: SignalType,
        time_frame: int
):
    global symbol_stop_loss_details
    default_log.debug(f"inside remove_sl_details_of_completed_trade with symbol={symbol}, signal_type={signal_type} "
                      f"and timeframe={time_frame} and symbol_stop_loss_details={symbol_stop_loss_details}")

    # stop_loss_details={('NIFTY', <SignalType.BUY: 1>): {1: (22499.05, '2024-03-05 09:27 (1)')},
    # ('NIFTY', <SignalType.SELL: 2>): {1: (22440.2, '2024-03-05 09:30 (1)')}}

    # Check whether if symbol stop loss details already present
    key = (symbol, signal_type)
    symbol_stop_loss = symbol_stop_loss_details.get(key, None)
    if symbol_stop_loss is None:
        default_log.debug(f"Symbol stop loss not found for symbol ({symbol}) and time_frame ({time_frame}) "
                          f"for signal_type={signal_type}")
    else:
        # Remove the SL details of the key
        # Update the stop loss value of the symbol
        if symbol_stop_loss.get(time_frame, None) is not None:
            default_log.debug(f"Removing stop loss details for time_frame={time_frame} and key={key}")
            del symbol_stop_loss_details[key][time_frame]
        else:
            default_log.debug(f"Stop Loss details not found for time_frame={time_frame} and key={key}")
            return


def store_sl_details_of_active_trade(
        symbol: str,
        signal_type: SignalType,
        stop_loss: float,
        event1_occur_time: datetime,
        time_frame: int
):
    default_log.debug(f"inside store_sl_details_of_active_trade for symbol={symbol} having "
                      f"signal_type={signal_type}, time_frame={time_frame}, event1_occur_time={event1_occur_time} "
                      f"and stop_loss={stop_loss}")
    global symbol_stop_loss_details

    # Check whether if symbol stop loss details already present
    key = (symbol, signal_type)
    formatted_time = event1_occur_time.strftime("%Y-%m-%d %H:%M")
    event1_occur_time_details = f"{formatted_time} ({time_frame})"

    symbol_stop_loss = symbol_stop_loss_details.get(key, None)
    if symbol_stop_loss is None:
        default_log.debug(f"Adding stop loss ({stop_loss}) for symbol ({symbol}) and time_frame ({time_frame}) "
                          f"for signal_type={signal_type}")
        symbol_stop_loss_details[key] = {time_frame: (stop_loss, event1_occur_time_details)}
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

            symbol_stop_loss_details[key][time_frame] = (stop_loss, event1_occur_time_details)


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
        (timeframe, symbol): [
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

    # If no timeframe budget has been set then budget = 100% and no_of_trades=ALL_3_TRADES (This excludes
    # COVER_SL_TRADE)
    if len(timeframe_budgets) == 0:
        # If no timeframe budget details found
        key = ('basic', 'All Stocks')  # Key if timeframe budgets details not set at all
        timeframe_budget_dict[key] = TimeframeBudgetDetailsDTO(
            budget=100,  # budget would be in percentages like (10, 20, 50)
            no_of_trades=Trades.ALL_3_TRADES,
        )
        return

    for timeframe_budget in timeframe_budgets:
        # if timeframe_budget.time_frame is None:
        if timeframe_budget.symbol is None:
            key = (timeframe_budget.time_frame, 'All Stocks')  # Timeframe should not be None

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

                # If time frame budget exists for the symbol and timeframe key then add this timeframe budget details
                # in the existing timeframe budget
                timeframe_budget_dict[key] = existing_timeframe_budget
        else:
            # key = timeframe_budget.time_frame
            key = (timeframe_budget.time_frame, timeframe_budget.symbol)

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

                # If time frame budget exists for the symbol and timeframe key then add this timeframe budget details
                # in the existing timeframe budget
                timeframe_budget_dict[key] = existing_timeframe_budget
    default_log.debug(f"Stored all timeframe budgets => {timeframe_budget_dict}")
    return


def get_budget_and_no_of_trade_details(
        symbol: str,
        budget: float,
        close_price: float,
        dto: EventDetailsDTO
) -> TimeframeBudgetAndTradesDetailsDTO:
    def calculate_points_range(highest_point: float, lowest_point: float):
        default_log.debug(f"inside calculate_points_range with highest_point={highest_point} and "
                          f"lowest_point={lowest_point}")

        return abs(highest_point - lowest_point)

    global timeframe_budget_dict
    default_log.debug(f"inside get_budget_and_no_of_trade_details with symbol={symbol}, budget={budget}, "
                      f"close_price={close_price} and dto={dto}")

    timeframe_budget_and_trades_details_dto = TimeframeBudgetAndTradesDetailsDTO()

    # Check under which range the budget will lie
    points_range = calculate_points_range(dto.highest_point, dto.lowest_point)

    key_symbol = symbol
    if symbol not in indices_list:
        key_symbol = 'All Stocks'

    key = (dto.time_frame, key_symbol)
    timeframe_budgets = timeframe_budget_dict.get(key, None)
    if timeframe_budgets is None:
        # key = (dto.time_frame, 'default')
        # timeframe_budgets = timeframe_budget_dict.get(key, None)
        # if timeframe_budgets is None:
        key = ('basic', 'All Stocks')
        timeframe_budgets = timeframe_budget_dict.get(key)
        timeframe_budget_and_trades_details_dto.budget = timeframe_budgets.budget
        trades_to_make_dto = TradesToMakeDTO(
            entry_trade=True,
            extension1_trade=True,
            extension2_trade=True
        )
        timeframe_budget_and_trades_details_dto.trades_to_make = trades_to_make_dto
        timeframe_budget_and_trades_details_dto.start_range = 0
        timeframe_budget_and_trades_details_dto.end_range = 0

    target_timeframe_budget = None

    # If timeframe budgets details were not set at all then no need to check range to decide about the trades to make
    # and budget to be allotted
    if key != ('basic', 'All Stocks'):
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
    else:
        target_timeframe_budget = timeframe_budgets

    # if target_timeframe_budget is None:
    #     basic_key = 'basic'
    #     default_log.debug(f"Target Timeframe Budget not found so setting the basic timeframe budget: "
    #                       f"{timeframe_budget_dict.get(basic_key)}")
    #     target_timeframe_budget = timeframe_budget_dict.get(basic_key)

    default_log.debug(f"Target Time Frame budget = {target_timeframe_budget}")

    budget_part = target_timeframe_budget.budget
    timeframe_budget_and_trades_details_dto.budget = (budget_part / 100) * budget
    try:
        timeframe_budget_and_trades_details_dto.start_range = target_timeframe_budget.start_range
        timeframe_budget_and_trades_details_dto.end_range = target_timeframe_budget.end_range
    except Exception as e:
        default_log.debug(f"An error occurred while storing the start_range and end_range of target_timeframe_budget="
                          f"{target_timeframe_budget} in timeframe_budget_and_trades_details_dto="
                          f"{timeframe_budget_and_trades_details_dto}. Error: {e}")

    # if budget_part == BudgetPart.FULL_BUDGET:
    #     timeframe_budget_and_trades_details_dto.budget = budget
    # elif budget_part == BudgetPart.TWO_THIRD_BUDGET:
    #     timeframe_budget_and_trades_details_dto.budget = 2 * (budget / 3)
    # elif budget_part == BudgetPart.ONE_THIRD_BUDGET:
    #     timeframe_budget_and_trades_details_dto.budget = 1 * (budget / 3)
    # else:
    #     timeframe_budget_and_trades_details_dto.budget = 0

    # Decide the no of trades
    trades_to_make_dto = TradesToMakeDTO(
        entry_trade=False,
        extension1_trade=False,
        extension2_trade=False,
        cover_sl_trade=False
    )

    if target_timeframe_budget.no_of_trades == Trades.NO_TRADE:
        timeframe_budget_and_trades_details_dto.trades_to_make = trades_to_make_dto
        return timeframe_budget_and_trades_details_dto

    if target_timeframe_budget.no_of_trades == Trades.COVER_SL_TRADE:
        trades_to_make_dto.cover_sl_trade = True

    if target_timeframe_budget.no_of_trades == Trades.LAST_TRADE:
        trades_to_make_dto.extension2_trade = True
        trades_to_make_dto.cover_sl_trade = True

    if target_timeframe_budget.no_of_trades == Trades.FIRST_2_TRADES:
        trades_to_make_dto.extension1_trade = True
        trades_to_make_dto.entry_trade = True
        trades_to_make_dto.extension2_trade = False
        trades_to_make_dto.cover_sl_trade = True

    if target_timeframe_budget.no_of_trades == Trades.ALL_3_TRADES:
        trades_to_make_dto.extension1_trade = True
        trades_to_make_dto.entry_trade = True
        trades_to_make_dto.extension2_trade = True
        trades_to_make_dto.cover_sl_trade = True

    timeframe_budget_and_trades_details_dto.trades_to_make = trades_to_make_dto
    default_log.debug(f"returning timeframe_budget_and_trades_details_dto for symbol={dto.symbol} and "
                      f"timeframe={dto.time_frame}: {timeframe_budget_and_trades_details_dto}")
    return timeframe_budget_and_trades_details_dto


# def place_initial_reverse_trade(
#         data_dictionary,
#         event_data_dto: EventDetailsDTO,
#         reverse_trade_signal_type: SignalType,
#         loss_budget: float
# ):
#     default_log.debug(f"inside place_reverse_trade with symbol={event_data_dto.symbol} having time_frame="
#                       f"{event_data_dto.time_frame} with reverse_trade_signal_type={reverse_trade_signal_type} and "
#                       f"loss_budget={loss_budget} and "
#                       f"event_data_dto={event_data_dto}")
#
#     kite = get_kite_account_api()
#
#     # Calculate the quantity
#     loss_percent = loss_budget * 0.5
#
#     adjusted_sl = event_data_dto.sl_value + event_data_dto.candle_length
#
#     reverse_trade_stop_loss = event_data_dto.reverse_trade_stop_loss
#     reverse_trade_take_profit = event_data_dto.reverse_trade_take_profit
#
#     reverse_trade_quantity = loss_percent / abs(adjusted_sl - reverse_trade_stop_loss)
#     # Round off reverse_trade_quantity to 0 decimal places and convert to int
#     reverse_trade_quantity = int(round(reverse_trade_quantity, 0))
#
#     default_log.debug(f"[REVERSE 1 TRADE] As Reverse 1 Trade has not been made so for calculating the quantity "
#                       f"adjusted SL ({adjusted_sl}) and reverse_trade_stop_loss ({reverse_trade_stop_loss}) would "
#                       f"be used and loss_percent={loss_percent}. for symbol={event_data_dto.symbol} having "
#                       f"timeframe={event_data_dto.time_frame}. Calculated Reverse 1 Trade "
#                       f"Quantity={reverse_trade_quantity}")
#
#     event_data_dto.reverse1_entry_price = adjusted_sl
#     entry_price = adjusted_sl
#
#     default_log.debug(f"[REVERSE TRADE 1] Placing MARKET order with quantity={reverse_trade_quantity} for symbol="
#                       f"{event_data_dto.symbol} having timeframe={event_data_dto.time_frame}")
#
#     use_simulation = get_use_simulation_status()
#     if use_simulation:
#         reverse_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             quantity=reverse_trade_quantity,
#             transaction_type=reverse_trade_signal_type,
#             average_price=entry_price,
#             exchange="NSE"
#         )
#     else:
#         reverse_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             quantity=reverse_trade_quantity,
#             transaction_type=reverse_trade_signal_type,
#             average_price=entry_price,
#             exchange="NSE"
#         )
#
#     if reverse_trade_order_id is None:
#         default_log.debug(f"An error occurred while placing REVERSE TRADE 1 MARKET ORDER for symbol="
#                           f"{event_data_dto.symbol} having timeframe={event_data_dto.time_frame} with quantity="
#                           f"{reverse_trade_quantity}")
#         # error has occurred so returning True
#         return event_data_dto, True
#
#     event_data_dto.reverse1_trade_order_id = reverse_trade_order_id
#
#     while True:
#         zerodha_order_status = get_status_of_zerodha_order(kite, reverse_trade_order_id)
#         default_log.debug(f"[REVERSE TRADE] Zerodha order status for MARKET order having id={reverse_trade_order_id} "
#                           f"is {zerodha_order_status} for symbol={event_data_dto.symbol}")
#
#         if zerodha_order_status == "COMPLETE":
#             # Now get the fill price when order was completed and then calculate the take profit
#             zerodha_market_order_details = get_zerodha_order_details(kite, reverse_trade_order_id)
#
#             if zerodha_market_order_details is None:
#                 default_log.debug(f"[REVERSE TRADE] An error occurred while fetching Zerodha MARKET order details for "
#                                   f"id={reverse_trade_order_id} for symbol={event_data_dto.symbol}")
#                 return event_data_dto, True
#
#             fill_price = zerodha_market_order_details['average_price']
#             default_log.debug(f"[REVERSE TRADE] Fill price of zerodha market order having id={reverse_trade_order_id} "
#                               f"is fill_price={fill_price} for symbol={event_data_dto.symbol}")
#
#             # This flow used to update the Take Profit by using the fill price
#             # value_to_add_to_reverse_trade_take_profit = event_data_dto.value_to_add_to_reverse_trade_take_profit
#             # old_take_profit = event_data_dto.reverse_trade_take_profit
#             #
#             # # tp_direction = 1 if signal_type == SignalType.BUY else -1  # +1 if tp order is SELL and -1 if tp is BUY
#             # take_profit_updated = fill_price + value_to_add_to_reverse_trade_take_profit
#             #
#             # default_log.debug(f"[REVERSE TRADE] Updating old TP value={old_take_profit} to {take_profit_updated} "
#             #                   f"by adding {value_to_add_to_reverse_trade_take_profit} for MARKET "
#             #                   f"order id={reverse_trade_order_id} for symbol={event_data_dto.symbol}")
#             #
#             # take_profit_with_buffer = take_profit_updated - (take_profit_updated * (buffer_for_tp_trade / 100))
#             #
#             # default_log.debug(f"[REVERSE TRADE] Updating old TP (by subtracting buffer of [{buffer_for_tp_trade}]) "
#             #                   f"value={take_profit_updated} to {take_profit_with_buffer} for "
#             #                   f"MARKET order id={reverse_trade_order_id} for symbol={event_data_dto.symbol}")
#             #
#             # # Now update the take profit and entry price
#             # event_data_dto.reverse_trade_take_profit = take_profit_with_buffer
#
#             # Now update entry price
#             default_log.debug(f"[REVERSE TRADE 1] Updating the entry price of REVERSE TRADE 1 from "
#                               f"{event_data_dto.reverse1_entry_price} to the fill price of the REVERSE TRADE 1 of="
#                               f"{fill_price} for symbol={event_data_dto.symbol} having timeframe="
#                               f"{event_data_dto.time_frame}")
#             event_data_dto.reverse1_entry_price = fill_price
#
#             break
#
#         if zerodha_order_status == "REJECTED":
#             default_log.debug(f"[REVERSE TRADE] MARKET Order has been REJECTED having id={reverse_trade_order_id} "
#                               f"for symbol={event_data_dto.symbol}")
#             return event_data_dto, True
#         tm.sleep(2)  # sleep for 2 seconds
#
#     # Get the transaction type of the SL and TP trade
#     sl_transaction_type = tp_transaction_type = SignalType.BUY if reverse_trade_signal_type == SignalType.SELL else SignalType.SELL
#
#     # Now calculate the quantity of SL and TP trade
#     tp_quantity = sl_quantity = reverse_trade_quantity
#
#     default_log.debug(f"[REVERSE TRADE] Placing SL order for reverse_trade_order={reverse_trade_order_id} for "
#                       f"trading_symbol={event_data_dto.symbol}, transaction_type as {sl_transaction_type} "
#                       f"with quantity={tp_quantity} and stop_loss={reverse_trade_stop_loss}")
#
#     use_simulation = get_use_simulation_status()
#     if use_simulation:
#         # Place a ZERODHA order with stop loss
#         sl_order_id = place_zerodha_order_with_stop_loss(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             transaction_type=sl_transaction_type,
#             quantity=sl_quantity,
#             stop_loss=reverse_trade_stop_loss,
#             exchange="NSE"
#         )
#     else:
#         # Place a ZERODHA order with stop loss
#         sl_order_id = place_zerodha_order_with_stop_loss(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             transaction_type=sl_transaction_type,
#             quantity=sl_quantity,
#             stop_loss=reverse_trade_stop_loss,
#             exchange="NSE"
#         )
#
#     if sl_order_id is None:
#         default_log.debug(f"[REVERSE TRADE] An error occurred while placing SL order for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={sl_quantity} and stop_loss={reverse_trade_stop_loss}")
#     else:
#         default_log.debug(f"[REVERSE TRADE] Placed SL order with id={sl_order_id} "
#                           f"for reverse_trade_order_id={reverse_trade_order_id} for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={reverse_trade_quantity} and stop_loss={reverse_trade_stop_loss}")
#
#         event_data_dto.reverse_trade_sl_order_id = sl_order_id
#
#     default_log.debug(f"Placing TP order for reverse_trade_order_id={reverse_trade_order_id} for "
#                       f"trading_symbol={event_data_dto.symbol}, transaction_type as {tp_transaction_type} "
#                       f"with quantity={reverse_trade_quantity} and take_profit={reverse_trade_take_profit} ")
#
#     use_simulation = get_use_simulation_status()
#     # Place a ZERODHA order with take profit
#     if use_simulation:
#         tp_order_id = place_zerodha_order_with_take_profit(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             transaction_type=tp_transaction_type,
#             quantity=reverse_trade_quantity,
#             take_profit=reverse_trade_take_profit,
#             exchange="NSE"
#         )
#     else:
#         tp_order_id = place_zerodha_order_with_take_profit(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             transaction_type=tp_transaction_type,
#             quantity=reverse_trade_quantity,
#             take_profit=reverse_trade_take_profit,
#             exchange="NSE"
#         )
#
#     if tp_order_id is None:
#         default_log.debug(f"[REVERSE TRADE] An error occurred while placing TP order for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={reverse_trade_quantity} and take_profit={reverse_trade_take_profit}")
#     else:
#         default_log.debug(f"[REVERSE TRADE] Placed TP order with id={tp_order_id} "
#                           f"for reverse_trade_order_id={reverse_trade_order_id} for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={reverse_trade_quantity} and take_profit={reverse_trade_take_profit}")
#
#         event_data_dto.tp_order_id = tp_order_id
#
#     is_reverse_trade = True
#     event_data_dto.total_reverse_trade_quantity = reverse_trade_quantity
#     thread = threading.Thread(target=update_tp_and_sl_status, args=(event_data_dto, data_dictionary, is_reverse_trade))
#     thread.start()
#
#     return event_data_dto, False


# def place_next_reverse_trade(
#         event_data_dto: EventDetailsDTO,
#         candle_data,
#         reverse_trade_signal_type: SignalType,
#         loss_budget: float
# ):
#     default_log.debug(f"inside place_next_reverse_trade with symbol={event_data_dto.symbol} having time_frame="
#                       f"{event_data_dto.time_frame} with reverse_trade_signal_type={reverse_trade_signal_type} and "
#                       f"loss_budget={loss_budget} and "
#                       f"event_data_dto={event_data_dto}")
#
#     kite = get_kite_account_api()
#
#     # Calculate the quantity
#     loss_percent = loss_budget * 0.5
#
#     actual_sl = event_data_dto.sl_value
#
#     reverse_trade_stop_loss = event_data_dto.reverse_trade_stop_loss
#
#     reverse_trade_quantity = loss_percent / abs(actual_sl - reverse_trade_stop_loss)
#     # Round off reverse_trade_quantity to 0 decimal places and convert to int
#     reverse_trade_quantity = int(round(reverse_trade_quantity, 0))
#
#     default_log.debug(f"[REVERSE 2 TRADE] As Reverse 1 Trade has been made so for calculating the quantity "
#                       f"actual SL ({actual_sl}) and reverse_trade_stop_loss ({reverse_trade_stop_loss}) would "
#                       f"be used and loss_percent={loss_percent} for symbol={event_data_dto.symbol} having "
#                       f"timeframe={event_data_dto.time_frame}")
#     event_data_dto.reverse2_entry_price = actual_sl
#
#     use_simulation = get_use_simulation_status()
#     # Start trade
#     if use_simulation:
#         average_price = candle_data['low'] if reverse_trade_signal_type == SignalType.SELL else candle_data['high']
#         reverse_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             transaction_type=reverse_trade_signal_type,
#             quantity=reverse_trade_quantity,
#             exchange="NSE",
#             average_price=average_price
#         )
#     else:
#         reverse_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=event_data_dto.symbol,
#             transaction_type=reverse_trade_signal_type,
#             quantity=reverse_trade_quantity,
#             exchange="NSE"
#         )
#
#     while True:
#         zerodha_order_status = get_status_of_zerodha_order(kite, reverse_trade_order_id)
#         default_log.debug(f"[REVERSE TRADE 2] Zerodha order status for MARKET order having id="
#                           f"{reverse_trade_order_id} is {zerodha_order_status} for symbol="
#                           f"{event_data_dto.symbol} and ")
#
#         if zerodha_order_status == "COMPLETE":
#             default_log.debug(f"[REVERSE TRADE 2] Reverse trade 2 with id={reverse_trade_order_id} status is "
#                               f"{zerodha_order_status}")
#             zerodha_market_order_details = get_zerodha_order_details(kite, reverse_trade_order_id)
#
#             if zerodha_market_order_details is None:
#                 default_log.debug(
#                     f"[REVERSE TRADE 2] An error occurred while fetching Zerodha MARKET order details for "
#                     f"id={reverse_trade_order_id} for symbol={event_data_dto.symbol}")
#                 return event_data_dto, True
#
#             fill_price = zerodha_market_order_details['average_price']
#             default_log.debug(
#                 f"[REVERSE TRADE 2] Fill price of zerodha market order having id={reverse_trade_order_id} "
#                 f"is fill_price={fill_price} for symbol={event_data_dto.symbol}")
#
#             event_data_dto.reverse2_entry_price = fill_price
#
#             break
#
#         if zerodha_order_status == "REJECTED":
#             default_log.debug(f"[REVERSE TRADE 2] Reverse Trade 2 MARKET order with id={reverse_trade_order_id} "
#                               f"is REJECTED for symbol={event_data_dto.symbol}")
#
#             if event_data_dto.trade1_quantity is None:
#                 default_log.debug(f"[Reverse Trade 2 order has been rejected] Setting Reverse Trade 2 quantity as 0 as "
#                                   f"trade1_quantity={event_data_dto.trade1_quantity}")
#                 event_data_dto.trade1_quantity = 0
#
#             event_data_dto.extension_quantity = event_data_dto.trade1_quantity if event_data_dto.extension_quantity is None else event_data_dto.extension_quantity
#
#             return event_data_dto, True
#
#         tm.sleep(2)  # sleep for 2 seconds
#
#     sl_quantity = tp_quantity = event_data_dto.reverse1_trade_quantity + reverse_trade_quantity
#     sl_transaction_type = tp_transaction_type = SignalType.BUY if reverse_trade_signal_type == SignalType.SELL else SignalType.SELL
#
#     default_log.debug(f"[REVERSE TRADE 2] Placing SL order for reverse_trade_order={reverse_trade_order_id} for "
#                       f"trading_symbol={event_data_dto.symbol}, transaction_type as {sl_transaction_type} "
#                       f"with quantity={sl_quantity} and stop_loss={reverse_trade_stop_loss}")
#
#     use_simulation = get_use_simulation_status()
#     # Add stop loss and take profit while updating the SL-M and LIMIT order
#     # Update a ZERODHA order with stop loss quantity
#     if use_simulation:
#         sl_order_id = update_zerodha_order_with_stop_loss(
#             kite=kite,
#             zerodha_order_id=event_data_dto.reverse_trade_sl_order_id,
#             trade_quantity=sl_quantity,
#             quantity=sl_quantity,
#             transaction_type=sl_transaction_type,
#             trading_symbol=event_data_dto.symbol,
#             candle_high=candle_data['high'],
#             candle_low=candle_data['low'],
#             exchange="NSE"
#         )
#     else:
#         sl_order_id = update_zerodha_order_with_stop_loss(
#             kite=kite,
#             zerodha_order_id=event_data_dto.reverse_trade_sl_order_id,
#             trade_quantity=sl_quantity,
#             quantity=sl_quantity,
#             trading_symbol=event_data_dto.symbol,
#             transaction_type=sl_transaction_type,
#             exchange="NSE"
#         )
#
#     if sl_order_id is None:
#         default_log.debug(f"[REVERSE TRADE 2] An error occurred while UPDATING SL order for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={sl_quantity}")
#     else:
#         default_log.debug(f"[REVERSE TRADE 2] UPDATED SL order with id={sl_order_id} "
#                           f"for reverse_trade_order_id={reverse_trade_order_id} for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={sl_quantity}")
#
#         event_data_dto.reverse_trade_sl_order_id = sl_order_id
#
#     default_log.debug(f"[REVERSE TRADE 2] UPDATING TP order for reverse_trade_order_id={reverse_trade_order_id} for "
#                       f"trading_symbol={event_data_dto.symbol}, transaction_type as {tp_transaction_type} "
#                       f"with quantity={tp_quantity}")
#
#     use_simulation = get_use_simulation_status()
#     # Update a ZERODHA order with take profit
#     if use_simulation:
#         tp_order_id = update_zerodha_order_with_take_profit(
#             kite=kite,
#             zerodha_order_id=event_data_dto.reverse_trade_tp_order_id,
#             transaction_type=tp_transaction_type,
#             trade_quantity=tp_quantity,
#             quantity=tp_quantity,
#             trading_symbol=event_data_dto.symbol,
#             candle_high=candle_data['high'],
#             candle_low=candle_data['low'],
#             exchange="NSE"
#         )
#     else:
#         tp_order_id = update_zerodha_order_with_take_profit(
#             kite=kite,
#             zerodha_order_id=event_data_dto.reverse_trade_tp_order_id,
#             transaction_type=tp_transaction_type,
#             trade_quantity=tp_quantity,
#             quantity=tp_quantity,
#             trading_symbol=event_data_dto.symbol,
#             exchange="NSE"
#         )
#
#     if tp_order_id is None:
#         default_log.debug(f"[REVERSE TRADE 2] An error occurred while UPDATING TP order for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={tp_quantity}")
#     else:
#         default_log.debug(f"[REVERSE TRADE 2] UPDATED TP order with id={tp_order_id} "
#                           f"for reverse_trade_order_id={reverse_trade_order_id} for "
#                           f"trading_symbol={event_data_dto.symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={tp_quantity}")
#
#         event_data_dto.reverse_trade_tp_order_id = tp_order_id
#
#     return event_data_dto, False


def do_update_of_sl_values(
        timeframe: int,
        entry_price: float,
        close_price: float,
        signal_type: SignalType,
        symbol: str
) -> tuple[bool, float, str]:
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
    # If any data present then it will return the data in the following format:
    # {'timeframe': (stop_loss, event1_occur_time), 'timeframe2': (stop_loss, event1_occur_time)}

    update_sl = False  # keep track if sl needs to be updated
    sl_value_to_update_to = 0  # value to be updated to
    if symbol_stop_loss_time_frames_with_stop_loss is None:
        default_log.debug("Not updating SL value as no symbol_stop_loss_time_frames_with_stop_loss found "
                          f"for key={key} and time_frame={timeframe}")
        return update_sl, sl_value_to_update_to, ""

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
        return update_sl, sl_value_to_update_to, ""

    # Get all timeframe:sl value dictionaries that are just bigger than the current timeframe
    bigger_timeframe_with_sl_values_list = [
        {sl_timeframe: sl_value_with_event1_occur_time} for sl_timeframe, sl_value_with_event1_occur_time in
        symbol_stop_loss_time_frames_with_stop_loss.items() if sl_timeframe in bigger_timeframes
    ]

    default_log.debug(
        f"bigger_timeframe_with_sl_values_list={bigger_timeframe_with_sl_values_list} for symbol={symbol} "
        f"and timeframe={timeframe} with key={key}")

    current_timeframe_sl_value, event1_occur_time = symbol_stop_loss_time_frames_with_stop_loss[timeframe]
    # times_multiplied_sl = current_timeframe_sl_value * 1.5
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
        time_frame, timeframe_sl_value_with_event1_occur_time = list(timeframe_sl_dict.items())[0]
        timeframe_sl_value, event1_occur_time = timeframe_sl_value_with_event1_occur_time

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

                return update_sl, sl_value_to_update_to, event1_occur_time
            else:

                default_log.debug(f"Can update SL of key={key} from {current_timeframe_sl_value} to "
                                  f"{timeframe_sl_value}. But, won't do it as the condition "
                                  f"(start_threshold [{start_threshold}] < sl_and_entry_price_difference "
                                  f"[{sl_and_entry_price_difference}] < end_threshold [{end_threshold}]) is not "
                                  f"satisfied when sl is update from {current_timeframe_sl_value} to "
                                  f"{timeframe_sl_value} ")

    return update_sl, sl_value_to_update_to, ""

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
        key = ('default', time_frame)
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

    default_log.debug(f"Stored all symbol budgets => {budget_dict}")


def log_event_trigger(dto: CheckEventsDTO, alert_time: datetime):
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
    global latest_trade_tracking_alerts
    default_log.debug(f"inside log_event_trigger with dto={dto} and alert_time={alert_time}")
    symbol = dto.symbol
    inst_token = instrument_tokens_map.get(dto.symbol, None)

    # Acquire the lock
    latest_trade_tracking_lock.acquire()

    if len(latest_trade_tracking_alerts) > 0:
        default_log.debug(f"checking current tracking alert ({dto}) is duplicate or not from "
                          f"latest_trade_tracking_alerts ({latest_trade_tracking_alerts})")

        current_alert_time = alert_time
        last_tracking_alert, last_alert_time = latest_trade_tracking_alerts[-1]
        # symbol: str
        #     time_frame_in_minutes: str
        #     signal_type: str

        difference_in_seconds_between_alerts = (current_alert_time - last_alert_time).total_seconds()

        if (last_tracking_alert.symbol == dto.symbol) and \
                (last_tracking_alert.time_frame_in_minutes == dto.time_frame_in_minutes) and \
                (last_tracking_alert.signal_type == dto.signal_type) and \
                difference_in_seconds_between_alerts < 10:
            default_log.debug(f"As last alert with alert_time={last_alert_time} with symbol={dto.symbol} "
                              f"and time_frame_in_minutes={dto.time_frame_in_minutes} and signal_type={dto.signal_type} "
                              f"have less than 10 seconds difference between current_alert_time={current_alert_time}. "
                              f"So not tracking it!")
            # Release the lock
            latest_trade_tracking_lock.release()
            return
        latest_trade_tracking_alerts.append((dto, alert_time))

    if len(latest_trade_tracking_alerts) == 0:
        default_log.debug(f"Adding current alert tracking={dto} with the alert_time={alert_time}")
        latest_trade_tracking_alerts.append((dto, alert_time))

    exchange = "NFO" if symbol in indices_list else "NSE"
    if inst_token is None:
        inst_token = get_instrument_token_for_symbol(symbol, exchange)
        default_log.debug(f"instrument token received for symbol={symbol} and exchange={exchange}: "
                          f"{inst_token}")

    time_frame = dto.time_frame_in_minutes

    try:
        default_log.debug(f"Converting string value of {dto.signal_type} to SignalType value")
        signal_type = SignalType(int(dto.signal_type))
        default_log.debug(f"Converted string value {dto.signal_type} to {signal_type}")
    except Exception as e:
        default_log.debug(f"An error occurred while converting string signal type value ({dto.signal_type}) to "
                          f"SignalType value for symbol={dto.symbol}. Error: {e}")
        # Release the lock
        latest_trade_tracking_lock.release()
        return

    configuration = Configuration.HIGH if dto.signal_type == SignalType.BUY else Configuration.LOW

    # Create and start a thread for each symbol
    if signal_type == SignalType.BUY:
        thread = threading.Thread(target=start_market_logging_for_buy,
                                  args=(symbol, time_frame, inst_token, 2, configuration, alert_time))
        thread.start()
    else:
        thread = threading.Thread(target=start_market_logging_for_sell,
                                  args=(symbol, time_frame, inst_token, 2, configuration, alert_time))
        thread.start()

    # Release the lock
    latest_trade_tracking_lock.release()
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

        # market_symbol = ""

        # for k, v in instrument_tokens_map.items():
        #     if v == instrument_token:
        #         market_symbol = k

        if interval == "minute":
            time_frame = 1
        else:
            time_frame = int(interval.split('minute')[0])

        if from_date is not None:
            current_timestamp = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
            from_date_without_timezone = from_date.replace(tzinfo=None)
            from_date_with_ist_timezone = pytz.timezone("Asia/Kolkata").localize(from_date_without_timezone)
            # to_timestamp = from_date_with_ist_timezone.astimezone(pytz.timezone("Asia/Kolkata")) + timedelta(minutes=time_frame)
            to_timestamp = from_date_with_ist_timezone + timedelta(
                minutes=time_frame)

            if to_timestamp >= current_timestamp:
                default_log.debug(f"Stopping receiving of historical data and starting to get the tick data as "
                                  f"to_timestamp ({to_timestamp}) >= current_timestamp ({current_timestamp})")

                is_restart = False
                from_date = None

        current_datetime = None
        if is_restart:
            from_date_without_timezone = from_date.replace(tzinfo=None)
            from_date = pytz.timezone("Asia/Kolkata").localize(from_date_without_timezone)
            current_datetime = from_date + timedelta(minutes=time_frame)
            # current_datetime = current_datetime.astimezone(pytz.timezone("Asia/Kolkata"))
            # from_date = from_date.astimezone(pytz.timezone("Asia/Kolkata"))
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

        use_simulation = get_use_simulation_status()
        if use_simulation:

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

        if use_global_feed:
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
    symbol = symbol_tokens_map.get(instrument_token, None)

    if symbol is None:
        inst_token = str(instrument_token)
        symbol = get_symbol_for_instrument_token(inst_token)
        default_log.debug(f"Symbol Details fetched for instrument_token ({inst_token}) => {symbol}")

    default_log.debug(f"inside get_next_data with "
                      f"is_restart={is_restart} "
                      f"timeframe={timeframe} "
                      f"instrument_token={instrument_token} "
                      f"interval={interval} "
                      f"from_timestamp={from_timestamp} "
                      f"and symbol={symbol}")

    if is_restart:
        # wait_time = get_wait_time(timestamp, int(timeframe))
        use_simulation = get_use_simulation_status()
        if use_simulation:
            wait_time = 0
        else:
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
        use_simulation = get_use_simulation_status()
        if use_simulation:
            wait_time = 0
        else:
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

    timestamp = candle_data["time"]

    if event1_signal_type == SignalType.BUY:
        current_candle_high = candle_data["high"]
        # Set the H1 data
        event_data_dto.high_1 = current_candle_high if event_data_dto.high_1 is None else event_data_dto.high_1

        # Get the H1 data
        if current_candle_high > event_data_dto.high_1:
            default_log.debug(f"Highest Point (H1) found at={timestamp} "
                              f"H1={current_candle_high}")

            event_data_dto.high_1 = current_candle_high

        # To Calculate the TP data
        sl_minus_h1 = event_data_dto.sl_value - event_data_dto.high_1

        h1_minus_h = event_data_dto.high_1 - h

        greatest = max(h1_minus_h, sl_minus_h1)

        # tp_val = (event_data_dto.entry_price - greatest)
        # tp_val = (h - greatest)
        tp_val = (event_data_dto.high_1 - greatest)
        # tp_buffer = None
        # update tp value
        if event_data_dto.symbol not in indices_list:
            default_log.debug(f"For TP value for symbol={event_data_dto.symbol} and "
                              f"timeframe={event_data_dto.time_frame} at timestamp={timestamp} calculating TP value "
                              f"by subtracting extra percent buffer of {buffer_for_tp_trade}")

            tp_buffer = buffer_for_tp_trade

            # Calculate TP with buffer
            tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))
        else:
            default_log.debug(f"For TP value for symbol={event_data_dto.symbol} and "
                              f"timeframe={event_data_dto.time_frame} at timestamp={timestamp} calculating TP value "
                              f"by subtracting extra percent buffer of {buffer_for_indices_tp_trade}")

            tp_buffer = buffer_for_indices_tp_trade

            # Calculate TP with buffer
            tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))

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
                              f"L1={current_candle_low}")

            event_data_dto.low_1 = current_candle_low

        # To Calculate the TP data
        l1_minus_sl = event_data_dto.low_1 - event_data_dto.sl_value

        l_minus_l1 = l - event_data_dto.low_1

        greatest = max(l1_minus_sl, l_minus_l1)

        # tp_val = (event_data_dto.entry_price + greatest)
        # tp_val = (l + greatest)
        tp_val = (event_data_dto.low_1 + greatest)

        # update tp value
        if event_data_dto.symbol not in indices_list:
            default_log.debug(f"For TP value for symbol={event_data_dto.symbol} and "
                              f"timeframe={event_data_dto.time_frame} at timestamp={timestamp} calculating TP value "
                              f"by subtracting extra percent buffer of {buffer_for_tp_trade}")

            tp_buffer = buffer_for_tp_trade

            # Calculate TP with buffer
            tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))
        else:
            default_log.debug(f"For TP value for symbol={event_data_dto.symbol} and "
                              f"timeframe={event_data_dto.time_frame} at timestamp={timestamp} calculating TP value "
                              f"by subtracting extra percent buffer of {buffer_for_indices_tp_trade}")

            tp_buffer = buffer_for_indices_tp_trade

            # Calculate TP with buffer
            tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))

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
        tp_buffer_percent=tp_buffer,
        tp_with_buffer=tp_with_buffer
    )

    event_data_dto.tp_values.append(tp_details)

    return event_data_dto


def trade_logic_sell(
        symbol: str, timeframe: str, candle_data: pd.DataFrame,
        data_dictionary: dict[tuple[str, str], Optional[EventDetailsDTO]],
        is_continuity: Optional[bool] = False
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
    default_log.debug(f"inside trade_logic_sell with symbol={symbol} having time_frame={timeframe} and "
                      f"candle_data={candle_data} and data_dictionary={data_dictionary}")
    key = (symbol, timeframe)

    event_data_dto = data_dictionary.get(key, False)

    if event_data_dto:
        highest_point = None
        lowest_point = None
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
                highest_point = current_candle_high
                # event_data_dto.highest_point = current_candle_high

            current_lowest_point = event_data_dto.lowest_point if event_data_dto.lowest_point is not None else current_candle_low
            if current_candle_low <= current_lowest_point:
                default_log.debug(f"Lowest point found lower than {current_lowest_point} = {current_candle_low} "
                                  f"at {timestamp}")
                lowest_point = current_candle_low
                # event_data_dto.lowest_point = current_candle_low

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

            # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
            if highest_point is not None:
                default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                  f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                event_data_dto.highest_point = highest_point

            if lowest_point is not None:
                default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                  f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                event_data_dto.lowest_point = lowest_point

            data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        # Check for AH condition
        # If event 3 occurs before event 2
        if event_data_dto.event2_occur_time is None:

            if (timestamp.hour < event_data_dto.event1_occur_time.hour or
                (timestamp.hour == event_data_dto.event1_occur_time.hour and
                 timestamp.minute <= event_data_dto.event1_occur_time.minute)) and (not is_continuity):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
                                  f"({event_data_dto.event1_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

            # TODO: add a flow that updates highest and lowest point if continuity
            if is_continuity:
                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

            event1_candle_high = event_data_dto.event1_candle_high
            event1_candle_low = event_data_dto.event1_candle_low

            candle_high = event_data_dto.adjusted_high if event_data_dto.adjusted_high is not None else event1_candle_high
            if current_candle_high > candle_high:
                default_log.debug(f"Adjusted HIGH condition occurred at timestamp={timestamp} as "
                                  f"current_candle_high ({current_candle_high}) > candle_high ({candle_high}) "
                                  f"for symbol={symbol} having timeframe={timeframe}")

                # Check if event 2 occurs with the previous event2_breakpoint before updating the adjusted value
                event2_occurring_breakpoint = event_data_dto.event2_occur_breakpoint
                if current_candle_low < event2_occurring_breakpoint:
                    default_log.debug(
                        f"Event 2 occurred as at timestamp={timestamp} before adjusted high condition"
                        f"Candle Low={current_candle_low} < Buy Candle Event 2 occurring breakpoint={event2_occurring_breakpoint}")

                    event_data_dto.event2_occur_time = timestamp

                    # data_dictionary[key] = event_data_dto
                    #
                    # return event_data_dto, data_dictionary

                else:
                    # The condition for a sell signal in the "HIGH" configuration has been met
                    # You can add your sell signal logic here

                    # For example, update event_data_dto or perform other actions for a sell signal
                    event_data_dto.adjusted_high = current_candle_high

                    # Update the event2_occur_breakpoint for the sell signal
                    event_data_dto.event2_occur_breakpoint = event_data_dto.event1_candle_low - (
                            event_data_dto.adjusted_high - event_data_dto.event1_candle_low)

                    event_data_dto.combined_height = (event_data_dto.adjusted_high - event_data_dto.event1_candle_low)

                    # Adjusted is only used for calculation of SL value
                    # event_data_dto.event2_occur_breakpoint = event_data_dto.event1_candle_low - (
                    #         event_data_dto.event1_candle_high - event_data_dto.event1_candle_low)

                    event_data_dto.previous_timestamp = timestamp
                    # data_dictionary[key] = event_data_dto

                # return event_data_dto, data_dictionary

        # The event 1 has already happened
        # Check for event 2
        if event_data_dto.event2_occur_time is None:
            previous_timestamp = event_data_dto.previous_timestamp

            # Check first Event 2 condition
            event2_occurring_breakpoint = event_data_dto.event2_occur_breakpoint
            if current_candle_low < event2_occurring_breakpoint:
                default_log.debug(
                    f"Event 2 occurred as at timestamp={timestamp}"
                    f"Candle Low={current_candle_low} < Buy Candle Event 2 occurring breakpoint={event2_occurring_breakpoint}")

                event_data_dto.event2_occur_time = timestamp

                data_dictionary[key] = event_data_dto

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

            # Check whether the adjusted_high has traced more than the candle length, if yes then stop tracking
            if event_data_dto.adjusted_high is not None:
                adjusted_difference = event_data_dto.adjusted_high - event_data_dto.event1_candle_high

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = event1_candle_height
                event_data_dto.combined_height = event_data_dto.adjusted_high - event_data_dto.event1_candle_low

                if adjusted_difference > event1_candle_height:
                    default_log.debug(f"The adjusted_high difference={adjusted_difference} has gone above "
                                      f"by more than the candle_length={event_data_dto.candle_length} so stopping "
                                      f"tracking of the events for symbol={symbol} having timeframe={timeframe}. "
                                      f"Event 1 Candle Low ({event_data_dto.event1_candle_low}), Adjusted High "
                                      f"({event_data_dto.adjusted_high}), Event 1 Candle High "
                                      f"({event_data_dto.event1_candle_high})")
                    event_data_dto.stop_tracking_further_events = True
                    data_dictionary[key] = event_data_dto

                    # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                    if highest_point is not None:
                        default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                          f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                        event_data_dto.highest_point = highest_point

                    if lowest_point is not None:
                        default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                          f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                        event_data_dto.lowest_point = lowest_point

                    data_dictionary[key] = event_data_dto

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

            # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
            if highest_point is not None:
                default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                  f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                event_data_dto.highest_point = highest_point

            if lowest_point is not None:
                default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                  f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                event_data_dto.lowest_point = lowest_point

            data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        # Check for event 3
        if (event_data_dto.event3_occur_time is None) and (event_data_dto.event2_occur_time is not None):

            if (timestamp.hour < event_data_dto.event2_occur_time.hour or
                (timestamp.hour == event_data_dto.event2_occur_time.hour and
                 timestamp.minute <= event_data_dto.event2_occur_time.minute)) and (not is_continuity):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 2 occur time "
                                  f"({event_data_dto.event2_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

            sell_candle_high = event_data_dto.event1_candle_high if event_data_dto.adjusted_high is None else event_data_dto.adjusted_high
            sell_candle_low = event_data_dto.event1_candle_low if event_data_dto.adjusted_low is None else event_data_dto.adjusted_low
            timestamp = candle_data["time"]

            # candle_high_to_check = sell_candle_high if configuration == Configuration.HIGH else sell_candle_low
            if event_data_dto.symbol not in indices_list:
                default_log.debug(f"Adding a buffer percent ({buffer_for_entry_trade}) from the sell_candle_low "
                                  f"({sell_candle_low}) as the breakpoint for event 3 for symbol={event_data_dto.symbol} "
                                  f"and time_frame={event_data_dto.time_frame}")

                candle_high_to_check = sell_candle_low + (sell_candle_low * (buffer_for_entry_trade / 100))
                event_data_dto.event3_occur_breakpoint = candle_high_to_check
            else:
                default_log.debug(f"Adding a buffer percent ({buffer_for_indices_entry_trade}) "
                                  f"from the sell_candle_low ({sell_candle_low}) as the breakpoint for "
                                  f"event 3 for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")

                candle_high_to_check = sell_candle_low + (sell_candle_low * (buffer_for_indices_entry_trade / 100))
                event_data_dto.event3_occur_breakpoint = candle_high_to_check

            if current_candle_high > candle_high_to_check:
                default_log.debug(f"Event 3 occurred for symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} at timestamp={timestamp}")
                default_log.debug(f"Event 3 occurred as Current Candle High={current_candle_high} > "
                                  f"candle_high_to_check={candle_high_to_check}")
                # event_data_dto.entry_price = current_candle_high
                event_data_dto.entry_price = sell_candle_low
                event_data_dto.event3_occur_time = timestamp

                # Calculate SL
                # value_to_add_for_stop_loss_entry_price = (
                #         event_data_dto.highest_point - event_data_dto.event1_candle_low)

                value_to_add_for_stop_loss_entry_price = (
                        event_data_dto.highest_point - event_data_dto.lowest_point)

                if event_data_dto.adjusted_high is not None:
                    default_log.debug(f"Calculating combined difference using adjusted_high "
                                      f"({event_data_dto.adjusted_high}) and event1_candle_low "
                                      f"({event_data_dto.event1_candle_low})")
                    event_data_dto.combined_height = event_data_dto.adjusted_high - event_data_dto.event1_candle_low
                    event_data_dto.sl_buffer = event_data_dto.combined_height
                else:
                    default_log.debug(f"Calculating sl buffer difference using event1_candle_high "
                                      f"({event_data_dto.event1_candle_high}) and event1_candle_high "
                                      f"({event_data_dto.event1_candle_low})")
                    event_data_dto.sl_buffer = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = event1_candle_height

                # sl_value = event_data_dto.entry_price + value_to_add_for_stop_loss_entry_price
                sl_value = event_data_dto.highest_point + value_to_add_for_stop_loss_entry_price

                event_data_dto.value_to_add_for_stop_loss_entry_price = value_to_add_for_stop_loss_entry_price

                event_data_dto.sl_value = sl_value

                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.BUY)

                data_dictionary[key] = event_data_dto
            else:

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                # CHECK RANGE ISSUE
                start_range, end_range = fetch_start_and_end_range(symbol=symbol, timeframe=timeframe)
                if (start_range is None) or (end_range is None):
                    default_log.debug(
                        f"Start Range and End Range has not been defined for symbol={symbol} having timeframe="
                        f"{timeframe}")
                    event_data_dto.range_issue = True
                    data_dictionary[key] = event_data_dto

                    return event_data_dto, data_dictionary

                # CHECK RANGE ISSUE
                decreased_price = event_data_dto.event2_occur_breakpoint - (
                        event_data_dto.event2_occur_breakpoint * (end_range / 100))
                if current_candle_low < decreased_price:
                    default_log.debug(f"As the candle low ({current_candle_low}) has reached less than the "
                                      f"decreased_price ({decreased_price}) which is calculated using "
                                      f"event2_breakpoint ({event_data_dto.event2_occur_breakpoint}) and end_range% "
                                      f"({end_range}%) for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.range_issue = True
                    data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        if (event_data_dto.event2_occur_time is not None) and (
                event_data_dto.event3_occur_time is not None):

            current_timestamp = candle_data['time']
            previous_tp_timestamp = event_data_dto.tp_values[-1].timestamp

            # PREVIOUS TP Timestamp can be None when restart flow is working
            if previous_tp_timestamp is not None:
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
            combined_height=candle_data["high"] - candle_data["low"],
            highest_point=candle_data["high"],
            lowest_point=candle_data["low"],
            event2_occur_breakpoint=event2_occur_breakpoint,
            previous_timestamp=timestamp,
            stop_tracking_further_events=False,
            range_issue=False
        )

        data_dictionary[key] = dto

        return dto, data_dictionary


def trade_logic_buy(
        symbol: str,
        timeframe: str,
        candle_data: pd.DataFrame,
        data_dictionary: dict[tuple[str, str], Optional[EventDetailsDTO]],
        is_continuity: Optional[bool] = False
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
    default_log.debug(f"inside trade_logic_buy with symbol={symbol} having time_frame={timeframe} and "
                      f"candle_data={candle_data} and data_dictionary={data_dictionary}")
    key = (symbol, timeframe)

    event_data_dto = data_dictionary.get(key, False)

    default_log.debug(f"Candle Data={candle_data}")

    if event_data_dto:
        highest_point = None
        lowest_point = None
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
                lowest_point = current_candle_low
                # event_data_dto.lowest_point = current_candle_low

            current_highest_point = event_data_dto.highest_point if event_data_dto.highest_point else current_candle_high
            if current_candle_high >= current_highest_point:
                default_log.debug(f"Highest point found higher than {current_highest_point} i.e. {current_candle_high} "
                                  f"at {timestamp}")
                highest_point = current_candle_high
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

            if (timestamp.hour < event_data_dto.event1_occur_time.hour or
                (timestamp.hour == event_data_dto.event1_occur_time.hour and
                 timestamp.minute <= event_data_dto.event1_occur_time.minute)) and (not is_continuity):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 1 occur time "
                                  f"({event_data_dto.event1_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame} and is_continuity={is_continuity}")

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

            # TODO: add a flow that updates highest and lowest point if continuity
            if is_continuity:
                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

            buy_candle_high = event_data_dto.event1_candle_high
            buy_candle_low = event_data_dto.event1_candle_low

            candle_low = event_data_dto.adjusted_low if event_data_dto.adjusted_low is not None else buy_candle_low
            if current_candle_low < candle_low:

                # First check for event 2
                event2_occurring_breakpoint = event_data_dto.event2_occur_breakpoint
                if current_candle_high > event2_occurring_breakpoint:
                    default_log.debug(f"Event 2 occurred as Current Candle High={current_candle_high} > "
                                      f"event2_occurring_breakpoint={event2_occurring_breakpoint} at timestamp={timestamp}")

                    event_data_dto.event2_occur_time = timestamp

                else:
                    default_log.debug(f"Adjusted LOW condition occurred at timestamp={timestamp} as "
                                      f"current_candle_low ({current_candle_low}) < candle_low ({candle_low}) "
                                      f"for symbol={symbol} having timeframe={timeframe}")

                    event_data_dto.adjusted_low = current_candle_low

                    # Update the event2_occur_breakpoint
                    event_data_dto.event2_occur_breakpoint = event_data_dto.event1_candle_high + (
                            event_data_dto.event1_candle_high - event_data_dto.adjusted_low)

                    event_data_dto.combined_height = event_data_dto.event1_candle_high - event_data_dto.adjusted_low

                    # Adjusted is only used for calculation of SL value
                    # event_data_dto.event2_occur_breakpoint = event_data_dto.event1_candle_high + (
                    #         event_data_dto.event1_candle_high - event_data_dto.event1_candle_low)

                    event_data_dto.previous_timestamp = timestamp

                # data_dictionary[key] = event_data_dto
                # return event_data_dto, data_dictionary

        # The event 1 has already happened
        # Check for event 2
        if event_data_dto.event2_occur_time is None:
            previous_timestamp = event_data_dto.previous_timestamp

            # Check for event 2 first
            event2_occurring_breakpoint = event_data_dto.event2_occur_breakpoint
            if current_candle_high > event2_occurring_breakpoint:
                default_log.debug(f"Event 2 occurred as Current Candle High={current_candle_high} > "
                                  f"event2_occurring_breakpoint={event2_occurring_breakpoint} at timestamp={timestamp}")

                event_data_dto.event2_occur_time = timestamp

                data_dictionary[key] = event_data_dto

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

            # Check whether the adjusted_low has traced more than the candle length, if yes then stop tracking
            if event_data_dto.adjusted_low is not None:
                adjusted_difference = event_data_dto.event1_candle_low - event_data_dto.adjusted_low

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = event1_candle_height
                event_data_dto.combined_height = event_data_dto.event1_candle_high - event_data_dto.adjusted_low

                if adjusted_difference > event_data_dto.candle_length:
                    default_log.debug(f"The adjusted_low_difference={adjusted_difference} has gone below "
                                      f"by more than the candle_length={event_data_dto.candle_length} so stopping "
                                      f"tracking of the events for symbol={symbol} and time_frame={timeframe}. "
                                      f"Event 1 Candle Low ({event_data_dto.event1_candle_low}), Adjusted Low "
                                      f"({event_data_dto.adjusted_low}), Event 1 Candle High "
                                      f"({event_data_dto.event1_candle_high})")
                    event_data_dto.stop_tracking_further_events = True

                    # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                    if highest_point is not None:
                        default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                          f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                        event_data_dto.highest_point = highest_point

                    if lowest_point is not None:
                        default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                          f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                        event_data_dto.lowest_point = lowest_point

                    data_dictionary[key] = event_data_dto

                    return event_data_dto, data_dictionary

            # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
            if highest_point is not None:
                default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                  f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                event_data_dto.highest_point = highest_point

            if lowest_point is not None:
                default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                  f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                event_data_dto.lowest_point = lowest_point

            data_dictionary[key] = event_data_dto

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

        # Check for event 3
        if (event_data_dto.event3_occur_time is None) and (event_data_dto.event2_occur_time is not None):

            if (timestamp.hour < event_data_dto.event2_occur_time.hour or
                (timestamp.hour == event_data_dto.event2_occur_time.hour and
                 timestamp.minute <= event_data_dto.event2_occur_time.minute)) and (not is_continuity):
                default_log.debug(f"Current Timestamp ({timestamp}) is earlier/equal than Event 2 occur time "
                                  f"({event_data_dto.event2_occur_time}) for symbol={event_data_dto.symbol} and "
                                  f"time_frame={event_data_dto.time_frame}")

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                return event_data_dto, data_dictionary

            buy_candle_high = event_data_dto.event1_candle_high if event_data_dto.adjusted_high is None else event_data_dto.adjusted_high
            buy_candle_low = event_data_dto.event1_candle_low if event_data_dto.adjusted_low is None else event_data_dto.adjusted_low
            timestamp = candle_data["time"]

            # candle_low_to_check = buy_candle_high if configuration == Configuration.HIGH else buy_candle_low
            if event_data_dto.symbol not in indices_list:
                default_log.debug(f"Adding a buffer percent ({buffer_for_entry_trade}) to the buy_candle_high "
                                  f"({buy_candle_high}) as the breakpoint for event 3 for symbol={event_data_dto.symbol} "
                                  f"and time_frame={event_data_dto.time_frame}")

                candle_low_to_check = buy_candle_high + (buy_candle_high * (buffer_for_entry_trade / 100))
                event_data_dto.event3_occur_breakpoint = candle_low_to_check
            else:
                default_log.debug(f"Adding a buffer percent ({buffer_for_indices_entry_trade}) to the buy_candle_high "
                                  f"({buy_candle_high}) as the breakpoint for event 3 for symbol={event_data_dto.symbol} "
                                  f"and time_frame={event_data_dto.time_frame}")

                candle_low_to_check = buy_candle_high + (buy_candle_high * (buffer_for_indices_entry_trade / 100))
                event_data_dto.event3_occur_breakpoint = candle_low_to_check

            if current_candle_low < candle_low_to_check:
                default_log.debug(f"Event 3 occurred for symbol={event_data_dto.symbol} and "
                                  f"timeframe={event_data_dto.time_frame} at timestamp={timestamp}")
                default_log.debug(f"Event 3 occurred as Current Candle Low={current_candle_low} < "
                                  f"candle_low_to_check={candle_low_to_check}")
                # event_data_dto.entry_price = current_candle_low
                event_data_dto.entry_price = buy_candle_high

                # value_to_add_for_stop_loss_entry_price = -(
                #         event_data_dto.event1_candle_high - event_data_dto.lowest_point)

                value_to_add_for_stop_loss_entry_price = -(
                        event_data_dto.highest_point - event_data_dto.lowest_point)

                default_log.debug(f"Value to add to stop loss = {value_to_add_for_stop_loss_entry_price} using "
                                  f"highest_point={event_data_dto.highest_point} and lowest_point="
                                  f"{event_data_dto.lowest_point} for symbol={event_data_dto.symbol} having "
                                  f"timeframe={event_data_dto.time_frame}")

                if event_data_dto.adjusted_low is not None:
                    default_log.debug(f"Calculating combined difference using adjusted_low "
                                      f"({event_data_dto.adjusted_low}) and event1_candle_high "
                                      f"({event_data_dto.event1_candle_high})")
                    event_data_dto.combined_height = event_data_dto.event1_candle_high - event_data_dto.adjusted_low
                    event_data_dto.sl_buffer = -event_data_dto.combined_height
                else:
                    default_log.debug(f"Calculating sl buffer difference using event1_candle_high "
                                      f"({event_data_dto.event1_candle_high}) and event1_candle_low "
                                      f"({event_data_dto.event1_candle_low})")
                    event_data_dto.sl_buffer = -(event_data_dto.event1_candle_high - event_data_dto.event1_candle_low)

                event1_candle_height = event_data_dto.event1_candle_high - event_data_dto.event1_candle_low
                event_data_dto.candle_length = -event1_candle_height

                # sl_value = event_data_dto.entry_price + value_to_add_for_stop_loss_entry_price
                sl_value = event_data_dto.lowest_point + value_to_add_for_stop_loss_entry_price

                event_data_dto.value_to_add_for_stop_loss_entry_price = value_to_add_for_stop_loss_entry_price

                event_data_dto.sl_value = sl_value

                event_data_dto.event3_occur_time = timestamp

                event_data_dto = calculate_tp(candle_data, event_data_dto, SignalType.SELL)

                data_dictionary[key] = event_data_dto

            else:

                # UPDATING THE HIGHEST AND LOWEST POINT BEFORE RETURNING
                if highest_point is not None:
                    default_log.debug(f"Updating the highest point from {event_data_dto.highest_point} to "
                                      f"{highest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.highest_point = highest_point

                if lowest_point is not None:
                    default_log.debug(f"Updating the lowest point from {event_data_dto.lowest_point} to "
                                      f"{lowest_point} for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.lowest_point = lowest_point

                data_dictionary[key] = event_data_dto

                # CHECK RANGE ISSUE
                start_range, end_range = fetch_start_and_end_range(symbol=symbol, timeframe=timeframe)
                if (start_range is None) or (end_range is None):
                    default_log.debug(
                        f"Start Range and End Range has not been defined for symbol={symbol} having timeframe="
                        f"{timeframe}")
                    event_data_dto.range_issue = True
                    data_dictionary[key] = event_data_dto

                    return event_data_dto, data_dictionary

                # CHECK RANGE ISSUE
                increased_price = event_data_dto.event2_occur_breakpoint + (
                        event_data_dto.event2_occur_breakpoint * (end_range / 100))
                if current_candle_high > increased_price:
                    default_log.debug(f"As the candle high ({current_candle_high}) has reached more than the "
                                      f"increased_price ({increased_price}) which is calculated using "
                                      f"event2_breakpoint ({event_data_dto.event2_occur_breakpoint}) and end_range% "
                                      f"({end_range}%) for symbol={symbol} having timeframe={timeframe}")
                    event_data_dto.range_issue = True
                    data_dictionary[key] = event_data_dto

            return event_data_dto, data_dictionary

        if (event_data_dto.event2_occur_time is not None) and (event_data_dto.event3_occur_time is not None):
            # Check if current candle timestamp equal or less than previous tp value timestamp

            current_timestamp = candle_data['time']
            previous_tp_timestamp = event_data_dto.tp_values[-1].timestamp

            # PREVIOUS TP Timestamp can be None when restart flow is working
            if previous_tp_timestamp is not None:
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
            combined_height=candle_data["high"] - candle_data["low"],
            lowest_point=candle_data["low"],
            highest_point=candle_data["high"],
            event2_occur_breakpoint=event2_occur_breakpoint,
            previous_timestamp=timestamp,
            stop_tracking_further_events=False,
            range_issue=False
        )

        data_dictionary[key] = dto

        return dto, data_dictionary


def update_tp_and_sl_status(event_data_dto: EventDetailsDTO, data_dictionary, is_reverse_trade: bool = False):
    kite = get_kite_account_api()
    default_log.debug(f"inside update_tp_and_sl_status with event_data_dto={event_data_dto}")

    symbol = event_data_dto.symbol
    time_frame = event_data_dto.time_frame

    key = (symbol, time_frame)
    while True:
        dto = data_dictionary.get(key)

        if is_reverse_trade:
            tp_order_id = dto.reverse_trade_tp_order_id
            sl_order_id = dto.reverse_trade_sl_order_id
        else:
            tp_order_id = dto.tp_order_id
            sl_order_id = dto.sl_order_id

        default_log.debug(f"Getting status of tp_order_id={tp_order_id} and "
                          f"sl_order_id={sl_order_id} of symbol={symbol} having timeframe={time_frame}")
        tp_order_details = kite.order_history(tp_order_id)
        sl_order_details = kite.order_history(sl_order_id)

        tp_order_status = tp_order_details[-1].get("status", None)
        sl_order_status = sl_order_details[-1].get("status", None)

        if not is_reverse_trade:
            dto.tp_order_status = tp_order_status
            dto.sl_order_status = sl_order_status
        else:
            dto.reverse_trade_tp_order_status = tp_order_status
            dto.reverse_trade_sl_order_status = sl_order_status

        default_log.debug(f"Status of tp_order_id={tp_order_id} is {tp_order_status} and "
                          f"sl_order_id={sl_order_id} is {tp_order_status} for symbol={symbol} having timeframe="
                          f"{time_frame}")

        if (tp_order_status is not None) and (tp_order_status == "COMPLETE"):
            default_log.debug(f"TP Hit of symbol={symbol} at "
                              f"time={datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))}")

            default_log.debug(f"Cancelling SL trade order with id={tp_order_id} as TP is hit")
            cancel_order(kite, sl_order_id)

            if not is_reverse_trade:
                dto.tp_order_status = tp_order_status
                dto.tp_candle_time = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))
            else:
                dto.reverse_trade_tp_order_status = tp_order_status
                dto.reverse_trade_tp_candle_time = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))

            data_dictionary[key] = dto
            break

        if (sl_order_status is not None) and (sl_order_status == "COMPLETE"):
            default_log.debug(f"SL Hit of symbol={symbol} at "
                              f"time={datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))}")

            default_log.debug(f"Cancelling TP trade order with id={tp_order_id} as SL is hit")
            cancel_order(kite, tp_order_id)

            if not is_reverse_trade:
                dto.sl_order_status = sl_order_status
                dto.sl_candle_time = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))
            else:
                dto.reverse_trade_sl_order_status = sl_order_status
                dto.reverse_trade_sl_candle_time = datetime.now().astimezone(pytz.timezone('Asia/Kolkata'))

            data_dictionary[key] = dto
            break

        # dto.sl_order_status = sl_order_status
        # dto.tp_order_status = tp_order_status

        if not is_reverse_trade:
            dto.tp_order_status = tp_order_status
            dto.sl_order_status = sl_order_status
        else:
            dto.reverse_trade_tp_order_status = tp_order_status
            dto.reverse_trade_sl_order_status = sl_order_status

        data_dictionary[key] = dto

        tm.sleep(2)  # sleep for 2 second before fetching order history data


# def place_initial_zerodha_trades(
#         event_data_dto: EventDetailsDTO,
#         data_dictionary,
#         signal_type: SignalType,
#         candle_data,
#         symbol: str,
#         loss_budget: float,
#         indices_symbol: str = None,
#         extra_extension: bool = False
# ) -> tuple[EventDetailsDTO, bool]:
#     default_log.debug(f"inside place_zerodha_trades with event_data_dto={event_data_dto} and "
#                       f"signal_type={signal_type} for symbol={symbol} and indices_symbol={indices_symbol} and "
#                       f"loss_budget={loss_budget} and extra_extension status={extra_extension}")
#     kite = get_kite_account_api()
#     entry_price = event_data_dto.entry_price
#     entry_sl_value = event_data_dto.sl_value
#
#     default_log.debug(f"Entry Price = {entry_price} and Entry SL value = {entry_sl_value} for "
#                       f"symbol={symbol} and indices_symbol={indices_symbol}")
#
#     loss_percent = loss_budget * trade1_loss_percent
#
#     trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
#     # Round off trade1_quantity to 0 decimal places and convert to int
#     trade1_quantity = int(round(trade1_quantity, 0))
#
#     if not extra_extension:
#         default_log.debug(f"Creating MARKET order for trading_symbol={symbol} "
#                           f"transaction_type={signal_type} and quantity={trade1_quantity} "
#                           f"at timestamp={candle_data['time']} with event1_occur_time={event_data_dto.event1_occur_time} "
#                           f"and event3_occur_time={event_data_dto.event3_occur_time} and "
#                           f"indices_symbol={indices_symbol}")
#     else:
#         default_log.debug(f"[BEYOND EXTENSION] Creating MARKET order for trading_symbol={symbol} "
#                           f"transaction_type={signal_type} and quantity={event_data_dto.extension_quantity} "
#                           f"at timestamp={candle_data['time']} with event1_occur_time={event_data_dto.event1_occur_time} "
#                           f"and event3_occur_time={event_data_dto.event3_occur_time} and "
#                           f"indices_symbol={indices_symbol} with cover_sl_quantity={event_data_dto.extension_quantity}")
#         event_data_dto.cover_sl_quantity = event_data_dto.extension_quantity
#
#     event_data_dto.trade1_quantity = trade1_quantity
#     extra_extension_quantity = event_data_dto.extension_quantity
#
#     use_simulation = get_use_simulation_status()
#     # Start trade
#     if use_simulation:
#         entry_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=signal_type,
#             quantity=trade1_quantity if not extra_extension else extra_extension_quantity,
#             exchange="NSE",
#             average_price=event_data_dto.entry_price
#         )
#     else:
#         entry_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=signal_type,
#             quantity=trade1_quantity if not extra_extension else extra_extension_quantity,
#             exchange="NSE"
#         )
#
#     if entry_trade_order_id is None:
#         if not extra_extension:
#             default_log.debug(
#                 f"An error has occurred while placing MARKET order for symbol={symbol} having timeframe="
#                 f"{event_data_dto.time_frame} and "
#                 f"event_data_dto={event_data_dto}")
#         else:
#             default_log.debug(
#                 f"[BEYOND EXTENSION] An error has occurred while placing MARKET order for symbol={symbol} "
#                 f"having timeframe={event_data_dto.time_frame} and "
#                 f"event_data_dto={event_data_dto}")
#         return event_data_dto, True
#
#     if not extra_extension:
#         default_log.debug(
#             f"[{signal_type.name}] Signal Trade order placed for symbol={symbol} at {candle_data['time']} "
#             f"signal_trade_order_id={entry_trade_order_id} "
#             f"and indices_symbol={indices_symbol}")
#         event_data_dto.entry_trade_order_id = entry_trade_order_id
#     else:
#         default_log.debug(
#             f"[BEYOND EXTENSION] [{signal_type.name}] Signal Trade order placed for symbol={symbol} at "
#             f"{candle_data['time']} signal_trade_order_id={entry_trade_order_id} "
#             f"and indices_symbol={indices_symbol}")
#         event_data_dto.cover_sl_trade_order_id = entry_trade_order_id
#
#     while True:
#         zerodha_order_status = get_status_of_zerodha_order(kite, entry_trade_order_id)
#         default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                           f"Zerodha order status for MARKET order having id={entry_trade_order_id} is "
#                           f"{zerodha_order_status} for symbol={symbol} and "
#                           f"indices_symbol={indices_symbol}")
#
#         if zerodha_order_status == "COMPLETE":
#             # Now get the fill price when order was completed and then calculate the take profit
#             zerodha_market_order_details = get_zerodha_order_details(kite, entry_trade_order_id)
#
#             if zerodha_market_order_details is None:
#                 default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                                   f"An error occurred while fetching Zerodha MARKET order details for "
#                                   f"id={entry_trade_order_id} for symbol={symbol} and "
#                                   f"indices_symbol={indices_symbol}")
#                 return event_data_dto, True
#
#             fill_price = zerodha_market_order_details['average_price']
#             default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                               f"Fill price of zerodha market order having id={entry_trade_order_id} is "
#                               f"fill_price={fill_price} for symbol={symbol} and "
#                               f"indices_symbol={indices_symbol}")
#
#             # This flow used to update the Take profit using the fill price
#             # greatest_price = event_data_dto.tp_values[-1].greatest_price
#             # old_take_profit = event_data_dto.tp_values[-1].tp_with_buffer
#             #
#             # # tp_direction = 1 if signal_type == SignalType.BUY else -1  # +1 if tp order is SELL and -1 if tp is BUY
#             # take_profit_updated = fill_price + greatest_price
#             #
#             # default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#             #                   f"Updating old TP value={old_take_profit} to {take_profit_updated} for "
#             #                   f"MARKET order id={entry_trade_order_id} for symbol={symbol} and "
#             #                   f"indices_symbol={indices_symbol}")
#             #
#             # take_profit_with_buffer = take_profit_updated - (take_profit_updated * (buffer_for_tp_trade / 100))
#             #
#             # default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#             #                   f"Updating old TP (by adding/subtracting buffer of [{buffer_for_tp_trade}]) "
#             #                   f"value={take_profit_updated} to {take_profit_with_buffer} for "
#             #                   f"MARKET order id={entry_trade_order_id} for symbol={symbol} and "
#             #                   f"indices_symbol={indices_symbol}")
#             #
#             # # Now update the take profit and entry price
#             # # event_data_dto.tp_values[-1].tp_value = take_profit_updated
#             # event_data_dto.tp_values[-1].tp_with_buffer = take_profit_with_buffer
#
#             # Now update entry price
#             # old_entry_price = event_data_dto.entry_price
#             # new_entry_price = fill_price
#             # default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#             #                   f"Updating old Entry Price of={old_entry_price} to {new_entry_price} "
#             #                   f"for symbol={symbol} and "
#             #                   f"indices_symbol={indices_symbol}")
#             # event_data_dto.entry_price = new_entry_price
#
#             # This flow used to update SL according to fill price
#             # if indices_symbol is not None:
#             # old_sl_value = event_data_dto.sl_value
#             # new_sl_value = event_data_dto.entry_price + event_data_dto.value_to_add_for_stop_loss_entry_price
#             #
#             # default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#             #                   f"Updating old SL Value of={old_sl_value} to {new_sl_value} "
#             #                   f"for symbol={symbol} and "
#             #                   f"indices_symbol={indices_symbol}")
#             # event_data_dto.sl_value = new_sl_value
#
#             break
#
#         if zerodha_order_status == "REJECTED":
#             default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                               f"MARKET Order has been REJECTED having id={entry_trade_order_id} "
#                               f"for symbol={symbol} and "
#                               f"indices_symbol={indices_symbol}")
#             return event_data_dto, True
#         tm.sleep(2)  # sleep for 2 seconds
#
#     default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                       f"Adding buffer of {event_data_dto.candle_length} to the stop loss ({event_data_dto.sl_value}) ="
#                       f" {event_data_dto.sl_value + (2 * event_data_dto.candle_length)}")
#
#     # changed it to 2 times the length of candle
#     stop_loss = event_data_dto.sl_value + (2 * event_data_dto.candle_length)
#
#     take_profit = event_data_dto.tp_values[-1].tp_with_buffer
#     default_log.debug(
#         f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#         f"Entering the Market with stop_loss_value={stop_loss} and take_profit_value={take_profit} "
#         f"and quantity={trade1_quantity} for symbol={symbol} and indices_symbol={indices_symbol}")
#
#     tp_transaction_type = sl_transaction_type = SignalType.SELL if signal_type == SignalType.BUY else SignalType.BUY
#
#     # round off the price of stop loss
#     formatted_value = round_value(
#         symbol=symbol if indices_symbol is None else indices_symbol,
#         price=stop_loss,
#         exchange="NSE" if indices_symbol is None else "NFO"
#     )
#     stop_loss = formatted_value
#
#     default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                       f"Formatted SL value for symbol={event_data_dto.symbol} and timeframe = "
#                       f"{event_data_dto.time_frame} is {stop_loss}")
#
#     # event_data_dto.sl_value = stop_loss
#
#     # round off the price of take profit
#     formatted_value = round_value(
#         symbol=symbol if indices_symbol is None else indices_symbol,
#         price=take_profit,
#         exchange="NSE" if indices_symbol is None else "NFO"
#     )
#
#     take_profit = formatted_value
#
#     event_data_dto.tp_values[-1].tp_with_buffer = take_profit
#     # event_data_dto.tp_values[-1].tp_value = take_profit  # commented out as tp value should not be updated
#
#     # Continue with creating a TP and SL trade
#     default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                       f"Placing SL order for entry_trade_order_id={entry_trade_order_id} for "
#                       f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                       f"with quantity={trade1_quantity} and stop_loss={stop_loss} ")
#
#     use_simulation = get_use_simulation_status()
#     if use_simulation:
#         # Place a ZERODHA order with stop loss
#         sl_order_id = place_zerodha_order_with_stop_loss(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=sl_transaction_type,
#             quantity=trade1_quantity if indices_symbol is None else 50,
#             stop_loss=stop_loss,
#             exchange="NSE" if indices_symbol is None else "NFO"
#         )
#     else:
#         # Place a ZERODHA order with stop loss
#         sl_order_id = place_zerodha_order_with_stop_loss(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=sl_transaction_type,
#             quantity=trade1_quantity if indices_symbol is None else 50,
#             stop_loss=stop_loss,
#             exchange="NSE" if indices_symbol is None else "NFO"
#         )
#
#     if sl_order_id is None:
#         default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                           f"An error occurred while placing SL order for "
#                           f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={trade1_quantity} and stop_loss={stop_loss} and "
#                           f"indices_symbol={indices_symbol} ")
#     else:
#         default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                           f"Placed SL order with id={sl_order_id} "
#                           f"for entry_trade_order_id={entry_trade_order_id} for "
#                           f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={trade1_quantity} and stop_loss={stop_loss} "
#                           f"indices_symbol={indices_symbol} ")
#
#         event_data_dto.sl_order_id = sl_order_id
#
#     default_log.debug(f"Placing TP order for signal_order_id={entry_trade_order_id} for "
#                       f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                       f"with quantity={trade1_quantity} and take_profit={take_profit} ")
#
#     use_simulation = get_use_simulation_status()
#     # Place a ZERODHA order with take profit
#     if use_simulation:
#         tp_order_id = place_zerodha_order_with_take_profit(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=tp_transaction_type,
#             quantity=trade1_quantity if indices_symbol is None else 50,
#             take_profit=take_profit,
#             exchange="NSE" if indices_symbol is None else "NFO"
#         )
#     else:
#         tp_order_id = place_zerodha_order_with_take_profit(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=tp_transaction_type,
#             quantity=trade1_quantity if indices_symbol is None else 50,
#             take_profit=take_profit,
#             exchange="NSE" if indices_symbol is None else "NFO"
#         )
#
#     if tp_order_id is None:
#         default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                           f"An error occurred while placing TP order for "
#                           f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={trade1_quantity} and stop_loss={stop_loss} ")
#     else:
#         default_log.debug(f"{'[BEYOND EXTENSION] ' if extra_extension else ''}"
#                           f"Placed TP order with id={sl_order_id} "
#                           f"for entry_trade_order_id={entry_trade_order_id} for "
#                           f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={trade1_quantity} and stop_loss={stop_loss} "
#                           f"indices_symbol={indices_symbol} ")
#
#         event_data_dto.tp_order_id = tp_order_id
#
#     thread = threading.Thread(target=update_tp_and_sl_status, args=(event_data_dto, data_dictionary))
#     thread.start()
#
#     return event_data_dto, False
#
#
# def place_extension_zerodha_trades(
#         event_data_dto: EventDetailsDTO,
#         signal_type: SignalType,
#         candle_data,
#         extension_quantity: float,
#         symbol: str,
#         multiplier: int,
#         extension_no: int,
#         exchange: str = "NSE",
#         indices_symbol: str = None
# ) -> tuple[EventDetailsDTO, bool]:
#     default_log.debug(f"inside place_extension_zerodha_trades with event_data_dto={event_data_dto} and "
#                       f"signal_type={signal_type} for symbol={symbol} and exchange={exchange} with "
#                       f"multiplier={multiplier} and extension no={extension_no}")
#
#     kite = get_kite_account_api()
#
#     # Round off extension quantity to 0 decimal places and convert to int
#     extension_quantity = int(round(extension_quantity, 0))
#
#     default_log.debug(f"[EXTENSION] Creating MARKET order for trading_symbol={symbol} "
#                       f"transaction_type={signal_type} and extension_quantity={extension_quantity} "
#                       f"at timestamp={candle_data['time']} with event1_occur_time={event_data_dto.event1_occur_time} "
#                       f"and event3_occur_time={event_data_dto.event3_occur_time} and "
#                       f"indices_symbol={indices_symbol}")
#
#     sl_order_id = event_data_dto.sl_order_id
#     tp_order_id = event_data_dto.tp_order_id
#
#     use_simulation = get_use_simulation_status()
#     # Start trade
#     if use_simulation:
#         average_price = candle_data['low'] if signal_type == SignalType.SELL else candle_data['high']
#         extension_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=signal_type,
#             quantity=extension_quantity,
#             exchange="NSE",
#             average_price=average_price
#         )
#     else:
#         extension_trade_order_id = place_zerodha_order(
#             kite=kite,
#             trading_symbol=symbol if indices_symbol is None else indices_symbol,
#             transaction_type=signal_type,
#             quantity=extension_quantity,
#             exchange="NSE"
#         )
#
#     # Calculate the quantity for the extension tp and sl order update
#     if event_data_dto.trade1_quantity is None:
#         default_log.debug(f"Setting Trade 1 quantity as 0 as trade1_quantity={event_data_dto.trade1_quantity}")
#         event_data_dto.trade1_quantity = 0
#
#     event_data_dto.extension_quantity = event_data_dto.trade1_quantity if event_data_dto.extension_quantity is None else event_data_dto.extension_quantity
#
#     # [LOGIC] if extension_quantity is None: extension_quantity = dto.trade1_quantity
#     # tp_sl_quantity = extension_quantity + extension
#     # 1st Extension: extension_quantity = trade1_quantity = 4 =>
#     # 4 + 6 = 10 (extension_quantity=10) = extension1_quantity
#
#     # 2nd Extension: 10 + 3 = 13 = extension2_quantity = extension_quantity
#
#     # [LOGIC] trade1_quantity + extension1_quantity + extension2_quantity + extension
#     # 1st Extension: 4 + 0 + 0 + 6 = 10 (extension1_quantity = 10)
#
#     # 2nd Extension: 4 + 10 + 0 + 3 =
#     # 4 + 0 + 6 = 10 => extension_quantity
#     # 4 + 10 + 3
#
#     # tp_quantity = sl_quantity = event_data_dto.trade1_quantity + (
#     #         extension_quantity * multiplier) + previous_extension_quantity
#
#     tp_quantity = sl_quantity = event_data_dto.extension_quantity + extension_quantity
#
#     if event_data_dto.extension1_quantity is None:
#         default_log.debug(f"Updating Extension 1 quantity to {tp_quantity}")
#         event_data_dto.extension1_quantity = extension_quantity
#     else:
#         default_log.debug(f"Updating Extension 2 quantity to {tp_quantity}")
#         event_data_dto.extension2_quantity = extension_quantity
#
#     event_data_dto.extension_quantity = tp_quantity
#
#     if extension_trade_order_id is None:
#         default_log.debug(
#             f"An error has occurred while placing MARKET order for symbol={symbol} and "
#             f"event_data_dto={event_data_dto}")
#
#         return event_data_dto, True
#
#     if event_data_dto.extension1_trade_order_id is None:
#         event_data_dto.extension1_trade_order_id = extension_trade_order_id
#     else:
#         event_data_dto.extension2_trade_order_id = extension_trade_order_id
#
#     default_log.debug(f"[{signal_type.name}] Signal Trade order placed for symbol={symbol} at {candle_data['time']} "
#                       f"extension_quantity={extension_quantity} "
#                       f"and indices_symbol={indices_symbol}")
#
#     while True:
#         zerodha_order_status = get_status_of_zerodha_order(kite, extension_trade_order_id)
#         default_log.debug(f"[EXTENSION] Zerodha order status for MARKET order having id={extension_trade_order_id} is "
#                           f"{zerodha_order_status} for symbol={symbol} and "
#                           f"indices_symbol={indices_symbol}")
#
#         if zerodha_order_status == "COMPLETE":
#             default_log.debug(f"[EXTENSION] Extension trade with id={extension_trade_order_id} status is "
#                               f"COMPLETE")
#             zerodha_market_order_details = get_zerodha_order_details(kite, extension_trade_order_id)
#
#             if zerodha_market_order_details is None:
#                 default_log.debug(f"[EXTENSION] An error occurred while fetching Zerodha MARKET order details for "
#                                   f"id={extension_trade_order_id} for symbol={symbol} and "
#                                   f"indices_symbol={indices_symbol}")
#                 return event_data_dto, True
#
#             fill_price = zerodha_market_order_details['average_price']
#             default_log.debug(f"[EXTENSION] Fill price of zerodha market order having id={extension_trade_order_id} is "
#                               f"fill_price={fill_price} for symbol={symbol} and "
#                               f"indices_symbol={indices_symbol}")
#             if event_data_dto.extension1_entry_price is None:
#                 event_data_dto.extension1_entry_price = fill_price
#             else:
#                 event_data_dto.extension2_entry_price = fill_price
#             break
#
#         if zerodha_order_status == "REJECTED":
#             default_log.debug(f"[EXTENSION] Extension MARKET order with id={extension_trade_order_id} is REJECTED "
#                               f"for symbol={symbol} and "
#                               f"indices_symbol={indices_symbol}")
#
#             if event_data_dto.trade1_quantity is None:
#                 default_log.debug(f"[EXTENSION order has been rejected] Setting Trade 1 quantity as 0 as "
#                                   f"trade1_quantity={event_data_dto.trade1_quantity}")
#                 event_data_dto.trade1_quantity = 0
#
#             event_data_dto.extension_quantity = event_data_dto.trade1_quantity if event_data_dto.extension_quantity is None else event_data_dto.extension_quantity
#
#             return event_data_dto, True
#
#         tm.sleep(2)  # sleep for 2 seconds
#
#     default_log.debug(
#         f"[EXTENSION] Updating the SL and LIMIT with "
#         f"quantity={extension_quantity} for symbol={symbol} "
#         f"and tp_quantity={tp_quantity} and sl_quantity={sl_quantity} and "
#         f"trade1_quantity={event_data_dto.trade1_quantity}")
#
#     tp_transaction_type = sl_transaction_type = SignalType.SELL if SignalType.BUY else SignalType.BUY
#
#     # if tp and sl trades are not made at all then create one else update the existing TP and SL trades
#     if (tp_order_id is None) and (sl_order_id is None):
#
#         # Get the direction that would be used if fill price needs to be subtracted or not
#         direction = -1 if signal_type == SignalType.SELL else 1
#
#         # Check whether which extension trade is this and accordingly using the config threshold
#         if extension_no == 1:
#             default_log.debug(f"[EXTENSION] As it is extension no {extension_no} trade so will be using "
#                               f"{extension1_threshold_percent} as threshold percent [EXTENSION 1]")
#
#             extension1_fill_price = event_data_dto.extension1_entry_price
#             pseudo_entry_trade_fill_price = extension1_fill_price + (direction * extension1_threshold_percent)
#             default_log.debug(
#                 f"[EXTENSION] Pseudo Entry Trade fill price calculated as={pseudo_entry_trade_fill_price} "
#                 f"as extension1_fill_price={extension1_fill_price}, direction={direction} and "
#                 f"extension1_threshold_percent={extension1_threshold_percent}")
#         else:
#             default_log.debug(f"[EXTENSION] As it is extension no {extension_no} trade so will be using "
#                               f"{extension2_threshold_percent} as threshold percent [EXTENSION 2]")
#
#             extension2_fill_price = event_data_dto.extension2_entry_price
#             pseudo_entry_trade_fill_price = extension2_fill_price + (direction * extension2_threshold_percent)
#             default_log.debug(
#                 f"[EXTENSION] Pseudo Entry Trade fill price calculated as={pseudo_entry_trade_fill_price} "
#                 f"as extension2_fill_price={extension2_fill_price}, direction={direction} and "
#                 f"extension2_threshold_percent={extension2_threshold_percent}")
#
#         # Calculate Stop Loss and Take Profit
#         # For take profit use take profit with buffer
#
#         # This flow used to update the Take Profit using fill price
#         # greatest_price = event_data_dto.tp_values[-1].greatest_price
#         # old_take_profit = event_data_dto.tp_values[-1].tp_with_buffer
#         #
#         # # tp_direction = 1 if signal_type == SignalType.BUY else -1  # +1 if tp order is SELL and -1 if tp is BUY
#         # take_profit_updated = fill_price + greatest_price
#         #
#         # default_log.debug(f"[EXTENSION] Updating old TP value={old_take_profit} to {take_profit_updated} for "
#         #                   f"MARKET order id={extension_trade_order_id} for symbol={symbol} and "
#         #                   f"indices_symbol={indices_symbol}")
#         #
#         # take_profit_with_buffer = take_profit_updated - (take_profit_updated * (buffer_for_tp_trade / 100))
#         #
#         # default_log.debug(f"[EXTENSION] Updating old TP (by adding/subtracting buffer of [{buffer_for_tp_trade}]) "
#         #                   f"value={take_profit_updated} to {take_profit_with_buffer} for "
#         #                   f"MARKET order id={extension_trade_order_id} for symbol={symbol} and "
#         #                   f"indices_symbol={indices_symbol}")
#         #
#         # # Now update the take profit and entry price
#         # # event_data_dto.tp_values[-1].tp_value = take_profit_updated
#         # event_data_dto.tp_values[-1].tp_with_buffer = take_profit_with_buffer
#
#         # Now update entry price
#         # old_entry_price = event_data_dto.entry_price
#         # new_entry_price = fill_price
#         # default_log.debug(f"[EXTENSION] Updating old Entry Price of={old_entry_price} to {new_entry_price} "
#         #                   f"for symbol={symbol} and "
#         #                   f"indices_symbol={indices_symbol}")
#         # event_data_dto.entry_price = new_entry_price
#
#         # if indices_symbol is not None:
#         # old_sl_value = event_data_dto.sl_value
#         # new_sl_value = event_data_dto.entry_price + event_data_dto.value_to_add_for_stop_loss_entry_price
#         #
#         # default_log.debug(f"[EXTENSION] Updating old SL Value of={old_sl_value} to {new_sl_value} "
#         #                   f"for symbol={symbol} and "
#         #                   f"indices_symbol={indices_symbol}")
#         # event_data_dto.sl_value = new_sl_value
#
#         # Create TP and SL trade
#
#         # Adding a buffer of candle length to the stop loss
#         default_log.debug(f"[EXTENSION] Adding buffer of {event_data_dto.candle_length} to the stop loss "
#                           f"({event_data_dto.sl_value}) = {event_data_dto.sl_value + (2 * event_data_dto.candle_length)}")
#
#         # stop_loss = event_data_dto.sl_value + event_data_dto.candle_length
#         stop_loss = event_data_dto.sl_value + (2 * event_data_dto.candle_length)
#
#         # Rounding of STOP LOSS and TAKE PROFIT to its tick size
#         # round off the price of stop loss
#         formatted_value = round_value(
#             symbol=symbol if indices_symbol is None else indices_symbol,
#             price=stop_loss,
#             exchange="NSE" if indices_symbol is None else "NFO"
#         )
#         stop_loss = formatted_value
#
#         default_log.debug(f"[EXTENSION] Formatted SL value for symbol={event_data_dto.symbol} and timeframe = "
#                           f"{event_data_dto.time_frame} is {stop_loss}")
#
#         take_profit = event_data_dto.tp_values[-1].tp_with_buffer
#
#         # round off the price of take profit
#         formatted_value = round_value(
#             symbol=symbol if indices_symbol is None else indices_symbol,
#             price=take_profit,
#             exchange="NSE" if indices_symbol is None else "NFO"
#         )
#
#         take_profit = formatted_value
#
#         default_log.debug(f"[EXTENSION] Formatted TP value for symbol={event_data_dto.symbol} and timeframe = "
#                           f"{event_data_dto.time_frame} is {take_profit}")
#
#         default_log.debug(f"[EXTENSION] Placing SL order for extension_trade_order_id={extension_trade_order_id} for "
#                           f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={sl_quantity} and stop_loss={stop_loss}"
#                           f"exchange={exchange}")
#
#         use_simulation = get_use_simulation_status()
#         if use_simulation:
#             sl_order_id = place_zerodha_order_with_stop_loss(
#                 kite=kite,
#                 quantity=sl_quantity,
#                 transaction_type=sl_transaction_type,
#                 trading_symbol=symbol,
#                 stop_loss=stop_loss,
#                 exchange=exchange
#             )
#         else:
#             sl_order_id = place_zerodha_order_with_stop_loss(
#                 kite=kite,
#                 quantity=sl_quantity,
#                 trading_symbol=symbol,
#                 transaction_type=sl_transaction_type,
#                 stop_loss=stop_loss,
#                 exchange=exchange
#             )
#
#         if sl_order_id is None:
#             default_log.debug(f"[EXTENSION] An error occurred while placing SL order for "
#                               f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                               f"with quantity={sl_quantity} and stop_loss={stop_loss} and "
#                               f"indices_symbol={indices_symbol} ")
#         else:
#             default_log.debug(f"[EXTENSION] Placed SL order with id={sl_order_id} "
#                               f"for extension_trade_order_id={extension_trade_order_id} for "
#                               f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                               f"with quantity={sl_quantity} and stop_loss={stop_loss}"
#                               f"indices_symbol={indices_symbol} and exchange={exchange}")
#
#             event_data_dto.sl_order_id = sl_order_id
#
#         default_log.debug(f"[EXTENSION] Placing TP order for extension_trade_order_id={extension_trade_order_id} for "
#                           f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={tp_quantity} and "
#                           f"exchange={exchange}")
#
#         use_simulation = get_use_simulation_status()
#         # Update a ZERODHA order with take profit
#         if use_simulation:
#             tp_order_id = place_zerodha_order_with_take_profit(
#                 kite=kite,
#                 transaction_type=tp_transaction_type,
#                 quantity=tp_quantity,
#                 trading_symbol=symbol,
#                 take_profit=take_profit,
#                 exchange=exchange
#             )
#         else:
#             tp_order_id = place_zerodha_order_with_take_profit(
#                 kite=kite,
#                 transaction_type=tp_transaction_type,
#                 quantity=tp_quantity,
#                 trading_symbol=symbol,
#                 take_profit=take_profit,
#                 exchange=exchange
#             )
#
#         if tp_order_id is None:
#             default_log.debug(f"[EXTENSION] An error occurred while placing TP order for "
#                               f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                               f"with quantity={tp_quantity} and take_profit={take_profit} and"
#                               f"exchange={exchange}")
#         else:
#             default_log.debug(f"[EXTENSION] Updated TP order with id={sl_order_id} "
#                               f"for extension_trade_order_id={extension_trade_order_id} for "
#                               f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                               f"with quantity={tp_quantity}  and take_profit={take_profit} and "
#                               f"indices_symbol={indices_symbol} and exchange={exchange}")
#
#             event_data_dto.tp_order_id = tp_order_id
#
#         return event_data_dto, False
#
#     # Continue with updating TP and SL trade
#     default_log.debug(f"[EXTENSION] Updating SL order for extension_trade_order_id={extension_trade_order_id} for "
#                       f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                       f"with quantity={sl_quantity} "
#                       f"exchange={exchange}")
#
#     use_simulation = get_use_simulation_status()
#     # Add stop loss and take profit while updating the SL-M and LIMIT order
#     # Update a ZERODHA order with stop loss quantity
#     if use_simulation:
#         sl_order_id = update_zerodha_order_with_stop_loss(
#             kite=kite,
#             zerodha_order_id=sl_order_id,
#             trade_quantity=sl_quantity if indices_symbol is None else 50,
#             quantity=sl_quantity if indices_symbol is None else 50,
#             transaction_type=sl_transaction_type,
#             trading_symbol=symbol,
#             candle_high=candle_data['high'],
#             candle_low=candle_data['low'],
#             exchange=exchange
#         )
#     else:
#         sl_order_id = update_zerodha_order_with_stop_loss(
#             kite=kite,
#             zerodha_order_id=sl_order_id,
#             trade_quantity=sl_quantity if indices_symbol is None else 50,
#             quantity=sl_quantity if indices_symbol is None else 50,
#             trading_symbol=symbol,
#             transaction_type=sl_transaction_type,
#             exchange=exchange
#         )
#
#     if sl_order_id is None:
#         default_log.debug(f"[EXTENSION] An error occurred while placing SL order for "
#                           f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={sl_quantity} and "
#                           f"indices_symbol={indices_symbol} ")
#     else:
#         default_log.debug(f"[EXTENSION] Updated SL order with id={sl_order_id} "
#                           f"for extension_trade_order_id={extension_trade_order_id} for "
#                           f"trading_symbol={symbol}, transaction_type as {sl_transaction_type} "
#                           f"with quantity={sl_quantity} "
#                           f"indices_symbol={indices_symbol} and exchange={exchange}")
#
#         event_data_dto.sl_order_id = sl_order_id
#
#     default_log.debug(f"[EXTENSION] Updating TP order for extension_trade_order_id={extension_trade_order_id} for "
#                       f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                       f"with quantity={tp_quantity} and "
#                       f"exchange={exchange}")
#
#     use_simulation = get_use_simulation_status()
#     # Update a ZERODHA order with take profit
#     if use_simulation:
#         tp_order_id = update_zerodha_order_with_take_profit(
#             kite=kite,
#             zerodha_order_id=tp_order_id,
#             transaction_type=tp_transaction_type,
#             trade_quantity=tp_quantity if indices_symbol is None else 50,
#             quantity=tp_quantity if indices_symbol is None else 50,
#             trading_symbol=symbol,
#             candle_high=candle_data['high'],
#             candle_low=candle_data['low'],
#             exchange=exchange
#         )
#     else:
#         tp_order_id = update_zerodha_order_with_take_profit(
#             kite=kite,
#             zerodha_order_id=tp_order_id,
#             transaction_type=tp_transaction_type,
#             trade_quantity=tp_quantity if indices_symbol is None else 50,
#             quantity=tp_quantity if indices_symbol is None else 50,
#             trading_symbol=symbol,
#             exchange=exchange
#         )
#
#     if tp_order_id is None:
#         default_log.debug(f"[EXTENSION] An error occurred while updating TP order for "
#                           f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={tp_quantity} "
#                           f"exchange={exchange}")
#     else:
#         default_log.debug(f"[EXTENSION] Updated TP order with id={sl_order_id} "
#                           f"for extension_trade_order_id={extension_trade_order_id} for "
#                           f"trading_symbol={symbol}, transaction_type as {tp_transaction_type} "
#                           f"with quantity={tp_quantity} "
#                           f"indices_symbol={indices_symbol} and exchange={exchange}")
#
#         event_data_dto.tp_order_id = tp_order_id
#
#     return event_data_dto, False


def update_zerodha_stop_loss_order(event_data_dto: EventDetailsDTO, indices_symbol: str = None,
                                   candle_high: float = None, candle_low: float = None):
    kite = get_kite_account_api()
    default_log.debug(f"inside update_zerodha_stop_loss_order for symbol={event_data_dto.symbol} "
                      f"and timeframe={event_data_dto.time_frame} and indices_symbol={indices_symbol}"
                      f"and with event_data_dto={event_data_dto} and candle_high={candle_high} and "
                      f"candle_low={candle_low} and stop_loss={event_data_dto.sl_value} and "
                      f"buffer={event_data_dto.sl_buffer}")

    default_log.debug(f"Updating SL value of symbol={event_data_dto.symbol} and timeframe={event_data_dto.time_frame} "
                      f"from {event_data_dto.sl_value} to {event_data_dto.sl_value + (2 * event_data_dto.sl_buffer)} "
                      f"by adding buffer of {event_data_dto.sl_buffer}")

    # sl_value = event_data_dto.sl_value + event_data_dto.candle_length
    sl_value = event_data_dto.sl_value + (2 * event_data_dto.sl_buffer)
    symbol = event_data_dto.symbol

    # round off the price of stop loss
    formatted_value = round_value(
        symbol=symbol if indices_symbol is None else indices_symbol,
        price=sl_value,
        exchange="NSE" if indices_symbol is None else "NFO"
    )
    stop_loss = formatted_value

    # event_data_dto.sl_value = stop_loss
    use_simulation = get_use_simulation_status()
    quantity = event_data_dto.trade1_quantity if event_data_dto.extension_quantity is None else event_data_dto.extension_quantity
    if use_simulation:
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
        alert_time: Optional[datetime] = None,
        restart_dto: RestartEventDTO = None,
        continuity_dto: RestartEventDTO = None
):
    default_log.debug("inside start_market_logging_for_buy with "
                      f"symbol={symbol}, timeframe={timeframe}, instrument_token={instrument_token} "
                      f"wait_time={wait_time} and configuration={configuration}, alert_time={alert_time} "
                      f"restart_dto={restart_dto}, and continuity_dto={continuity_dto}")

    data_dictionary = {}
    wait_time = 2  # as ticker data is being used now

    interval = get_interval_from_timeframe(timeframe)

    key = (symbol, timeframe)
    trades_made = 0

    is_restart = False
    is_continuity = False
    extension_diff = None

    tried_creating_entry_order = False
    tried_creating_extension1_order = False
    tried_creating_extension2_order = False
    tried_creating_reverse1_trade = False
    tried_creating_reverse2_trade = False
    tried_creating_cover_sl_trade = False
    tried_creating_reverse_cover_sl_trade = False

    candles_checked = 0
    entry_price = None

    indices_symbol = None
    prev_timestamp = None

    sl_got_extended = False
    initial_close_price = None

    # STATUSES
    not_enough_equity = False  # FOR KEEPING TRACK OF EQUITY STATUS
    range_issue = False  # FOR KEEPING TRACK OF RANGE STATUS
    opposite_issue = False  # FOR KEEPING TRACK OF OPPOSITE STATUS
    short_quantity_issue = False  # FOR KEEPING TRACK OF SHORT QUANTITY STATUS
    trade_alert_status = "PENDING"

    total_budget_used = 0

    reached_extension1_point = False
    reached_extension2_point = False

    # 50 FOR NIFTY AND 15 FOR BANKNIFTY
    indices_quantity_multiplier = 50 if symbol == "NIFTY" else 15
    initial_event1_done = False

    dto = None

    if restart_dto is not None:
        is_restart = True
        initial_event1_done = True
        default_log.debug(f"Restarting the thread with restart_dto={restart_dto}")

        thread_detail_id = restart_dto.thread_id

        # ALERT SYMBOL AND TIMEFRAME DETAIL
        symbol = restart_dto.symbol
        time_frame = restart_dto.time_frame

        # EVENT TIMES
        event1_occur_time = restart_dto.event1_occur_time
        event2_occur_time = restart_dto.event2_occur_time
        event3_occur_time = restart_dto.event3_occur_time

        # ALERT TIME
        restart_thread_alert_time = restart_dto.alert_time

        # ALERT MISC
        event2_breakpoint = restart_dto.event2_breakpoint
        highest_point = restart_dto.highest_point
        lowest_point = restart_dto.lowest_point
        sl_value = restart_dto.sl_value
        tp_value = restart_dto.tp_value
        high_1 = restart_dto.high_1
        low_1 = restart_dto.low_1
        candle_high = restart_dto.candle_high  # EVENT 1 CANDLE HIGH
        candle_low = restart_dto.candle_low  # EVENT 1 CANDLE LOW
        candle_length = candle_high - candle_low
        adjusted_high = restart_dto.adjusted_high
        adjusted_low = restart_dto.adjusted_low
        entry_price = restart_dto.entry_price
        reverse_trade_stop_loss = restart_dto.reverse_trade_stop_loss
        reverse_trade_take_profit = restart_dto.reverse_trade_take_profit

        # Add SL Buffer and Combined Height
        combined_height = None
        sl_buffer = None
        if sl_value is not None:
            if adjusted_high is not None:
                default_log.debug(f"Calculating combined difference using adjusted_high "
                                  f"({adjusted_high}) and event1_candle_low "
                                  f"({candle_low})")
                combined_height = adjusted_high - candle_low
                sl_buffer = combined_height
            else:
                default_log.debug(f"Calculating sl buffer difference using event1_candle_high "
                                  f"({candle_high}) and event1_candle_high "
                                  f"({candle_low})")
                sl_buffer = candle_high - candle_low

        # QUANTITY DETAILS
        trade1_quantity = restart_dto.trade1_quantity
        extension_quantity = restart_dto.extension_quantity
        extension1_quantity = restart_dto.extension1_quantity
        extension2_quantity = restart_dto.extension2_quantity
        cover_sl_quantity = restart_dto.cover_sl_quantity
        reverse1_trade_quantity = restart_dto.reverse1_trade_quantity
        reverse2_trade_quantity = restart_dto.reverse2_trade_quantity

        # ALERT TRADES ORDER IDs
        trade1_order_id = restart_dto.signal_trade_order_id
        extension1_order_id = restart_dto.extension1_order_id
        extension2_order_id = restart_dto.extension2_order_id
        cover_sl_trade_order_id = restart_dto.cover_sl_trade_order_id
        tp_order_id = restart_dto.tp_order_id
        sl_order_id = restart_dto.sl_order_id
        reverse1_trade_order_id = restart_dto.reverse1_trade_order_id
        reverse2_trade_order_id = restart_dto.reverse2_trade_order_id
        reverse_cover_sl_trade_order_id = restart_dto.reverse_cover_sl_trade_order_id

        h = candle_high if adjusted_high is None else adjusted_high
        l = candle_low if adjusted_low is None else adjusted_low

        tp_details = []

        # EVENT 1 IS BUY
        if tp_value is not None:
            tp_val = tp_value
            if symbol not in indices_list:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_tp_trade}")

                tp_buffer = buffer_for_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))
            else:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_indices_tp_trade}")

                tp_buffer = buffer_for_indices_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))

            tp_details = [TPDetailsDTO(
                tp_value=tp_val,
                low_1=low_1,
                high_1=high_1,
                sl_value=sl_value,
                low=l,
                high=h,
                entry_price=entry_price,
                tp_buffer_percent=tp_buffer,
                tp_with_buffer=tp_with_buffer
            )]

        event_details_dto = EventDetailsDTO(
            alert_time=restart_thread_alert_time,
            event1_occur_time=event1_occur_time,
            symbol=symbol,
            time_frame=time_frame,
            event1_candle_high=candle_high,
            event1_candle_low=candle_low,
            candle_length=candle_length,
            event2_occur_breakpoint=event2_breakpoint,
            adjusted_high=adjusted_high,
            adjusted_low=adjusted_low,
            event2_occur_time=event2_occur_time,
            event3_occur_time=event3_occur_time,
            highest_point=highest_point,
            lowest_point=lowest_point,
            sl_value=sl_value,
            sl_buffer=sl_buffer,
            combined_height=combined_height,
            tp_values=tp_details,
            trade1_quantity=trade1_quantity,
            extension1_quantity=extension1_quantity,
            extension2_quantity=extension2_quantity,
            extension_quantity=extension_quantity,
            cover_sl_quantity=cover_sl_quantity,
            reverse1_trade_quantity=reverse1_trade_quantity,
            reverse2_trade_quantity=reverse2_trade_quantity,
            entry_trade_order_id=trade1_order_id,
            entry_price=entry_price,
            extension1_trade_order_id=extension1_order_id,
            extension2_trade_order_id=extension2_order_id,
            cover_sl_trade_order_id=cover_sl_trade_order_id,
            tp_order_id=tp_order_id,
            sl_order_id=sl_order_id,
            reverse1_trade_order_id=reverse1_trade_order_id,
            reverse2_trade_order_id=reverse2_trade_order_id,
            reverse_cover_sl_trade_order_id=reverse_cover_sl_trade_order_id,
            reverse_trade_stop_loss=reverse_trade_stop_loss,
            reverse_trade_take_profit=reverse_trade_take_profit,
            stop_tracking_further_events=False
        )

        if (event1_occur_time is not None) and (event2_occur_time is None):
            # Start the thread from event 1 timestamp
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

            data_dictionary[key] = event_details_dto

        elif (event1_occur_time is not None) and (event2_occur_time is not None) and (event3_occur_time is None):
            # Event 2 has been completed but not event 3
            # Start the thread from event 2 timestamp

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

            data_dictionary[key] = event_details_dto

        else:
            # Event 3 has been completed but tp or sl has not been hit yet Start the thread from event 3 timestamp
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

            data_dictionary[key] = event_details_dto

            # Set the trades made value depending on the extension trade
            if trade1_order_id is not None:
                tried_creating_entry_order = True

            if extension1_order_id is not None:
                tried_creating_extension1_order = True
                reached_extension1_point = True

            if extension2_order_id is not None:
                tried_creating_extension2_order = True
                reached_extension2_point = True

            if cover_sl_trade_order_id is not None:
                tried_creating_cover_sl_trade = True

            if reverse1_trade_order_id is not None:
                tried_creating_reverse1_trade = True

            if reverse2_trade_order_id is not None:
                tried_creating_reverse2_trade = True

            if reverse_cover_sl_trade_order_id is not None:
                tried_creating_reverse_cover_sl_trade = True

    elif continuity_dto is not None:
        is_continuity = True
        thread_detail_id = continuity_dto.thread_id

        # ALERT SYMBOL AND TIMEFRAME DETAIL
        symbol = continuity_dto.symbol
        time_frame = continuity_dto.time_frame

        # EVENT TIMES
        event1_occur_time = continuity_dto.event1_occur_time
        event2_occur_time = continuity_dto.event2_occur_time
        event3_occur_time = continuity_dto.event3_occur_time

        # ALERT TIME
        restart_thread_alert_time = continuity_dto.alert_time

        # ALERT MISC
        event2_breakpoint = continuity_dto.event2_breakpoint
        highest_point = continuity_dto.highest_point
        lowest_point = continuity_dto.lowest_point
        sl_value = continuity_dto.sl_value
        tp_value = continuity_dto.tp_value
        high_1 = continuity_dto.high_1
        low_1 = continuity_dto.low_1
        candle_high = continuity_dto.candle_high  # EVENT 1 CANDLE HIGH
        candle_low = continuity_dto.candle_low  # EVENT 1 CANDLE LOW
        candle_length = candle_high - candle_low
        adjusted_high = continuity_dto.adjusted_high
        adjusted_low = continuity_dto.adjusted_low
        entry_price = continuity_dto.entry_price
        reverse_trade_stop_loss = continuity_dto.reverse_trade_stop_loss
        reverse_trade_take_profit = continuity_dto.reverse_trade_take_profit

        # Add SL Buffer and Combined Height
        combined_height = None
        sl_buffer = None
        if sl_value is not None:
            if adjusted_high is not None:
                default_log.debug(f"Calculating combined difference using adjusted_high "
                                  f"({adjusted_high}) and event1_candle_low "
                                  f"({candle_low})")
                combined_height = adjusted_high - candle_low
                sl_buffer = combined_height
            else:
                default_log.debug(f"Calculating sl buffer difference using event1_candle_high "
                                  f"({candle_high}) and event1_candle_high "
                                  f"({candle_low})")
                sl_buffer = candle_high - candle_low

        # QUANTITY DETAILS
        trade1_quantity = continuity_dto.trade1_quantity
        extension_quantity = continuity_dto.extension_quantity
        extension1_quantity = continuity_dto.extension1_quantity
        extension2_quantity = continuity_dto.extension2_quantity
        cover_sl_quantity = continuity_dto.cover_sl_quantity
        reverse1_trade_quantity = continuity_dto.reverse1_trade_quantity
        reverse2_trade_quantity = continuity_dto.reverse2_trade_quantity

        # ALERT TRADES ORDER IDs
        trade1_order_id = continuity_dto.signal_trade_order_id
        extension1_order_id = continuity_dto.extension1_order_id
        extension2_order_id = continuity_dto.extension2_order_id
        cover_sl_trade_order_id = continuity_dto.cover_sl_trade_order_id
        tp_order_id = continuity_dto.tp_order_id
        sl_order_id = continuity_dto.sl_order_id
        reverse1_trade_order_id = continuity_dto.reverse1_trade_order_id
        reverse2_trade_order_id = continuity_dto.reverse2_trade_order_id
        reverse_cover_sl_trade_order_id = continuity_dto.reverse_cover_sl_trade_order_id

        h = candle_high if adjusted_high is None else adjusted_high
        l = candle_low if adjusted_low is None else adjusted_low

        tp_details = []

        # EVENT 1 IS BUY
        if tp_value is not None:
            tp_val = tp_value
            if symbol not in indices_list:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_tp_trade}")

                tp_buffer = buffer_for_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))
            else:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_indices_tp_trade}")

                tp_buffer = buffer_for_indices_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))

            tp_details = [TPDetailsDTO(
                tp_value=tp_val,
                low_1=low_1,
                high_1=high_1,
                sl_value=sl_value,
                low=l,
                high=h,
                entry_price=entry_price,
                tp_buffer_percent=tp_buffer,
                tp_with_buffer=tp_with_buffer
            )]

        event_details_dto = EventDetailsDTO(
            alert_time=restart_thread_alert_time,
            event1_occur_time=event1_occur_time,
            symbol=symbol,
            time_frame=time_frame,
            event1_candle_high=candle_high,
            event1_candle_low=candle_low,
            candle_length=candle_length,
            event2_occur_breakpoint=event2_breakpoint,
            adjusted_high=adjusted_high,
            adjusted_low=adjusted_low,
            event2_occur_time=event2_occur_time,
            event3_occur_time=event3_occur_time,
            highest_point=highest_point,
            lowest_point=lowest_point,
            sl_value=sl_value,
            sl_buffer=sl_buffer,
            combined_height=combined_height,
            tp_values=tp_details,
            trade1_quantity=trade1_quantity,
            extension1_quantity=extension1_quantity,
            extension2_quantity=extension2_quantity,
            extension_quantity=extension_quantity,
            cover_sl_quantity=cover_sl_quantity,
            reverse1_trade_quantity=reverse1_trade_quantity,
            reverse2_trade_quantity=reverse2_trade_quantity,
            entry_trade_order_id=trade1_order_id,
            extension1_trade_order_id=extension1_order_id,
            extension2_trade_order_id=extension2_order_id,
            cover_sl_trade_order_id=cover_sl_trade_order_id,
            tp_order_id=tp_order_id,
            sl_order_id=sl_order_id,
            reverse1_trade_order_id=reverse1_trade_order_id,
            reverse2_trade_order_id=reverse2_trade_order_id,
            reverse_cover_sl_trade_order_id=reverse_cover_sl_trade_order_id,
            reverse_trade_stop_loss=reverse_trade_stop_loss,
            reverse_trade_take_profit=reverse_trade_take_profit,
            stop_tracking_further_events=False
        )

        data_dictionary[key] = event_details_dto

        # Set the trades made value depending on the extension trade
        if trade1_order_id is not None:
            tried_creating_entry_order = True

        if extension1_order_id is not None:
            tried_creating_extension1_order = True
            reached_extension1_point = True

        if extension2_order_id is not None:
            tried_creating_extension2_order = True
            reached_extension2_point = True

        if cover_sl_trade_order_id is not None:
            tried_creating_cover_sl_trade = True

        if reverse1_trade_order_id is not None:
            tried_creating_reverse1_trade = True

        if reverse2_trade_order_id is not None:
            tried_creating_reverse2_trade = True

        if reverse_cover_sl_trade_order_id is not None:
            tried_creating_reverse_cover_sl_trade = True

        # Check if current time is greater than the start market time of 09:15 IST
        # If not then wait till it is 09:15 IST
        current_time = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
        try:
            if current_time < market_start_time:
                wait_time_in_seconds = (market_start_time - current_time).seconds
                wait_time_in_seconds += ((60 * int(timeframe)) + 5)  # Adding a 5-second buffer
                default_log.debug(
                    f"As Current Time ({current_time}) < Market Start Time ({market_start_time}) so waiting "
                    f"{wait_time_in_seconds} seconds before continuing alert tracking for symbol={symbol} "
                    f"having timeframe={timeframe}")
                tm.sleep(wait_time_in_seconds)
            else:
                default_log.debug(
                    f"As Current Time ({current_time}) >= Market Start Time ({market_start_time}) so starting "
                    f"subscribing for realtime ticks for alert tracking for symbol={symbol} "
                    f"having timeframe={timeframe}")
        except Exception as e:
            default_log.debug(f"An error occurred while checking if current time ({current_time}) was less than the "
                              f"market_start_time {market_start_time} for continuing alert for symbol={symbol} having "
                              f"timeframe={timeframe}. Error: {e}")
            return

        data = get_zerodha_data(
            instrument_token=instrument_token,
            market_symbol=symbol,
            interval=interval
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol}"
                              f"and timeframe={timeframe}")
            return None

    else:
        # Not restarted flow
        use_simulation = get_use_simulation_status()
        if not use_simulation:
            default_log.debug(f"As not running on simulator as use_simulation={use_simulation} for symbol={symbol} "
                              f"having timeframe={timeframe}, so not sleeping for the initial wait_time of {wait_time}")
            tm.sleep(wait_time)
        current_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))

        # Fetch candle data
        # Initially get the historical data with from_time = alert_time - timeframe
        # and the from_time time should be of the following format: HH:MM:00 (the seconds should be 00)
        # and the result after subtracting timeframe should be done in ist timezone
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
            alert_time=alert_time,
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.BUY,
            configuration_type=configuration,
            trade_alert_status="PENDING",
            is_completed=False
        )

        response = add_thread_event_details(new_event_thread_dto)

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

        if not (len(data) > 1):
            # todo: remove this if using global data feed
            initial_event1_done = True

        thread_detail_id = response

    while True:
        # defining loss budget
        loss_budget = fetch_symbol_budget(symbol, timeframe)

        timestamp = data.iloc[-1]['time']
        if prev_timestamp is None:
            prev_timestamp = timestamp

        if initial_event1_done:
            dto, data_dictionary = trade_logic_sell(symbol, timeframe, data.iloc[-1], data_dictionary, is_continuity)
            dto.current_candle_low = data.iloc[-1]["low"]
            dto.current_candle_high = data.iloc[-1]["high"]
        else:
            dto, data_dictionary = trade_logic_sell(symbol, timeframe, data.iloc[-2], data_dictionary, is_continuity)
            dto.current_candle_low = data.iloc[-2]["low"]
            dto.current_candle_high = data.iloc[-2]["high"]
            initial_event1_done = True

        # Adding a check of if stop_tracking_further_events is True then break out and mark thread as completed
        if dto.stop_tracking_further_events:
            default_log.debug(f"Stopping tracking of further events for symbol={symbol} having timeframe={timeframe} "
                              f"as stop_tracking_further_events={dto.stop_tracking_further_events}")
            opposite_issue = True
            break

        if dto.event2_occur_time is not None:
            # CHECK RANGE ISSUE
            if dto.range_issue:
                default_log.debug(f"Range issue has occurred for symbol={symbol} having timeframe={timeframe}")
                range_issue = True
                break

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

                # CHECK RANGE ISSUE
                # Calculate the distance between event 2 breakpoint and candle high
                # candle_high = data["high"][0]
                #
                # if dto.event3_occur_time is None:
                #     increased_price = dto.event2_occur_breakpoint + (dto.event2_occur_breakpoint * (end_range / 100))
                #     if candle_high > increased_price:
                #         default_log.debug(f"As the candle high ({candle_high}) has reached more than the "
                #                           f"increased_price ({increased_price}) which is calculated using "
                #                           f"event2_breakpoint ({dto.event2_occur_breakpoint}) and end_range "
                #                           f"({end_range}) for symbol={symbol} having timeframe={timeframe}")
                #         range_issue = True
                #         break

                continue

            # CHECK RANGE ISSUE
            # Calculate the distance between event 2 breakpoint and candle high
            # candle_high = data["high"][0]
            #
            # if dto.event3_occur_time is None:
            #     increased_price = dto.event2_occur_breakpoint + (dto.event2_occur_breakpoint * (end_range / 100))
            #     if candle_high > increased_price:
            #         default_log.debug(f"As the candle high ({candle_high}) has reached more than the "
            #                           f"increased_price ({increased_price}) which is calculated using "
            #                           f"event2_breakpoint ({dto.event2_occur_breakpoint}) and end_range "
            #                           f"({end_range}) for symbol={symbol} having timeframe={timeframe}")
            #         range_issue = True
            #         break

        if dto.event3_occur_time is None:
            if dto.range_issue:
                default_log.debug(f"Range issue has occurred for symbol={symbol} having timeframe={timeframe}")
                range_issue = True
                break
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

            # TODO: Move this to a proper place
            use_simulation = get_use_simulation_status()
            # if not use_simulation:
            if ((dto.entry_trade_order_id is not None) or (dto.extension1_trade_order_id is not None) or
                (dto.extension2_trade_order_id is not None) or (dto.cover_sl_trade_order_id is not None) or
                (dto.reverse1_trade_order_id is not None) or (dto.reverse2_trade_order_id is not None)) and \
                    (not use_simulation):

                current_time = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                if symbol in indices_list:

                    if current_time >= close_indices_position_time:
                        default_log.debug(f"Closing Trades for symbol={symbol} having timeframe={timeframe} as "
                                          f"already trade is in progress and current_time="
                                          f"{current_time} >= close_indices_position_time "
                                          f"({close_indices_position_time})")

                        close_position_quantity = int(round(dto.extension_quantity, 0))

                        default_log.debug(f"[CLOSE POSITION] Placing STOP TRADE for symbol={symbol}, indices_symbol="
                                          f"{indices_symbol} having timeframe={timeframe} with quantity="
                                          f"{close_position_quantity}")

                        close_position_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            quantity=close_position_quantity,
                            signal_type=SignalType.SELL,
                            entry_price=data.iloc[-1]['high']
                        )

                        if close_position_order_id is None:
                            default_log.debug(f"[CLOSE POSITION] Failed to close position of the active trade having "
                                              f"symbol={symbol}, indices_symbol={indices_symbol} and timeframe={timeframe} "
                                              f"with quantity={close_position_quantity}")
                            break

                        default_log.debug(
                            f"[CLOSE POSITION] Successfully closed trades of symbol={symbol}, indices_symbol="
                            f"{indices_symbol} having timeframe={timeframe}")

                        break

                    # If current time >= 15:29 IST then stop the trades
                    else:
                        default_log.debug(f"Continuing the trade alert tracking for symbol={symbol}, indices_symbol="
                                          f"{indices_symbol} having timeframe={timeframe} as current_time "
                                          f"({current_time}) >= close_indices_position_time "
                                          f"({close_indices_position_time})")

                else:

                    if current_time >= close_cash_trades_position_time:
                        close_position_quantity = int(round(dto.extension_quantity, 0))

                        default_log.debug(f"[CLOSE POSITION] Placing STOP TRADE for symbol={symbol} having timeframe="
                                          f"{timeframe} with quantity={close_position_quantity} as current_time "
                                          f"({current_time}) > close_cash_trades_position_time "
                                          f"({close_cash_trades_position_time})")

                        close_position_order_id = place_market_order(
                            symbol=symbol,
                            quantity=close_position_quantity,
                            signal_type=SignalType.BUY,
                            exchange="NSE",
                            entry_price=data.iloc[-1]['high']
                        )

                        if close_position_order_id is None:
                            default_log.debug(f"[CLOSE POSITION] Failed to close position of the active trade having "
                                              f"symbol={symbol} and timeframe={timeframe} with quantity="
                                              f"{close_position_quantity}")
                            break

                        default_log.debug(f"[CLOSE POSITION] Successfully closed trades of symbol={symbol} having "
                                          f"timeframe={timeframe}")

                        break

                    # If current time < 15:20 IST then stop the trades
                    else:
                        default_log.debug(f"Continuing the trade alert tracking for symbol={symbol}, indices_symbol="
                                          f"{indices_symbol} having timeframe={timeframe} as current_time "
                                          f"({current_time}) >= close_indices_position_time "
                                          f"({close_indices_position_time})")

            # find out how many trades needs to be made and the budget to be used
            # get the initial close price
            if initial_close_price is None:
                initial_close_price = data.iloc[-1]["close"]

            # if trades_details_dto is None:

            close_price = initial_close_price
            trades_details_dto = get_budget_and_no_of_trade_details(
                symbol=symbol,
                budget=loss_budget,
                close_price=close_price,
                dto=dto
            )

            default_log.debug(f"Budget and Trade details retrieved for symbol={symbol} "
                              f"and time_frame={dto.time_frame} having close_price={close_price}: "
                              f"{trades_details_dto}")

            if (not trades_details_dto.trades_to_make.entry_trade) and \
                    (not trades_details_dto.trades_to_make.extension1_trade) and \
                    (not trades_details_dto.trades_to_make.extension2_trade) and \
                    (not trades_details_dto.trades_to_make.cover_sl_trade):
                default_log.debug(f"No TRADES are to be made for symbol={symbol} and time_frame={timeframe}")
                break

            # Find out how many trades would be made
            # and calculating percentage to considered based on the trades to make
            maximum_trades_to_make = 0
            total_percentage = 0
            if trades_details_dto.trades_to_make.entry_trade:
                default_log.debug(f"Make Entry Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
                total_percentage += trade1_loss_percent
            else:
                # if first trade should not be made then increment trades_made by 1 (for checking of condition of
                # extension 1 and extension 2 trade)
                tried_creating_entry_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension1_trade:
                default_log.debug(f"Make Extension 1 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
                total_percentage += trade2_loss_percent
            else:
                tried_creating_extension1_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension2_trade:
                default_log.debug(f"Make Extension 2 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
                total_percentage += trade3_loss_percent
            else:
                tried_creating_extension2_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.cover_sl_trade:
                default_log.debug(f"Make Cover SL Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
            else:
                tried_creating_cover_sl_trade = True
                trades_made += 1

            # Adding cover sl trade
            if trades_details_dto.trades_to_make.cover_sl_trade:
                default_log.debug(f"Make Cover SL Trade for symbol={symbol} and indices_symbol={indices_symbol} "
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

            # If stop trade time i.e. 14:45 IST has been hit then only do calculations and don't take any trades
            if ((dto.entry_trade_order_id is None) and (dto.extension1_trade_order_id is None) and
                (dto.extension2_trade_order_id is None) and (dto.cover_sl_trade_order_id is None)) and \
                    (not use_simulation):

                current_time = datetime.now()
                if current_time >= stop_trade_time:

                    # CHECKING IF TP LEVEL REACHED
                    tp_value = dto.tp_values[-1].tp_with_buffer
                    candle_low = data.iloc[-1]['low']
                    current_close_price = data.iloc[-1]['close']

                    if current_close_price <= tp_value:
                        default_log.debug(
                            f"Current Candle Close ({current_close_price}) <= TP value ({tp_value}) for indices_"
                            f"symbol={indices_symbol} and symbol={symbol} and time_frame={timeframe}. "
                            f"Before placing any order as so EXITING the alert tracking")
                        break

                    # TODO: CHECKING IF SL LEVEL REACHED
                    sl_value = dto.sl_value + (2 * dto.sl_buffer)

                    trade_alert_status = "NO TRADE TIME"
                    default_log.debug(
                        f"As current time ({current_time}) >= stop_trade_time {stop_trade_time} and Entry"
                        f" Trade Order ID={dto.entry_trade_order_id}, Extension 1 Trade Order ID="
                        f"{dto.extension1_trade_order_id}, Extension 2 Trade Order ID="
                        f"{dto.extension2_trade_order_id}, SL Trade Order ID="
                        f"{dto.cover_sl_trade_order_id} for symbol={symbol} having time_frame={timeframe}")

                    # Store the current state of event in the database
                    response = store_current_state_of_event(
                        thread_detail_id=thread_detail_id,
                        symbol=symbol,
                        time_frame=timeframe,
                        signal_type=SignalType.BUY,
                        trade_alert_status=trade_alert_status,
                        configuration=configuration,
                        is_completed=False,
                        dto=dto
                    )

                    if not response:
                        default_log.debug(f"An error occurred while storing thread event details in database")
                        return False

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

                        # Store the current state of event in the database
                        response = store_current_state_of_event(
                            thread_detail_id=thread_detail_id,
                            symbol=symbol,
                            time_frame=timeframe,
                            signal_type=SignalType.BUY,
                            trade_alert_status=trade_alert_status,
                            configuration=configuration,
                            is_completed=True,
                            dto=dto
                        )

                        if not response:
                            default_log.debug(
                                f"An error occurred while storing thread event details in database")
                            return False

                        return

                    # Continue calculating the take profit and stop loss but DON'T TAKE TRADE
                    continue

            # Flow to check if current time is greater than 15:30 IST then mark the alert as NEXT DAY for continuing
            use_simulation = get_use_simulation_status()
            if not use_simulation:
                current_timestamp = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                try:
                    if current_timestamp > market_close_time:
                        default_log.debug(
                            f"As current timestamp ({current_timestamp}) > market close time ({market_close_time})"
                            f" so stopping the alert tracking and marking the status of the alert as NEXT DAY "
                            f"of symbol={symbol} having timeframe={timeframe}")

                        # Mark the status as NEXT DAY for the alert and return
                        # Store the current state of event in the database
                        response = store_current_state_of_event(
                            thread_detail_id=thread_detail_id,
                            symbol=symbol,
                            time_frame=timeframe,
                            signal_type=SignalType.BUY,
                            trade_alert_status="NEXT DAY",
                            configuration=configuration,
                            is_completed=True,
                            dto=dto
                        )

                        if not response:
                            default_log.debug(
                                f"An error occurred while storing thread event details in database")
                            return False

                        return
                    else:
                        default_log.debug(f"Not marking the status of the alert as NEXT DAY as current timestamp "
                                          f"({current_timestamp}) < market close time ({market_close_time}) for symbol={symbol}"
                                          f" having timestamp={timestamp}")
                except Exception as e:
                    default_log.debug(f"An error occurred while checking if current timestamp ({current_timestamp}) > "
                                      f"market close time ({market_close_time}) for symbol={symbol} having "
                                      f"timeframe={timeframe}. Error: {e}")

            # ======================================================================================= #

            # Placing the entry MARKET order trade
            if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
                    not tried_creating_entry_order:

                tried_creating_entry_order = True

                # Calculate trade 1 quantity
                entry_sl_value = dto.sl_value
                entry_price = dto.entry_price
                loss_percent = loss_budget * trade1_loss_percent

                default_log.debug(f"Entry Price={entry_price} and Entry SL value={entry_sl_value} for symbol={symbol} "
                                  f"and indices_symbol={indices_symbol} having timeframe={timeframe}")

                trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
                trade1_quantity = int(round(trade1_quantity, 0))
                dto.trade1_quantity = trade1_quantity
                dto.actual_calculated_trade1_quantity = trade1_quantity

                # PLACING OPTION CHAIN ORDER
                if indices_symbol is not None:
                    default_log.debug(f"Rounding off trade1_quantity ({trade1_quantity}) to the "
                                      f"indices_quantity_multiplier ({indices_quantity_multiplier}) for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                    trade1_quantity = round_to_nearest_multiplier(trade1_quantity,
                                                                  indices_quantity_multiplier)

                    default_log.debug(f"After rounding off trade1_quantity to {trade1_quantity} using "
                                      f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                    # make_entry_trade = trades_details_dto.trades_to_make.entry_trade

                    if trade1_quantity == 0:
                        default_log.debug(
                            f"As trade1_quantity ({trade1_quantity}) 0 so skipping placing MARKET "
                            f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
                            f"timeframe={timeframe}")
                        # dto.trade1_quantity = trade1_quantity
                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'
                    elif (trade1_quantity % indices_quantity_multiplier) != 0:
                        default_log.debug(
                            f"As trade1_quantity ({trade1_quantity}) is not divisible by indices_quantity_"
                            f"multiplier ({indices_quantity_multiplier}) so skipping placing MARKET "
                            f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
                            f"timeframe={timeframe}")
                        # dto.trade1_quantity = trade1_quantity
                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'
                    else:
                        default_log.debug(f"Placing indices MARKET order for symbol={symbol} and indices_symbol="
                                          f"{indices_symbol} having timeframe={timeframe} as "
                                          f"quantity={trade1_quantity} is divisible by indices_quantity_multiplier="
                                          f"{indices_quantity_multiplier}")

                        entry_trade_order_id, fill_price = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.BUY,
                            quantity=trade1_quantity,
                            entry_price=entry_price
                        )

                        if entry_trade_order_id is None:
                            default_log.debug(f"An error occurred while placing MARKET order for indices_symbol="
                                              f"{indices_symbol} and symbol={symbol} having timeframe={timeframe} "
                                              f"with quantity={trade1_quantity}")

                            # TODO: changed here
                            # As TRADE 1 failed so set the trade 1 quantity as zero
                            # dto.trade1_quantity = 0
                            # dto.extension_quantity = 0

                            # Set tried_creating_entry_order as false
                            # tried_creating_entry_order = False

                        else:
                            dto.entry_trade_order_id = entry_trade_order_id
                            dto.entry_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                            budget_used = fill_price * trade1_quantity
                            # budget_used = entry_price * trade1_quantity

                            # Calculate total budget that will be required for the remaining trades (including EXTENSION
                            # TRADES)
                            # remaining_trade_percentage (y_perc) = total_percentage - trade1_loss_percent (x_perc)
                            # x_perc_value = 5000 then y_perc_value = ?

                            total_budget_required = calculate_required_budget_for_trades(
                                used_percent_ratio=trade1_loss_percent,
                                used_ratio_value=budget_used,
                                total_percent_ratio=total_percentage
                            )

                            zerodha_equity = get_zerodha_equity()

                            if (zerodha_equity - total_budget_required) < 0:
                                default_log.debug(
                                    f"Not Enough Equity remaining for placing remaining trades with required "
                                    f"budget={total_budget_required} for symbol={symbol} having "
                                    f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                    f"remaining equity={zerodha_equity}")
                                # Even if equity is less, then also retry when equity is enough
                                # tried_creating_entry_order = False
                                # not_enough_equity = True
                                # break
                            else:
                                remaining_equity = allocate_equity_for_trade(total_budget_required)
                                default_log.debug(
                                    f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                    f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                    f"Remaining Equity: Rs. {remaining_equity}")

                                total_budget_used = total_budget_required

                            # dto.extension_quantity = trade1_quantity
                            dto.trade1_quantity = trade1_quantity

                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'

                # PLACING STOCK MARKET ORDER
                else:
                    default_log.debug(f"Placing MARKET order for STOCK symbol={symbol} having timeframe={timeframe} "
                                      f"with quantity={trade1_quantity}")

                    entry_trade_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        quantity=trade1_quantity,
                        exchange="NSE",
                        entry_price=entry_price
                    )

                    if entry_trade_order_id is None:
                        default_log.debug(f"An error occurred while placing MARKET order for symbol="
                                          f"{symbol} and indices_symbol={indices_symbol} having timeframe={timeframe} "
                                          f"with quantity={trade1_quantity}")

                        # As TRADE 1 failed so set the trade 1 quantity as zero
                        # dto.trade1_quantity = 0
                        # dto.extension_quantity = 0

                        # Set tried_creating_entry_order as false
                        # tried_creating_entry_order = False

                    else:
                        dto.entry_trade_order_id = entry_trade_order_id
                        dto.entry_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        budget_used = fill_price * trade1_quantity
                        # budget_used = entry_price * trade1_quantity

                        # Calculate total budget that will be required for the remaining trades (including EXTENSION
                        # TRADES)
                        total_budget_required = calculate_required_budget_for_trades(
                            used_percent_ratio=trade1_loss_percent,
                            used_ratio_value=budget_used,
                            total_percent_ratio=total_percentage
                        )

                        zerodha_equity = get_zerodha_equity()

                        if (zerodha_equity - total_budget_required) < 0:
                            default_log.debug(f"Not Enough Equity remaining for placing remaining trades with required "
                                              f"budget={total_budget_required} for symbol={symbol} having "
                                              f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                              f"remaining equity={zerodha_equity}")
                            # Even if equity is less, then also retry when equity is enough
                            # tried_creating_entry_order = False
                            # not_enough_equity = True
                            # break
                        else:
                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                            default_log.debug(
                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                f"Remaining Equity: Rs. {remaining_equity}")

                            total_budget_used = total_budget_required

                        dto.trade1_quantity = trade1_quantity
                        dto.extension_quantity = trade1_quantity

                    dto.tp_order_status = 'OPEN'
                    dto.sl_order_status = 'OPEN'

                # Even if trade making failed or succeeded increment the trades counter by 1
                trades_made += 1

            # This will keep track of LIMIT or SL-M order get completed or not ONLY for non-REVERSE TRADE ORDERS
            if ((dto.entry_trade_order_id is not None) or (dto.extension1_trade_order_id is not None) or
                (dto.extension2_trade_order_id is not None) or (
                        dto.cover_sl_trade_order_id is not None)) and (
                    (dto.reverse1_trade_order_id is None) and (dto.reverse1_trade_order_id is None)):

                candle_low = data.iloc[-1]['low']
                candle_high = data.iloc[-1]['high']
                current_close_price = data.iloc[-1]['close']

                # CHECK IF TP OR SL HAS BEEN HIT
                tp_value = dto.tp_values[-1].tp_with_buffer
                sl_value = dto.sl_value + (2 * dto.sl_buffer)

                quantity = dto.extension_quantity if dto.extension_quantity is not None else dto.trade1_quantity

                if (current_close_price <= tp_value) and (dto.tp_order_id is None) and \
                        (dto.tp_order_status != 'COMPLETE') and (dto.sl_order_id is None):
                    # TODO: Remove SL details from SL dictionary
                    try:
                        default_log.debug(f"As Take Profit level has been hit for symbol={symbol} having timeframe="
                                          f"{timeframe} with signal_type=BUY. So removing the SL details of the alert")
                        remove_sl_details_of_completed_trade(
                            symbol=symbol,
                            signal_type=SignalType.BUY,
                            time_frame=int(timeframe)
                        )
                    except Exception as e:
                        default_log.debug(f"An error occurred while removing SL details for the COMPLETED trade having "
                                          f"symbol={symbol} and timeframe={timeframe}")

                    default_log.debug(
                        f"Current Candle Close ({current_close_price}) <= TP value ({tp_value}) for indices_"
                        f"symbol={indices_symbol} and symbol={symbol} and time_frame={timeframe}. "
                        f"So placing MARKET order with quantity={quantity} and "
                        f"signal_type={SignalType.BUY}")

                    if indices_symbol is None:
                        tp_order_id, fill_price = place_market_order(
                            symbol=symbol,
                            signal_type=SignalType.BUY,
                            quantity=quantity,
                            exchange="NSE",
                            entry_price=tp_value
                        )

                        if tp_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (LIMIT) MARKET order for symbol={symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.BUY}")
                        else:
                            dto.tp_order_id = tp_order_id

                            # Reallocate the budget
                            default_log.debug(f"Reallocating the budget ({total_budget_used}) kept aside to the "
                                              f"equity for symbol={symbol} having timeframe={timeframe} and "
                                              f"indices_symbol={indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.tp_hit = True
                        dto.tp_order_status = 'COMPLETE'
                        break

                    else:
                        tp_order_id, fill_price = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity,
                            entry_price=tp_value
                        )

                        if tp_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (LIMIT) MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")
                        else:
                            dto.tp_order_id = tp_order_id

                            # Reallocate the budget
                            default_log.debug(
                                f"Reallocating the budget ({total_budget_used}) kept aside to the equity for "
                                f"symbol={symbol} having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.tp_hit = True
                        dto.tp_order_status = 'COMPLETE'
                        break

                    # dto.tp_order_id = tp_order_id
                    # dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    # data_not_found = False
                    # dto.tp_order_status = 'COMPLETE'
                    # break

                # Check SL hit or not
                elif (current_close_price >= sl_value) and (dto.sl_order_id is None) and \
                        (dto.sl_order_status != 'COMPLETE') and (dto.tp_order_id is None):
                    # TODO: Remove SL details from SL dictionary
                    try:
                        default_log.debug(f"As Take Profit level has been hit for symbol={symbol} having timeframe="
                                          f"{timeframe} with signal_type=BUY. So removing the SL details of the alert")
                        remove_sl_details_of_completed_trade(
                            symbol=symbol,
                            signal_type=SignalType.BUY,
                            time_frame=int(timeframe)
                        )
                    except Exception as e:
                        default_log.debug(f"An error occurred while removing SL details for the COMPLETED trade having "
                                          f"symbol={symbol} and timeframe={timeframe}")

                    default_log.debug(
                        f"Current Candle Close ({current_close_price}) >= SL value ({sl_value}) for indices_symbol="
                        f"{indices_symbol} and symbol={symbol} and time_frame={timeframe}. So placing MARKET (SL-M) "
                        f"order with quantity={quantity} and signal_type={SignalType.BUY}")

                    if indices_symbol is None:
                        sl_order_id, fill_price = place_market_order(
                            symbol=symbol,
                            signal_type=SignalType.BUY,
                            quantity=quantity,
                            exchange="NSE",
                            entry_price=sl_value
                        )

                        if sl_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (SL-M) MARKET order for symbol={symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.BUY}")
                        else:
                            dto.sl_order_id = sl_order_id

                            # Reallocate the budget
                            default_log.debug(
                                f"Reallocating the budget (Rs. {total_budget_used}) kept aside to the equity for "
                                f"symbol={symbol} having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.sl_hit = True
                        dto.sl_order_status = 'COMPLETE'
                        if not take_reverse_trade:
                            default_log.debug(f"Not Placing Reverse Trade as take_reverse_trade={take_reverse_trade} "
                                              f"for symbol={symbol}, indices_symbol={indices_symbol} having "
                                              f"timeframe={timeframe}")
                            break

                    else:
                        sl_order_id, fill_price = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity,
                            entry_price=sl_value
                        )

                        if sl_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (SL-M) MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")
                        else:
                            dto.sl_order_id = sl_order_id

                            # Reallocate the budget
                            default_log.debug(
                                f"Reallocating the budget (Rs. {total_budget_used}) kept aside to the equity for "
                                f"symbol={symbol} having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.sl_hit = True
                        dto.sl_order_status = 'COMPLETE'
                        if not take_reverse_trade:
                            default_log.debug(f"Not Placing Reverse Trade as take_reverse_trade={take_reverse_trade} "
                                              f"for symbol={symbol}, indices_symbol={indices_symbol} having "
                                              f"timeframe={timeframe}")
                            break

            # This will keep track that if all trades order ids are null and if it reaches TP level then stop alert
            # tracking and exit
            if (dto.entry_trade_order_id is None) and (dto.extension1_trade_order_id is None) and \
                    (dto.extension2_trade_order_id is None) and (dto.cover_sl_trade_order_id is None):

                # CHECKING IF TP LEVEL REACHED
                tp_value = dto.tp_values[-1].tp_with_buffer
                candle_low = data.iloc[-1]['low']
                current_close_price = data.iloc[-1]['close']

                if current_close_price <= tp_value:
                    default_log.debug(
                        f"Current Candle Close ({current_close_price}) <= TP value ({tp_value}) for indices_"
                        f"symbol={indices_symbol} and symbol={symbol} and time_frame={timeframe}. "
                        f"Before placing any order as so EXITING the alert tracking")
                    dto.trade1_quantity = dto.actual_calculated_trade1_quantity if dto.actual_calculated_trade1_quantity is not None else 0
                    dto.extension1_quantity = dto.actual_calculated_extension1_quantity if dto.actual_calculated_extension1_quantity is not None else 0
                    dto.extension2_quantity = dto.actual_calculated_extension2_quantity if dto.actual_calculated_extension2_quantity is not None else 0
                    short_quantity_issue = True
                    break

            # ======================================================================================= #

            # OLD FLOW OF CREATING ENTRY ORDER WITH SL AND TP ORDERS ALSO
            # if indices_symbol is not None:
            #     candle_high = data.iloc[-1]["high"]
            #     candle_low = data.iloc[-1]["low"]
            #
            #     default_log.debug(f"Indices symbol ({indices_symbol}) is present so only will place MARKET orders and "
            #                       f"not LIMIT and SL-M orders with current_candle_high={candle_high} and "
            #                       f"current_candle_low={candle_low}")
            #
            #     # Placing the entry MARKET order trade
            #     if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
            #             not tried_creating_entry_order:
            #
            #         # Calculate trade 1 quantity
            #         entry_sl_value = dto.sl_value
            #         entry_price = dto.entry_price
            #         loss_percent = loss_budget * trade1_loss_percent
            #
            #         default_log.debug(f"[For indices_symbol={indices_symbol}] Entry Price={entry_price} and "
            #                           f"Entry SL value={entry_sl_value}")
            #
            #         trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
            #         trade1_quantity = int(round(trade1_quantity, 0))
            #         dto.trade1_quantity = trade1_quantity
            #
            #         default_log.debug(f"Rounding off trade1_quantity ({trade1_quantity}) to the "
            #                           f"indices_quantity_multiplier ({indices_quantity_multiplier}) for symbol={symbol} "
            #                           f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
            #
            #         trade1_quantity = round_to_nearest_multiplier(trade1_quantity,
            #                                                       indices_quantity_multiplier)
            #
            #         default_log.debug(f"After rounding off trade1_quantity to {trade1_quantity} using "
            #                           f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
            #                           f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
            #         make_entry_trade = trades_details_dto.trades_to_make.entry_trade
            #         if (trade1_quantity > 0) and (
            #                 (trade1_quantity % indices_quantity_multiplier) != 0) and make_entry_trade:
            #             default_log.debug(
            #                 f"As trade1_quantity ({trade1_quantity}) is not divisible by indices_quantity_"
            #                 f"multiplier ({indices_quantity_multiplier}) so skipping placing MARKET "
            #                 f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
            #                 f"timeframe={timeframe}")
            #             # dto.trade1_quantity = trade1_quantity
            #             tried_creating_entry_order = True
            #             dto.tp_order_status = 'OPEN'
            #             dto.sl_order_status = 'OPEN'
            #         else:
            #             quantity = trade1_quantity
            #             # quantity = 50 if symbol == "NIFTY" else 45
            #             entry_trade_order_id = place_indices_market_order(
            #                 indice_symbol=indices_symbol,
            #                 signal_type=SignalType.BUY,
            #                 quantity=quantity
            #             )
            #
            #             tried_creating_entry_order = True
            #
            #             if entry_trade_order_id is None:
            #                 default_log.debug(
            #                     f"An error occurred while placing MARKET order for indices symbol={indices_symbol} "
            #                     f"with quantity={quantity} with signal_type={SignalType.SELL}")
            #             else:
            #                 dto.entry_trade_order_id = entry_trade_order_id
            #
            #             dto.tp_order_status = 'OPEN'
            #             dto.sl_order_status = 'OPEN'
            #
            #             dto.trade1_quantity = quantity
            #
            #         # Even if trade making failed or succeeded increment the trades counter by 1
            #         trades_made += 1
            #
            #     if dto.entry_trade_order_id or dto.extension1_trade_order_id or dto.extension2_trade_order_id:
            #         # Check TP hit or not only if order has been placed
            #         tp_value = dto.tp_values[-1].tp_value
            #         # sl_value = dto.sl_value + dto.candle_length  # added buffer
            #         sl_value = dto.sl_value + (2 * dto.candle_length)  # added buffer
            #
            #         quantity = dto.extension_quantity if dto.extension_quantity is not None else dto.trade1_quantity
            #
            #         if candle_low <= tp_value:
            #             default_log.debug(f"Current Candle Low ({candle_low}) <= TP value ({tp_value}) for indices_"
            #                               f"symbol={indices_symbol} and time_frame={timeframe}. So placing MARKET order "
            #                               f"with quantity={quantity} and signal_type={SignalType.BUY}")
            #
            #             tp_order_id = place_indices_market_order(
            #                 indice_symbol=indices_symbol,
            #                 signal_type=SignalType.SELL,
            #                 quantity=quantity
            #             )
            #
            #             if tp_order_id is None:
            #                 default_log.debug(
            #                     f"An error occurred while placing (LIMIT) MARKET order for indices symbol={indices_symbol} "
            #                     f"with quantity={quantity} with signal_type={SignalType.SELL}")
            #
            #             dto.tp_order_id = tp_order_id
            #             dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
            #             dto.tp_hit = True
            #             data_not_found = False
            #             dto.tp_order_status = 'COMPLETE'
            #             break
            #
            #         # Check SL hit or not
            #         elif candle_high >= sl_value:
            #             default_log.debug(
            #                 f"Current Candle High ({candle_high}) >= SL value ({sl_value}) for indices_symbol="
            #                 f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
            #                 f"quantity={quantity} and signal_type={SignalType.BUY}")
            #
            #             sl_order_id = place_indices_market_order(
            #                 indice_symbol=indices_symbol,
            #                 signal_type=SignalType.SELL,
            #                 quantity=quantity
            #             )
            #
            #             if sl_order_id is None:
            #                 default_log.debug(
            #                     f"An error occurred while placing (SL-M) MARKET order for indices symbol={indices_symbol} "
            #                     f"with quantity={quantity} with signal_type={SignalType.SELL}")
            #
            #             dto.sl_order_id = sl_order_id
            #             dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
            #             dto.sl_hit = True
            #             data_not_found = False
            #             dto.sl_order_status = 'COMPLETE'
            #             break

            # Only Store SL value when reverse trade have not been placed
            if (dto.reverse1_trade_order_id is None) and (dto.reverse2_trade_order_id is None):
                default_log.debug(f"Storing SL value of symbol={symbol}, timeframe={timeframe}, "
                                  f"signal_type={SignalType.BUY} having stop_loss={dto.sl_value}")

                store_sl_details_of_active_trade(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    stop_loss=dto.sl_value,
                    event1_occur_time=dto.event1_occur_time,
                    time_frame=int(timeframe)
                )

            if extension_diff is None:
                default_log.debug(f"Extension Difference = SL Value ({dto.sl_value}) - "
                                  f"Event 1 Candle Low ({dto.event1_candle_low})")
                extension_diff = abs(dto.sl_value - dto.event1_candle_low)

            # if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
            #         (indices_symbol is None) and not tried_creating_entry_order:
            #     # Check the SL increase condition
            #     entry_price = dto.entry_price
            #
            #     event_data_dto, error_occurred = place_initial_zerodha_trades(
            #         event_data_dto=dto,
            #         data_dictionary=data_dictionary,
            #         signal_type=SignalType.SELL,
            #         candle_data=data.iloc[-1],
            #         symbol=symbol,
            #         loss_budget=loss_budget,
            #         indices_symbol=indices_symbol
            #     )
            #
            #     if error_occurred:
            #         default_log.debug(f"An error occurred while placing MARKET order for symbol={symbol} and "
            #                           f"indices_symbol={indices_symbol} and event_data_dto={dto}")
            #
            #     tried_creating_entry_order = True
            #     dto = event_data_dto
            #     trades_made += 1
            #
            #     # Updating the extension difference
            #     default_log.debug(f"[UPDATING] Extension Difference = Entry Price ({dto.entry_price}) - "
            #                       f"SL Value ({dto.sl_value})")
            #     extension_diff = abs(dto.entry_price - dto.sl_value)

            if not trades_details_dto.trades_to_make.entry_trade:
                dto.trade1_quantity = 0

            # THIS FLOW USED TO UPDATE TAKE PROFIT VALUE CONSTANTLY
            # if (dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.tp_order_id is not None) and \
            #         (indices_symbol is None):
            #     take_profit = dto.tp_values[-1].tp_with_buffer
            #
            #     # round off the price of take profit
            #     formatted_value = round_value(
            #         symbol=symbol if indices_symbol is None else indices_symbol,
            #         price=take_profit,
            #         exchange="NSE" if indices_symbol is None else "NFO"
            #     )
            #     take_profit = formatted_value
            #
            #     # dto.tp_values[-1].tp_value = take_profit
            #     dto.tp_values[-1].tp_with_buffer = take_profit
            #     use_simulation = get_use_simulation_status()
            #     if use_simulation:
            #         default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
            #                           f"id={dto.entry_trade_order_id} take_profit to {take_profit}")
            #
            #         tp_order_id = update_zerodha_order_with_take_profit(
            #             kite=kite,
            #             zerodha_order_id=dto.tp_order_id,
            #             transaction_type=SignalType.BUY,
            #             trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
            #             take_profit=take_profit,
            #             candle_high=data.iloc[-1]["high"],
            #             candle_low=data.iloc[-1]["low"],
            #             trading_symbol=symbol,
            #             exchange="NSE" if indices_symbol is None else "NFO"
            #         )
            #
            #         if tp_order_id is None:
            #             default_log.debug(f"An error occurred while updating TP order for "
            #                               f"trading_symbol={symbol}, having transaction_type as {SignalType.SELL} "
            #                               f"and take_profit={take_profit} ")
            #         else:
            #             default_log.debug(f"[BUY] Updated TP order with ID: {tp_order_id} with "
            #                               f"take profit={take_profit} "
            #                               f"for symbol={symbol} and indices_symbol={indices_symbol}")
            #             dto.tp_order_id = tp_order_id
            #
            #     else:
            #         default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
            #                           f"id={dto.entry_trade_order_id} take_profit to {take_profit}")
            #
            #         tp_order_id = update_zerodha_order_with_take_profit(
            #             kite=kite,
            #             zerodha_order_id=dto.tp_order_id,
            #             transaction_type=SignalType.BUY,
            #             trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
            #             take_profit=take_profit,
            #             trading_symbol=symbol,
            #             exchange="NSE" if indices_symbol is None else "NFO"
            #         )
            #
            #         if tp_order_id is None:
            #             default_log.debug(f"An error occurred while updating TP order for "
            #                               f"trading_symbol={symbol}, having transaction_type as {SignalType.SELL} "
            #                               f"and take_profit={take_profit} ")
            #         else:
            #             default_log.debug(f"[BUY] Updated TP order with ID: {tp_order_id} with "
            #                               f"take profit={take_profit} "
            #                               f"for symbol={symbol} and indices_symbol={indices_symbol}")
            #             dto.tp_order_id = tp_order_id

            # if (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.sl_order_id is not None):

            # Condition 1 [EXTENSION OF SL]
            # Check the SL increase condition
            entry_price = dto.entry_price
            current_candle_close = data.iloc[-1]["close"]

            # Check for condition of entry price
            # if ((entry_price + ((dto.sl_value - entry_price) / 2)) <= current_candle_high) and not sl_got_extended:
            #     default_log.debug(f"[EXTENSION OF SL] For symbol={symbol} and time_frame={dto.time_frame} "
            #                       f"Entry Price ({entry_price}) + [[SL value ({dto.sl_value}) - "
            #                       f"Entry Price ({entry_price})] / 2] "
            #                       f"<= Current Candle High ({current_candle_high})")

            # Only Update SL value when reverse trade have not been placed
            if (dto.reverse1_trade_order_id is None) and (dto.reverse2_trade_order_id is None):
                do_update, stop_loss_to_update_to, event1_occur_time = do_update_of_sl_values(
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
                    dto.extended_sl = stop_loss_to_update_to

                    dto.extended_sl_timestamp = event1_occur_time

                    dto.cover_sl = stop_loss_to_update_to
                    sl_got_extended = True

                    # if indices_symbol is None:
                    #     use_simulation = get_use_simulation_status()
                    #     # Only updating SL order when indices symbol is None
                    #     # as for indices symbol SL-M order is not placed
                    #     if use_simulation:
                    #         candle_high = data.iloc[-1]["high"]
                    #         candle_low = data.iloc[-1]["low"]
                    #         event_data_dto = update_zerodha_stop_loss_order(
                    #             dto,
                    #             indices_symbol=indices_symbol,
                    #             candle_high=candle_high,
                    #             candle_low=candle_low
                    #         )
                    #
                    #         dto = event_data_dto
                    #     else:
                    #         event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                    #         dto = event_data_dto

                # Condition 2
                # Check condition of updating Stop Loss according to average price
                # average_entry_price = dto.entry_price
                # if dto.extension1_trade_order_id is not None:
                #     average_entry_price = (dto.entry_price + dto.extension1_entry_price) / 2
                #
                # if dto.extension2_trade_order_id is not None:
                #     average_entry_price = (dto.entry_price + dto.extension1_entry_price + dto.extension2_entry_price) / 3
                #
                # current_candle_close = data.iloc[-1]["close"]
                #
                # if (average_entry_price - current_candle_close) > ((dto.sl_value - average_entry_price) * 0.8):
                #     default_log.debug(f"Satisfied condition for updating SL according to average entry price as "
                #                       f"[Average Entry Price ({average_entry_price}) - Current Candle close "
                #                       f"({current_candle_close})] > "
                #                       f"[SL value ({dto.sl_value}) - Average Entry Price ({average_entry_price})] * 0.8")
                #     dto.sl_value = average_entry_price
                #     dto.extended_sl = average_entry_price
                #     dto.cover_sl = stop_loss_to_update_to
                #
                #     if indices_symbol is None:
                #         use_simulation = get_use_simulation_status()
                #         # Only updating SL order when indices symbol is None
                #         # as for indices symbol SL-M order is not placed
                #         if use_simulation:
                #             candle_high = data.iloc[-1]["high"]
                #             candle_low = data.iloc[-1]["low"]
                #             event_data_dto = update_zerodha_stop_loss_order(
                #                 dto,
                #                 indices_symbol=indices_symbol,
                #                 candle_high=candle_high,
                #                 candle_low=candle_low
                #             )
                #
                #             dto = event_data_dto
                #         else:
                #             event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                #             dto = event_data_dto

            # Extra Trade placing logic
            # Place extra trade if candle high goes ABOVE by a threshold value
            if (extension_diff is not None) and \
                    ((dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])
                     and (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])) and \
                    (trades_details_dto.trades_to_make.extension1_trade or
                     trades_details_dto.trades_to_make.extension2_trade):

                default_log.debug(f"Extension Diff={extension_diff}, trades_made={trades_made}, "
                                  f"TP Order status={dto.tp_order_status} with id={dto.tp_order_id} and "
                                  f"SL Order status={dto.sl_order_status} with id={dto.sl_order_id} ")

                extension_time_stamp = data.iloc[-1]["time"]
                candle_high_price = data.iloc[-1]["high"]
                current_close_price = data.iloc[-1]['close']

                default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                  f"and candle_high_price = {candle_high_price} at timestamp = {extension_time_stamp}")

                # entry_price_difference = abs(dto.sl_value - candle_high_price)
                entry_price_difference = abs(dto.sl_value - dto.entry_price)

                # if tried_creating_extension1_order and trades_details_dto.trades_to_make.extension1_trade:
                #     default_log.debug(f"Extension 1 trade has been made as Extension 1 Trade order id="
                #                       f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                #                       f"{tried_creating_extension1_order} and Make extension 1 trade status="
                #                       f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 2 "
                #                       f"trade threshold percent={extension2_threshold_percent}")
                #     threshold_percent = extension2_threshold_percent
                # else:
                #     default_log.debug(f"Extension 1 trade has not been made as Extension 1 Trade order id="
                #                       f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                #                       f"{tried_creating_extension1_order} and Make extension 1 trade status="
                #                       f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 1 "
                #                       f"trade threshold percent={extension1_threshold_percent}")
                #     threshold_percent = extension1_threshold_percent

                extension1_point = dto.entry_price + (extension_diff * extension1_threshold_percent)
                extension2_point = dto.entry_price + (extension_diff * extension2_threshold_percent)

                if (current_close_price >= extension1_point) and not reached_extension1_point:
                    default_log.debug(f"Reached Extension 1 Point as current_close_price ({current_close_price}) <= "
                                      f"Extension 1 point ({extension1_point}) with entry_price={dto.entry_price}, "
                                      f"extension_diff={extension_diff} for symbol={symbol} having "
                                      f"timeframe={timeframe}")
                    reached_extension1_point = True
                    threshold_point = extension1_point
                    threshold = (extension_diff * extension1_threshold_percent)
                    entry_price_difference = abs(dto.sl_value - threshold_point)

                    default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                      f"at timestamp = {extension_time_stamp} and "
                                      f"current_close_price={current_close_price} and threshold={threshold} and "
                                      f"threshold_point={threshold_point} and Entry Price Difference="
                                      f"{entry_price_difference}")

                if (current_close_price >= extension2_point) and not reached_extension2_point:
                    default_log.debug(f"Reached Extension 2 Point as current_close_price ({current_close_price}) <= "
                                      f"Extension 2 point ({extension2_point}) with entry_price={dto.entry_price}, "
                                      f"extension_diff={extension_diff} for symbol={symbol} having "
                                      f"timeframe={timeframe}")
                    reached_extension2_point = True
                    threshold_point = extension2_point
                    threshold = (extension_diff * extension2_threshold_percent)
                    entry_price_difference = abs(dto.sl_value - threshold_point)

                    default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                      f"at timestamp = {extension_time_stamp} and "
                                      f"current_close_price={current_close_price} and threshold={threshold} and "
                                      f"threshold_point={threshold_point} and Entry Price Difference="
                                      f"{entry_price_difference}")

                # threshold = extension_diff * (config_threshold_percent * trades_made)
                # threshold = extension_diff * threshold_percent
                # threshold_point = dto.entry_price + threshold

                # default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                #                   f"at timestamp = {extension_time_stamp} and "
                #                   f"current_candle_high={candle_high_price} and threshold={threshold} and "
                #                   f"threshold_point={threshold_point} ")

                # if entry_price_difference >= threshold:
                # if candle_high_price >= threshold_point:
                # if current_close_price >= threshold_point:
                if reached_extension1_point or reached_extension2_point:
                    default_log.debug(
                        f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
                        f"and SL value = {dto.sl_value} "
                        f"and current_close_price = {current_close_price} "
                        f"at timestamp = {extension_time_stamp} "
                        f"Reached Extension 1 Point={reached_extension1_point} and "
                        f"Reached Extension 2 Point={reached_extension2_point}")

                    # Check if entry trade was placed or not
                    # if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
                    #         not tried_creating_entry_order and (reached_extension1_point or reached_extension2_point):
                    #     # This condition will occur only when an attempt was made to place entry trade but failed
                    #     # So don't place entry trade and mark tried_creating_entry_order as True
                    #     default_log.debug(f"As Entry Trade order id={dto.entry_trade_order_id} and Make Entry Trade="
                    #                       f"{trades_details_dto.trades_to_make.entry_trade} and tried_creating_entry_"
                    #                       f"order={tried_creating_entry_order} and current_close_price="
                    #                       f"{current_close_price} and reached_extension1_point="
                    #                       f"{reached_extension1_point}, reached_extension2_point="
                    #                       f"{reached_extension2_point} so will stop "
                    #                       f"trying to place entry trade and place extension trade")
                    #     tried_creating_entry_order = True

                    # Check if extension 1 trade was placed or not
                    # if (dto.extension1_trade_order_id is None) and trades_details_dto.trades_to_make.extension1_trade and \
                    #         not tried_creating_extension1_order and reached_extension2_point:
                    #     default_log.debug(
                    #         f"As Extension 1 Trade order id={dto.extension1_trade_order_id} and Make Extension 1 Trade="
                    #         f"{trades_details_dto.trades_to_make.extension1_trade} and tried_creating_extension1_order="
                    #         f"{tried_creating_entry_order} and current_close_price="
                    #         f"{current_close_price} and reached_extension2_point="
                    #         f"{reached_extension2_point} so will stop "
                    #         f"trying to place extension 1 trade and place extension 2 trade")
                    #     tried_creating_extension1_order = True

                    # PLACING EXTENSION 2 ORDER
                    # If first extension trade is already done placing second extension trade
                    if tried_creating_extension1_order and (not tried_creating_extension2_order) and \
                            (dto.extension2_trade_order_id is None) and reached_extension2_point:
                        # If first two trades were placed then check if third trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension2_trade:
                            tried_creating_extension2_order = True
                            loss_percent = loss_budget * trade3_loss_percent
                            # loss_percent = trade3_loss_percent
                            default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference

                            # if indices_symbol is not None:

                            total_quantity = int(round(extension_quantity, 0))
                            # make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                            # make_extension1_trade = trades_details_dto.trades_to_make.extension1_trade

                            dto.extension2_quantity = total_quantity
                            dto.actual_calculated_extension2_quantity = total_quantity

                            # EXTENSION 2 OPTION CHAIN TRADE
                            if indices_symbol is not None:

                                # QUANTITY LOGIC FOR EXTENSION 2 TRADE
                                if dto.extension1_trade_order_id is None:
                                    extension1_quantity = dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                    trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0
                                    if dto.entry_trade_order_id is None:
                                        total_quantity += (extension1_quantity + trade1_quantity)

                                        dto.extension_quantity = extension1_quantity + trade1_quantity

                                    else:
                                        total_quantity += extension1_quantity

                                        dto.extension_quantity = trade1_quantity

                                elif dto.entry_trade_order_id is None:
                                    extension1_quantity = dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                    trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0

                                    if dto.extension1_trade_order_id is None:
                                        total_quantity += (extension1_quantity + trade1_quantity)

                                        dto.extension_quantity = extension1_quantity + trade1_quantity

                                    else:
                                        total_quantity = total_quantity

                                        dto.extension_quantity = extension1_quantity

                                elif (dto.entry_trade_order_id is not None) and \
                                        (dto.extension1_trade_order_id is not None):
                                    extension1_quantity = dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                    trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0

                                    dto.extension_quantity = (extension1_quantity + trade1_quantity)

                                # OLD EXTENSION QUANTITY LOGIC
                                # if (dto.entry_trade_order_id is None) and tried_creating_entry_order:
                                #     total_quantity += dto.trade1_quantity
                                # else:
                                #     # if entry trade was placed then don't add that quantity for extension 2 trade
                                #     total_quantity += dto.extension_quantity if dto.extension_quantity is not None else 0
                                #
                                # if (dto.extension1_trade_order_id is None) and tried_creating_extension2_order:
                                #     total_quantity += dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                # else:
                                #     # if extension 1 trade was placed then add that quantity
                                #     total_quantity += dto.extension_quantity if dto.extension_quantity is not None else 0

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

                                if total_quantity == 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 2 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is 0 ")
                                    # dto.extension_quantity += total_quantity
                                    if tried_creating_cover_sl_trade:
                                        default_log.debug(f"Already Tried creating BEYOND EXTENSION TRADE as "
                                                          f"tried_creating_cover_sl_trade="
                                                          f"{tried_creating_cover_sl_trade} for symbol={symbol} "
                                                          f"having timeframe={timeframe}")
                                        break
                                elif (total_quantity % indices_quantity_multiplier) != 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 2 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier})")
                                    # dto.extension_quantity += total_quantity
                                    if tried_creating_cover_sl_trade:
                                        default_log.debug(f"Already Tried creating BEYOND EXTENSION TRADE as "
                                                          f"tried_creating_cover_sl_trade="
                                                          f"{tried_creating_cover_sl_trade} for symbol={symbol} "
                                                          f"having timeframe={timeframe}")
                                        break

                                else:
                                    default_log.debug(
                                        f"Creating EXTENSION 2 MARKET order with quantity={total_quantity} for "
                                        f"symbol={symbol} and time_frame={timeframe}. Current Extension Quantity="
                                        f"{dto.extension_quantity}")

                                    # if dto.extension_quantity is None:
                                    #     dto.extension_quantity = 0
                                    #
                                    # extension2_quantity = total_quantity
                                    # extension_quantity_for_indices_symbol = dto.extension_quantity + extension2_quantity

                                    extension_order_id, fill_price = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=total_quantity,
                                        entry_price=candle_high_price
                                    )

                                    # dto.extension_quantity += total_quantity

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION 2 MARKET order for "
                                            f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                        if ((dto.trade1_quantity is None) or (dto.trade1_quantity == 0)) and \
                                                ((dto.extension1_quantity is None) or (dto.extension1_quantity == 0)):
                                            dto.extension_quantity = 0
                                        # todo: changed here
                                        # dto.extension2_quantity = 0

                                        # Set tried_creating_extension2_order as false
                                        # tried_creating_extension2_order = False

                                    else:
                                        dto.extension2_trade_order_id = extension_order_id
                                        dto.extension2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                        # if (tried_creating_extension1_order and tried_creating_entry_order) and \
                                        #         ((dto.entry_trade_order_id is None) and
                                        #          (dto.extension1_trade_order_id is None)):

                                        budget_used = fill_price * total_quantity

                                        default_log.debug(f"As not tried creating entry_order as "
                                                          f"tried_creating_entry_order={tried_creating_entry_order}"
                                                          f" and not tried creating extension 1 order as "
                                                          f"tried_creating_extension1_order="
                                                          f"{tried_creating_extension1_order}. Therefore allocating"
                                                          f" equity of Rs. {budget_used} for the extension 2 trade")

                                        # Calculate total budget that will be required for the remaining trades
                                        percent_ratio_used = trade3_loss_percent
                                        if tried_creating_entry_order:
                                            percent_ratio_used += trade1_loss_percent

                                        if tried_creating_extension1_order:
                                            percent_ratio_used += trade2_loss_percent

                                        total_budget_required = calculate_required_budget_for_trades(
                                            used_percent_ratio=percent_ratio_used,
                                            used_ratio_value=budget_used,
                                            total_percent_ratio=total_percentage
                                        )

                                        zerodha_equity = get_zerodha_equity()

                                        if (zerodha_equity - total_budget_required) < 0:
                                            default_log.debug(
                                                f"Not Enough Equity remaining for placing remaining trades with "
                                                f"required budget={total_budget_required} for symbol={symbol} having "
                                                f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                                f"remaining equity={zerodha_equity}")

                                            # Even if equity is less then also retry when equity is enough
                                            # tried_creating_extension2_order = False
                                            # not_enough_equity = True
                                            # break

                                        else:
                                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                                            default_log.debug(
                                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                                f"Remaining Equity: Rs. {remaining_equity}")

                                            total_budget_used = total_budget_required

                                        dto.extension2_quantity = total_quantity
                                        if (dto.entry_trade_order_id is None) and (
                                                dto.extension1_trade_order_id is None):
                                            dto.extension_quantity = total_quantity
                                        else:
                                            dto.extension_quantity += total_quantity

                            # EXTENSION 2 STOCKS TRADE
                            else:
                                extension_order_id, fill_price = place_market_order(
                                    symbol=symbol,
                                    signal_type=SignalType.SELL,
                                    quantity=total_quantity,
                                    exchange="NSE",
                                    entry_price=candle_high_price
                                )

                                if extension_order_id is None:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION MARKET order for "
                                        f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                    if ((dto.trade1_quantity is None) or (dto.trade1_quantity == 0)) and \
                                            ((dto.extension1_quantity is None) and (dto.extension1_quantity == 0)):
                                        dto.extension_quantity = 0
                                    # todo: changed here
                                    # dto.extension2_quantity = 0

                                    # Set tried_creating_extension2_order as false
                                    # tried_creating_extension2_order = False

                                else:
                                    dto.extension2_trade_order_id = extension_order_id
                                    dto.extension2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                    # if (tried_creating_extension1_order and tried_creating_entry_order) and \
                                    #         ((dto.entry_trade_order_id is None) and
                                    #          (dto.extension1_trade_order_id is None)):

                                    budget_used = fill_price * total_quantity

                                    default_log.debug(f"As not tried creating entry_order as "
                                                      f"tried_creating_entry_order={tried_creating_entry_order}"
                                                      f" and not tried creating extension 1 order as "
                                                      f"tried_creating_extension1_order="
                                                      f"{tried_creating_extension1_order}. Therefore allocating"
                                                      f" equity of Rs. {budget_used} for the extension 2 trade")

                                    # Calculate total budget that will be required for the remaining trades
                                    percent_ratio_used = trade3_loss_percent
                                    if tried_creating_entry_order:
                                        percent_ratio_used += trade1_loss_percent

                                    if tried_creating_extension1_order:
                                        percent_ratio_used += trade2_loss_percent

                                    total_budget_required = calculate_required_budget_for_trades(
                                        used_percent_ratio=percent_ratio_used,
                                        used_ratio_value=budget_used,
                                        total_percent_ratio=total_percentage
                                    )

                                    zerodha_equity = get_zerodha_equity()

                                    if (zerodha_equity - total_budget_required) < 0:
                                        default_log.debug(
                                            f"Not Enough Equity remaining for placing remaining trades with "
                                            f"required budget={total_budget_required} for symbol={symbol} having "
                                            f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                            f"remaining equity={zerodha_equity}")

                                        # Even if equity is less, then also retry when equity is enough
                                        # tried_creating_extension2_order = False
                                        # not_enough_equity = True
                                        # break
                                    else:
                                        remaining_equity = allocate_equity_for_trade(total_budget_required)
                                        default_log.debug(
                                            f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                            f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                            f"Remaining Equity: Rs. {remaining_equity}")

                                        total_budget_used = total_budget_required

                                    extension_quantity = 0 if dto.extension_quantity is None else dto.extension_quantity
                                    dto.extension_quantity = total_quantity + extension_quantity

                            # Even if trade making failed or succeeded increment the trades_made counter by 1
                            trades_made += 1

                            # Mark TP and SL order status as OPEN as TP and SL order won't be placed for
                            # indices trade
                            dto.tp_order_status = 'OPEN'
                            dto.sl_order_status = 'OPEN'

                            # OLD FLOW
                            # else:
                            #     event_data_dto, error_occurred = place_extension_zerodha_trades(
                            #         event_data_dto=dto,
                            #         signal_type=SignalType.BUY,
                            #         candle_data=data.iloc[-1],
                            #         extension_quantity=extension_quantity if indices_symbol is None else 50,
                            #         symbol=symbol,
                            #         indices_symbol=indices_symbol,
                            #         multiplier=trades_made,
                            #         extension_no=2,
                            #         exchange="NSE" if indices_symbol is None else "NFO"
                            #     )
                            #
                            #     if error_occurred:
                            #         default_log.debug(
                            #             f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} "
                            #             f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
                            #             f"extension_quantity={extension_quantity} and "
                            #             f"trade1_quantity={dto.trade1_quantity}")
                            #
                            #     trades_made += 1
                            #     dto = event_data_dto
                        else:
                            default_log.debug(
                                f"[EXTENSION] Not placing Extension 2 trade has extension 2 trade "
                                f"condition is {trades_details_dto.trades_to_make.extension2_trade}")

                    # PLACING EXTENSION 1 ORDER
                    elif tried_creating_entry_order and (not tried_creating_extension1_order) and \
                            (dto.extension1_trade_order_id is None) and reached_extension1_point:
                        # If first trade was placed then check if second trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension1_trade:
                            tried_creating_extension1_order = True
                            loss_percent = loss_budget * trade2_loss_percent
                            # loss_percent = trade2_loss_percent
                            default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference
                            total_quantity = int(round(extension_quantity, 0))
                            dto.extension1_quantity = total_quantity
                            dto.actual_calculated_extension1_quantity = total_quantity

                            # ======================================================================= #

                            # EXTENSION 1 OPTION CHAIN TRADE
                            if indices_symbol is not None:

                                # QUANTITY LOGIC FOR EXTENSION 1 TRADE
                                trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0
                                if dto.entry_trade_order_id is None:
                                    total_quantity += trade1_quantity
                                    # dto.extension_quantity = total_quantity
                                else:
                                    total_quantity = total_quantity
                                    dto.extension_quantity = trade1_quantity

                                # OLD QUANTITY LOGIC FOR EXTENSION 1 TRADE
                                # if (dto.entry_trade_order_id is None) and tried_creating_entry_order:
                                #     total_quantity += dto.trade1_quantity
                                # else:
                                #     # If already entry trade was made then add that quantity
                                #     total_quantity += dto.extension_quantity if dto.extension_quantity is not None else 0

                                total_quantity = int(round(total_quantity, 0))

                                default_log.debug(
                                    f"[EXTENSION 1] Rounding off total_quantity ({total_quantity}) to the "
                                    f"indices_quantity_multiplier ({indices_quantity_multiplier}) for "
                                    f"symbol={symbol}"
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                total_quantity = round_to_nearest_multiplier(total_quantity,
                                                                             indices_quantity_multiplier)

                                default_log.debug(
                                    f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
                                    f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                if total_quantity == 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is 0")
                                    # trade1_quantity = 0 if dto.trade1_quantity is None else dto.trade1_quantity
                                    # dto.extension_quantity += total_quantity

                                elif (total_quantity % indices_quantity_multiplier) != 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier})")
                                    # trade1_quantity = 0 if dto.trade1_quantity is None else dto.trade1_quantity
                                    # dto.extension_quantity += total_quantity

                                else:
                                    default_log.debug(
                                        f"Creating EXTENSION MARKET order with quantity={total_quantity} for "
                                        f"symbol={symbol} and time_frame={timeframe}")

                                    # if dto.extension_quantity is None:
                                    #     dto.extension_quantity = 0
                                    #
                                    # extension2_quantity = total_quantity
                                    # extension_quantity_for_indices_symbol = dto.extension_quantity + extension2_quantity

                                    extension_order_id, fill_price = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=total_quantity,
                                        entry_price=candle_high_price
                                    )

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION MARKET order for "
                                            f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                        if (dto.trade1_quantity is None) or (dto.trade1_quantity == 0):
                                            dto.extension_quantity = 0
                                        # todo: changed here
                                        # dto.extension1_quantity = 0

                                        # Set tried_creating_extension1_order as false
                                        # tried_creating_extension1_order = False

                                    else:
                                        dto.extension1_trade_order_id = extension_order_id
                                        dto.extension1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                        # if tried_creating_entry_order:
                                        budget_used = fill_price * total_quantity
                                        default_log.debug(f"As tried creating entry_order as "
                                                          f"tried_creating_entry_order={tried_creating_entry_order}."
                                                          f"Therefore allocating equity of Rs. {budget_used} "
                                                          f"for the extension 1 trade")

                                        # Calculate total budget that will be required for the remaining trades
                                        percent_ratio_used = trade2_loss_percent
                                        if tried_creating_entry_order:
                                            percent_ratio_used += trade1_loss_percent

                                        total_budget_required = calculate_required_budget_for_trades(
                                            used_percent_ratio=percent_ratio_used,
                                            used_ratio_value=budget_used,
                                            total_percent_ratio=total_percentage
                                        )

                                        zerodha_equity = get_zerodha_equity()

                                        if (zerodha_equity - total_budget_required) < 0:
                                            default_log.debug(
                                                f"Not Enough Equity remaining for placing remaining trades with "
                                                f"required budget={total_budget_required} for symbol={symbol} "
                                                f"having timeframe={timeframe} and indices_symbol="
                                                f"{indices_symbol} and remaining equity={zerodha_equity}")

                                            # Even if equity is less, then also retry when equity is enough
                                            # tried_creating_extension1_order = False
                                            # not_enough_equity = True
                                            # break
                                        else:
                                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                                            default_log.debug(
                                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                                f"Remaining Equity: Rs. {remaining_equity}")

                                            total_budget_used = total_budget_required

                                        dto.extension1_quantity = total_quantity
                                        if dto.entry_trade_order_id is None:
                                            dto.extension_quantity = total_quantity
                                        else:
                                            dto.extension_quantity += total_quantity

                            # EXTENSION 1 STOCKS TRADE
                            else:
                                extension_order_id, fill_price = place_market_order(
                                    symbol=symbol,
                                    signal_type=SignalType.SELL,
                                    quantity=total_quantity,
                                    exchange="NSE",
                                    entry_price=candle_high_price
                                )

                                if extension_order_id is None:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION 1 MARKET order for "
                                        f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                    # If trade 1 order was failed to be placed
                                    if (dto.trade1_quantity is None) or (dto.trade1_quantity == 0):
                                        dto.extension_quantity = 0

                                    # todo: changed here
                                    # dto.extension1_quantity = 0

                                    # Set tried_creating_extension1_order as false
                                    # tried_creating_extension1_order = False

                                else:
                                    dto.extension1_trade_order_id = extension_order_id
                                    dto.extension1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                    # if tried_creating_entry_order and (dto.entry_trade_order_id is None):
                                    budget_used = fill_price * total_quantity
                                    default_log.debug(f"As not tried creating entry_order as "
                                                      f"tried_creating_entry_order={tried_creating_entry_order}."
                                                      f"Therefore allocating equity of Rs. {budget_used} "
                                                      f"for the extension 1 trade")

                                    # Calculate total budget that will be required for the remaining trades
                                    percent_ratio_used = trade2_loss_percent
                                    if tried_creating_entry_order:
                                        percent_ratio_used += trade1_loss_percent

                                    total_budget_required = calculate_required_budget_for_trades(
                                        used_percent_ratio=percent_ratio_used,
                                        used_ratio_value=budget_used,
                                        total_percent_ratio=total_percentage
                                    )

                                    zerodha_equity = get_zerodha_equity()

                                    if (zerodha_equity - total_budget_required) < 0:
                                        default_log.debug(
                                            f"Not Enough Equity remaining for placing remaining trades with "
                                            f"required budget={total_budget_required} for symbol={symbol} "
                                            f"having timeframe={timeframe} and indices_symbol="
                                            f"{indices_symbol} and remaining equity={zerodha_equity}")

                                        # Even if equity is less, then also retry when equity is enough
                                        # tried_creating_extension1_order = False

                                        # not_enough_equity = True
                                        # break
                                    else:
                                        remaining_equity = allocate_equity_for_trade(total_budget_required)
                                        default_log.debug(
                                            f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                            f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                            f"Remaining Equity: Rs. {remaining_equity}")

                                        total_budget_used = total_budget_required

                                    trade1_quantity = 0 if dto.trade1_quantity is None else dto.trade1_quantity
                                    dto.extension_quantity = total_quantity + trade1_quantity

                            # Even if trade making failed or succeeded increment the trades_made counter by 1
                            trades_made += 1

                            # Mark TP and SL order status as OPEN as TP and SL order won't be placed for
                            # indices trade
                            dto.tp_order_status = 'OPEN'
                            dto.sl_order_status = 'OPEN'

                            # ======================================================================= #

                            # if indices_symbol is not None:
                            #
                            #     total_quantity = extension_quantity
                            #     make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                            #     make_extension2_trade = trades_details_dto.trades_to_make.extension2_trade
                            #
                            #     dto.extension1_quantity = int(round(total_quantity, 0))
                            #     if (dto.entry_trade_order_id is None) and make_entry_trade:
                            #         total_quantity += dto.trade1_quantity
                            #
                            #     total_quantity = int(round(total_quantity, 0))
                            #     default_log.debug(
                            #         f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
                            #         f"indices_quantity_multiplier ({indices_quantity_multiplier}) "
                            #         f"for symbol={symbol} and indices_symbol={indices_symbol} "
                            #         f"having time_frame={timeframe}")
                            #
                            #     total_quantity = round_to_nearest_multiplier(total_quantity,
                            #                                                  indices_quantity_multiplier)
                            #
                            #     default_log.debug(
                            #         f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
                            #         f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                            #         f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
                            #
                            #     if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0):
                            #         default_log.debug(
                            #             f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                            #             f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                            #             f"the total_quantity ({total_quantity}) is not divisible by "
                            #             f"indices_quantity_multiplier ({indices_quantity_multiplier}). ")
                            #
                            #         dto.extension_quantity = total_quantity
                            #
                            #         if not make_extension2_trade:
                            #             default_log.debug(f"Not making Extension 2 trade as make_extension2_trade="
                            #                               f"{make_extension2_trade} and quantity ({total_quantity}) is "
                            #                               f"not a multiplier of {indices_quantity_multiplier}")
                            #             break
                            #     else:
                            #         default_log.debug(
                            #             f"Creating EXTENSION indices MARKET order with quantity={total_quantity} for "
                            #             f"indices_symbol={indices_symbol} and time_frame={timeframe}")
                            #
                            #         if dto.extension_quantity is None:
                            #             dto.extension_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0
                            #
                            #         extension1_quantity = total_quantity
                            #
                            #         extension_quantity_for_indices_symbol = dto.extension_quantity + extension1_quantity
                            #
                            #         extension_order_id = place_indices_market_order(
                            #             indice_symbol=indices_symbol,
                            #             signal_type=SignalType.BUY,
                            #             quantity=extension_quantity_for_indices_symbol,
                            #             entry_price=dto.entry_price
                            #         )
                            #
                            #         if extension_order_id is None:
                            #             default_log.debug(
                            #                 f"An error occurred while placing EXTENSION MARKET order for symbol={indices_symbol} and "
                            #                 f"and event_data_dto={dto} and "
                            #                 f"extension_quantity={extension_quantity_for_indices_symbol} "
                            #                 f"and trade1_quantity={dto.trade1_quantity}")
                            #         else:
                            #             dto.extension1_trade_order_id = extension_order_id
                            #
                            #         # dto.extension1_quantity = extension1_quantity
                            #         dto.extension_quantity = extension_quantity_for_indices_symbol
                            #
                            #     # Even if trade making failed or succeeded increment the trades_made counter by 1
                            #     trades_made += 1
                            #
                            #     dto.sl_order_status = 'OPEN'
                            #     dto.tp_order_status = 'OPEN'
                            #
                            # else:
                            #     event_data_dto, error_occurred = place_extension_zerodha_trades(
                            #         event_data_dto=dto,
                            #         signal_type=SignalType.SELL,
                            #         candle_data=data.iloc[-1],
                            #         extension_quantity=extension_quantity if indices_symbol is None else 50,
                            #         symbol=symbol,
                            #         indices_symbol=indices_symbol,
                            #         multiplier=trades_made,
                            #         extension_no=1,
                            #         exchange="NSE" if indices_symbol is None else "NFO"
                            #     )
                            #
                            #     tried_creating_extension1_order = True
                            #
                            #     if error_occurred:
                            #         default_log.debug(
                            #             f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} "
                            #             f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
                            #             f"extension_quantity={extension_quantity} and "
                            #             f"trade1_quantity={dto.trade1_quantity}")
                            #
                            #     dto = event_data_dto
                            #     trades_made += 1
                        else:
                            default_log.debug(
                                f"[EXTENSION] Not placing Extension 1 trade has extension 1 trade "
                                f"condition is {trades_details_dto.trades_to_make.extension1_trade}")
                else:
                    default_log.debug(
                        f"Extension Trade condition not met as values: extension_diff={extension_diff} "
                        f"trades_made={trades_made}, entry_price={entry_price} and sl_value={dto.sl_value} "
                        f"and reached_extension1_point: {reached_extension1_point} and reached_extension2_point: "
                        f"{reached_extension2_point} and symbol={symbol} and indices_symbol={indices_symbol} and "
                        f"Make Extension 1 trade={trades_details_dto.trades_to_make.extension1_trade} "
                        f"and Make Extension 2 trade={trades_details_dto.trades_to_make.extension2_trade} ")

            # Extra Trade placing logic
            # Place extra trade if candle high goes ABOVE by a threshold value

            # Check if tried creating market order, extension1 order and extension2 order. If yes then create a MARKET
            # order with only SL-M order and LIMIT order
            # SL Trade
            if (tried_creating_entry_order and tried_creating_extension1_order and tried_creating_extension2_order) \
                    and (dto.entry_trade_order_id is None and dto.extension1_trade_order_id is None and
                         dto.extension2_trade_order_id is None) and (not tried_creating_cover_sl_trade) and \
                    (dto.cover_sl_trade_order_id is None):
                default_log.debug(f"For symbol={symbol} having timeframe={timeframe} there has been a attempt to "
                                  f"create entry order (as tried_creating_entry_order={tried_creating_entry_order}) "
                                  f"and to create extension1_order (as tried_creating_extension1_order="
                                  f"{tried_creating_extension1_order}) and to create extension2_order (as "
                                  f"tried_creating_extension2_order={tried_creating_extension2_order}). But Failed to "
                                  f"create these orders as Entry Trade order id={dto.entry_trade_order_id}, "
                                  f"Extension 1 order id={dto.extension1_trade_order_id} and Extension 2 order id="
                                  f"{dto.extension2_trade_order_id}. So will create a MARKET order and SL-M order only "
                                  f"with stop_loss={dto.sl_value} with quantity={dto.extension_quantity}")

                candle_high_price = data.iloc[-1]['high']
                candle_close_price = data.iloc[-1]['close']

                # This case can occur when only SL Trade (COVER SL) need to be placed
                if dto.extension_quantity is None:
                    default_log.debug(f"Extension Quantity is None so calculating the extension quantity for "
                                      f"BEYOND EXTENSION Trade using Entry Price ({dto.entry_price}) and SL Value "
                                      f"({dto.sl_value}) with loss_percent of 100% for symbol={symbol} having timeframe"
                                      f"={timeframe}")
                    # beyond_extension_quantity = (1 * loss_budget) / abs(dto.entry_price - dto.sl_value)
                    beyond_extension_quantity = (1 * loss_budget) / abs(candle_close_price - dto.sl_value)
                    dto.extension_quantity = int(round(beyond_extension_quantity, 0))
                    default_log.debug(f"[BEYOND EXTENSION] Rounded off beyond_extension_quantity="
                                      f"{beyond_extension_quantity} to {dto.extension_quantity} for symbol={symbol} "
                                      f"having timeframe={timeframe}")

                tried_creating_cover_sl_trade = True

                # OPTION CHAIN SL TRADE
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
                    dto.cover_sl_quantity = dto.extension_quantity
                    rounded_down_extension_quantity = round_to_nearest_multiplier(
                        dto.extension_quantity, indices_quantity_multiplier)

                    # rounded_down_extension_quantity = int(math.floor(
                    #     dto.extension_quantity / indices_quantity_multiplier) * indices_quantity_multiplier)
                    default_log.debug(f"[BEYOND EXTENSION] Rounded down extension quantity "
                                      f"{dto.extension_quantity} to nearest multiplier of indices "
                                      f"{indices_quantity_multiplier} using the formula: "
                                      f"Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) "
                                      f"* Indices => {rounded_down_extension_quantity}")

                    if (rounded_down_extension_quantity < indices_quantity_multiplier) or \
                            (rounded_down_extension_quantity % indices_quantity_multiplier != 0):
                        default_log.debug(f'[BEYOND EXTENSION] Not placing beyond extension trade as '
                                          f'rounded_down_extension_quantity ({rounded_down_extension_quantity}) < '
                                          f'indices_quantity_multiplier ({indices_quantity_multiplier}) for '
                                          f'indices_symbol={indices_symbol} and symbol={symbol} having timeframe='
                                          f'{timeframe}. OR rounded_down_extension_quantity '
                                          f'({rounded_down_extension_quantity}) is not divisible by '
                                          f'indices_quantity_multiplier ({indices_quantity_multiplier})')
                        # Quantity fell short so returning
                        short_quantity_issue = True
                        break

                    dto.extension_quantity = rounded_down_extension_quantity
                    dto.cover_sl_quantity = rounded_down_extension_quantity
                    extension_indices_market_order_id, fill_price = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        quantity=rounded_down_extension_quantity,
                        signal_type=SignalType.BUY,
                        entry_price=candle_high_price
                    )

                    if extension_indices_market_order_id is None:
                        default_log.debug(f"[BEYOND EXTENSION] An error occurred while placing BEYOND Extension Trade "
                                          f"for indices_symbol={indices_symbol} having time_frame={timeframe}")

                        # Set tried_creating_cover_sl_trade as false due to LESS EQUITY
                        # tried_creating_cover_sl_trade = False
                        short_quantity_issue = True
                        break

                    else:
                        default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                          f"id={extension_indices_market_order_id} for symbol={symbol} having time_frame="
                                          f"{timeframe} with quantity={dto.extension_quantity}")

                        dto.cover_sl_trade_order_id = extension_indices_market_order_id
                        dto.sl_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                        dto.sl_order_status = 'OPEN'
                        dto.tp_order_status = 'OPEN'

                        zerodha_equity = get_zerodha_equity()

                        total_budget_required = fill_price * dto.extension_quantity

                        if (zerodha_equity - total_budget_required) < 0:
                            default_log.debug(
                                f"Not Enough Equity remaining for placing remaining trades with "
                                f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                f"having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                            # Even if equity is less, then also retry when equity is enough
                            # tried_creating_cover_sl_trade = True
                            not_enough_equity = True
                            break
                        else:
                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                            default_log.debug(
                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                f"Remaining Equity: Rs. {remaining_equity}")

                            total_budget_used = total_budget_required

                # STOCK MARKET COVER SL TRADE
                else:

                    cover_sl_trade_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        quantity=dto.extension_quantity,
                        signal_type=SignalType.SELL,
                        exchange="NSE",
                        entry_price=candle_high_price
                    )

                    dto.cover_sl_quantity = dto.extension_quantity

                    if cover_sl_trade_order_id is None:
                        default_log.debug(f"[BEYOND EXTENSION] An error occurred while placing BEYOND Extension Trade "
                                          f"for indices_symbol={indices_symbol} having time_frame={timeframe}")
                        # Set tried_creating_cover_sl_trade as false due to LESS EQUITY
                        # tried_creating_cover_sl_trade = False
                        short_quantity_issue = True
                        break
                    else:
                        default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                          f"id={cover_sl_trade_order_id} for symbol={symbol} having time_frame="
                                          f"{timeframe} with quantity={dto.extension_quantity}")

                        dto.cover_sl_trade_order_id = cover_sl_trade_order_id
                        dto.sl_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                        dto.sl_order_status = 'OPEN'
                        dto.tp_order_status = 'OPEN'

                        zerodha_equity = get_zerodha_equity()

                        total_budget_required = fill_price * dto.extension_quantity

                        if (zerodha_equity - total_budget_required) < 0:
                            default_log.debug(
                                f"Not Enough Equity remaining for placing remaining trades with "
                                f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                f"having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                            # Even if equity is less, then also retry when equity is enough
                            # tried_creating_cover_sl_trade = False
                            not_enough_equity = True
                            break
                        else:
                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                            default_log.debug(
                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                f"Remaining Equity: Rs. {remaining_equity}")

                            total_budget_used = total_budget_required

        if dto.sl_order_status == "COMPLETE":
            default_log.debug(f"Stop Loss Order with ID: {dto.sl_order_id} has been triggered and COMPLETED")

            # Check if SL was adjusted
            if dto.extended_sl is None:
                default_log.debug(f"An Stop Loss Order with ID: {dto.sl_order_id} was COMPLETED and cover SL was not "
                                  f"done so creating a REVERSE TRADE")

                # Calculate the SL value
                # Stop Loss = Adjusted SL - (2 * Candle Height (buffer also)) [It is the buffer]
                actual_sl = dto.sl_value
                adjusted_sl = dto.sl_value + (2 * dto.sl_buffer)

                dto.reverse1_entry_price = adjusted_sl

                if symbol in indices_list:
                    # Getting the indices symbol for the index symbol
                    default_log.debug(f"Getting indices symbol as trading symbol={symbol} is in "
                                      f"indices_list={indices_list} with entry price={entry_price} ")

                    # if indices_symbol is None:
                    default_log.debug(f"Getting indices symbol for symbol={symbol}, price={adjusted_sl} "
                                      f"and for transaction_type={SignalType.BUY}")
                    indices_symbol = get_indices_symbol_for_trade(trading_symbol=symbol, price=adjusted_sl,
                                                                  transaction_type=SignalType.BUY)

                    if indices_symbol is None:
                        default_log.debug(
                            f"Cannot find indices symbol for symbol={symbol} and time_frame={timeframe} with "
                            f"transaction_type={SignalType.BUY}")
                        break

                    default_log.debug(f"Indices symbol retrieved={indices_symbol}")

                # Calculating the REVERSE TRADE 1 SL VALUE
                calculated_stop_loss = adjusted_sl - (2 * abs(actual_sl - adjusted_sl))
                dto.reverse_trade_stop_loss = calculated_stop_loss

                # Calculating the REVERSE TRADE TP VALUE
                # Take Profit in case of BUY REVERSE TRADE
                # Take Profit = Adjusted SL + (Adjusted SL - Event 1 Candle High)
                calculated_take_profit = adjusted_sl + abs(adjusted_sl - dto.event1_candle_high)
                dto.reverse_trade_take_profit = calculated_take_profit

                if (dto.reverse1_trade_order_id is None) and (not tried_creating_reverse1_trade):
                    tried_creating_reverse1_trade = True
                    default_log.debug(f"As REVERSE 1 TRADE was not placed for symbol={symbol} having "
                                      f"timeframe={timeframe} so placing REVERSE TRADE 1 with reverse_trade_stop_loss="
                                      f"{calculated_stop_loss} and reverse_trade_take_profit={calculated_take_profit}")

                    reverse_trade_quantity = loss_budget * 0.5 / abs(adjusted_sl - calculated_stop_loss)
                    reverse_trade_quantity = int(round(reverse_trade_quantity, 0))

                    dto.reverse1_trade_quantity = reverse_trade_quantity
                    dto.total_reverse_trade_quantity = reverse_trade_quantity

                    if indices_symbol is not None:

                        # Calculate the quantity
                        # For 1st BUY REVERSE 1 TRADE:
                        # Quantity = loss_budget * 0.5 / abs(adjusted SL - stop loss)

                        rounded_off_reverse_trade_quantity = round_to_nearest_multiplier(reverse_trade_quantity,
                                                                                         indices_quantity_multiplier)
                        if rounded_off_reverse_trade_quantity != 0 and (
                                rounded_off_reverse_trade_quantity % indices_quantity_multiplier) == 0:
                            default_log.debug(
                                f"Reverse trade quantity for indices_symbol={indices_symbol} is calculated "
                                f"as {reverse_trade_quantity} with loss_budget={loss_budget}, adjusted_sl="
                                f"{adjusted_sl} and stop_loss_of_reverse_trade={calculated_stop_loss}")

                            dto.reverse1_trade_quantity = rounded_off_reverse_trade_quantity
                            dto.total_reverse_trade_quantity = rounded_off_reverse_trade_quantity

                            reverse1_trade_order_id, fill_price = place_indices_market_order(
                                indice_symbol=indices_symbol,
                                quantity=rounded_off_reverse_trade_quantity,
                                signal_type=SignalType.BUY,
                                entry_price=adjusted_sl,
                            )

                            if reverse1_trade_order_id is None:
                                default_log.debug(
                                    f"An error occurred while placing REVERSE TRADE 1 for symbol={symbol} "
                                    f"having timeframe={timeframe}")

                                # dto.reverse1_trade_quantity = 0
                                # dto.total_reverse_trade_quantity = 0

                                # Set tried_creating_reverse1_trade as false due to LESS EQUITY
                                # tried_creating_reverse1_trade = False

                            else:
                                dto.reverse1_trade_order_id = reverse1_trade_order_id
                                dto.reverse1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                budget_used = fill_price * rounded_off_reverse_trade_quantity

                                total_budget_required = 2 * budget_used

                                zerodha_equity = get_zerodha_equity()

                                if (zerodha_equity - total_budget_required) < 0:
                                    default_log.debug(
                                        f"Not Enough Equity remaining for placing remaining trades with "
                                        f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                        f"having timeframe={timeframe} and indices_symbol="
                                        f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                                    # Even if equity is less, then also retry when equity is enough
                                    # tried_creating_reverse1_trade = False
                                    # not_enough_equity = True
                                    # break
                                else:
                                    remaining_equity = allocate_equity_for_trade(total_budget_required)
                                    default_log.debug(
                                        f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                        f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                        f"Remaining Equity: Rs. {remaining_equity}")

                                    total_budget_used = total_budget_required

                                default_log.debug(
                                    f"[REVERSE TRADE 1] Successfully placed REVERSE TRADE 1 with quantity="
                                    f"{dto.reverse1_trade_quantity} with stop loss order having stop_loss="
                                    f"{dto.reverse_trade_stop_loss} and take profit order having take_profit="
                                    f"{dto.reverse_trade_take_profit} for symbol={dto.symbol} having "
                                    f"timeframe={dto.time_frame}")

                        else:
                            default_log.debug(
                                f"[REVERSE TRADE 1] Not placing reverse trade 1 as rounded_off_reverse_trade_quantity "
                                f"({rounded_off_reverse_trade_quantity}) % indices_quantity_multiplier "
                                f"({indices_quantity_multiplier}) != 0. OR rounded_off_reverse_trade_quantity <= 0")

                    # STOCK MARKET REVERSE TRADE 1 ORDER
                    else:

                        reverse_trade_quantity = loss_budget * 0.5 / abs(adjusted_sl - calculated_stop_loss)
                        reverse_trade_quantity = int(round(reverse_trade_quantity, 0))

                        dto.reverse1_trade_quantity = reverse_trade_quantity
                        dto.total_reverse_trade_quantity = reverse_trade_quantity

                        reverse1_trade_order_id, fill_price = place_market_order(
                            symbol=symbol,
                            quantity=reverse_trade_quantity,
                            signal_type=SignalType.BUY,
                            exchange="NSE",
                            entry_price=adjusted_sl
                        )

                        if reverse1_trade_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing REVERSE TRADE 1 for symbol={symbol} "
                                f"having timeframe={timeframe}")

                            # dto.reverse1_trade_quantity = 0
                            # dto.total_reverse_trade_quantity = 0

                            # Set tried_creating_reverse1_trade as false due to LESS EQUITY
                            # tried_creating_reverse1_trade = False

                        else:
                            dto.reverse1_trade_order_id = reverse1_trade_order_id
                            dto.reverse1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                            budget_used = fill_price * reverse_trade_quantity

                            total_budget_required = 2 * budget_used

                            zerodha_equity = get_zerodha_equity()

                            if (zerodha_equity - total_budget_required) < 0:
                                default_log.debug(
                                    f"Not Enough Equity remaining for placing remaining trades with "
                                    f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                    f"having timeframe={timeframe} and indices_symbol="
                                    f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                            else:
                                remaining_equity = allocate_equity_for_trade(total_budget_required)
                                default_log.debug(
                                    f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                    f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                    f"Remaining Equity: Rs. {remaining_equity}")

                                total_budget_used = total_budget_required

                            default_log.debug(f"[REVERSE TRADE 1] Successfully placed REVERSE TRADE 1 with quantity="
                                              f"{dto.reverse1_trade_quantity} with stop loss order having stop_loss="
                                              f"{dto.reverse_trade_stop_loss} and take profit order having take_profit="
                                              f"{dto.reverse_trade_take_profit} for symbol={dto.symbol} having "
                                              f"timeframe={dto.time_frame}")
                # REVERSE TRADE 2
                elif tried_creating_reverse1_trade and (not tried_creating_reverse2_trade) and \
                        (dto.reverse2_trade_order_id is None):
                    default_log.debug(f"As REVERSE 1 TRADE was placed with quantity={dto.reverse1_trade_quantity} with "
                                      f"stop_loss ({dto.reverse_trade_stop_loss}) and take_profit "
                                      f"({dto.reverse_trade_take_profit}) and reverse1_trade_order_id="
                                      f"{dto.reverse1_trade_order_id}")
                    current_candle_low = data.iloc[-1]['low']
                    current_close_price = data.iloc[-1]['close']
                    # Initial Trade Signal Type was SELL
                    # if (current_candle_low < actual_sl) and (not tried_creating_reverse2_trade):

                    # TODO: update this
                    # actual_sl_with_buffer

                    if (current_close_price < actual_sl) and (not tried_creating_reverse2_trade):
                        default_log.debug(f"Placing REVERSE 2 TRADE as current candle close ({current_close_price}) < "
                                          f"actual sl ({actual_sl}) for symbol={symbol} having timeframe={timeframe}")
                        tried_creating_reverse2_trade = True
                        dto.reverse2_entry_price = actual_sl

                        if indices_symbol is not None:
                            # Calculate the quantity
                            # For 2nd BUY REVERSE 2 TRADE:
                            # Quantity = loss_budget * 0.5 / abs(adjusted SL - stop loss)
                            reverse_trade_quantity = loss_budget * 0.5 / abs(actual_sl - calculated_stop_loss)
                            reverse_trade_quantity = int(round(reverse_trade_quantity, 0))
                            dto.reverse2_trade_quantity = reverse_trade_quantity

                            default_log.debug(f"Initial Reverse Trade 1 quantity={dto.total_reverse_trade_quantity}")
                            total_reverse_trade_quantity = dto.total_reverse_trade_quantity + reverse_trade_quantity

                            rounded_off_reverse_trade_quantity = round_to_nearest_multiplier(
                                total_reverse_trade_quantity,
                                indices_quantity_multiplier)
                            if rounded_off_reverse_trade_quantity != 0 and (
                                    rounded_off_reverse_trade_quantity % indices_quantity_multiplier) == 0:
                                default_log.debug(
                                    f"Reverse trade quantity for indices_symbol={indices_symbol} is calculated "
                                    f"as {reverse_trade_quantity} with loss_budget={loss_budget}, adjusted_sl="
                                    f"{adjusted_sl} and stop_loss_of_reverse_trade={calculated_stop_loss}")

                                dto.total_reverse_trade_quantity = rounded_off_reverse_trade_quantity

                                reverse2_trade_order_id, fill_price = place_indices_market_order(
                                    indice_symbol=indices_symbol,
                                    quantity=rounded_off_reverse_trade_quantity,
                                    signal_type=SignalType.BUY,
                                    entry_price=current_candle_low,
                                )

                                if reverse2_trade_order_id is None:
                                    default_log.debug(
                                        f"An error occurred while placing REVERSE TRADE 2 for symbol={symbol} "
                                        f"having timeframe={timeframe}")

                                    if (dto.reverse1_trade_quantity is None) or (dto.reverse1_trade_quantity == 0):
                                        dto.total_reverse_trade_quantity = 0

                                    # dto.reverse2_trade_quantity = 0

                                    if dto.reverse1_trade_order_id is None:
                                        default_log.debug(f"[REVERSE TRADE 2] As Failed to place both REVERSE trades as "
                                                          f"Reverse 1 trade id={dto.reverse1_trade_order_id} and "
                                                          f"Reverse 2 trade order id={reverse2_trade_order_id} for "
                                                          f"symbol={dto.symbol} having timeframe={dto.time_frame} so "
                                                          f"stopping alert tracking")
                                        break

                                    # Set tried_creating_reverse2_trade as false due to LESS EQUITY
                                    # tried_creating_reverse2_trade = False

                                else:
                                    dto.reverse2_trade_order_id = reverse2_trade_order_id
                                    dto.reverse2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                                    default_log.debug(
                                        f"[REVERSE TRADE 2] Successfully placed REVERSE TRADE 2 with quantity="
                                        f"{rounded_off_reverse_trade_quantity} with stop loss order having stop_loss="
                                        f"{dto.reverse_trade_stop_loss} and take profit order having take_profit="
                                        f"{dto.reverse_trade_take_profit} for symbol={dto.symbol} having "
                                        f"timeframe={dto.time_frame}. Reverse Trade 2 order id={reverse2_trade_order_id}")

                                    # if dto.reverse1_trade_order_id is None:
                                    budget_used = fill_price * rounded_off_reverse_trade_quantity

                                    total_budget_required = 2 * budget_used

                                    zerodha_equity = get_zerodha_equity()

                                    if (zerodha_equity - total_budget_required) < 0:
                                        default_log.debug(
                                            f"Not Enough Equity remaining for placing remaining trades with "
                                            f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                            f"having timeframe={timeframe} and indices_symbol="
                                            f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")
                                        # Even if equity is less, then also retry when equity is enough
                                        # tried_creating_reverse2_trade = False
                                        # not_enough_equity = True
                                        # break
                                    else:
                                        remaining_equity = allocate_equity_for_trade(total_budget_required)
                                        default_log.debug(
                                            f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                            f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                            f"Remaining Equity: Rs. {remaining_equity}")

                                        total_budget_used = total_budget_required

                                    default_log.debug(
                                        f"[REVERSE TRADE 2] Successfully placed REVERSE TRADE 2 with quantity="
                                        f"{dto.reverse2_trade_quantity} with stop loss order having stop_loss="
                                        f"{dto.reverse_trade_stop_loss} and take profit order having take_profit="
                                        f"{dto.reverse_trade_take_profit} for symbol={dto.symbol} having "
                                        f"timeframe={dto.time_frame}")

                            else:
                                default_log.debug(
                                    f"[REVERSE TRADE 2] Not placing reverse trade 2 as rounded_off_reverse_trade"
                                    f"_quantity ({rounded_off_reverse_trade_quantity}) % indices_quantity_multiplier "
                                    f"({indices_quantity_multiplier}) != 0. OR reverse_trade_quantity <= 0")

                                if dto.reverse1_trade_order_id is None:
                                    short_quantity_issue = True
                                    return
                        else:

                            reverse_trade_quantity = loss_budget * 0.5 / abs(actual_sl - calculated_stop_loss)
                            reverse_trade_quantity = int(round(reverse_trade_quantity, 0))
                            dto.reverse2_trade_quantity = reverse_trade_quantity

                            reverse1_trade_quant = 0 if dto.reverse1_trade_quantity is None else dto.reverse1_trade_quantity
                            dto.total_reverse_trade_quantity = reverse_trade_quantity + reverse1_trade_quant

                            reverse2_trade_order_id, fill_price = place_market_order(
                                symbol=symbol,
                                quantity=reverse_trade_quantity,
                                signal_type=SignalType.BUY,
                                exchange="NSE",
                                entry_price=current_candle_low
                            )

                            if reverse2_trade_order_id is None:
                                default_log.debug(
                                    f"An error occurred while placing REVERSE TRADE 2 for symbol={symbol} "
                                    f"having timeframe={timeframe}")

                                if (dto.reverse1_trade_quantity is None) or (dto.reverse1_trade_quantity == 0):
                                    dto.total_reverse_trade_quantity = 0

                                # dto.reverse2_trade_quantity = 0

                                if dto.reverse1_trade_order_id is None:
                                    default_log.debug(f"[REVERSE TRADE 2] As Failed to place both REVERSE trades as "
                                                      f"Reverse 1 trade id={dto.reverse1_trade_order_id} and "
                                                      f"Reverse 2 trade order id={reverse2_trade_order_id} for "
                                                      f"symbol={dto.symbol} having timeframe={dto.time_frame} so "
                                                      f"stopping alert tracking")
                                    break

                                # Set tried_creating_reverse2_trade as false due to LESS EQUITY
                                # tried_creating_reverse2_trade = False

                            else:
                                dto.reverse2_trade_order_id = reverse2_trade_order_id
                                dto.reverse2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                # if dto.reverse1_trade_order_id is None:
                                budget_used = fill_price * reverse_trade_quantity

                                total_budget_required = budget_used

                                zerodha_equity = get_zerodha_equity()

                                if (zerodha_equity - total_budget_required) < 0:
                                    default_log.debug(
                                        f"Not Enough Equity remaining for placing remaining trades with "
                                        f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                        f"having timeframe={timeframe} and indices_symbol="
                                        f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                                    # Even if equity is less, then also retry when equity is enough
                                    # tried_creating_reverse2_trade = False
                                    # not_enough_equity = True
                                    # break

                                else:
                                    remaining_equity = allocate_equity_for_trade(total_budget_required)
                                    default_log.debug(
                                        f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                        f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                        f"Remaining Equity: Rs. {remaining_equity}")

                                    total_budget_used = total_budget_required

                                default_log.debug(
                                    f"[REVERSE TRADE 2] Successfully placed REVERSE TRADE 2 with quantity="
                                    f"{dto.reverse2_trade_quantity} with stop loss order having stop_loss="
                                    f"{dto.reverse_trade_stop_loss} and take profit order having take_profit="
                                    f"{dto.reverse_trade_take_profit} for symbol={dto.symbol} having "
                                    f"timeframe={dto.time_frame}")

            else:
                default_log.debug(f"As SL was adjusted to {dto.cover_sl} for symbol={symbol} having "
                                  f"timeframe={timeframe} and the SL order has been triggered so not placing the "
                                  f"REVERSE TRADE")
                break

        # CHECK WHETHER REVERSE TRADES HAVE BEEN PLACED OR NOT
        if (dto.reverse1_trade_order_id is not None) or (dto.reverse2_trade_order_id is not None) or \
                (dto.reverse_cover_sl_trade_order_id is not None):

            candle_high = data.iloc[-1]['high']
            candle_low = data.iloc[-1]['low']
            current_close_price = data.iloc[-1]['close']

            # Check TP hit or not
            tp_value = dto.reverse_trade_take_profit

            # todo: complete this
            # tp_value_with_buffer
            # sl_value = dto.sl_value + dto.candle_length
            sl_value = dto.reverse_trade_stop_loss
            tp_quantity = sl_quantity = dto.total_reverse_trade_quantity

            # if candle_high >= tp_value:
            if (current_close_price >= tp_value):

                default_log.debug(
                    f"[REVERSE TRADE] Current Candle Close ({current_close_price}) >= TP value ({tp_value}) for indices_symbol="
                    f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
                    f"quantity={tp_quantity} and signal_type={SignalType.SELL}")

                # STOCK MARKET LIMIT TRADE
                if indices_symbol is None:

                    tp_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        quantity=tp_quantity,
                        exchange="NSE",
                        entry_price=candle_high
                    )

                    if tp_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (LIMIT) order for indices symbol={indices_symbol} "
                            f"with quantity={tp_quantity} with signal_type={SignalType.SELL}")
                    else:
                        dto.reverse_trade_tp_order_id = tp_order_id
                        dto.reverse_trade_tp_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} and "
                                          f"indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)

                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_tp_order_status = 'COMPLETE'
                    break

                # OPTION CHAIN MARKET LIMIT TRADE
                else:
                    tp_order_id, fill_price = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        signal_type=SignalType.SELL,
                        quantity=tp_quantity,
                        entry_price=candle_high
                    )

                    if tp_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (LIMIT) order for indices symbol={indices_symbol} "
                            f"with quantity={tp_quantity} with signal_type={SignalType.SELL}")
                    else:
                        dto.reverse_trade_tp_order_id = tp_order_id
                        dto.reverse_trade_tp_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} "
                                          f"and indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)
                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_tp_order_status = 'COMPLETE'
                    break

            # Check SL-M hit or not
            # elif candle_low <= sl_value:
            elif (current_close_price <= sl_value):
                default_log.debug(
                    f"Current Candle Close ({current_close_price}) <= SL value ({sl_value}) for indices_symbol="
                    f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
                    f"quantity={sl_quantity} and signal_type={SignalType.SELL}")

                # STOCK MARKET LIMIT TRADE
                if indices_symbol is None:

                    sl_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        quantity=tp_quantity,
                        exchange="NSE",
                        entry_price=candle_low
                    )

                    if sl_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (SL-M) order for indices symbol={indices_symbol} "
                            f"with quantity={tp_quantity} with signal_type={SignalType.SELL}")
                    else:
                        dto.reverse_trade_sl_order_id = sl_order_id
                        dto.reverse_trade_sl_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} "
                                          f"and indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)

                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_sl_order_status = 'COMPLETE'
                    data_dictionary[key] = dto
                    break

                # OPTION CHAIN MARKET SL-M TRADE
                else:
                    sl_order_id, fill_price = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        signal_type=SignalType.SELL,
                        quantity=sl_quantity,
                        entry_price=candle_low
                    )

                    if sl_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (SL-M) order for symbol={symbol} "
                            f"with quantity={sl_quantity} with signal_type={SignalType.SELL}")
                    else:
                        dto.reverse_trade_sl_order_id = sl_order_id
                        dto.reverse_trade_sl_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} "
                                          f"and indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)

                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_tp_order_status = 'COMPLETE'
                    data_dictionary[key] = dto
                    break

        data_dictionary[key] = dto
        default_log.debug(f"[{data['time']}] Event Details: {data_dictionary.get(key, None)}")

        # Store the current state of event in the database
        response = store_current_state_of_event(
            thread_detail_id=thread_detail_id,
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.BUY,
            trade_alert_status=trade_alert_status,
            configuration=configuration,
            is_completed=False,
            dto=dto
        )

        if not response:
            default_log.debug(f"An error occurred while storing thread event details in database")
            return False

        # if dto.tp_order_status == "COMPLETE":
        #     default_log.debug(f"Take Profit Order with ID: {dto.tp_order_id} has been triggered and COMPLETED "
        #                       f"for symbol={symbol} having timeframe={timeframe}")
        #     break

        if (dto.reverse_trade_sl_order_status == "COMPLETE") or (dto.reverse_trade_tp_order_status == "COMPLETE"):
            type_of_order_hit = 'TAKE PROFIT' if dto.reverse_trade_tp_order_status == "COMPLETE" else 'STOP LOSS'

            default_log.debug(f"{type_of_order_hit} has been triggered for symbol={symbol} having timeframe="
                              f"{timeframe}. Stopping Alert Tracking now.")
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

            # Flow to check if current time is greater than 15:30 IST then mark the alert as NEXT DAY for continuing
            use_simulation = get_use_simulation_status()
            if not use_simulation:
                current_timestamp = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                try:
                    if current_timestamp > market_close_time:
                        default_log.debug(
                            f"As current timestamp ({current_timestamp}) > market close time ({market_close_time})"
                            f" so stopping the alert tracking and marking the status of the alert as NEXT DAY "
                            f"of symbol={symbol} having timeframe={timeframe}")

                        # Mark the status as NEXT DAY for the alert and return
                        # Store the current state of event in the database
                        response = store_current_state_of_event(
                            thread_detail_id=thread_detail_id,
                            symbol=symbol,
                            time_frame=timeframe,
                            signal_type=SignalType.SELL,
                            trade_alert_status="NEXT DAY",
                            configuration=configuration,
                            is_completed=True,
                            dto=dto
                        )

                        if not response:
                            default_log.debug(
                                f"An error occurred while storing thread event details in database")
                            return False

                        return
                    else:
                        default_log.debug(
                            f"Not marking the status of the alert as NEXT DAY as current timestamp "
                            f"({current_timestamp}) < market close time ({market_close_time}) for symbol={symbol}"
                            f" having timestamp={timestamp}")
                except Exception as e:
                    default_log.debug(
                        f"An error occurred while checking if current timestamp ({current_timestamp}) > "
                        f"market close time ({market_close_time}) for symbol={symbol} having "
                        f"timeframe={timeframe}. Error: {e}")
            return None

    trade_alert_status = "COMPLETE"
    if not_enough_equity:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = EQUITY as "
                          f"not_enough_equity={not_enough_equity} ")
        trade_alert_status = "EQUITY"

    if opposite_issue:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = OPPOSITE as "
                          f"opposite_issue={opposite_issue} ")
        trade_alert_status = "OPPOSITE"

    if range_issue:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = RANGE as "
                          f"range_issue={range_issue} ")
        trade_alert_status = "RANGE"

    if short_quantity_issue:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = SHORT QUANTITY as "
                          f"short_quantity_issue={short_quantity_issue} ")
        trade_alert_status = "SHORT QUANTITY"

    # Store the current state of event in the database
    response = store_current_state_of_event(
        thread_detail_id=thread_detail_id,
        symbol=symbol,
        time_frame=timeframe,
        signal_type=SignalType.BUY,
        trade_alert_status=trade_alert_status,
        configuration=configuration,
        is_completed=True,
        dto=dto
    )

    if not response:
        default_log.debug(f"An error occurred while storing thread event details in database")
        return False

    return


def start_market_logging_for_sell(
        symbol: str,
        timeframe: str,
        instrument_token: int,
        wait_time: int,
        configuration: Configuration,
        alert_time: Optional[datetime] = None,
        restart_dto: RestartEventDTO = None,
        continuity_dto: RestartEventDTO = None
):
    default_log.debug("inside start_market_logging_for_sell with "
                      f"symbol={symbol}, timeframe={timeframe}, instrument_token={instrument_token} "
                      f"wait_time={wait_time} and configuration={configuration}, alert_time={alert_time} and "
                      f"restart_dto={restart_dto}, and continuity_dto={continuity_dto}")

    data_dictionary = {}
    wait_time = 2  # as ticker data is now being used

    interval = get_interval_from_timeframe(timeframe)

    key = (symbol, timeframe)
    trades_made = 0
    extension_diff = None
    entry_price = None

    tried_creating_entry_order = False
    tried_creating_extension1_order = False
    tried_creating_extension2_order = False
    tried_creating_reverse1_trade = False
    tried_creating_reverse2_trade = False
    tried_creating_cover_sl_trade = False
    tried_creating_reverse_cover_sl_trade = False

    candles_checked = 0

    indices_symbol = None
    prev_timestamp = None

    sl_got_extended = False

    # STATUSES
    not_enough_equity = False  # FOR KEEPING TRACK OF EQUITY STATUS
    range_issue = False  # FOR KEEPING TRACK OF RANGE STATUS
    opposite_issue = False  # FOR KEEPING TRACK OF OPPOSITE STATUS
    short_quantity_issue = False  # FOR KEEPING TRACK OF SHORT QUANTITY STATUS
    trade_alert_status = "PENDING"

    total_budget_used = 0
    initial_close_price = None

    reached_extension2_point = False
    reached_extension1_point = False

    indices_quantity_multiplier = 50 if symbol == "NIFTY" else 15
    initial_event1_done = False
    dto = None

    is_restart = False
    is_continuity = False

    if restart_dto is not None:
        is_restart = True
        initial_event1_done = True
        default_log.debug(f"Restarting the thread with restart_dto={restart_dto}")

        thread_detail_id = restart_dto.thread_id

        # ALERT SYMBOL AND TIMEFRAME DETAIL
        symbol = restart_dto.symbol
        time_frame = restart_dto.time_frame

        # EVENT TIMES
        event1_occur_time = restart_dto.event1_occur_time
        event2_occur_time = restart_dto.event2_occur_time
        event3_occur_time = restart_dto.event3_occur_time

        # ALERT TIME
        restart_thread_alert_time = restart_dto.alert_time

        # ALERT MISC
        event2_breakpoint = restart_dto.event2_breakpoint
        highest_point = restart_dto.highest_point
        lowest_point = restart_dto.lowest_point
        sl_value = restart_dto.sl_value
        tp_value = restart_dto.tp_value
        high_1 = restart_dto.high_1
        low_1 = restart_dto.low_1
        candle_high = restart_dto.candle_high  # EVENT 1 CANDLE HIGH
        candle_low = restart_dto.candle_low  # EVENT 1 CANDLE LOW
        candle_length = candle_high - candle_low
        adjusted_high = restart_dto.adjusted_high
        adjusted_low = restart_dto.adjusted_low
        entry_price = restart_dto.entry_price
        reverse_trade_stop_loss = restart_dto.reverse_trade_stop_loss
        reverse_trade_take_profit = restart_dto.reverse_trade_take_profit

        # Add SL Buffer and Combined Height
        combined_height = None
        sl_buffer = None
        if sl_value is not None:
            if adjusted_high is not None:
                default_log.debug(f"Calculating combined difference using event1_candle_high "
                                  f"({candle_high}) and adjusted_low "
                                  f"({adjusted_low})")
                combined_height = candle_high - adjusted_low
                sl_buffer = -combined_height
            else:
                default_log.debug(f"Calculating sl buffer difference using event1_candle_high "
                                  f"({candle_high}) and event1_candle_high "
                                  f"({candle_low})")
                sl_buffer = -(candle_high - candle_low)

        # QUANTITY DETAILS
        trade1_quantity = restart_dto.trade1_quantity
        extension_quantity = restart_dto.extension_quantity
        extension1_quantity = restart_dto.extension1_quantity
        extension2_quantity = restart_dto.extension2_quantity
        cover_sl_quantity = restart_dto.cover_sl_quantity
        reverse1_trade_quantity = restart_dto.reverse1_trade_quantity
        reverse2_trade_quantity = restart_dto.reverse2_trade_quantity

        # ALERT TRADES ORDER IDs
        trade1_order_id = restart_dto.signal_trade_order_id
        extension1_order_id = restart_dto.extension1_order_id
        extension2_order_id = restart_dto.extension2_order_id
        cover_sl_trade_order_id = restart_dto.cover_sl_trade_order_id
        tp_order_id = restart_dto.tp_order_id
        sl_order_id = restart_dto.sl_order_id
        reverse1_trade_order_id = restart_dto.reverse1_trade_order_id
        reverse2_trade_order_id = restart_dto.reverse2_trade_order_id
        reverse_cover_sl_trade_order_id = restart_dto.reverse_cover_sl_trade_order_id

        h = candle_high if adjusted_high is None else adjusted_high
        l = candle_low if adjusted_low is None else adjusted_low

        tp_details = []
        if tp_value is not None:
            tp_val = tp_value
            if symbol not in indices_list:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_tp_trade}")

                tp_buffer = buffer_for_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))
            else:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_indices_tp_trade}")

                tp_buffer = buffer_for_indices_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))

            tp_details = [TPDetailsDTO(
                tp_value=tp_val,
                low_1=low_1,
                high_1=high_1,
                sl_value=sl_value,
                low=l,
                high=h,
                entry_price=entry_price,
                tp_buffer_percent=tp_buffer,
                tp_with_buffer=tp_with_buffer
            )]

        event_details_dto = EventDetailsDTO(
            alert_time=restart_thread_alert_time,
            event1_occur_time=event1_occur_time,
            symbol=symbol,
            time_frame=time_frame,
            event1_candle_high=candle_high,
            event1_candle_low=candle_low,
            candle_length=candle_length,
            event2_occur_breakpoint=event2_breakpoint,
            adjusted_high=adjusted_high,
            adjusted_low=adjusted_low,
            sl_buffer=sl_buffer,
            combined_height=combined_height,
            event2_occur_time=event2_occur_time,
            event3_occur_time=event3_occur_time,
            highest_point=highest_point,
            lowest_point=lowest_point,
            sl_value=sl_value,
            tp_values=tp_details,
            trade1_quantity=trade1_quantity,
            extension1_quantity=extension1_quantity,
            extension2_quantity=extension2_quantity,
            extension_quantity=extension_quantity,
            cover_sl_quantity=cover_sl_quantity,
            reverse1_trade_quantity=reverse1_trade_quantity,
            reverse2_trade_quantity=reverse2_trade_quantity,
            entry_trade_order_id=trade1_order_id,
            entry_price=entry_price,
            extension1_trade_order_id=extension1_order_id,
            extension2_trade_order_id=extension2_order_id,
            cover_sl_trade_order_id=cover_sl_trade_order_id,
            tp_order_id=tp_order_id,
            sl_order_id=sl_order_id,
            reverse1_trade_order_id=reverse1_trade_order_id,
            reverse2_trade_order_id=reverse2_trade_order_id,
            reverse_cover_sl_trade_order_id=reverse_cover_sl_trade_order_id,
            reverse_trade_stop_loss=reverse_trade_stop_loss,
            reverse_trade_take_profit=reverse_trade_take_profit,
            stop_tracking_further_events=False
        )

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

            if data is None:
                default_log.debug(f"No data received from ZERODHA for symbol={symbol}, datetime={event1_occur_time} "
                                  f"and timeframe={timeframe}")
                return None

            data_dictionary[key] = event_details_dto

        elif (event1_occur_time is not None) and (event2_occur_time is not None) and (event3_occur_time is None):
            # Event 2 has been completed but not event 3
            # Start the thread from event 2 timestamp

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

            data_dictionary[key] = event_details_dto
        else:
            # Event 3 has been completed but tp or sl has not been hit yet Start the thread from event 3 timestamp
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

            data_dictionary[key] = event_details_dto

            # Set the trades made value depending on the extension trade
            if trade1_order_id is not None:
                tried_creating_entry_order = True

            if extension1_order_id is not None:
                tried_creating_extension1_order = True

            if extension2_order_id is not None:
                tried_creating_extension2_order = True

            if cover_sl_trade_order_id is not None:
                tried_creating_cover_sl_trade = True

            if reverse1_trade_order_id is not None:
                tried_creating_reverse1_trade = True

            if reverse2_trade_order_id is not None:
                tried_creating_reverse2_trade = True

            if reverse_cover_sl_trade_order_id is not None:
                tried_creating_reverse_cover_sl_trade = True

    elif continuity_dto is not None:
        is_continuity = True
        thread_detail_id = continuity_dto.thread_id

        # ALERT SYMBOL AND TIMEFRAME DETAIL
        symbol = continuity_dto.symbol
        time_frame = continuity_dto.time_frame

        # EVENT TIMES
        event1_occur_time = continuity_dto.event1_occur_time
        event2_occur_time = continuity_dto.event2_occur_time
        event3_occur_time = continuity_dto.event3_occur_time

        # ALERT TIME
        restart_thread_alert_time = continuity_dto.alert_time

        # ALERT MISC
        event2_breakpoint = continuity_dto.event2_breakpoint
        highest_point = continuity_dto.highest_point
        lowest_point = continuity_dto.lowest_point
        sl_value = continuity_dto.sl_value
        tp_value = continuity_dto.tp_value
        high_1 = continuity_dto.high_1
        low_1 = continuity_dto.low_1
        candle_high = continuity_dto.candle_high  # EVENT 1 CANDLE HIGH
        candle_low = continuity_dto.candle_low  # EVENT 1 CANDLE LOW
        candle_length = candle_high - candle_low
        adjusted_high = continuity_dto.adjusted_high
        adjusted_low = continuity_dto.adjusted_low
        entry_price = continuity_dto.entry_price
        reverse_trade_stop_loss = continuity_dto.reverse_trade_stop_loss
        reverse_trade_take_profit = continuity_dto.reverse_trade_take_profit

        # Add SL Buffer and Combined Height
        combined_height = None
        sl_buffer = None
        if sl_value is not None:
            if adjusted_high is not None:
                default_log.debug(f"Calculating combined difference using event1_candle_high "
                                  f"({candle_high}) and adjusted_low "
                                  f"({adjusted_low})")
                combined_height = candle_high - adjusted_low
                sl_buffer = -combined_height
            else:
                default_log.debug(f"Calculating sl buffer difference using event1_candle_high "
                                  f"({candle_high}) and event1_candle_high "
                                  f"({candle_low})")
                sl_buffer = -(candle_high - candle_low)

        # QUANTITY DETAILS
        trade1_quantity = continuity_dto.trade1_quantity
        extension_quantity = continuity_dto.extension_quantity
        extension1_quantity = continuity_dto.extension1_quantity
        extension2_quantity = continuity_dto.extension2_quantity
        cover_sl_quantity = continuity_dto.cover_sl_quantity
        reverse1_trade_quantity = continuity_dto.reverse1_trade_quantity
        reverse2_trade_quantity = continuity_dto.reverse2_trade_quantity

        # ALERT TRADES ORDER IDs
        trade1_order_id = continuity_dto.signal_trade_order_id
        extension1_order_id = continuity_dto.extension1_order_id
        extension2_order_id = continuity_dto.extension2_order_id
        cover_sl_trade_order_id = continuity_dto.cover_sl_trade_order_id
        tp_order_id = continuity_dto.tp_order_id
        sl_order_id = continuity_dto.sl_order_id
        reverse1_trade_order_id = continuity_dto.reverse1_trade_order_id
        reverse2_trade_order_id = continuity_dto.reverse2_trade_order_id
        reverse_cover_sl_trade_order_id = continuity_dto.reverse_cover_sl_trade_order_id

        h = candle_high if adjusted_high is None else adjusted_high
        l = candle_low if adjusted_low is None else adjusted_low

        tp_details = []

        # EVENT 1 IS BUY
        if tp_value is not None:
            tp_val = tp_value
            if symbol not in indices_list:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_tp_trade}")

                tp_buffer = buffer_for_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))
            else:
                default_log.debug(f"For TP value for symbol={symbol} and "
                                  f"timeframe={time_frame} calculating TP value "
                                  f"by subtracting extra percent buffer of {buffer_for_indices_tp_trade}")

                tp_buffer = buffer_for_indices_tp_trade

                # Calculate TP with buffer
                tp_with_buffer = tp_val - (tp_val * (tp_buffer / 100))

            tp_details = [TPDetailsDTO(
                tp_value=tp_val,
                low_1=low_1,
                high_1=high_1,
                sl_value=sl_value,
                low=l,
                high=h,
                entry_price=entry_price,
                tp_buffer_percent=tp_buffer,
                tp_with_buffer=tp_with_buffer
            )]

        event_details_dto = EventDetailsDTO(
            alert_time=restart_thread_alert_time,
            event1_occur_time=event1_occur_time,
            symbol=symbol,
            time_frame=time_frame,
            event1_candle_high=candle_high,
            event1_candle_low=candle_low,
            candle_length=candle_length,
            event2_occur_breakpoint=event2_breakpoint,
            adjusted_high=adjusted_high,
            adjusted_low=adjusted_low,
            sl_buffer=sl_buffer,
            combined_height=combined_height,
            event2_occur_time=event2_occur_time,
            event3_occur_time=event3_occur_time,
            highest_point=highest_point,
            lowest_point=lowest_point,
            sl_value=sl_value,
            tp_values=tp_details,
            trade1_quantity=trade1_quantity,
            extension1_quantity=extension1_quantity,
            extension2_quantity=extension2_quantity,
            extension_quantity=extension_quantity,
            cover_sl_quantity=cover_sl_quantity,
            reverse1_trade_quantity=reverse1_trade_quantity,
            reverse2_trade_quantity=reverse2_trade_quantity,
            entry_trade_order_id=trade1_order_id,
            extension1_trade_order_id=extension1_order_id,
            extension2_trade_order_id=extension2_order_id,
            cover_sl_trade_order_id=cover_sl_trade_order_id,
            tp_order_id=tp_order_id,
            sl_order_id=sl_order_id,
            reverse1_trade_order_id=reverse1_trade_order_id,
            reverse2_trade_order_id=reverse2_trade_order_id,
            reverse_cover_sl_trade_order_id=reverse_cover_sl_trade_order_id,
            reverse_trade_stop_loss=reverse_trade_stop_loss,
            reverse_trade_take_profit=reverse_trade_take_profit,
            stop_tracking_further_events=False
        )

        data_dictionary[key] = event_details_dto

        # Set the trades made value depending on the extension trade
        if trade1_order_id is not None:
            tried_creating_entry_order = True

        if extension1_order_id is not None:
            tried_creating_extension1_order = True

        if extension2_order_id is not None:
            tried_creating_extension2_order = True

        if cover_sl_trade_order_id is not None:
            tried_creating_cover_sl_trade = True

        if reverse1_trade_order_id is not None:
            tried_creating_reverse1_trade = True

        if reverse2_trade_order_id is not None:
            tried_creating_reverse2_trade = True

        if reverse_cover_sl_trade_order_id is not None:
            tried_creating_reverse_cover_sl_trade = True

        # Check if current time is greater than the start market time of 09:15 IST
        # If not then wait till it is 09:15 IST
        current_time = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
        try:
            if current_time < market_start_time:
                wait_time_in_seconds = (market_start_time - current_time).seconds
                wait_time_in_seconds += ((60 * int(timeframe)) + 5)  # Adding a 5-second buffer
                default_log.debug(
                    f"As Current Time ({current_time}) < Market Start Time ({market_start_time}) so waiting "
                    f"{wait_time_in_seconds} seconds before continuing alert tracking for symbol={symbol} "
                    f"having timeframe={timeframe}")
                tm.sleep(wait_time_in_seconds)
            else:
                default_log.debug(
                    f"As Current Time ({current_time}) >= Market Start Time ({market_start_time}) so starting "
                    f"subscribing for realtime ticks for alert tracking for symbol={symbol} "
                    f"having timeframe={timeframe}")
        except Exception as e:
            default_log.debug(
                f"An error occurred while checking if current time ({current_time}) was less than the "
                f"market_start_time {market_start_time} for continuing alert for symbol={symbol} having "
                f"timeframe={timeframe}. Error: {e}")
            return

        data = get_zerodha_data(
            instrument_token=instrument_token,
            market_symbol=symbol,
            interval=interval
        )

        if data is None:
            default_log.debug(f"No data received from ZERODHA for symbol={symbol}"
                              f"and timeframe={timeframe}")
            return None

    else:
        # Non restart flow
        use_simulation = get_use_simulation_status()
        if not use_simulation:
            default_log.debug(f"As not running on simulator as use_simulation={use_simulation} for symbol={symbol} "
                              f"having timeframe={timeframe}, so not sleeping for the initial wait_time of {wait_time}")
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
            alert_time=alert_time,
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.SELL,
            configuration_type=configuration,
            trade_alert_status="PENDING",
            is_completed=False
        )

        response = add_thread_event_details(new_event_thread_dto)

        if not (len(data) > 1):
            # todo: remove this if using global data feed
            initial_event1_done = True

        if type(response) == DBApiExceptionResponse:
            default_log.debug(f"An error occurred while storing thread event details in database: {response.error}")
            return False

        thread_detail_id = response

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

        if initial_event1_done:
            dto, data_dictionary = trade_logic_buy(symbol, timeframe, data.iloc[-1], data_dictionary, is_continuity)
            dto.current_candle_low = data.iloc[-1]["low"]
            dto.current_candle_high = data.iloc[-1]["high"]
        else:
            dto, data_dictionary = trade_logic_buy(symbol, timeframe, data.iloc[-2], data_dictionary, is_continuity)
            dto.current_candle_low = data.iloc[-2]["low"]
            dto.current_candle_high = data.iloc[-2]["high"]
            initial_event1_done = True

        # Adding a check of if stop_tracking_further_events is True then break out and mark thread as completed
        if dto.stop_tracking_further_events:
            default_log.debug(f"Stopping tracking of further events for symbol={symbol} having timeframe={timeframe} "
                              f"as stop_tracking_further_events={dto.stop_tracking_further_events}")
            opposite_issue = True
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
            # CHECK RANGE ISSUE
            if dto.range_issue:
                default_log.debug(f"Range issue has occurred for symbol={symbol} having timeframe={timeframe}")
                range_issue = True
                break

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

                # # CHECK RANGE ISSUE
                # # Calculate the distance between event 2 breakpoint and candle high
                # candle_low = data["low"][0]
                #
                # if dto.event3_occur_time is None:
                #     decreased_price = dto.event2_occur_breakpoint - (
                #                 dto.event2_occur_breakpoint * (end_range / 100))
                #     if candle_low < decreased_price:
                #         default_log.debug(f"As the candle low ({candle_low}) has reached less than the "
                #                           f"decreased_price ({decreased_price}) which is calculated using "
                #                           f"event2_breakpoint ({dto.event2_occur_breakpoint}) and end_range% "
                #                           f"({end_range}%) for symbol={symbol} having timeframe={timeframe}")
                #         range_issue = True
                #         break

                continue

            # CHECK RANGE ISSUE
            # Calculate the distance between event 2 breakpoint and candle high
            # candle_low = data["low"][0]
            #
            # if dto.event3_occur_time is None:
            #     decreased_price = dto.event2_occur_breakpoint - (
            #             dto.event2_occur_breakpoint * (end_range / 100))
            #     if candle_low < decreased_price:
            #         default_log.debug(f"As the candle low ({candle_low}) has reached less than the "
            #                           f"decreased_price ({decreased_price}) which is calculated using "
            #                           f"event2_breakpoint ({dto.event2_occur_breakpoint}) and end_range% "
            #                           f"({end_range}%) for symbol={symbol} having timeframe={timeframe}")
            #         range_issue = True
            #         break

        if dto.event3_occur_time is None:
            if dto.range_issue:
                default_log.debug(f"Range issue has occurred for symbol={symbol} having timeframe={timeframe}")
                range_issue = True
                break
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

            # # Stop Event Tracking after 14:45 IST or 9:15 UTC
            # use_simulation = get_use_simulation_status()
            # if not use_simulation:
            #     if datetime.now() > stop_trade_time:
            #         default_log.debug(f"Current Datetime ({datetime.now()}) is greater than Stop Trade Time "
            #                           f"({stop_trade_time}), so stopping event tracking for symbol={symbol} having "
            #                           f"timeframe={timeframe}")
            #         break

            # TODO: Move this to a proper place
            use_simulation = get_use_simulation_status()
            # if not use_simulation:
            if ((dto.entry_trade_order_id is not None) or (dto.extension1_trade_order_id is not None) or
                (dto.extension2_trade_order_id is not None) or (dto.cover_sl_trade_order_id is not None) or
                (dto.reverse1_trade_order_id is not None) or (dto.reverse2_trade_order_id is not None)) and \
                    (not use_simulation):

                current_time = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                if symbol in indices_list:

                    if current_time >= close_indices_position_time:
                        default_log.debug(f"Closing Trades for symbol={symbol} having timeframe={timeframe} as "
                                          f"already trade is in progress and current_time="
                                          f"{current_time} >= close_indices_position_time "
                                          f"({close_indices_position_time})")

                        close_position_quantity = int(round(dto.extension_quantity, 0))

                        default_log.debug(f"[CLOSE POSITION] Placing STOP TRADE for symbol={symbol}, indices_symbol="
                                          f"{indices_symbol} having timeframe={timeframe} with quantity="
                                          f"{close_position_quantity}")

                        close_position_order_id = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            quantity=close_position_quantity,
                            signal_type=SignalType.SELL,
                            entry_price=data.iloc[-1]['high']
                        )

                        if close_position_order_id is None:
                            default_log.debug(f"[CLOSE POSITION] Failed to close position of the active trade having "
                                              f"symbol={symbol}, indices_symbol={indices_symbol} and timeframe={timeframe} "
                                              f"with quantity={close_position_quantity}")
                            break

                        default_log.debug(
                            f"[CLOSE POSITION] Successfully closed trades of symbol={symbol}, indices_symbol="
                            f"{indices_symbol} having timeframe={timeframe}")

                        break

                    # If current time >= 15:29 IST then stop the trades
                    else:
                        default_log.debug(f"Continuing the trade alert tracking for symbol={symbol}, indices_symbol="
                                          f"{indices_symbol} having timeframe={timeframe} as current_time "
                                          f"({current_time}) >= close_indices_position_time "
                                          f"({close_indices_position_time})")

                else:

                    if current_time >= close_cash_trades_position_time:
                        close_position_quantity = int(round(dto.extension_quantity, 0))

                        default_log.debug(f"[CLOSE POSITION] Placing STOP TRADE for symbol={symbol} having timeframe="
                                          f"{timeframe} with quantity={close_position_quantity} as current_time "
                                          f"({current_time}) >= close_cash_trades_position_time "
                                          f"({close_cash_trades_position_time})")

                        close_position_order_id = place_market_order(
                            symbol=symbol,
                            quantity=close_position_quantity,
                            signal_type=SignalType.SELL,
                            exchange="BSE",
                            entry_price=data.iloc[-1]['high']
                        )

                        if close_position_order_id is None:
                            default_log.debug(f"[CLOSE POSITION] Failed to close position of the active trade having "
                                              f"symbol={symbol} and timeframe={timeframe} with quantity="
                                              f"{close_position_quantity}")
                            break

                        default_log.debug(f"[CLOSE POSITION] Successfully closed trades of symbol={symbol} having "
                                          f"timeframe={timeframe}")

                        break

                    # If current time >= 15:20 IST then stop the trades
                    else:
                        default_log.debug(f"Continuing the trade alert tracking for symbol={symbol}, indices_symbol="
                                          f"{indices_symbol} having timeframe={timeframe} as current_time "
                                          f"({current_time}) >= close_indices_position_time "
                                          f"({close_indices_position_time})")

            # find out how many trades needs to be made and the budget to be used
            # get the initial close price
            if initial_close_price is None:
                initial_close_price = data.iloc[-1]["close"]

            # if trades_details_dto is None:

            close_price = initial_close_price
            trades_details_dto = get_budget_and_no_of_trade_details(
                symbol=symbol,
                budget=loss_budget,
                close_price=close_price,
                dto=dto
            )

            default_log.debug(f"Budget and Trade details retrieved for symbol={symbol} "
                              f"and time_frame={dto.time_frame} having close_price={close_price}: "
                              f"{trades_details_dto}")

            if (not trades_details_dto.trades_to_make.entry_trade) and \
                    (not trades_details_dto.trades_to_make.extension1_trade) and \
                    (not trades_details_dto.trades_to_make.extension2_trade) and \
                    (not trades_details_dto.trades_to_make.cover_sl_trade):
                default_log.debug(f"No TRADES are to be made for symbol={symbol} and time_frame={timeframe}")
                break

            # Find out how many trades would be made
            maximum_trades_to_make = 0
            total_percentage = 0
            if trades_details_dto.trades_to_make.entry_trade:
                default_log.debug(f"Make Entry Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
                total_percentage += trade1_loss_percent
            else:
                tried_creating_entry_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension1_trade:
                default_log.debug(f"Make Extension 1 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
                total_percentage += trade2_loss_percent
            else:
                tried_creating_extension1_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.extension2_trade:
                default_log.debug(f"Make Extension 2 Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
                total_percentage += trade3_loss_percent
            else:
                tried_creating_extension2_order = True
                trades_made += 1

            if trades_details_dto.trades_to_make.cover_sl_trade:
                default_log.debug(f"Make Cover SL Trade for symbol={symbol} and indices_symbol={indices_symbol} "
                                  f"having time_frame={timeframe}")
                maximum_trades_to_make += 1
            else:
                tried_creating_cover_sl_trade = True
                trades_made += 1

            if symbol in indices_list:
                default_log.debug(f"Getting indices symbol as trading symbol={symbol} is in "
                                  f"indices_list={indices_list} with entry price={entry_price} "
                                  f"and transaction type as {SignalType.BUY}")
                if indices_symbol is None:
                    default_log.debug(f"Getting indices symbol for symbol={symbol}, price={dto.entry_price} "
                                      f"and for transaction_type={SignalType.BUY}")
                    indices_symbol = get_indices_symbol_for_trade(
                        trading_symbol=symbol,
                        price=dto.entry_price,
                        transaction_type=SignalType.BUY
                    )

                    if indices_symbol is None:
                        default_log.debug(f"Cannot find indices symbol for symbol={symbol} and time_frame={timeframe} "
                                          f"with transaction_type={SignalType.BUY}")
                        break

            # If stop trade time i.e. 14:45 IST has been hit then only do calculations and don't take any trades
            if ((dto.entry_trade_order_id is None) and (dto.extension1_trade_order_id is None) and
                (dto.extension2_trade_order_id is None) and (dto.cover_sl_trade_order_id is None)) and \
                    (not use_simulation):

                current_time = datetime.now()
                if current_time >= stop_trade_time:

                    # CHECKING IF TP LEVEL REACHED
                    tp_value = dto.tp_values[-1].tp_with_buffer
                    candle_high = data.iloc[-1]['high']
                    current_close_price = data.iloc[-1]['close']

                    # if candle_high >= tp_value:
                    if current_close_price >= tp_value:
                        default_log.debug(
                            f"Current Candle Close ({current_close_price}) >= TP value ({tp_value}) for indices_"
                            f"symbol={indices_symbol} and symbol={symbol} and time_frame={timeframe}. "
                            f"Before placing any order as so EXITING the alert tracking")
                        break

                    trade_alert_status = "NO TRADE TIME"
                    default_log.debug(
                        f"As current time ({current_time}) >= stop_trade_time {stop_trade_time} and Entry"
                        f" Trade Order ID={dto.entry_trade_order_id}, Extension 1 Trade Order ID="
                        f"{dto.extension1_trade_order_id}, Extension 2 Trade Order ID="
                        f"{dto.extension2_trade_order_id}, SL Trade Order ID="
                        f"{dto.cover_sl_trade_order_id} for symbol={symbol} having time_frame={timeframe}")

                    # Store the current state of event in the database
                    response = store_current_state_of_event(
                        thread_detail_id=thread_detail_id,
                        symbol=symbol,
                        time_frame=timeframe,
                        signal_type=SignalType.SELL,
                        trade_alert_status=trade_alert_status,
                        configuration=configuration,
                        is_completed=False,
                        dto=dto
                    )

                    if not response:
                        default_log.debug(
                            f"An error occurred while storing thread event details in database")
                        return False

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

                        # Store the current state of event in the database
                        response = store_current_state_of_event(
                            thread_detail_id=thread_detail_id,
                            symbol=symbol,
                            time_frame=timeframe,
                            signal_type=SignalType.BUY,
                            trade_alert_status=trade_alert_status,
                            configuration=configuration,
                            is_completed=True,
                            dto=dto
                        )

                        if not response:
                            default_log.debug(
                                f"An error occurred while storing thread event details in database")
                            return False

                        return

                    # Continue calculating the take profit and stop loss but DON'T TAKE TRADE
                    continue

            # Flow to check if current time is greater than 15:30 IST then mark the alert as NEXT DAY for continuing
            use_simulation = get_use_simulation_status()
            if not use_simulation:
                current_timestamp = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                try:
                    if current_timestamp > market_close_time:
                        default_log.debug(
                            f"As current timestamp ({current_timestamp}) > market close time ({market_close_time})"
                            f" so stopping the alert tracking and marking the status of the alert as NEXT DAY "
                            f"of symbol={symbol} having timeframe={timeframe}")

                        # Mark the status as NEXT DAY for the alert and return
                        # Store the current state of event in the database
                        response = store_current_state_of_event(
                            thread_detail_id=thread_detail_id,
                            symbol=symbol,
                            time_frame=timeframe,
                            signal_type=SignalType.SELL,
                            trade_alert_status="NEXT DAY",
                            configuration=configuration,
                            is_completed=True,
                            dto=dto
                        )

                        if not response:
                            default_log.debug(
                                f"An error occurred while storing thread event details in database")
                            return False

                        return
                    else:
                        default_log.debug(
                            f"Not marking the status of the alert as NEXT DAY as current timestamp "
                            f"({current_timestamp}) < market close time ({market_close_time}) for symbol={symbol}"
                            f" having timestamp={timestamp}")
                except Exception as e:
                    default_log.debug(
                        f"An error occurred while checking if current timestamp ({current_timestamp}) > "
                        f"market close time ({market_close_time}) for symbol={symbol} having "
                        f"timeframe={timeframe}. Error: {e}")

            # ======================================================================================= #

            # Placing the entry MARKET order trade
            if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
                    not tried_creating_entry_order:

                tried_creating_entry_order = True

                # Calculate trade 1 quantity
                entry_sl_value = dto.sl_value
                entry_price = dto.entry_price
                loss_percent = loss_budget * trade1_loss_percent

                default_log.debug(
                    f"Entry Price={entry_price} and Entry SL value={entry_sl_value} for symbol={symbol} "
                    f"and indices_symbol={indices_symbol} having timeframe={timeframe}")

                trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
                trade1_quantity = int(round(trade1_quantity, 0))
                dto.trade1_quantity = trade1_quantity
                dto.actual_calculated_trade1_quantity = trade1_quantity

                # PLACING OPTION CHAIN ORDER
                if indices_symbol is not None:
                    default_log.debug(f"Rounding off trade1_quantity ({trade1_quantity}) to the "
                                      f"indices_quantity_multiplier ({indices_quantity_multiplier}) for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                    trade1_quantity = round_to_nearest_multiplier(trade1_quantity,
                                                                  indices_quantity_multiplier)

                    dto.extension_quantity = trade1_quantity

                    default_log.debug(f"After rounding off trade1_quantity to {trade1_quantity} using "
                                      f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                      f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                    # make_entry_trade = trades_details_dto.trades_to_make.entry_trade

                    if trade1_quantity == 0:
                        default_log.debug(
                            f"As trade1_quantity ({trade1_quantity}) 0 so skipping placing MARKET "
                            f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
                            f"timeframe={timeframe}")

                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'

                    elif (trade1_quantity % indices_quantity_multiplier) != 0:
                        default_log.debug(
                            f"As trade1_quantity ({trade1_quantity}) is not divisible by indices_quantity_"
                            f"multiplier ({indices_quantity_multiplier}) so skipping placing MARKET "
                            f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
                            f"timeframe={timeframe}")

                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'

                    else:
                        default_log.debug(
                            f"Placing indices MARKET order for symbol={symbol} and indices_symbol="
                            f"{indices_symbol} having timeframe={timeframe} as "
                            f"quantity={trade1_quantity} is divisible by indices_quantity_multiplier="
                            f"{indices_quantity_multiplier}")

                        entry_trade_order_id, fill_price = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.BUY,
                            quantity=trade1_quantity,
                            entry_price=entry_price
                        )

                        if entry_trade_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing MARKET order for indices_symbol="
                                f"{indices_symbol} and symbol={symbol} having timeframe={timeframe} "
                                f"with quantity={trade1_quantity}")

                            # As TRADE 1 failed so set the trade 1 quantity as zero
                            # todo: changed here
                            # dto.trade1_quantity = 0
                            dto.extension_quantity = 0

                            # Set tried_creating_entry_order as false
                            # tried_creating_entry_order = False

                        else:
                            dto.entry_trade_order_id = entry_trade_order_id
                            dto.entry_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                            budget_used = fill_price * trade1_quantity

                            # Calculate total budget that will be required for the remaining trades (including EXTENSION
                            # TRADES)
                            # remaining_trade_percentage (y_perc) = total_percentage - trade1_loss_percent (x_perc)
                            # x_perc_value = 5000 then y_perc_value = ?

                            total_budget_required = calculate_required_budget_for_trades(
                                used_percent_ratio=trade1_loss_percent,
                                used_ratio_value=budget_used,
                                total_percent_ratio=total_percentage
                            )

                            zerodha_equity = get_zerodha_equity()

                            if (zerodha_equity - total_budget_required) < 0:
                                default_log.debug(
                                    f"Not Enough Equity remaining for placing remaining trades with required "
                                    f"budget={total_budget_required} for symbol={symbol} having "
                                    f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                    f"remaining equity={zerodha_equity}")
                                # Even if equity is less try creating entry order when equity is enough
                                # tried_creating_entry_order = False
                                # not_enough_equity = True
                                # break
                            else:
                                remaining_equity = allocate_equity_for_trade(total_budget_required)
                                default_log.debug(
                                    f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                    f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                    f"Remaining Equity: Rs. {remaining_equity}")

                                total_budget_used = total_budget_required

                            # dto.extension_quantity = trade1_quantity
                            dto.trade1_quantity = trade1_quantity

                        dto.tp_order_status = 'OPEN'
                        dto.sl_order_status = 'OPEN'

                # PLACING STOCK MARKET ORDER
                else:
                    default_log.debug(
                        f"Placing MARKET order for STOCK symbol={symbol} having timeframe={timeframe} "
                        f"with quantity={trade1_quantity}")

                    entry_trade_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        quantity=trade1_quantity,
                        exchange="BSE",
                        entry_price=entry_price
                    )

                    if entry_trade_order_id is None:
                        default_log.debug(f"An error occurred while placing MARKET order for symbol="
                                          f"{symbol} and indices_symbol={indices_symbol} having timeframe={timeframe} "
                                          f"with quantity={trade1_quantity}")
                        # As TRADE 1 failed so set the trade 1 quantity as zero
                        # todo: changed here
                        # dto.trade1_quantity = 0
                        dto.extension_quantity = 0

                        # Set tried_creating_entry_order as false
                        # tried_creating_entry_order = False

                    else:
                        dto.entry_trade_order_id = entry_trade_order_id
                        dto.entry_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        budget_used = fill_price * trade1_quantity

                        # Calculate total budget that will be required for the remaining trades (including EXTENSION
                        # TRADES)
                        # remaining_trade_percentage (y_perc) = total_percentage - trade1_loss_percent (x_perc)
                        # x_perc_value = 5000 then y_perc_value = ?

                        total_budget_required = calculate_required_budget_for_trades(
                            used_percent_ratio=trade1_loss_percent,
                            used_ratio_value=budget_used,
                            total_percent_ratio=total_percentage
                        )

                        zerodha_equity = get_zerodha_equity()

                        if (zerodha_equity - total_budget_required) < 0:
                            default_log.debug(f"Not Enough Equity remaining for placing remaining trades with required "
                                              f"budget={total_budget_required} for symbol={symbol} having "
                                              f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                              f"remaining equity={zerodha_equity}")
                            # Even if equity is less try creating entry order when equity is enough
                            # tried_creating_entry_order = False
                            # not_enough_equity = True
                            # break
                        else:
                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                            default_log.debug(
                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                f"Remaining Equity: Rs. {remaining_equity}")

                            total_budget_used = total_budget_required

                        dto.trade1_quantity = trade1_quantity
                        dto.extension_quantity = trade1_quantity

                    dto.tp_order_status = 'OPEN'
                    dto.sl_order_status = 'OPEN'

                # Even if trade making failed or succeeded increment the trades counter by 1
                trades_made += 1

            # This will keep track of LIMIT or SL-M order get completed or not. ONLY for non-REVERSE TRADE ORDERS
            if ((dto.entry_trade_order_id is not None) or (dto.extension1_trade_order_id is not None) or
                (dto.extension2_trade_order_id is not None) or (
                        dto.cover_sl_trade_order_id is not None)) and (
                    (dto.reverse1_trade_order_id is None) and (dto.reverse1_trade_order_id is None)):

                candle_low = data.iloc[-1]['low']
                candle_high = data.iloc[-1]['high']
                current_close_price = data.iloc[-1]['close']

                # CHECK IF TP OR SL HAS BEEN HIT
                tp_value = dto.tp_values[-1].tp_with_buffer
                sl_value = dto.sl_value + (2 * dto.sl_buffer)

                quantity = dto.extension_quantity if dto.extension_quantity is not None else dto.trade1_quantity

                # if candle_high >= tp_value:
                if (current_close_price >= tp_value) and (dto.tp_order_id is None) and \
                    (dto.tp_order_status != 'COMPLETE') and (dto.sl_order_id is None):

                    # TODO: Remove SL details from SL dictionary
                    try:
                        default_log.debug(f"As Take Profit level has been hit for symbol={symbol} having timeframe="
                                          f"{timeframe} with signal_type=SELL. So removing the SL details of the alert")
                        remove_sl_details_of_completed_trade(
                            symbol=symbol,
                            signal_type=SignalType.SELL,
                            time_frame=int(timeframe)
                        )
                    except Exception as e:
                        default_log.debug(f"An error occurred while removing SL details for the COMPLETED trade having "
                                          f"symbol={symbol} and timeframe={timeframe}")

                    default_log.debug(
                        f"Current Candle Close ({current_close_price}) >= TP value ({tp_value}) for indices_"
                        f"symbol={indices_symbol} and symbol={symbol} and time_frame={timeframe}. "
                        f"So placing MARKET order with quantity={quantity} and "
                        f"signal_type={SignalType.SELL}")

                    if indices_symbol is None:
                        tp_order_id, fill_price = place_market_order(
                            symbol=symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity,
                            exchange="BSE",
                            entry_price=tp_value
                        )

                        if tp_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (LIMIT) MARKET order for symbol={symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")
                        else:
                            dto.tp_order_id = tp_order_id

                            # Reallocate the budget
                            default_log.debug(
                                f"Reallocating the budget ({total_budget_used}) kept aside to the equity for "
                                f"symbol={symbol} having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.tp_hit = True
                        dto.tp_order_status = 'COMPLETE'

                    else:
                        tp_order_id, fill_price = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity,
                            entry_price=tp_value
                        )

                        if tp_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (LIMIT) MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")
                        else:
                            dto.tp_order_id = tp_order_id

                            # Reallocate the budget
                            default_log.debug(f"Reallocating the budget ({total_budget_used}) kept aside to the "
                                              f"equity for symbol={symbol} having timeframe={timeframe} and "
                                              f"indices_symbol={indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.tp_hit = True
                        dto.tp_order_status = 'COMPLETE'

                    # dto.tp_order_id = tp_order_id
                    # dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    # data_not_found = False
                    # dto.tp_order_status = 'COMPLETE'
                    # break

                # Check SL hit or not
                # elif candle_low <= sl_value:
                elif (current_close_price <= sl_value) and (dto.sl_order_id is None) and \
                    (dto.sl_order_status != 'COMPLETE') and (dto.tp_order_id is None):

                    # TODO: Remove SL details from SL dictionary
                    try:
                        default_log.debug(f"As Take Profit level has been hit for symbol={symbol} having timeframe="
                                          f"{timeframe} with signal_type=SELL. So removing the SL details of the alert")
                        remove_sl_details_of_completed_trade(
                            symbol=symbol,
                            signal_type=SignalType.SELL,
                            time_frame=int(timeframe)
                        )
                    except Exception as e:
                        default_log.debug(f"An error occurred while removing SL details for the COMPLETED trade having "
                                          f"symbol={symbol} and timeframe={timeframe}")

                    default_log.debug(
                        f"Current Candle Close ({current_close_price}) <= SL value ({sl_value}) for indices_symbol="
                        f"{indices_symbol} and symbol={symbol} and time_frame={timeframe}. So placing MARKET (SL-M) "
                        f"order with quantity={quantity} and signal_type={SignalType.SELL}")

                    if indices_symbol is None:
                        sl_order_id, fill_price = place_market_order(
                            symbol=symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity,
                            exchange="BSE",
                            entry_price=sl_value
                        )

                        if sl_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (SL-M) MARKET order for symbol={symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")
                        else:
                            dto.sl_order_id = sl_order_id
                            # Reallocate the budget
                            default_log.debug(f"Reallocating the budget ({total_budget_used}) kept aside to the "
                                              f"equity for symbol={symbol} having timeframe={timeframe} and "
                                              f"indices_symbol={indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.sl_hit = True
                        dto.sl_order_status = 'COMPLETE'
                        if not take_reverse_trade:
                            default_log.debug(f"Not Placing Reverse Trade as take_reverse_trade={take_reverse_trade} "
                                              f"for symbol={symbol}, indices_symbol={indices_symbol} having "
                                              f"timeframe={timeframe}")
                            break

                    else:
                        sl_order_id, fill_price = place_indices_market_order(
                            indice_symbol=indices_symbol,
                            signal_type=SignalType.SELL,
                            quantity=quantity,
                            entry_price=sl_value
                        )

                        if sl_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing (SL-M) MARKET order for indices symbol={indices_symbol} "
                                f"with quantity={quantity} with signal_type={SignalType.SELL}")
                        else:
                            dto.sl_order_id = sl_order_id
                            # Reallocate the budget
                            default_log.debug(f"Reallocating the budget ({total_budget_used}) kept aside to the "
                                              f"equity for symbol={symbol} having timeframe={timeframe} and "
                                              f"indices_symbol={indices_symbol}")
                            reallocate_equity_after_trade(total_budget_used)

                        dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                        dto.sl_hit = True
                        dto.sl_order_status = 'COMPLETE'
                        if not take_reverse_trade:
                            default_log.debug(f"Not Placing Reverse Trade as take_reverse_trade={take_reverse_trade} "
                                              f"for symbol={symbol}, indices_symbol={indices_symbol} having "
                                              f"timeframe={timeframe}")
                            break

            # This will keep track that if all trades order ids are null and if it reaches TP level then stop alert
            # tracking and exit
            if (dto.entry_trade_order_id is None) and (dto.extension1_trade_order_id is None) and \
                    (dto.extension2_trade_order_id is None) and (dto.cover_sl_trade_order_id is None):

                # CHECKING IF TP LEVEL REACHED
                tp_value = dto.tp_values[-1].tp_with_buffer
                candle_high = data.iloc[-1]['high']
                current_close_price = data.iloc[-1]['close']

                # if candle_high >= tp_value:
                if current_close_price >= tp_value:
                    default_log.debug(
                        f"Current Candle Close ({current_close_price}) >= TP value ({tp_value}) for indices_"
                        f"symbol={indices_symbol} and symbol={symbol} and time_frame={timeframe}. "
                        f"Before placing any order as so EXITING the alert tracking")
                    dto.trade1_quantity = dto.actual_calculated_trade1_quantity if dto.actual_calculated_trade1_quantity is not None else 0
                    dto.extension1_quantity = dto.actual_calculated_extension1_quantity if dto.actual_calculated_extension1_quantity is not None else 0
                    dto.extension2_quantity = dto.actual_calculated_extension2_quantity if dto.actual_calculated_extension2_quantity is not None else 0
                    short_quantity_issue = True
                    break

                # TODO: Add SL Level Check also

            # ======================================================================================= #

            # if indices_symbol is not None:
            #     candle_high = data.iloc[-1]["high"]
            #     candle_low = data.iloc[-1]["low"]
            #
            #     default_log.debug(f"Indices symbol ({indices_symbol}) is present so only will place MARKET orders and "
            #                       f"not LIMIT and SL-M orders with current_candle_high={candle_high} and "
            #                       f"current_candle_low={candle_low}")
            #
            #     if (dto.entry_trade_order_id is None) and not tried_creating_entry_order:
            #
            #         # Calculate trade 1 quantity
            #         entry_sl_value = dto.sl_value
            #         entry_price = dto.entry_price
            #         loss_percent = loss_budget * trade1_loss_percent
            #
            #         default_log.debug(f"[For indices_symbol={indices_symbol}] Entry Price={entry_price} and "
            #                           f"Entry SL value={entry_sl_value}")
            #
            #         trade1_quantity = loss_percent / abs(entry_price - entry_sl_value)
            #         trade1_quantity = int(round(trade1_quantity, 0))
            #
            #         dto.trade1_quantity = trade1_quantity
            #
            #         default_log.debug(f"Rounding off trade1_quantity ({trade1_quantity}) to the "
            #                           f"indices_quantity_multiplier ({indices_quantity_multiplier}) for symbol={symbol} "
            #                           f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
            #
            #         trade1_quantity = round_to_nearest_multiplier(trade1_quantity, indices_quantity_multiplier)
            #
            #         default_log.debug(f"After rounding off trade1_quantity to {trade1_quantity} using "
            #                           f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
            #                           f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
            #
            #         make_entry_trade = trades_details_dto.trades_to_make.entry_trade
            #         if (trade1_quantity > 0) and (
            #                 (trade1_quantity % indices_quantity_multiplier) != 0) and make_entry_trade:
            #             default_log.debug(
            #                 f"As trade1_quantity ({trade1_quantity}) is not divisible by indices_quantity_"
            #                 f"multiplier ({indices_quantity_multiplier}) so skipping placing MARKET "
            #                 f"order for symbol={symbol} and indices_symbol={indices_symbol} having "
            #                 f"timeframe={timeframe}")
            #             # dto.trade1_quantity = trade1_quantity
            #             tried_creating_entry_order = True
            #             dto.tp_order_status = 'OPEN'
            #             dto.sl_order_status = 'OPEN'
            #         else:
            #             quantity = trade1_quantity
            #             # quantity = 50 if symbol == "NIFTY" else 45
            #             default_log.debug(f"Placing MARKET order for indices_symbol={indices_symbol} and time_frame="
            #                               f"{timeframe} with quantity={quantity}")
            #
            #             entry_trade_order_id = place_indices_market_order(
            #                 indice_symbol=indices_symbol,
            #                 signal_type=SignalType.BUY,
            #                 quantity=quantity,
            #                 entry_price=dto.entry_price
            #             )
            #
            #             if entry_trade_order_id is None:
            #                 default_log.debug(
            #                     f"An error occurred while placing MARKET order for indices symbol={indices_symbol} "
            #                     f"with quantity={quantity} with signal_type={SignalType.BUY}")
            #             else:
            #                 dto.entry_trade_order_id = entry_trade_order_id
            #
            #             tried_creating_entry_order = True
            #             dto.tp_order_status = 'OPEN'
            #             dto.sl_order_status = 'OPEN'
            #             dto.trade1_quantity = quantity
            #
            #         # Even if trade making failed or succeeded increment the trades_made counter by 1
            #         trades_made += 1
            #
            #     if dto.entry_trade_order_id or dto.extension1_trade_order_id or dto.extension2_trade_order_id:
            #         # Check TP hit or not
            #         tp_value = dto.tp_values[-1].tp_value
            #         # sl_value = dto.sl_value + dto.candle_length
            #         sl_value = dto.sl_value + (2 * dto.candle_length)
            #         tp_quantity = sl_quantity = dto.extension_quantity if dto.extension_quantity is not None else dto.trade1_quantity
            #
            #         if candle_high >= tp_value:
            #             default_log.debug(
            #                 f"Current Candle High ({candle_high}) >= TP value ({tp_value}) for indices_symbol="
            #                 f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
            #                 f"quantity={tp_quantity} and signal_type={SignalType.SELL}")
            #
            #             tp_order_id = place_indices_market_order(
            #                 indice_symbol=indices_symbol,
            #                 signal_type=SignalType.SELL,
            #                 quantity=tp_quantity,
            #                 entry_price=dto.entry_price
            #             )
            #
            #             if tp_order_id is None:
            #                 default_log.debug(
            #                     f"An error occurred while placing MARKET (LIMIT) order for indices symbol={indices_symbol} "
            #                     f"with quantity={tp_quantity} with signal_type={SignalType.SELL}")
            #
            #             dto.tp_order_id = tp_order_id
            #             dto.tp_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
            #             dto.tp_hit = True
            #             dto.tp_order_status = 'COMPLETE'
            #             break
            #
            #         # Check SL-M hit or not
            #         elif candle_low <= sl_value:
            #             default_log.debug(
            #                 f"Current Candle Low ({candle_high}) <= SL value ({sl_value}) for indices_symbol="
            #                 f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
            #                 f"quantity={sl_quantity} and signal_type={SignalType.SELL}")
            #
            #             sl_order_id = place_indices_market_order(
            #                 indice_symbol=indices_symbol,
            #                 signal_type=SignalType.SELL,
            #                 quantity=sl_quantity,
            #                 entry_price=dto.entry_price
            #             )
            #
            #             if sl_order_id is None:
            #                 default_log.debug(
            #                     f"An error occurred while placing MARKET (SL-M) order for indices symbol={indices_symbol} "
            #                     f"with quantity={sl_quantity} with signal_type={SignalType.SELL}")
            #
            #             dto.sl_order_id = sl_order_id
            #             dto.sl_candle_time = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
            #             dto.sl_hit = True
            #             dto.sl_order_status = 'COMPLETE'
            #             break

            # Only Store SL value when reverse trade have not been placed

            if (dto.reverse1_trade_order_id is None) and (dto.reverse2_trade_order_id is None):
                default_log.debug(f"Storing SL value of symbol={symbol}, timeframe={timeframe}, "
                                  f"signal_type={SignalType.BUY} having stop_loss={dto.sl_value}")

                store_sl_details_of_active_trade(
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    stop_loss=dto.sl_value,
                    event1_occur_time=dto.event1_occur_time,
                    time_frame=int(timeframe)
                )

            if extension_diff is None:
                default_log.debug(f"Extension Difference = Event 1 Candle High ({dto.event1_candle_high}) - "
                                  f"SL Value ({dto.sl_value})")
                extension_diff = abs(dto.event1_candle_high - dto.sl_value)

            # if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
            #         (indices_symbol is None) and not tried_creating_entry_order:
            #     entry_price = dto.entry_price
            #
            #     event_data_dto, error_occurred = place_initial_zerodha_trades(
            #         event_data_dto=dto,
            #         data_dictionary=data_dictionary,  # used for tracking tp and sl order status
            #         signal_type=SignalType.BUY,
            #         candle_data=data.iloc[-1],
            #         symbol=symbol,
            #         loss_budget=loss_budget,
            #         indices_symbol=indices_symbol
            #     )
            #
            #     tried_creating_entry_order = True
            #     if error_occurred:
            #         default_log.debug(f"An error occurred while placing MARKET order for symbol={symbol} and "
            #                           f"indices_symbol={indices_symbol} and event_data_dto={dto}")
            #
            #     dto = event_data_dto
            #     trades_made += 1
            #
            #     default_log.debug(f"[UPDATING] Extension Difference = Entry Price ({dto.entry_price}) "
            #                       f"- SL Value ({dto.sl_value})")
            #     extension_diff = abs(dto.entry_price - dto.sl_value)

            if not trades_details_dto.trades_to_make.entry_trade:
                dto.trade1_quantity = 0

            # if (dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]) and (dto.tp_order_id is not None) and \
            #         (indices_symbol is None):
            #     take_profit = dto.tp_values[-1].tp_with_buffer
            #
            #     # round off the price of take profit
            #     formatted_value = round_value(
            #         symbol=symbol if indices_symbol is None else indices_symbol,
            #         price=take_profit,
            #         exchange="NSE" if indices_symbol is None else "NFO"
            #     )
            #     take_profit = formatted_value
            #
            #     # dto.tp_values[-1].tp_value = take_profit
            #     dto.tp_values[-1].tp_with_buffer = take_profit
            #     use_simulation = get_use_simulation_status()
            #     if use_simulation:
            #         default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
            #                           f"id={dto.entry_trade_order_id} take_profit to {take_profit}")
            #         tp_order_id = update_zerodha_order_with_take_profit(
            #             kite=kite,
            #             zerodha_order_id=dto.tp_order_id,
            #             transaction_type=SignalType.SELL,
            #             trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
            #             exchange="NSE" if indices_symbol is None else "NFO",
            #             take_profit=take_profit,
            #             trading_symbol=symbol,
            #             candle_high=data.iloc[-1]['high'],
            #             candle_low=data.iloc[-1]['low']
            #         )
            #     else:
            #         default_log.debug(f"Updating Zerodha TP order with id={dto.tp_order_id} having market order "
            #                           f"id={dto.entry_trade_order_id} take_profit to {take_profit}")
            #         tp_order_id = update_zerodha_order_with_take_profit(
            #             kite=kite,
            #             zerodha_order_id=dto.tp_order_id,
            #             transaction_type=SignalType.SELL,
            #             trade_quantity=dto.trade1_quantity if dto.extension_quantity is None else dto.extension_quantity,
            #             exchange="NSE" if indices_symbol is None else "NFO",
            #             take_profit=take_profit,
            #             trading_symbol=symbol
            #         )
            #
            #     if tp_order_id is None:
            #         default_log.debug(f"An error occurred while updating TP order for "
            #                           f"trading_symbol={symbol}, having transaction_type as {SignalType.SELL} "
            #                           f"having quantity={dto.trade1_quantity} with take_profit={take_profit} ")
            #     else:
            #         default_log.debug(
            #             f"Updated TP order with ID: {tp_order_id} with take profit={take_profit} "
            #             f"for symbol={symbol} and indices_symbol={indices_symbol}")
            #
            #         dto.tp_order_id = tp_order_id

            # if dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"]:

            # Condition 1
            # Check the SL increase condition
            entry_price = dto.entry_price
            current_candle_low = data.iloc[-1]["low"]
            current_candle_close = data.iloc[-1]["close"]

            # if ((entry_price - ((entry_price - dto.sl_value) / 2)) >= current_candle_low) and not sl_got_extended:
            #     default_log.debug(f"For symbol={symbol} and time_frame={dto.time_frame} "
            #                       f"Entry Price ({entry_price}) - [Entry Price ({entry_price}) - "
            #                       f"SL value ({dto.sl_value})] >= Current Candle Low ({current_candle_low})")

            # Only Update SL value when reverse trade have not been placed
            if (dto.reverse1_trade_order_id is None) and (dto.reverse2_trade_order_id is None):
                do_update, stop_loss_to_update_to, event1_occur_time = do_update_of_sl_values(
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
                    dto.extended_sl = stop_loss_to_update_to

                    dto.extended_sl_timestamp = event1_occur_time

                    dto.cover_sl = stop_loss_to_update_to
                    sl_got_extended = True

                    # if indices_symbol is None:
                    #     # Only updating SL order when indices symbol is None
                    #     # as for indices symbol SL-M order is not placed
                    #     use_simulation = get_use_simulation_status()
                    #     if use_simulation:
                    #         candle_high = data.iloc[-1]["high"]
                    #         candle_low = data.iloc[-1]["low"]
                    #         event_data_dto = update_zerodha_stop_loss_order(
                    #             dto,
                    #             indices_symbol=indices_symbol,
                    #             candle_high=candle_high,
                    #             candle_low=candle_low
                    #         )
                    #
                    #         dto = event_data_dto
                    #     else:
                    #         event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                    #         dto = event_data_dto

                # Condition 2
                # Check condition of updating Stop Loss according to average price
                # average_entry_price = dto.entry_price
                # if dto.extension1_trade_order_id is not None:
                #     average_entry_price = (dto.entry_price + dto.extension1_entry_price) / 2
                #
                # if dto.extension2_trade_order_id is not None:
                #     average_entry_price = (dto.entry_price + dto.extension1_entry_price + dto.extension2_entry_price) / 3
                #
                # current_candle_close = data.iloc[-1]["close"]
                #
                # if (current_candle_close - average_entry_price) > ((average_entry_price - dto.sl_value) * 0.8):
                #     default_log.debug(f"Satisfied condition for updating SL according to average entry price as "
                #                       f"[Current Candle close ({current_candle_close}) - "
                #                       f"Average Entry Price ({average_entry_price})] > "
                #                       f"[Average Entry Price ({average_entry_price}) - SL value ({dto.sl_value})] * 0.8")
                #     dto.sl_value = average_entry_price
                #     dto.extended_sl = average_entry_price
                #     dto.cover_sl = average_entry_price
                #
                #     if indices_symbol is None:
                #         # Only updating SL order when indices symbol is None
                #         # as for indices symbol SL-M order is not placed
                #         use_simulation = get_use_simulation_status()
                #         if use_simulation:
                #             candle_high = data.iloc[-1]["high"]
                #             candle_low = data.iloc[-1]["low"]
                #             event_data_dto = update_zerodha_stop_loss_order(
                #                 dto,
                #                 indices_symbol=indices_symbol,
                #                 candle_high=candle_high,
                #                 candle_low=candle_low
                #             )
                #
                #             dto = event_data_dto
                #         else:
                #             event_data_dto = update_zerodha_stop_loss_order(dto, indices_symbol=indices_symbol)
                #             dto = event_data_dto

            # Extra Trade placing logic
            # Place extra trade if candle high goes ABOVE by a threshold value
            if (extension_diff is not None) and \
                    ((dto.tp_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])
                     and (dto.sl_order_status in ["MODIFIED", "OPEN", "TRIGGER PENDING"])) and \
                    (trades_details_dto.trades_to_make.extension1_trade or
                     trades_details_dto.trades_to_make.extension2_trade):

                default_log.debug(f"Extension Diff={extension_diff}, trades_made={trades_made}, "
                                  f"TP Order status={dto.tp_order_status} with id={dto.tp_order_id} and "
                                  f"SL Order status={dto.sl_order_status} with id={dto.sl_order_id} ")

                extension_time_stamp = data.iloc[-1]["time"]
                current_candle_low = data.iloc[-1]["low"]
                current_close_price = data.iloc[-1]['close']
                # threshold = extension_diff * (1 + (config_threshold_percent * trades_made))

                # entry_price_difference = abs(dto.sl_value - current_candle_low)
                entry_price_difference = abs(dto.sl_value - dto.entry_price)

                # reached_extension2_point = False
                # reached_extension1_point = False

                # if tried_creating_extension1_order and trades_details_dto.trades_to_make.extension1_trade:
                # if (dto.extension1_trade_order_id is not None) and trades_details_dto.trades_to_make.extension1_trade:
                #     default_log.debug(f"Extension 1 trade has been made as Extension 1 Trade order id="
                #                       f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                #                       f"{tried_creating_extension1_order} and Make extension 1 trade status="
                #                       f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 2 "
                #                       f"trade threshold percent={extension2_threshold_percent}")
                #     threshold_percent = extension2_threshold_percent
                # else:
                #     default_log.debug(f"Extension 1 trade has not been made as Extension 1 Trade order id="
                #                       f"{dto.extension1_trade_order_id} and Tried creating extension 1 order="
                #                       f"{tried_creating_extension1_order} and Make extension 1 trade status="
                #                       f"{trades_details_dto.trades_to_make.extension1_trade}. So using Extension 1 "
                #                       f"trade threshold percent={extension1_threshold_percent}")
                #     threshold_percent = extension1_threshold_percent

                extension1_point = dto.entry_price - (extension_diff * extension1_threshold_percent)
                extension2_point = dto.entry_price - (extension_diff * extension2_threshold_percent)

                if (current_close_price <= extension1_point) and not reached_extension1_point:
                    default_log.debug(f"Reached Extension 1 Point as current_close_price ({current_close_price}) <= "
                                      f"Extension 1 point ({extension1_point}) with entry_price={dto.entry_price}, "
                                      f"extension_diff={extension_diff} for symbol={symbol} having "
                                      f"timeframe={timeframe}")
                    reached_extension1_point = True
                    threshold_point = extension1_point
                    threshold = (extension_diff * extension1_threshold_percent)
                    entry_price_difference = abs(dto.sl_value - threshold_point)

                    default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                      f"at timestamp = {extension_time_stamp} and "
                                      f"current_candle_low={current_candle_low} and threshold={threshold} and "
                                      f"threshold_point={threshold_point} and Entry Price Difference="
                                      f"{entry_price_difference}")

                if (current_close_price <= extension2_point) and not reached_extension2_point:
                    default_log.debug(f"Reached Extension 2 Point as current_close_price ({current_close_price}) <= "
                                      f"Extension 2 point ({extension2_point}) with entry_price={dto.entry_price}, "
                                      f"extension_diff={extension_diff} for symbol={symbol} having "
                                      f"timeframe={timeframe}")
                    reached_extension2_point = True
                    threshold_point = extension2_point
                    threshold = (extension_diff * extension2_threshold_percent)
                    entry_price_difference = abs(dto.sl_value - threshold_point)

                    default_log.debug(f"[EXTENSION] Entry Price = {dto.entry_price} and SL value = {dto.sl_value} "
                                      f"at timestamp = {extension_time_stamp} and "
                                      f"current_candle_low={current_candle_low} and threshold={threshold} and "
                                      f"threshold_point={threshold_point} and Entry Price Difference="
                                      f"{entry_price_difference}")

                # threshold = extension_diff * (config_threshold_percent * trades_made)
                # threshold = extension_diff * threshold_percent
                # threshold_point = dto.entry_price - threshold

                # if entry_price_difference >= threshold:
                # if current_candle_low <= threshold_point:
                # if current_close_price <= threshold_point:
                if reached_extension1_point or reached_extension2_point:
                    default_log.debug(f"[EXTENSION] Creating EXTENSION trade as Entry Price = {dto.entry_price} "
                                      f"and SL value = {dto.sl_value} "
                                      f"and current_candle_low = {current_candle_low} "
                                      f"at timestamp = {extension_time_stamp} "
                                      f"Reached Extension 1 Point={reached_extension1_point} and "
                                      f"Reached Extension 2 Point={reached_extension2_point}")

                    # Check if entry trade was placed or not
                    # if (dto.entry_trade_order_id is None) and trades_details_dto.trades_to_make.entry_trade and \
                    #         not tried_creating_entry_order and (reached_extension1_point or reached_extension2_point):
                    #     # This condition will occur only when an attempt was made to place entry trade but failed
                    #     # So don't place entry trade and mark tried_creating_entry_order as True
                    #     default_log.debug(f"As Entry Trade order id={dto.entry_trade_order_id} and Make Entry Trade="
                    #                       f"{trades_details_dto.trades_to_make.entry_trade} and tried_creating_entry_"
                    #                       f"order={tried_creating_entry_order} and current_close_price="
                    #                       f"{current_close_price} and reached_extension1_point="
                    #                       f"{reached_extension1_point}, reached_extension2_point="
                    #                       f"{reached_extension1_point} so will stop "
                    #                       f"trying to place entry trade and place extension trade")
                    #     tried_creating_entry_order = True

                    # Check if extension 1 trade was placed or not
                    # if (dto.extension1_trade_order_id is None) and trades_details_dto.trades_to_make.extension1_trade and \
                    #         not tried_creating_extension1_order and reached_extension2_point:
                    #     default_log.debug(
                    #         f"As Extension 1 Trade order id={dto.extension1_trade_order_id} and Make Extension 1 Trade="
                    #         f"{trades_details_dto.trades_to_make.extension1_trade} and tried_creating_extension1_order="
                    #         f"{tried_creating_entry_order} and current_close_price="
                    #         f"{current_close_price} and reached_extension2_point="
                    #         f"{reached_extension2_point} so will stop "
                    #         f"trying to place extension 1 trade and place extension 2 trade")
                    #     tried_creating_extension1_order = True

                    # PLACING EXTENSION 2 ORDER
                    # If first extension trade is already done placing second extension trade
                    if tried_creating_extension1_order and (not tried_creating_extension2_order) and \
                            (dto.extension2_trade_order_id is None) and reached_extension2_point:
                        # If first two trades were placed then check if third trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension2_trade:
                            tried_creating_extension2_order = True
                            loss_percent = loss_budget * trade3_loss_percent
                            # loss_percent = trade3_loss_percent
                            default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference

                            # if indices_symbol is not None:

                            total_quantity = int(round(extension_quantity, 0))
                            # make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                            # make_extension1_trade = trades_details_dto.trades_to_make.extension1_trade

                            dto.extension2_quantity = total_quantity
                            dto.actual_calculated_extension2_quantity = total_quantity

                            # EXTENSION 2 OPTION CHAIN TRADE
                            if indices_symbol is not None:

                                # QUANTITY LOGIC FOR EXTENSION 2 TRADE
                                if dto.extension1_trade_order_id is None:
                                    extension1_quantity = dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                    trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0
                                    if dto.entry_trade_order_id is None:

                                        total_quantity += (extension1_quantity + trade1_quantity)

                                        dto.extension_quantity = extension1_quantity + trade1_quantity
                                    else:
                                        total_quantity += extension1_quantity

                                        dto.extension_quantity = trade1_quantity

                                elif dto.entry_trade_order_id is None:
                                    extension1_quantity = dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                    trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0

                                    if dto.extension1_trade_order_id is None:
                                        total_quantity += (extension1_quantity + trade1_quantity)

                                        dto.extension_quantity = extension1_quantity + trade1_quantity

                                    else:
                                        total_quantity = total_quantity

                                        dto.extension_quantity = extension1_quantity

                                elif (dto.entry_trade_order_id is not None) and \
                                        (dto.extension1_trade_order_id is not None):
                                    extension1_quantity = dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                    trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0

                                    dto.extension_quantity = (extension1_quantity + trade1_quantity)

                                # OLD QUANTITY LOGIC FOR EXTENSION 2 TRADE
                                # if (dto.entry_trade_order_id is None) and tried_creating_entry_order:
                                #     total_quantity += dto.trade1_quantity
                                # else:
                                #     # if entry trade was placed then add that quantity
                                #     total_quantity += dto.extension_quantity if dto.extension_quantity is not None else 0
                                #
                                # if (dto.extension1_trade_order_id is None) and tried_creating_extension2_order:
                                #     total_quantity += dto.extension1_quantity if dto.extension1_quantity is not None else 0
                                # else:
                                #     # if extension 1 trade was placed then add that quantity
                                #     total_quantity += dto.extension_quantity if dto.extension_quantity is not None else 0

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

                                if total_quantity == 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 2 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is 0 ")
                                    # dto.extension_quantity += total_quantity
                                    if tried_creating_cover_sl_trade:
                                        default_log.debug(f"Already Tried creating BEYOND EXTENSION TRADE as "
                                                          f"tried_creating_cover_sl_trade="
                                                          f"{tried_creating_cover_sl_trade} for symbol={symbol} "
                                                          f"having timeframe={timeframe}")
                                        break
                                elif (total_quantity % indices_quantity_multiplier) != 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 2 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier})")
                                    # dto.extension_quantity += total_quantity
                                    if tried_creating_cover_sl_trade:
                                        default_log.debug(f"Already Tried creating BEYOND EXTENSION TRADE as "
                                                          f"tried_creating_cover_sl_trade="
                                                          f"{tried_creating_cover_sl_trade} for symbol={symbol} "
                                                          f"having timeframe={timeframe}")
                                        break
                                else:
                                    default_log.debug(
                                        f"Creating EXTENSION 2 MARKET order with quantity={total_quantity} for "
                                        f"symbol={symbol} and time_frame={timeframe}")

                                    # if dto.extension_quantity is None:
                                    #     dto.extension_quantity = 0
                                    #
                                    # extension2_quantity = total_quantity
                                    # extension_quantity_for_indices_symbol = dto.extension_quantity + extension2_quantity

                                    extension_order_id, fill_price = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=total_quantity,
                                        entry_price=current_candle_low
                                    )

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION MARKET order for "
                                            f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                        if ((dto.trade1_quantity is None) or (dto.trade1_quantity == 0)) and \
                                                ((dto.extension1_quantity is None) and (dto.extension1_quantity == 0)):
                                            dto.extension_quantity = 0

                                        # todo: changed here
                                        # dto.extension2_quantity = 0

                                        # Set tried_creating_extension2_order as false
                                        # tried_creating_extension2_order = False

                                    else:
                                        dto.extension2_trade_order_id = extension_order_id
                                        dto.extension2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                        # if (tried_creating_extension1_order and tried_creating_entry_order) and \
                                        #         ((dto.entry_trade_order_id is None) and
                                        #          (dto.extension1_trade_order_id is None)):

                                        # SETTING THE BUDGET USED AND WILL BE REQUIRED
                                        budget_used = fill_price * total_quantity

                                        default_log.debug(f"Allocating equity of Rs. {budget_used} for the "
                                                          f"extension 2 trade of symbol={symbol} and having "
                                                          f"timeframe={timeframe}")

                                        # Calculate total budget that will be required for the remaining trades
                                        percent_ratio_used = trade3_loss_percent
                                        if tried_creating_entry_order:
                                            percent_ratio_used += trade1_loss_percent

                                        if tried_creating_extension1_order:
                                            percent_ratio_used += trade2_loss_percent

                                        total_budget_required = calculate_required_budget_for_trades(
                                            used_percent_ratio=percent_ratio_used,
                                            used_ratio_value=budget_used,
                                            total_percent_ratio=total_percentage
                                        )

                                        zerodha_equity = get_zerodha_equity()

                                        if (zerodha_equity - total_budget_required) < 0:
                                            default_log.debug(
                                                f"Not Enough Equity remaining for placing remaining trades with "
                                                f"required budget={total_budget_required} for symbol={symbol} having "
                                                f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                                f"remaining equity={zerodha_equity}")

                                            # Even if equity is less, then also retry when equity is enough
                                            # tried_creating_extension2_order = False
                                            # not_enough_equity = True
                                            # break
                                        else:
                                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                                            default_log.debug(
                                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                                f"Remaining Equity: Rs. {remaining_equity}")

                                            total_budget_used = total_budget_required

                                        dto.extension2_quantity = total_quantity
                                        if (dto.entry_trade_order_id is None) and (
                                                dto.extension1_trade_order_id is None):
                                            dto.extension_quantity = total_quantity
                                        else:
                                            dto.extension_quantity += total_quantity

                            # EXTENSION 2 STOCKS TRADE
                            else:
                                extension_order_id, fill_price = place_market_order(
                                    symbol=symbol,
                                    signal_type=SignalType.BUY,
                                    quantity=total_quantity,
                                    exchange="BSE",
                                    entry_price=current_candle_low
                                )

                                if extension_order_id is None:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION MARKET order for "
                                        f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                    if ((dto.trade1_quantity is None) or (dto.trade1_quantity == 0)) and \
                                            ((dto.extension1_quantity is None) and (dto.extension1_quantity == 0)):
                                        dto.extension_quantity = 0

                                    # todo: changed here
                                    # dto.extension2_quantity = 0

                                    # Set tried_creating_extension2_order as false
                                    # tried_creating_extension2_order = False

                                else:
                                    dto.extension2_trade_order_id = extension_order_id
                                    dto.extension2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                    # if (tried_creating_extension1_order and tried_creating_entry_order) and \
                                    #         ((dto.entry_trade_order_id is None) and
                                    #          (dto.extension1_trade_order_id is None)):

                                    # SETTING THE BUDGET USED AND WILL BE REQUIRED
                                    budget_used = fill_price * total_quantity

                                    default_log.debug(f"Allocating equity of Rs. {budget_used} for the "
                                                      f"extension 2 trade for symbol={symbol} having "
                                                      f"timeframe={timeframe}")

                                    # Calculate total budget that will be required for the remaining trades
                                    percent_ratio_used = trade3_loss_percent
                                    if tried_creating_entry_order:
                                        percent_ratio_used += trade1_loss_percent

                                    if tried_creating_extension1_order:
                                        percent_ratio_used += trade2_loss_percent

                                    total_budget_required = calculate_required_budget_for_trades(
                                        used_percent_ratio=percent_ratio_used,
                                        used_ratio_value=budget_used,
                                        total_percent_ratio=total_percentage
                                    )

                                    zerodha_equity = get_zerodha_equity()

                                    if (zerodha_equity - total_budget_required) < 0:
                                        default_log.debug(
                                            f"Not Enough Equity remaining for placing remaining trades with "
                                            f"required budget={total_budget_required} for symbol={symbol} having "
                                            f"timeframe={timeframe} and indices_symbol={indices_symbol} and "
                                            f"remaining equity={zerodha_equity}")

                                        # tried_creating_extension2_order = False
                                        # not_enough_equity = True
                                        # break
                                    else:
                                        remaining_equity = allocate_equity_for_trade(total_budget_required)
                                        default_log.debug(
                                            f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                            f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}"
                                            f". Remaining Equity: Rs. {remaining_equity}")

                                        total_budget_used = total_budget_required

                                    extension_quantity = 0 if dto.extension_quantity is None else dto.extension_quantity
                                    dto.extension_quantity = total_quantity + extension_quantity

                            # Even if trade making failed or succeeded increment the trades_made counter by 1
                            trades_made += 1

                            # Mark TP and SL order status as OPEN as TP and SL order won't be placed for
                            # indices trade
                            dto.tp_order_status = 'OPEN'
                            dto.sl_order_status = 'OPEN'

                            # OLD FLOW
                            # else:
                            #     event_data_dto, error_occurred = place_extension_zerodha_trades(
                            #         event_data_dto=dto,
                            #         signal_type=SignalType.BUY,
                            #         candle_data=data.iloc[-1],
                            #         extension_quantity=extension_quantity if indices_symbol is None else 50,
                            #         symbol=symbol,
                            #         indices_symbol=indices_symbol,
                            #         multiplier=trades_made,
                            #         extension_no=2,
                            #         exchange="NSE" if indices_symbol is None else "NFO"
                            #     )
                            #
                            #     if error_occurred:
                            #         default_log.debug(
                            #             f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} "
                            #             f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
                            #             f"extension_quantity={extension_quantity} and "
                            #             f"trade1_quantity={dto.trade1_quantity}")
                            #
                            #     trades_made += 1
                            #     dto = event_data_dto
                        else:
                            default_log.debug(
                                f"[EXTENSION] Not placing Extension 2 trade has extension 2 trade "
                                f"condition is {trades_details_dto.trades_to_make.extension2_trade}")

                    # PLACING EXTENSION 1 ORDER
                    elif tried_creating_entry_order and (not tried_creating_extension1_order) and \
                            (dto.extension1_trade_order_id is None) and reached_extension1_point:

                        # If first trade was placed then check if second trade needs to be placed or not
                        if trades_details_dto.trades_to_make.extension1_trade:
                            tried_creating_extension1_order = True
                            loss_percent = loss_budget * trade2_loss_percent
                            # loss_percent = trade2_loss_percent
                            default_log.debug(f"Loss percent = {loss_percent} for trade no. {trades_made + 1}")

                            extension_quantity = loss_percent / entry_price_difference
                            total_quantity = int(round(extension_quantity, 0))

                            dto.extension1_quantity = total_quantity
                            dto.actual_calculated_extension1_quantity = total_quantity

                            # ======================================================================= #

                            # EXTENSION 1 OPTION CHAIN TRADE
                            if indices_symbol is not None:

                                # QUANTITY LOGIC FOR EXTENSION 1 TRADE
                                trade1_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0
                                if dto.entry_trade_order_id is None:
                                    total_quantity += trade1_quantity
                                    # dto.extension_quantity = total_quantity
                                else:
                                    total_quantity = total_quantity
                                    dto.extension_quantity = trade1_quantity

                                # OLD QUANTITY LOGIC FOR EXTENSION 1 TRADE
                                # if (dto.entry_trade_order_id is None) and tried_creating_entry_order:
                                #     total_quantity += dto.trade1_quantity
                                # else:
                                #     # If already entry trade was made then add that quantity
                                #     total_quantity += dto.extension_quantity if dto.extension_quantity is not None else 0

                                total_quantity = int(round(total_quantity, 0))

                                default_log.debug(
                                    f"[EXTENSION 1] Rounding off total_quantity ({total_quantity}) to the "
                                    f"indices_quantity_multiplier ({indices_quantity_multiplier}) for "
                                    f"symbol={symbol}"
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                total_quantity = round_to_nearest_multiplier(total_quantity,
                                                                             indices_quantity_multiplier)

                                default_log.debug(
                                    f"[EXTENSION 1] After rounding off total_quantity to {total_quantity} using "
                                    f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                                    f"and indices_symbol={indices_symbol} having time_frame={timeframe}")

                                if total_quantity == 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is 0")
                                    # trade1_quantity = 0 if dto.trade1_quantity is None else dto.trade1_quantity
                                    # dto.extension_quantity += total_quantity

                                elif (total_quantity % indices_quantity_multiplier) != 0:
                                    default_log.debug(
                                        f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                                        f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                                        f"the total_quantity ({total_quantity}) is not divisible by "
                                        f"indices_quantity_multiplier ({indices_quantity_multiplier})")

                                    # dto.extension_quantity += total_quantity

                                else:
                                    default_log.debug(
                                        f"Creating EXTENSION 1 MARKET order with quantity={total_quantity} for "
                                        f"symbol={symbol} and time_frame={timeframe}")

                                    extension_order_id, fill_price = place_indices_market_order(
                                        indice_symbol=indices_symbol,
                                        signal_type=SignalType.BUY,
                                        quantity=total_quantity,
                                        entry_price=current_candle_low
                                    )

                                    if extension_order_id is None:
                                        default_log.debug(
                                            f"An error occurred while placing EXTENSION 1 MARKET order for "
                                            f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                        if (dto.trade1_quantity is None) or (dto.trade1_quantity == 0):
                                            dto.extension_quantity = 0

                                        # todo: changed here
                                        # dto.extension1_quantity = 0

                                        # Set tried_creating_extension1_order as false
                                        # tried_creating_extension1_order = False

                                    else:
                                        dto.extension1_trade_order_id = extension_order_id
                                        dto.extension1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                        # if tried_creating_entry_order and (dto.entry_trade_order_id is None):
                                        # SETTING THE BUDGET USED AND WILL BE REQUIRED
                                        budget_used = fill_price * total_quantity
                                        default_log.debug(f"As not tried creating entry_order as "
                                                          f"tried_creating_entry_order={tried_creating_entry_order}."
                                                          f" Therefore allocating equity of Rs. {budget_used} "
                                                          f"for the extension 1 trade")

                                        # Calculate total budget that will be required for the remaining trades
                                        percent_ratio_used = trade2_loss_percent
                                        if tried_creating_entry_order:
                                            percent_ratio_used += trade1_loss_percent

                                        total_budget_required = calculate_required_budget_for_trades(
                                            used_percent_ratio=percent_ratio_used,
                                            used_ratio_value=budget_used,
                                            total_percent_ratio=total_percentage
                                        )

                                        zerodha_equity = get_zerodha_equity()

                                        if (zerodha_equity - total_budget_required) < 0:
                                            default_log.debug(
                                                f"Not Enough Equity remaining for placing remaining trades with "
                                                f"required budget={total_budget_required} for symbol={symbol} "
                                                f"having timeframe={timeframe} and indices_symbol="
                                                f"{indices_symbol} and remaining equity={zerodha_equity}")
                                            # Even if equity is less, then also try creating the order
                                            # tried_creating_extension1_order = False
                                            # not_enough_equity = True
                                            # break
                                        else:
                                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                                            default_log.debug(
                                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                                f"Remaining Equity: Rs. {remaining_equity}")

                                            total_budget_used = total_budget_required

                                        dto.extension1_quantity = total_quantity
                                        if dto.entry_trade_order_id is None:
                                            dto.extension_quantity = total_quantity
                                        else:
                                            dto.extension_quantity += total_quantity

                            # EXTENSION 1 STOCKS TRADE
                            else:
                                extension_order_id, fill_price = place_market_order(
                                    symbol=symbol,
                                    signal_type=SignalType.BUY,
                                    quantity=total_quantity,
                                    exchange="BSE",
                                    entry_price=current_candle_low
                                )

                                if extension_order_id is None:
                                    default_log.debug(
                                        f"An error occurred while placing EXTENSION MARKET order for "
                                        f"indices_symbol={indices_symbol} with quantity={total_quantity}")

                                    # If trade 1 order was failed to be placed
                                    if (dto.trade1_quantity is None) or (dto.trade1_quantity == 0):
                                        dto.extension_quantity = 0

                                    # todo: changed here
                                    # dto.extension1_quantity = 0

                                    # Set tried_creating_extension1_order as false
                                    # tried_creating_extension1_order = False

                                else:
                                    dto.extension1_trade_order_id = extension_order_id
                                    dto.extension1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                    # if tried_creating_entry_order and (dto.entry_trade_order_id is None):
                                    # SETTING THE BUDGET USED AND WILL BE REQUIRED
                                    budget_used = fill_price * total_quantity
                                    default_log.debug(f"As not tried creating entry_order as "
                                                      f"tried_creating_entry_order={tried_creating_entry_order}."
                                                      f"Therefore allocating equity of Rs. {budget_used} "
                                                      f"for the extension 1 trade")

                                    # Calculate total budget that will be required for the remaining trades
                                    percent_ratio_used = trade2_loss_percent
                                    if tried_creating_entry_order:
                                        percent_ratio_used += trade1_loss_percent

                                    total_budget_required = calculate_required_budget_for_trades(
                                        used_percent_ratio=percent_ratio_used,
                                        used_ratio_value=budget_used,
                                        total_percent_ratio=total_percentage
                                    )

                                    zerodha_equity = get_zerodha_equity()

                                    if (zerodha_equity - total_budget_required) < 0:
                                        default_log.debug(
                                            f"Not Enough Equity remaining for placing remaining trades with "
                                            f"required budget={total_budget_required} for symbol={symbol} "
                                            f"having timeframe={timeframe} and indices_symbol="
                                            f"{indices_symbol} and remaining equity={zerodha_equity}")
                                        # Even if equity is less, then also try creating the order
                                        # tried_creating_extension1_order = False
                                        # not_enough_equity = True
                                        # break
                                    else:
                                        remaining_equity = allocate_equity_for_trade(total_budget_required)
                                        default_log.debug(
                                            f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                            f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                            f"Remaining Equity: Rs. {remaining_equity}")

                                        total_budget_used = total_budget_required

                                    trade1_quantity = 0 if dto.trade1_quantity is None else dto.trade1_quantity
                                    dto.extension_quantity = total_quantity + trade1_quantity

                            # Even if trade making failed or succeeded increment the trades_made counter by 1
                            trades_made += 1

                            # Mark TP and SL order status as OPEN as TP and SL order won't be placed for
                            # indices trade
                            dto.tp_order_status = 'OPEN'
                            dto.sl_order_status = 'OPEN'

                            # ======================================================================= #

                            # if indices_symbol is not None:
                            #
                            #     total_quantity = extension_quantity
                            #     make_entry_trade = trades_details_dto.trades_to_make.entry_trade
                            #     make_extension2_trade = trades_details_dto.trades_to_make.extension2_trade
                            #
                            #     dto.extension1_quantity = int(round(total_quantity, 0))
                            #     if (dto.entry_trade_order_id is None) and make_entry_trade:
                            #         total_quantity += dto.trade1_quantity
                            #
                            #     total_quantity = int(round(total_quantity, 0))
                            #     default_log.debug(
                            #         f"[EXTENSION] Rounding off total_quantity ({total_quantity}) to the "
                            #         f"indices_quantity_multiplier ({indices_quantity_multiplier}) "
                            #         f"for symbol={symbol} and indices_symbol={indices_symbol} "
                            #         f"having time_frame={timeframe}")
                            #
                            #     total_quantity = round_to_nearest_multiplier(total_quantity,
                            #                                                  indices_quantity_multiplier)
                            #
                            #     default_log.debug(
                            #         f"[EXTENSION] After rounding off total_quantity to {total_quantity} using "
                            #         f"indices_quantity_multiplier={indices_quantity_multiplier} for symbol={symbol} "
                            #         f"and indices_symbol={indices_symbol} having time_frame={timeframe}")
                            #
                            #     if (total_quantity > 0) and ((total_quantity % indices_quantity_multiplier) != 0):
                            #         default_log.debug(
                            #             f"Avoiding placing EXTENSION 1 indices trade for symbol={symbol}, "
                            #             f"indices_symbol={indices_symbol} and timeframe={timeframe} as "
                            #             f"the total_quantity ({total_quantity}) is not divisible by "
                            #             f"indices_quantity_multiplier ({indices_quantity_multiplier}). ")
                            #
                            #         dto.extension_quantity = total_quantity
                            #
                            #         if not make_extension2_trade:
                            #             default_log.debug(f"Not making Extension 2 trade as make_extension2_trade="
                            #                               f"{make_extension2_trade} and quantity ({total_quantity}) is "
                            #                               f"not a multiplier of {indices_quantity_multiplier}")
                            #             break
                            #     else:
                            #         default_log.debug(
                            #             f"Creating EXTENSION indices MARKET order with quantity={total_quantity} for "
                            #             f"indices_symbol={indices_symbol} and time_frame={timeframe}")
                            #
                            #         if dto.extension_quantity is None:
                            #             dto.extension_quantity = dto.trade1_quantity if dto.trade1_quantity is not None else 0
                            #
                            #         extension1_quantity = total_quantity
                            #
                            #         extension_quantity_for_indices_symbol = dto.extension_quantity + extension1_quantity
                            #
                            #         extension_order_id = place_indices_market_order(
                            #             indice_symbol=indices_symbol,
                            #             signal_type=SignalType.BUY,
                            #             quantity=extension_quantity_for_indices_symbol,
                            #             entry_price=dto.entry_price
                            #         )
                            #
                            #         if extension_order_id is None:
                            #             default_log.debug(
                            #                 f"An error occurred while placing EXTENSION MARKET order for symbol={indices_symbol} and "
                            #                 f"and event_data_dto={dto} and "
                            #                 f"extension_quantity={extension_quantity_for_indices_symbol} "
                            #                 f"and trade1_quantity={dto.trade1_quantity}")
                            #         else:
                            #             dto.extension1_trade_order_id = extension_order_id
                            #
                            #         # dto.extension1_quantity = extension1_quantity
                            #         dto.extension_quantity = extension_quantity_for_indices_symbol
                            #
                            #     # Even if trade making failed or succeeded increment the trades_made counter by 1
                            #     trades_made += 1
                            #
                            #     dto.sl_order_status = 'OPEN'
                            #     dto.tp_order_status = 'OPEN'
                            #
                            # else:
                            #     event_data_dto, error_occurred = place_extension_zerodha_trades(
                            #         event_data_dto=dto,
                            #         signal_type=SignalType.SELL,
                            #         candle_data=data.iloc[-1],
                            #         extension_quantity=extension_quantity if indices_symbol is None else 50,
                            #         symbol=symbol,
                            #         indices_symbol=indices_symbol,
                            #         multiplier=trades_made,
                            #         extension_no=1,
                            #         exchange="NSE" if indices_symbol is None else "NFO"
                            #     )
                            #
                            #     tried_creating_extension1_order = True
                            #
                            #     if error_occurred:
                            #         default_log.debug(
                            #             f"An error occurred while placing EXTENSION MARKET order for symbol={symbol} "
                            #             f"and indices_symbol={indices_symbol} and event_data_dto={dto} and "
                            #             f"extension_quantity={extension_quantity} and "
                            #             f"trade1_quantity={dto.trade1_quantity}")
                            #
                            #     dto = event_data_dto
                            #     trades_made += 1
                        else:
                            default_log.debug(
                                f"[EXTENSION] Not placing Extension 1 trade has extension 1 trade "
                                f"condition is {trades_details_dto.trades_to_make.extension1_trade}")
                else:
                    default_log.debug(
                        f"Extension Trade condition not met as values: extension_diff={extension_diff} "
                        f"trades_made={trades_made}, "
                        f"entry_price={entry_price} and sl_value={dto.sl_value} and reached_extension1_point="
                        f"{reached_extension1_point} and reached_extension2_point={reached_extension2_point} "
                        f"and symbol={symbol} and indices_symbol={indices_symbol} and "
                        f"Make Extension 1 trade={trades_details_dto.trades_to_make.extension1_trade} "
                        f"and Make Extension 2 trade={trades_details_dto.trades_to_make.extension2_trade} ")

            # Check if tried creating market order, extension1 order and extension2 order. If yes then create a
            # MARKET order with only SL-M order and LIMIT order
            if (tried_creating_entry_order and tried_creating_extension1_order and tried_creating_extension2_order) \
                    and ((dto.entry_trade_order_id is None) and (dto.extension1_trade_order_id is None) and
                         (dto.extension2_trade_order_id is None)) and (not tried_creating_cover_sl_trade) and \
                    (dto.cover_sl_trade_order_id is None):
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
                current_candle_low = data.iloc[-1]['low']
                current_close_price = data.iloc[-1]['close']

                # This case can occur when only SL Trade (COVER SL) need to be placed
                if dto.extension_quantity is None:
                    default_log.debug(f"Extension Quantity is None so calculating the extension quantity for "
                                      f"BEYOND EXTENSION Trade using Entry Price ({dto.entry_price}) and SL Value "
                                      f"({dto.sl_value}) with loss_percent of 100% for symbol={symbol} having timeframe"
                                      f"={timeframe}")
                    # beyond_extension_quantity = (1 * loss_budget) / abs(dto.entry_price - dto.sl_value)
                    beyond_extension_quantity = (1 * loss_budget) / abs(current_close_price - dto.sl_value)
                    dto.extension_quantity = int(round(beyond_extension_quantity, 0))
                    default_log.debug(f"[BEYOND EXTENSION] Rounded off beyond_extension_quantity="
                                      f"{beyond_extension_quantity} to {dto.extension_quantity} for symbol={symbol} "
                                      f"having timeframe={timeframe}")

                tried_creating_cover_sl_trade = True
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
                    dto.cover_sl_quantity = dto.extension_quantity

                    rounded_down_extension_quantity = round_to_nearest_multiplier(
                        dto.extension_quantity, indices_quantity_multiplier)
                    # rounded_down_extension_quantity = math.floor(
                    #     dto.extension_quantity / indices_quantity_multiplier) * indices_quantity_multiplier

                    default_log.debug(f"[BEYOND EXTENSION] Rounded down extension quantity "
                                      f"{dto.extension_quantity} to nearest multiplier of indices "
                                      f"{indices_quantity_multiplier} using the formula: "
                                      f"Rounded Extension Quantity = (Extension Quantity / Indices Multiplier) "
                                      f"* Indices => {rounded_down_extension_quantity}")

                    if (rounded_down_extension_quantity < indices_quantity_multiplier) or \
                            (rounded_down_extension_quantity % indices_quantity_multiplier != 0):
                        default_log.debug(f'[BEYOND EXTENSION] Not placing beyond extension trade as '
                                          f'rounded_down_extension_quantity ({rounded_down_extension_quantity}) < '
                                          f'indices_quantity_multiplier ({indices_quantity_multiplier}) for '
                                          f'indices_symbol={indices_symbol} and symbol={symbol} having timeframe='
                                          f'{timeframe}. OR rounded_down_extension_quantity '
                                          f'({rounded_down_extension_quantity}) is not divisible by '
                                          f'indices_quantity_multiplier ({indices_quantity_multiplier})')
                        # The Quantity fell short for placing the trade
                        short_quantity_issue = True
                        break

                    dto.extension_quantity = rounded_down_extension_quantity
                    dto.cover_sl_quantity = rounded_down_extension_quantity
                    extension_indices_market_order_id, fill_price = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        quantity=dto.extension_quantity,
                        signal_type=SignalType.BUY,
                        entry_price=current_candle_low
                    )

                    if extension_indices_market_order_id is None:
                        default_log.debug(
                            f"[BEYOND EXTENSION] An error occurred while placing BEYOND Extension Trade "
                            f"for indices_symbol={indices_symbol} having time_frame={timeframe}")

                        # Set tried_creating_cover_sl_trade as false due to LESS EQUITY
                        # tried_creating_cover_sl_trade = False
                        short_quantity_issue = True
                        break
                    else:
                        default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                          f"id={extension_indices_market_order_id} for symbol={symbol} having "
                                          f"time_frame={timeframe} with quantity={dto.extension_quantity}")

                        dto.cover_sl_trade_order_id = extension_indices_market_order_id
                        dto.sl_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                        dto.sl_order_status = 'OPEN'
                        dto.tp_order_status = 'OPEN'

                        zerodha_equity = get_zerodha_equity()

                        total_budget_required = fill_price * dto.extension_quantity

                        if (zerodha_equity - total_budget_required) < 0:
                            default_log.debug(
                                f"Not Enough Equity remaining for placing remaining trades with "
                                f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                f"having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                            # tried_creating_cover_sl_trade = False
                            not_enough_equity = True
                            break
                        else:
                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                            default_log.debug(
                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                f"Remaining Equity: Rs. {remaining_equity}")

                            total_budget_used = total_budget_required

                # STOCK MARKET COVER SL TRADE
                else:
                    cover_sl_trade_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        quantity=dto.extension_quantity,
                        signal_type=SignalType.BUY,
                        exchange="BSE",
                        entry_price=current_candle_low
                    )

                    dto.cover_sl_quantity = dto.extension_quantity

                    if cover_sl_trade_order_id is None:
                        default_log.debug(f"[BEYOND EXTENSION] An error occurred while placing BEYOND Extension Trade "
                                          f"for indices_symbol={indices_symbol} having time_frame={timeframe}")

                        # Set tried_creating_cover_sl_trade as false due to LESS EQUITY
                        # tried_creating_cover_sl_trade = False
                        short_quantity_issue = True
                        break
                    else:
                        default_log.debug(f"[BEYOND EXTENSION] Successfully Placed BEYOND Extension trade with "
                                          f"id={cover_sl_trade_order_id} for symbol={symbol} having time_frame="
                                          f"{timeframe} with quantity={dto.extension_quantity}")

                        dto.cover_sl_trade_order_id = cover_sl_trade_order_id
                        dto.sl_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                        dto.sl_order_status = 'OPEN'
                        dto.tp_order_status = 'OPEN'

                        zerodha_equity = get_zerodha_equity()

                        total_budget_required = fill_price * dto.extension_quantity

                        if (zerodha_equity - total_budget_required) < 0:
                            default_log.debug(
                                f"Not Enough Equity remaining for placing remaining trades with "
                                f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                f"having timeframe={timeframe} and indices_symbol="
                                f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                            # tried_creating_cover_sl_trade = False
                            not_enough_equity = True
                            break
                        else:
                            remaining_equity = allocate_equity_for_trade(total_budget_required)
                            default_log.debug(
                                f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                f"Remaining Equity: Rs. {remaining_equity}")

                            total_budget_used = total_budget_required

        # REVERSE TRADE LOGIC FOR SELL REVERSE TRADE
        if dto.sl_order_status == "COMPLETE":
            default_log.debug(f"Stop Loss Order with ID: {dto.sl_order_id} has been triggered and COMPLETED")

            # Check if SL was adjusted
            if dto.extended_sl is None:
                default_log.debug(f"An Stop Loss Order with ID: {dto.sl_order_id} was COMPLETED and cover SL was not "
                                  f"done so creating a REVERSE TRADE")

                # Calculate the SL value
                # Stop Loss = Adjusted SL + (2 * Candle Height (buffer also)) [It is the buffer]
                actual_sl = dto.sl_value
                adjusted_sl = dto.sl_value + (2 * dto.sl_buffer)

                dto.reverse1_entry_price = adjusted_sl

                if symbol in indices_list:
                    # Getting the indices symbol for the index symbol
                    default_log.debug(f"Getting indices symbol as trading symbol={symbol} is in "
                                      f"indices_list={indices_list} with entry price={entry_price} ")

                    # if indices_symbol is None:
                    default_log.debug(f"Getting indices symbol for symbol={symbol}, price={adjusted_sl} "
                                      f"and for transaction_type={SignalType.SELL}")
                    indices_symbol = get_indices_symbol_for_trade(trading_symbol=symbol, price=adjusted_sl,
                                                                  transaction_type=SignalType.SELL)

                    if indices_symbol is None:
                        default_log.debug(
                            f"Cannot find indices symbol for symbol={symbol} and time_frame={timeframe} with "
                            f"transaction_type={SignalType.SELL}")
                        break

                    default_log.debug(f"Indices symbol retrieved={indices_symbol}")

                # Calculating the REVERSE TRADE 1 SL VALUE
                calculated_stop_loss = adjusted_sl + (2 * abs(actual_sl - adjusted_sl))
                dto.reverse_trade_stop_loss = calculated_stop_loss

                # Calculating the REVERSE TRADE TP VALUE
                # Take Profit in case of SELL REVERSE TRADE
                # Take Profit = Adjusted SL - (Event 1 Candle Low - Adjusted SL)
                calculated_take_profit = adjusted_sl - abs(dto.event1_candle_low - adjusted_sl)
                dto.reverse_trade_take_profit = calculated_take_profit

                if (dto.reverse1_trade_order_id is None) and (not tried_creating_reverse1_trade):
                    tried_creating_reverse1_trade = True
                    default_log.debug(f"As REVERSE 1 TRADE was not placed for symbol={symbol} having "
                                      f"timeframe={timeframe} so placing REVERSE TRADE 1 with reverse_trade_stop_loss="
                                      f"{calculated_stop_loss} and reverse_trade_take_profit={calculated_take_profit}")

                    # OPTION CHAIN REVERSE TRADE 1
                    if indices_symbol is not None:

                        # Calculate the quantity
                        # For 1st BUY REVERSE 1 TRADE:
                        # Quantity = loss_budget * 0.5 / abs(adjusted SL - stop loss)
                        reverse_trade_quantity = loss_budget * 0.5 / abs(adjusted_sl - calculated_stop_loss)
                        reverse_trade_quantity = int(round(reverse_trade_quantity, 0))

                        dto.reverse1_trade_quantity = reverse_trade_quantity
                        dto.total_reverse_trade_quantity = reverse_trade_quantity

                        rounded_off_reverse_trade_quantity = round_to_nearest_multiplier(reverse_trade_quantity,
                                                                                         indices_quantity_multiplier)
                        if rounded_off_reverse_trade_quantity != 0 and (
                                rounded_off_reverse_trade_quantity % indices_quantity_multiplier) == 0:
                            default_log.debug(
                                f"Reverse trade quantity for indices_symbol={indices_symbol} is calculated "
                                f"as {reverse_trade_quantity} with loss_budget={loss_budget}, adjusted_sl="
                                f"{adjusted_sl} and stop_loss_of_reverse_trade={calculated_stop_loss}")

                            dto.reverse1_trade_quantity = rounded_off_reverse_trade_quantity
                            dto.total_reverse_trade_quantity = rounded_off_reverse_trade_quantity

                            reverse1_trade_order_id, fill_price = place_indices_market_order(
                                indice_symbol=indices_symbol,
                                quantity=rounded_off_reverse_trade_quantity,
                                signal_type=SignalType.BUY,
                                entry_price=adjusted_sl,
                            )

                            if reverse1_trade_order_id is None:
                                default_log.debug(
                                    f"An error occurred while placing REVERSE TRADE 1 for indices_symbol="
                                    f"{indices_symbol} having timeframe={timeframe}")
                                dto.reverse1_trade_quantity = 0
                                dto.total_reverse_trade_quantity = 0

                                # Set tried_creating_reverse1_trade as false due to LESS EQUITY
                                # tried_creating_reverse1_trade = False

                            else:
                                dto.reverse1_trade_order_id = reverse1_trade_order_id
                                dto.reverse1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                # SETTING THE BUDGET USED AND WILL BE REQUIRED
                                budget_used = fill_price * rounded_off_reverse_trade_quantity
                                total_budget_required = 2 * budget_used

                                zerodha_equity = get_zerodha_equity()

                                if (zerodha_equity - total_budget_required) < 0:
                                    default_log.debug(
                                        f"Not Enough Equity remaining for placing remaining trades with "
                                        f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                        f"having timeframe={timeframe} and indices_symbol="
                                        f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")
                                    # Even if equity is less, then also retry when equity is enough
                                    # tried_creating_reverse1_trade = False
                                    # not_enough_equity = True
                                    # break
                                else:
                                    remaining_equity = allocate_equity_for_trade(total_budget_required)
                                    default_log.debug(
                                        f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                        f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                        f"Remaining Equity: Rs. {remaining_equity}")

                                    total_budget_used = total_budget_required

                        else:
                            default_log.debug(
                                f"[REVERSE TRADE 1] Not placing reverse trade 1 as rounded_off_reverse_trade_quantity "
                                f"({rounded_off_reverse_trade_quantity}) % indices_quantity_multiplier "
                                f"({indices_quantity_multiplier}) != 0. OR rounded_off_reverse_trade_quantity <= 0")

                    # STOCK MARKET REVERSE TRADE 1 ORDER
                    else:

                        reverse_trade_quantity = loss_budget * 0.5 / abs(adjusted_sl - calculated_stop_loss)
                        reverse_trade_quantity = int(round(reverse_trade_quantity, 0))

                        dto.reverse1_trade_quantity = reverse_trade_quantity
                        dto.total_reverse_trade_quantity = reverse_trade_quantity

                        reverse1_trade_order_id, fill_price = place_market_order(
                            symbol=symbol,
                            quantity=reverse_trade_quantity,
                            signal_type=SignalType.SELL,
                            exchange="BSE",
                            entry_price=adjusted_sl
                        )

                        if reverse1_trade_order_id is None:
                            default_log.debug(
                                f"An error occurred while placing REVERSE TRADE 1 for symbol={symbol} "
                                f"having timeframe={timeframe}")

                            # dto.reverse1_trade_quantity = 0
                            dto.total_reverse_trade_quantity = 0

                            # Set tried_creating_reverse1_trade as false due to LESS EQUITY
                            # tried_creating_reverse1_trade = False

                        else:
                            dto.reverse1_trade_order_id = reverse1_trade_order_id
                            dto.reverse1_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                            # SETTING THE BUDGET USED AND WILL BE REQUIRED
                            budget_used = fill_price * reverse_trade_quantity

                            total_budget_required = 2 * budget_used

                            zerodha_equity = get_zerodha_equity()

                            if (zerodha_equity - total_budget_required) < 0:
                                default_log.debug(
                                    f"Not Enough Equity remaining for placing remaining trades with "
                                    f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                    f"having timeframe={timeframe} and indices_symbol="
                                    f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")
                                # Even if equity is less, then also retry when equity is enough
                                # tried_creating_reverse1_trade = False
                                # not_enough_equity = True
                                # break
                            else:
                                remaining_equity = allocate_equity_for_trade(total_budget_required)
                                default_log.debug(
                                    f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                    f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                    f"Remaining Equity: Rs. {remaining_equity}")

                                total_budget_used = total_budget_required

                            default_log.debug(f"[REVERSE TRADE 1] Successfully placed REVERSE TRADE 1 with quantity="
                                              f"{dto.reverse1_trade_quantity} with stop loss order having stop_loss="
                                              f"{dto.reverse_trade_stop_loss} and take profit order having take_profit="
                                              f"{dto.reverse_trade_take_profit} for symbol={dto.symbol} having "
                                              f"timeframe={dto.time_frame}")

                # REVERSE TRADE 2
                elif tried_creating_reverse1_trade and (not tried_creating_reverse2_trade) and \
                        (dto.reverse2_trade_order_id is None):
                    default_log.debug(f"As REVERSE 1 TRADE was placed with quantity={dto.reverse1_trade_quantity} with "
                                      f"stop_loss ({dto.reverse_trade_stop_loss}) and take_profit "
                                      f"({dto.reverse_trade_take_profit}) and reverse1_trade_order_id="
                                      f"{dto.reverse1_trade_order_id}")
                    current_candle_high = data.iloc[-1]['high']
                    current_close_price = data.iloc[-1]['close']
                    # Initial Trade Signal Type was SELL
                    # if (current_candle_high > actual_sl) and (not tried_creating_reverse2_trade):

                    # todo: update this
                    # actual_sl_with_buffer

                    if (current_close_price > actual_sl) and (not tried_creating_reverse2_trade):
                        default_log.debug(f"Placing REVERSE 2 TRADE as current candle close ({current_close_price}) > "
                                          f"actual sl ({actual_sl}) for symbol={symbol} having timeframe={timeframe}")
                        tried_creating_reverse2_trade = True
                        dto.reverse2_entry_price = actual_sl

                        if indices_symbol is not None:
                            # Calculate the quantity
                            # For 2nd BUY REVERSE 2 TRADE:
                            # Quantity = loss_budget * 0.5 / abs(adjusted SL - stop loss)
                            reverse_trade_quantity = loss_budget * 0.5 / abs(actual_sl - calculated_stop_loss)
                            reverse_trade_quantity = int(round(reverse_trade_quantity, 0))

                            dto.reverse2_trade_quantity = reverse_trade_quantity

                            reverse1_trade_quant = 0 if dto.reverse1_trade_quantity is None else dto.reverse1_trade_quantity
                            dto.total_reverse_trade_quantity = reverse_trade_quantity + reverse1_trade_quant

                            default_log.debug(f"Initial Reverse Trade 1 quantity={dto.total_reverse_trade_quantity}")
                            total_reverse_trade_quantity = dto.total_reverse_trade_quantity + reverse_trade_quantity

                            rounded_off_reverse_trade_quantity = round_to_nearest_multiplier(
                                total_reverse_trade_quantity,
                                indices_quantity_multiplier)
                            if rounded_off_reverse_trade_quantity != 0 and (
                                    rounded_off_reverse_trade_quantity % indices_quantity_multiplier) == 0:
                                default_log.debug(
                                    f"Reverse trade quantity for indices_symbol={indices_symbol} is calculated "
                                    f"as {reverse_trade_quantity} with loss_budget={loss_budget}, adjusted_sl="
                                    f"{adjusted_sl} and stop_loss_of_reverse_trade={calculated_stop_loss}")

                                dto.total_reverse_trade_quantity = rounded_off_reverse_trade_quantity

                                reverse2_trade_order_id, fill_price = place_indices_market_order(
                                    indice_symbol=indices_symbol,
                                    quantity=rounded_off_reverse_trade_quantity,
                                    signal_type=SignalType.BUY,
                                    entry_price=actual_sl,
                                )

                                if reverse2_trade_order_id is None:
                                    default_log.debug(
                                        f"An error occurred while placing REVERSE TRADE 2 for indices_symbol="
                                        f"{indices_symbol} having timeframe={timeframe}")

                                    if (dto.reverse1_trade_quantity is None) or (dto.reverse1_trade_quantity == 0):
                                        dto.total_reverse_trade_quantity = 0

                                    if dto.reverse1_trade_order_id is None:
                                        default_log.debug(
                                            f"[REVERSE TRADE 2] As Failed to place both REVERSE trades as "
                                            f"Reverse 1 trade id={dto.reverse1_trade_order_id} and "
                                            f"Reverse 2 trade order id={reverse2_trade_order_id} for "
                                            f"symbol={dto.symbol} having timeframe={dto.time_frame} so "
                                            f"stopping alert tracking")
                                        break

                                    # dto.reverse2_trade_quantity = 0

                                    # Set tried_creating_reverse2_trade as false due to LESS EQUITY
                                    # tried_creating_reverse2_trade = False

                                else:
                                    dto.reverse2_trade_order_id = reverse2_trade_order_id
                                    dto.reverse2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                    default_log.debug(
                                        f"[REVERSE TRADE 2] Successfully placed REVERSE TRADE 2 with quantity="
                                        f"{rounded_off_reverse_trade_quantity} with stop loss order having stop_loss="
                                        f"{dto.reverse_trade_stop_loss} and take profit order having take_profit="
                                        f"{dto.reverse_trade_take_profit} for symbol={dto.symbol} having "
                                        f"timeframe={dto.time_frame}")

                                    # SETTING THE BUDGET USED
                                    budget_used = fill_price * rounded_off_reverse_trade_quantity
                                    total_budget_required = budget_used

                                    zerodha_equity = get_zerodha_equity()

                                    if (zerodha_equity - total_budget_required) < 0:
                                        default_log.debug(
                                            f"Not Enough Equity remaining for placing remaining trades with "
                                            f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                            f"having timeframe={timeframe} and indices_symbol="
                                            f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                                        # Even if equity is less, then also retry when equity is enough
                                        # tried_creating_reverse2_trade = False
                                        # not_enough_equity = True
                                        # break
                                    else:
                                        remaining_equity = allocate_equity_for_trade(total_budget_required)
                                        default_log.debug(
                                            f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                            f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                            f"Remaining Equity: Rs. {remaining_equity}")

                                        total_budget_used = total_budget_required

                            else:
                                default_log.debug(
                                    f"[REVERSE TRADE 2] Not placing reverse trade 2 as rounded_off_reverse_trade_"
                                    f"quantity ({rounded_off_reverse_trade_quantity}) % indices_quantity_multiplier "
                                    f"({indices_quantity_multiplier}) != 0. OR reverse_trade_quantity <= 0")

                                if dto.reverse1_trade_order_id is None:
                                    short_quantity_issue = True
                                    return

                        # REVERSE 2 STOCKS TRADE
                        else:

                            reverse_trade_quantity = loss_budget * 0.5 / abs(actual_sl - calculated_stop_loss)
                            reverse_trade_quantity = int(round(reverse_trade_quantity, 0))
                            dto.reverse2_trade_quantity = reverse_trade_quantity

                            reverse1_trade_quant = 0 if dto.reverse1_trade_quantity is None else dto.reverse1_trade_quantity
                            dto.total_reverse_trade_quantity = reverse_trade_quantity + reverse1_trade_quant

                            reverse2_trade_order_id, fill_price = place_market_order(
                                symbol=symbol,
                                quantity=reverse_trade_quantity,
                                signal_type=SignalType.SELL,
                                exchange="BSE",
                                entry_price=actual_sl
                            )

                            if reverse2_trade_order_id is None:
                                default_log.debug(
                                    f"An error occurred while placing REVERSE TRADE 1 for symbol={symbol} "
                                    f"having timeframe={timeframe}")

                                if (dto.reverse1_trade_quantity is None) or (dto.reverse1_trade_quantity == 0):
                                    dto.total_reverse_trade_quantity = 0

                                # dto.reverse2_trade_quantity = 0
                                if dto.reverse1_trade_order_id is None:
                                    default_log.debug(f"[REVERSE TRADE 2] As Failed to place both REVERSE trades as "
                                                      f"Reverse 1 trade id={dto.reverse1_trade_order_id} and "
                                                      f"Reverse 2 trade order id={reverse2_trade_order_id} for "
                                                      f"symbol={dto.symbol} having timeframe={dto.time_frame} so "
                                                      f"stopping alert tracking")
                                    break
                                # Set tried_creating_reverse2_trade as false due to LESS EQUITY
                                # tried_creating_reverse2_trade = False

                            else:
                                dto.reverse2_trade_order_id = reverse2_trade_order_id
                                dto.reverse2_trade_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                                default_log.debug(
                                    f"[REVERSE TRADE 2] Successfully placed REVERSE TRADE 2 with quantity="
                                    f"{dto.reverse2_trade_quantity} with stop loss order having stop_loss="
                                    f"{dto.reverse_trade_stop_loss} and take profit order having "
                                    f"take_profit= {dto.reverse_trade_take_profit} for "
                                    f"symbol={dto.symbol} having timeframe={dto.time_frame}")

                                # if dto.reverse2_trade_order_id is not None:
                                budget_used = fill_price * reverse_trade_quantity

                                total_budget_required = budget_used

                                zerodha_equity = get_zerodha_equity()

                                if (zerodha_equity - total_budget_required) < 0:
                                    default_log.debug(
                                        f"Not Enough Equity remaining for placing remaining trades with "
                                        f"required budget=Rs. {total_budget_required} for symbol={symbol} "
                                        f"having timeframe={timeframe} and indices_symbol="
                                        f"{indices_symbol} and remaining equity=Rs. {zerodha_equity}")

                                    # Even if equity is less, then also retry when equity is enough
                                    # tried_creating_reverse2_trade = False
                                    # not_enough_equity = True
                                    # break
                                else:
                                    remaining_equity = allocate_equity_for_trade(total_budget_required)
                                    default_log.debug(
                                        f"Allocated Rs. {total_budget_required} for the remaining trades of symbol="
                                        f"{symbol} having timeframe={timeframe} and indices_symbol={indices_symbol}. "
                                        f"Remaining Equity: Rs. {remaining_equity}")

                                    total_budget_used = total_budget_required

            else:
                default_log.debug(f"As SL was adjusted to {dto.extended_sl} for symbol={symbol} having "
                                  f"timeframe={timeframe} and the SL order has been triggered so not placing the "
                                  f"REVERSE TRADE")
                break

        # CHECK WHETHER REVERSE TRADES HAVE BEEN PLACED OR NOT
        if (dto.reverse1_trade_order_id is not None) or (dto.reverse2_trade_order_id is not None) or \
                (dto.reverse_cover_sl_trade_order_id is not None):

            candle_high = data.iloc[-1]['high']
            candle_low = data.iloc[-1]['low']
            current_close_price = data.iloc[-1]['close']

            # Check TP hit or not
            tp_value = dto.reverse_trade_take_profit

            # todo: update this
            # tp_value_with_buffer

            # sl_value = dto.sl_value + dto.candle_length
            sl_value = dto.reverse_trade_stop_loss

            # todo: update this
            # sl_value_with_buffer

            tp_quantity = sl_quantity = dto.total_reverse_trade_quantity

            # if candle_low <= tp_value:
            if current_close_price <= tp_value:
                default_log.debug(
                    f"[REVERSE TRADE] Current Candle Close ({current_close_price}) <= TP value ({tp_value}) for indices_symbol="
                    f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
                    f"quantity={tp_quantity} and signal_type={SignalType.SELL}")

                # STOCK MARKET LIMIT TRADE
                if indices_symbol is None:

                    tp_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        quantity=tp_quantity,
                        exchange="BSE",
                        entry_price=tp_value
                    )

                    if tp_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (LIMIT) order for indices symbol={indices_symbol} "
                            f"with quantity={tp_quantity} with signal_type={SignalType.SELL}")

                    else:
                        dto.reverse_trade_tp_order_id = tp_order_id
                        dto.reverse_trade_tp_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} and "
                                          f"indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)

                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_tp_order_status = 'COMPLETE'
                    break

                # OPTION CHAIN MARKET LIMIT TRADE
                else:
                    tp_order_id, fill_price = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        signal_type=SignalType.SELL,
                        quantity=tp_quantity,
                        entry_price=tp_value
                    )

                    if tp_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (LIMIT) order for indices symbol={indices_symbol} "
                            f"with quantity={tp_quantity} with signal_type={SignalType.SELL}")

                    else:
                        dto.reverse_trade_tp_order_id = tp_order_id
                        dto.reverse_trade_tp_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} and "
                                          f"indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)
                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_tp_order_status = 'COMPLETE'
                    break

            # Check SL-M hit or not
            # elif candle_high >= sl_value:
            elif current_close_price >= sl_value:
                default_log.debug(
                    f"Current Candle Close ({current_close_price}) >= SL value ({sl_value}) for indices_symbol="
                    f"{indices_symbol} and time_frame={timeframe}. So placing MARKET order with "
                    f"quantity={sl_quantity} and signal_type={SignalType.SELL}")

                # STOCK MARKET LIMIT TRADE
                if indices_symbol is None:

                    sl_order_id, fill_price = place_market_order(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        quantity=sl_quantity,
                        exchange="BSE",
                        entry_price=sl_value
                    )

                    if sl_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (SL-M) order for indices symbol={indices_symbol} "
                            f"with quantity={sl_quantity} with signal_type={SignalType.SELL}")
                    else:
                        dto.reverse_trade_sl_order_id = sl_order_id
                        dto.reverse_trade_sl_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} and "
                                          f"indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)

                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_sl_order_status = 'COMPLETE'
                    break

                # OPTION CHAIN MARKET SL-M TRADE
                else:
                    sl_order_id, fill_price = place_indices_market_order(
                        indice_symbol=indices_symbol,
                        signal_type=SignalType.SELL,
                        quantity=tp_quantity,
                        entry_price=sl_value
                    )

                    if sl_order_id is None:
                        default_log.debug(
                            f"An error occurred while placing MARKET (SL-M) order for symbol={symbol} "
                            f"with quantity={sl_quantity} with signal_type={SignalType.SELL}")

                    else:
                        dto.reverse_trade_sl_order_id = sl_order_id
                        dto.reverse_trade_sl_order_datetime = datetime.now(tz=pytz.timezone("Asia/Kolkata"))

                        # Reallocate the budget
                        default_log.debug(f"[REVERSE TRADE] Reallocating the budget ({total_budget_used}) kept aside "
                                          f"to the equity for symbol={symbol} having timeframe={timeframe} and "
                                          f"indices_symbol={indices_symbol}")
                        reallocate_equity_after_trade(total_budget_used)

                    # dto.reverse_trade_ = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
                    # dto.tp_hit = True
                    dto.reverse_trade_tp_order_status = 'COMPLETE'
                    break

        data_dictionary[key] = dto
        default_log.debug(f"[{data.iloc[-1]['time']}] Event Details: {data_dictionary.get(key, None)}")

        # Store the current state of event in the database
        response = store_current_state_of_event(
            thread_detail_id=thread_detail_id,
            symbol=symbol,
            time_frame=timeframe,
            signal_type=SignalType.SELL,
            trade_alert_status=trade_alert_status,
            configuration=configuration,
            is_completed=False,
            dto=dto
        )

        if not response:
            default_log.debug(f"An error occurred while storing thread event details in database")
            return False

        if dto.tp_order_status == "COMPLETE":
            default_log.debug(f"Take Profit Order with ID: {dto.tp_order_id} has been triggered and COMPLETED "
                              f"for symbol={symbol} having timeframe={timeframe}")
            break

        if (dto.reverse_trade_sl_order_status == "COMPLETE") or (dto.reverse_trade_tp_order_status == "COMPLETE"):
            type_of_order_hit = 'TAKE PROFIT' if dto.reverse_trade_tp_order_status == "COMPLETE" else 'STOP LOSS'

            default_log.debug(f"{type_of_order_hit} has been triggered for symbol={symbol} having timeframe="
                              f"{timeframe}. Stopping Alert Tracking now.")
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

            # Flow to check if current time is greater than 15:30 IST then mark the alert as NEXT DAY for continuing
            use_simulation = get_use_simulation_status()
            if not use_simulation:
                current_timestamp = datetime.now(tz=pytz.timezone("Asia/Kolkata"))
                try:
                    if current_timestamp > market_close_time:
                        default_log.debug(
                            f"As current timestamp ({current_timestamp}) > market close time ({market_close_time})"
                            f" so stopping the alert tracking and marking the status of the alert as NEXT DAY "
                            f"of symbol={symbol} having timeframe={timeframe}")

                        # Mark the status as NEXT DAY for the alert and return
                        # Store the current state of event in the database
                        response = store_current_state_of_event(
                            thread_detail_id=thread_detail_id,
                            symbol=symbol,
                            time_frame=timeframe,
                            signal_type=SignalType.SELL,
                            trade_alert_status="NEXT DAY",
                            configuration=configuration,
                            is_completed=True,
                            dto=dto
                        )

                        if not response:
                            default_log.debug(
                                f"An error occurred while storing thread event details in database")
                            return False

                        return
                    else:
                        default_log.debug(
                            f"Not marking the status of the alert as NEXT DAY as current timestamp "
                            f"({current_timestamp}) < market close time ({market_close_time}) for symbol={symbol}"
                            f" having timestamp={timestamp}")
                except Exception as e:
                    default_log.debug(
                        f"An error occurred while checking if current timestamp ({current_timestamp}) > "
                        f"market close time ({market_close_time}) for symbol={symbol} having "
                        f"timeframe={timeframe}. Error: {e}")

            break

    trade_alert_status = "COMPLETE"
    if not_enough_equity:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = EQUITY as "
                          f"not_enough_equity={not_enough_equity} ")
        trade_alert_status = "EQUITY"

    if opposite_issue:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = OPPOSITE as "
                          f"opposite_issue={opposite_issue} ")
        trade_alert_status = "OPPOSITE"

    if range_issue:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = RANGE as "
                          f"range_issue={range_issue} ")
        trade_alert_status = "RANGE"

    if short_quantity_issue:
        default_log.debug(f"For symbol={symbol} having timeframe={timeframe} the trade status = SHORT QUANTITY as "
                          f"short_quantity_issue={short_quantity_issue} ")
        trade_alert_status = "SHORT QUANTITY"

    # Store the current state of event in the database
    response = store_current_state_of_event(
        thread_detail_id=thread_detail_id,
        symbol=symbol,
        time_frame=timeframe,
        signal_type=SignalType.SELL,
        trade_alert_status=trade_alert_status,
        configuration=configuration,
        is_completed=True,
        dto=dto
    )

    if not response:
        default_log.debug(f"An error occurred while storing thread event details in database")
        return False

    return


def continue_alerts():
    default_log.debug(f"inside continue_alerts")

    # Get all incomplete thread details
    thread_details = get_all_continuity_thread_details()

    for thread_detail in thread_details:
        thread_detail_id = thread_detail.id
        signal_type = thread_detail.signal_type
        configuration_type = thread_detail.configuration_type

        # ALERT SYMBOL AND TIMEFRAME DETAIL
        symbol = thread_detail.symbol
        instrument_token = instrument_tokens_map.get(symbol, None)

        exchange = "NFO" if symbol in indices_list else "NSE"
        if instrument_token is None:
            instrument_token = get_instrument_token_for_symbol(symbol, exchange)
            default_log.debug(f"instrument token received for symbol={symbol} and exchange={exchange}: "
                              f"{instrument_token}")

        time_frame = thread_detail.time_frame

        # EVENT TIMES
        event1_occur_time = thread_detail.event1_occur_time
        event2_occur_time = thread_detail.event2_occur_time
        event3_occur_time = thread_detail.event3_occur_time

        # ALERT TIME
        restart_thread_alert_time = thread_detail.alert_time

        # ALERT MISC
        event2_breakpoint = thread_detail.event2_breakpoint
        highest_point = thread_detail.highest_point
        lowest_point = thread_detail.lowest_point
        sl_value = thread_detail.sl_value
        tp_value = thread_detail.tp_value
        high_1 = thread_detail.high_1
        low_1 = thread_detail.low_1
        candle_high = thread_detail.signal_candle_high  # EVENT 1 CANDLE HIGH
        candle_low = thread_detail.signal_candle_low  # EVENT 1 CANDLE LOW
        adjusted_high = thread_detail.adjusted_high
        adjusted_low = thread_detail.adjusted_low
        entry_price = thread_detail.entry_price
        reverse_trade_stop_loss = thread_detail.reverse_trade_stop_loss
        reverse_trade_take_profit = thread_detail.reverse_trade_take_profit

        # QUANTITY DETAILS
        trade1_quantity = thread_detail.trade1_quantity
        extension_quantity = thread_detail.extension_quantity
        extension1_quantity = thread_detail.extension1_quantity
        extension2_quantity = thread_detail.extension2_quantity
        cover_sl_quantity = thread_detail.cover_sl_quantity
        reverse1_trade_quantity = thread_detail.reverse1_trade_quantity
        reverse2_trade_quantity = thread_detail.reverse2_trade_quantity

        # ALERT TRADES ORDER IDs
        trade1_order_id = thread_detail.signal_trade_order_id
        extension1_order_id = thread_detail.extension1_order_id
        extension2_order_id = thread_detail.extension2_order_id
        cover_sl_trade_order_id = thread_detail.cover_sl_trade_order_id
        tp_order_id = thread_detail.tp_order_id
        sl_order_id = thread_detail.sl_order_id
        reverse1_trade_order_id = thread_detail.reverse1_trade_order_id
        reverse2_trade_order_id = thread_detail.reverse2_trade_order_id
        reverse_cover_sl_trade_order_id = thread_detail.reverse_cover_sl_trade_order_id

        continue_event_dto = RestartEventDTO(
            thread_id=thread_detail_id,
            alert_time=restart_thread_alert_time,
            event1_occur_time=event1_occur_time,
            symbol=symbol,
            time_frame=time_frame,
            candle_high=candle_high,
            candle_low=candle_low,
            event2_breakpoint=event2_breakpoint,
            adjusted_high=adjusted_high,
            adjusted_low=adjusted_low,
            event2_occur_time=event2_occur_time,
            event3_occur_time=event3_occur_time,
            highest_point=highest_point,
            lowest_point=lowest_point,
            high_1=high_1,
            low_1=low_1,
            sl_value=sl_value,
            tp_value=tp_value,
            entry_price=entry_price,
            trade1_quantity=trade1_quantity,
            extension1_quantity=extension1_quantity,
            extension2_quantity=extension2_quantity,
            extension_quantity=extension_quantity,
            cover_sl_quantity=cover_sl_quantity,
            reverse1_trade_quantity=reverse1_trade_quantity,
            reverse2_trade_quantity=reverse2_trade_quantity,
            signal_trade_order_id=trade1_order_id,
            extension1_order_id=extension1_order_id,
            extension2_order_id=extension2_order_id,
            cover_sl_trade_order_id=cover_sl_trade_order_id,
            tp_order_id=tp_order_id,
            sl_order_id=sl_order_id,
            reverse1_trade_order_id=reverse1_trade_order_id,
            reverse2_trade_order_id=reverse2_trade_order_id,
            reverse_cover_sl_trade_order_id=reverse_cover_sl_trade_order_id,
            reverse_trade_stop_loss=reverse_trade_stop_loss,
            reverse_trade_take_profit=reverse_trade_take_profit,
            stop_tracking_further_events=False
        )

        if signal_type == SignalType.BUY:

            threading.Thread(target=start_market_logging_for_buy, args=(
                symbol,
                time_frame,
                instrument_token,
                0,
                configuration_type,
                restart_thread_alert_time,
                None,
                continue_event_dto)).start()

        else:

            threading.Thread(target=start_market_logging_for_sell, args=(
                symbol,
                time_frame,
                instrument_token,
                0,
                configuration_type,
                restart_thread_alert_time,
                None,
                continue_event_dto)).start()


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

        thread_detail_id = thread_detail.id
        signal_type = thread_detail.signal_type
        configuration_type = thread_detail.configuration_type

        # ALERT SYMBOL AND TIMEFRAME DETAIL
        symbol = thread_detail.symbol
        instrument_token = instrument_tokens_map.get(symbol, None)

        exchange = "NFO" if symbol in indices_list else "NSE"
        if instrument_token is None:
            instrument_token = get_instrument_token_for_symbol(symbol, exchange)
            default_log.debug(f"instrument token received for symbol={symbol} and exchange={exchange}: "
                              f"{instrument_token}")

        time_frame = thread_detail.time_frame

        # EVENT TIMES
        event1_occur_time = thread_detail.event1_occur_time
        event2_occur_time = thread_detail.event2_occur_time
        event3_occur_time = thread_detail.event3_occur_time

        # ALERT TIME
        restart_thread_alert_time = thread_detail.alert_time

        # ALERT MISC
        event2_breakpoint = thread_detail.event2_breakpoint
        highest_point = thread_detail.highest_point
        lowest_point = thread_detail.lowest_point
        sl_value = thread_detail.sl_value
        tp_value = thread_detail.tp_value
        high_1 = thread_detail.high_1
        low_1 = thread_detail.low_1
        candle_high = thread_detail.signal_candle_high  # EVENT 1 CANDLE HIGH
        candle_low = thread_detail.signal_candle_low  # EVENT 1 CANDLE LOW
        adjusted_high = thread_detail.adjusted_high
        adjusted_low = thread_detail.adjusted_low
        entry_price = thread_detail.entry_price
        reverse_trade_stop_loss = thread_detail.reverse_trade_stop_loss
        reverse_trade_take_profit = thread_detail.reverse_trade_take_profit

        # QUANTITY DETAILS
        trade1_quantity = thread_detail.trade1_quantity
        extension_quantity = thread_detail.extension_quantity
        extension1_quantity = thread_detail.extension1_quantity
        extension2_quantity = thread_detail.extension2_quantity
        cover_sl_quantity = thread_detail.cover_sl_quantity
        reverse1_trade_quantity = thread_detail.reverse1_trade_quantity
        reverse2_trade_quantity = thread_detail.reverse2_trade_quantity

        # ALERT TRADES ORDER IDs
        trade1_order_id = thread_detail.signal_trade_order_id
        extension1_order_id = thread_detail.extension1_order_id
        extension2_order_id = thread_detail.extension2_order_id
        cover_sl_trade_order_id = thread_detail.cover_sl_trade_order_id
        tp_order_id = thread_detail.tp_order_id
        sl_order_id = thread_detail.sl_order_id
        reverse1_trade_order_id = thread_detail.reverse1_trade_order_id
        reverse2_trade_order_id = thread_detail.reverse2_trade_order_id
        reverse_cover_sl_trade_order_id = thread_detail.reverse_cover_sl_trade_order_id

        restart_dto = RestartEventDTO(
            thread_id=thread_detail_id,
            alert_time=restart_thread_alert_time,
            event1_occur_time=event1_occur_time,
            symbol=symbol,
            time_frame=time_frame,
            candle_high=candle_high,
            candle_low=candle_low,
            event2_breakpoint=event2_breakpoint,
            adjusted_high=adjusted_high,
            adjusted_low=adjusted_low,
            event2_occur_time=event2_occur_time,
            event3_occur_time=event3_occur_time,
            highest_point=highest_point,
            lowest_point=lowest_point,
            high_1=high_1,
            low_1=low_1,
            sl_value=sl_value,
            tp_value=tp_value,
            entry_price=entry_price,
            trade1_quantity=trade1_quantity,
            extension1_quantity=extension1_quantity,
            extension2_quantity=extension2_quantity,
            extension_quantity=extension_quantity,
            cover_sl_quantity=cover_sl_quantity,
            reverse1_trade_quantity=reverse1_trade_quantity,
            reverse2_trade_quantity=reverse2_trade_quantity,
            signal_trade_order_id=trade1_order_id,
            extension1_order_id=extension1_order_id,
            extension2_order_id=extension2_order_id,
            cover_sl_trade_order_id=cover_sl_trade_order_id,
            tp_order_id=tp_order_id,
            sl_order_id=sl_order_id,
            reverse1_trade_order_id=reverse1_trade_order_id,
            reverse2_trade_order_id=reverse2_trade_order_id,
            reverse_cover_sl_trade_order_id=reverse_cover_sl_trade_order_id,
            reverse_trade_stop_loss=reverse_trade_stop_loss,
            reverse_trade_take_profit=reverse_trade_take_profit,
            stop_tracking_further_events=False
        )

        if signal_type == SignalType.BUY:

            threading.Thread(target=start_market_logging_for_buy, args=(
                symbol,
                time_frame,
                instrument_token,
                0,
                configuration_type,
                restart_thread_alert_time,
                restart_dto,
                None)).start()

        else:

            threading.Thread(target=start_market_logging_for_sell, args=(
                symbol,
                time_frame,
                instrument_token,
                0,
                configuration_type,
                restart_thread_alert_time,
                restart_dto,
                None)).start()

    return
