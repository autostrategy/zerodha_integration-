#!python
import time

# import logging

import pandas as pd
import threading

import pytz
from kiteconnect import KiteTicker
from config import zerodha_api_key, default_log
import external_services.zerodha.zerodha_orders as zo
# from external_services.zerodha.zerodha_orders import get_symbol_for_instrument_token, \
#     get_instrument_token_for_symbol_for_ticks, get_historical_data_for_token, get_access_token

# logging.basicConfig(level=logging.DEBUG)

# columns in data frame
df_cols = ["date", "Token", "LTP"]

symbol_ticks = dict()
symbols_interval_data = dict()

websocket_obj = None
subscribed_symbols = []
subscribed_tokens = []
all_ticks_queue = []
callback_started = False

custom_symbol_token_map = dict()
# Define a lock
all_ticks_lock = threading.Lock()


def tick_callback():
    # This is the callback function that will be called when tick data is received
    # You can process the tick data here or perform any other actions
    global symbol_ticks
    global symbols_interval_data
    global all_ticks_queue
    global custom_symbol_token_map

    default_log.debug(f"inside tick_callback")

    while True:
        if len(all_ticks_queue) < 1:
            default_log.debug(f"As the all_ticks_queue is empty so waiting 1 second")
            time.sleep(1)  # Sleep for 1 second
            continue
        else:
            # default_log.debug(f"[BEFORE POPPING] All ticks queue: {all_ticks_queue}")
            # Remove the first tick and process it
            tick_data = all_ticks_queue.pop(0)

            instrument_token = tick_data['instrument_token']
            # Get the instrument symbol from the instrument token

            symbol = custom_symbol_token_map.get(instrument_token, None)
            if symbol is None:
                # Get the symbol's corresponding instrument token
                inst_token = str(instrument_token)
                symbol = zo.get_symbol_for_instrument_token(inst_token)
                default_log.debug(f"Symbol Details fetched for instrument_token ({inst_token}) => {symbol}")

            symbol_tick = symbol_ticks.get(symbol, [])

            symbol_tick.append(tick_data)
            symbol_ticks[symbol] = symbol_tick

            # Get the intervals of symbol
            symbol_intervals = symbols_interval_data.get(symbol, {})

            time_frames = symbol_intervals.keys()
            default_log.debug(f"Timeframes for symbol={symbol} having timeframe keys={time_frames}")
            for time_frame in time_frames:
                threading.Thread(target=prepare_interval_data_for_symbol,
                                 args=(time_frame, symbol, instrument_token)).start()

            # if started_backtesting and not trade_alerts_df.empty:
            #     # get the time of the tick data
            #     epoch_timestamp = tick_data["LastTradeTime"]
            #     # convert to ist_timestamp
            #     utc_timestamp = datetime.datetime.utcfromtimestamp(epoch_timestamp).replace(
            #         tzinfo=datetime.timezone.utc)
            #
            #     # Convert UTC to IST
            #     ist = pytz.timezone('Asia/Kolkata')
            #     timestamp_ist = utc_timestamp.astimezone(ist)
            #     default_log.debug(f"[inside tick_callback] "
            #                       f"Checking for trade initialize event for symbol={symbol} and timestamp_ist={timestamp_ist}")
            #     check_timestamp_and_start_event_checking(timestamp_ist, symbol)
            # default_log.debug(f"[AFTER POPPING] All ticks queue: {all_ticks_queue}")


def add_realtime_ticks(tick_data):
    global all_ticks_queue
    global callback_started
    default_log.debug(f"inside add_realtime_ticks with tick_data={tick_data}")

    # Measure start time
    start_time = time.time()

    # Acquire the lock before accessing the shared resource
    all_ticks_lock.acquire()
    try:
        all_ticks_queue.extend(tick_data)
    finally:
        # Release the lock after accessing the shared resource
        all_ticks_lock.release()

    # Measure end time
    end_time = time.time()
    execution_time = end_time - start_time
    default_log.debug(f"add_realtime_ticks execution time: {execution_time} seconds")

    if not callback_started:
        callback_started = True
        threading.Thread(target=tick_callback).start()


def on_ticks(ws, ticks):
    default_log.debug(f"inside on_ticks with ticks: {ticks}")
    threading.Thread(target=add_realtime_ticks,
                     args=(ticks, )).start()


def on_connect(ws, response):
    # Callback on successful connect.
    # Store the websocket token to be using to subscribe globally
    global websocket_obj
    default_log.debug("Connected to Zerodha server to receive ticks")

    # ws.subscribe([738561, 5633])
    # ws.subscribe([9372674])  # THIS THE INSTRUMENT TOKEN TAKEN FROM INSTRUMENT TOKENS FILE

    # # Set RELIANCE to tick in `full` mode.
    # # ws.set_mode(ws.MODE_FULL, [738561])
    # ws.set_mode(ws.MODE_FULL, [9372674])

    websocket_obj = ws


def on_close(ws, code, reason):
    # On connection close stop the event loop.
    # Reconnection will not happen after executing `ws.stop()`
    default_log.debug(f"Kite Ticker Stopped due to code={code} and: {reason}")

    start_kite_ticker()
    # ws.stop()


def restart_subscribing_for_realtime_zerodha_ticks():
    global websocket_obj
    global subscribed_tokens

    default_log.debug(f"inside restart_subscribing_for_realtime_ticks with subscribed_tokens={subscribed_tokens}")
    for token in subscribed_tokens:
        default_log.debug(f"Starting subscribing for realtime ticks for token={token}")
        websocket_obj.subscribe([token])
        websocket_obj.set_mode(websocket_obj.MODE_FULL, [token])
        default_log.debug(f"Request sent to subscribe to realtime ticks for token={token}")

    return


def prepare_interval_data_for_symbol(
        time_frame: int, instrument_symbol: str, instrument_token: int):
    default_log.debug(f"inside prepare_interval_data_from_ticks with time_frame={time_frame} "
                      f"and instrument_symbol={instrument_symbol}")
    global df_cols
    global symbols_interval_data
    global symbol_ticks

    # instrument_token = instrument_tokens_map.get(instrument_symbol, None)
    # exchange = "NFO" if instrument_symbol in indices_list else "NSE"
    # if instrument_token is None:
    #     instrument_token = get_instrument_token_for_symbol(instrument_symbol, exchange)
    #     default_log.debug(f"instrument token received for symbol={instrument_symbol} and exchange={exchange}: "
    #                       f"{instrument_token}")

    ticks = symbol_ticks.get(instrument_symbol, [])
    data = dict()

    interval_in_min = str(time_frame) + 'min'

    # Loop through the ticks of the symbol
    for company_data in ticks:
        token = company_data["instrument_token"]
        ltp = company_data["last_price"]
        timestamp = company_data["last_trade_time"].astimezone(pytz.timezone("Asia/Kolkata"))

        data[timestamp] = [timestamp, token, ltp]

    tick_df = pd.DataFrame(data.values(), columns=df_cols, index=data.keys())

    # Set the index column to "Timestamp"
    ggframe = tick_df.set_index("date")

    # Convert index to DatetimeIndex
    # tick_df.index = pd.to_datetime(tick_df.index)

    # Resample the data
    candles_interval_data = ggframe.groupby('Token').resample(interval_in_min).agg({'LTP': 'ohlc'}).dropna()

    # Set the columns
    candles_interval_data.columns = ['open', 'high', 'low', 'close']

    # Get the second to last row
    if len(candles_interval_data) < 2:
        # The previous candle data has not been prepared yet

        last_row = candles_interval_data.reset_index().iloc[-1]
        # Extract the relevant values for the columns 'open', 'high', 'low', 'close'
        last_row_json = {
            'timestamp': last_row['date'],
            'open': last_row['open'],
            'high': last_row['high'],
            'low': last_row['low'],
            'close': last_row['close']
        }
        symbols_interval_data[instrument_symbol][time_frame] = [last_row_json]

        return

    last_row = candles_interval_data.reset_index().iloc[-1]
    second_to_last_row = candles_interval_data.reset_index().iloc[-2]

    # Extract the relevant values for the columns 'open', 'high', 'low', 'close'
    last_row_json = {
        'timestamp': last_row['date'],
        'open': last_row['open'],
        'high': last_row['high'],
        'low': last_row['low'],
        'close': last_row['close']
    }

    second_last_row_json = {
        'timestamp': second_to_last_row['date'],
        'open': second_to_last_row['open'],
        'high': second_to_last_row['high'],
        'low': second_to_last_row['low'],
        'close': second_to_last_row['close']
    }

    # Store the json data for the symbol, interval
    json_data_for_symbol_interval = [second_last_row_json, last_row_json]
    # json_data_for_symbol_interval = [last_row_json]

    symbols_interval_data[instrument_symbol][time_frame] = json_data_for_symbol_interval


def get_zerodha_market_data(
    trading_symbol: str,
    time_frame: int = None
):
    global subscribed_symbols
    global symbols_interval_data
    global websocket_obj
    global custom_symbol_token_map
    global subscribed_tokens

    default_log.debug(f"inside get_zerodha_market_data with trading_symbol={trading_symbol}")

    # Get Tick Data
    if trading_symbol not in subscribed_symbols:
        default_log.debug(f"Trading Symbol ({trading_symbol}) is not in symbols={subscribed_symbols}")
        subscribed_symbols.append(trading_symbol)

        # Get the symbol's corresponding instrument token
        inst_token = zo.get_instrument_token_for_symbol_for_ticks(trading_symbol, "NFO")
        default_log.debug(f"Instrument token fetched for trading_symbol ({trading_symbol}) => {inst_token}")
        custom_symbol_token_map[inst_token] = trading_symbol
        subscribed_tokens.append(inst_token)

        hist_data = zo.get_historical_data_for_token(inst_token, time_frame)
        default_log.debug(f"As just subscribed now for realtime tick data so fetched historical data for "
                          f"symbol={trading_symbol} with timeframe={time_frame}: {hist_data}")

        # TODO: Add realtime tick subscription flow
        websocket_obj.subscribe([inst_token])
        websocket_obj.set_mode(websocket_obj.MODE_FULL, [inst_token])

        default_log.debug(f"Started subscribing to Zerodha about symbol={trading_symbol}")

        symbols_interval_data[trading_symbol] = {time_frame: []}
        symbols_interval_data[trading_symbol][time_frame] = []
        default_log.debug(f"[NEW] Symbol interval data: {symbols_interval_data}")
        return [hist_data]
        # return []

    symbol_interval_data = symbols_interval_data.get(trading_symbol)
    default_log.debug(f"Symbol interval data for symbol: {trading_symbol} = "
                      f"{symbol_interval_data}")

    if symbol_interval_data is None:
        default_log.debug(f"Ticker data not found for symbol={trading_symbol} and time_frame={time_frame}")
        symbols_interval_data[trading_symbol] = {time_frame: []}
        symbols_interval_data[trading_symbol][time_frame] = []
        return []

    interval_data = symbol_interval_data.get(time_frame, None)
    if interval_data is None:
        symbols_interval_data[trading_symbol][time_frame] = []
        return []

    default_log.debug(f"interval_data for symbol={trading_symbol} and timeframe={time_frame}: {interval_data}")
    return interval_data


# This function returns candlestick data
# def get_candlestick_data_using_ticker(
#         interval: str,
#         symbol: str
# ):
#     global symbols_interval_data
#     global subscribed_tokens
#     global websocket_obj
#
#     token = instrument_tokens_map.get(symbol, None)
#     # exchange = "NFO" if symbol in indices_list else "NSE"
#     exchange = "NFO"
#     if token is None:
#         token = get_instrument_token_for_symbol(symbol, exchange)
#         default_log.debug(f"instrument token received for symbol={symbol} and exchange={exchange}: "
#                           f"{token}")
#
#     # Check if symbol is subscribed
#     if token not in subscribed_tokens:
#         default_log.debug(f"Subscribing token={token} of symbol={symbol}")
#         websocket_obj.subscribe([token])
#         websocket_obj.set_mode(websocket_obj.MODE_FULL, [token])
#         subscribed_tokens.append(token)
#         symbols_interval_data[symbol] = {interval: []}
#         symbols_interval_data[symbol][interval] = []
#         return []
#
#     symbol_intervals_data = symbols_interval_data.get(symbol)
#     if symbol_intervals_data is None:
#         default_log.debug(f"Ticker data not found for symbol={symbol} and interval={interval}")
#         return []
#
#     interval_data = symbol_intervals_data.get(interval, [])
#
#     return interval_data


def start_kite_ticker():
    # Keep the program running
    # Assign the callbacks.
    # Initialise
    zerodha_access_token = zo.get_access_token()
    default_log.debug(f"inside start_kite_ticker with access_token={zerodha_access_token}")
    kws = KiteTicker(zerodha_api_key, zerodha_access_token)

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close

    # Infinite loop on the main thread. Nothing after this will run.
    # You have to use the pre-defined callbacks to manage subscriptions.
    kws.connect(threaded=True)

    time.sleep(2)  # sleep for 2 seconds till kite ticker is started and authenticated
    # Restart subscribing for realtime data
    threading.Thread(target=restart_subscribing_for_realtime_zerodha_ticks).start()


# if __name__ == "__main__":
    # Initialise
    # kws = KiteTicker(zerodha_api_key, zerodha_access_token)

    # Keep the program running
    # Assign the callbacks.
    # kws.on_ticks = on_ticks
    # kws.on_connect = on_connect
    # kws.on_close = on_close
    # kws.on

    # Infinite loop on the main thread. Nothing after this will run.
    # You have to use the pre-defined callbacks to manage subscriptions.
    # kws.connect(threaded=False)

    # get_candlestick_data_using_ticker('1', 'WIPRO')
