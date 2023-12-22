import threading
import logging

from copy import deepcopy
import pandas as pd
import time

from truedata_ws.websocket import TD

from config import default_log, sandbox_mode, realtime_port, truedata_username, \
    truedata_password

symbol_ticks = dict()
symbols_interval_data = dict()

symbols = []

counter = 0
dataframe = pd.DataFrame()
td_app_live = None
td_app_hist = None


def start_truedata_server():
    global symbols
    global dataframe
    global td_app_live

    # td_app_live = TD(truedata_username, truedata_password, live_port=realtime_port, historical_api=False,
    #                  log_level=logging.DEBUG, log_format="%(message)s")

    if sandbox_mode:
        default_log.debug(f"Starting server")
        # Load the csv dataframe
        csv_filename = 'AXISBANK_ticks.csv'

        dataframe = pd.read_csv(csv_filename, index_col=False)

        # Sort it by timestamp column
        dataframe['timestamp'] = pd.to_datetime(dataframe['timestamp'])
        dataframe.sort_values(by='timestamp', inplace=True)

        provide_thread = threading.Thread(target=provide_tick_data, args=())
        provide_thread.start()
    else:
        default_log.debug("inside start_truedata_server")

        default_log.debug('Starting Real Time Feed.... ')
        default_log.debug(f'Port > {realtime_port}')

        req_ids = td_app_live.start_live_data(symbols)
        live_data_objs = {}

        time.sleep(1)

        for req_id in req_ids:
            live_data_objs[req_id] = deepcopy(td_app_live.live_data[req_id])
            default_log.debug(f'touchlinedata -> {td_app_live.touchline_data[req_id]}')


def provide_tick_data():
    global counter
    global dataframe

    while True:
        selected_data = dataframe.iloc[counter]
        tick_data = {
            'symbol': 'AXISBANK',
            'timestamp': selected_data["timestamp"],
            'ltp': selected_data["ltp"],
            'volume': selected_data["volume"]
        }

        mytrade_callback_sandbox(tick_data)
        counter += 1
        time.sleep(1)


def process_symbol_ticks(symbol, time_frame):
    global symbol_ticks
    global symbols_interval_data

    df_cols = ["Timestamp", "Symbol", "LTP"]

    default_log.debug(f"inside process_symbol_ticks with symbol={symbol} and "
                      f"time_frame={time_frame}")

    symbol_tick = symbol_ticks.get(symbol, [])
    interval_in_min = str(time_frame) + 'min'

    data = dict()

    # Loop through the ticks of the symbol
    if sandbox_mode:
        for company_data in symbol_tick:
            symbol = company_data["symbol"]
            ltp = company_data["ltp"]
            timestamp = company_data["timestamp"]

            data[timestamp] = [timestamp, symbol, ltp]
    else:
        for company_data in symbol_tick:
            symbol = company_data.symbol if type(company_data) != dict else company_data["symbol"]
            ltp = company_data.ltp if type(company_data) != dict else company_data["ltp"]
            timestamp = company_data.timestamp if type(company_data) != dict else company_data["timestamp"]

            data[timestamp] = [timestamp, symbol, ltp]

    tick_df = pd.DataFrame(data.values(), columns=df_cols, index=data.keys())

    # default_log.debug(f"Tick DF = {tick_df}")

    # Set the index column to "Timestamp"
    ggframe = tick_df.set_index("Timestamp")

    # Resample the data
    candles_interval_data = ggframe.groupby('Symbol').resample(interval_in_min).agg({'LTP': 'ohlc'}).dropna()

    # Set the columns
    candles_interval_data.columns = ['open', 'high', 'low', 'close']

    # Get the last row
    last_row = candles_interval_data.reset_index().iloc[-1]

    # Extract the relevant values for the columns 'open', 'high', 'low', 'close'
    last_row_json = {
        'timestamp': last_row['Timestamp'],
        'open': last_row['open'],
        'high': last_row['high'],
        'low': last_row['low'],
        'close': last_row['close']
    }

    # Store the json data for the symbol, interval
    json_data_for_symbol_interval = [last_row_json]

    symbols_interval_data[symbol][time_frame] = json_data_for_symbol_interval

    # default_log.debug(f"symbols_interval_data[{symbol}][{time_frame}] = {symbols_interval_data[symbol][time_frame]}")

    # global symbol_ticks
    # global symbols_interval_data
    #
    # default_log.debug(f"inside process_symbol_ticks with symbol={symbol} and "
    #                   f"time_frame={time_frame}")
    #
    # symbol_tick = symbol_ticks.get(symbol, [])
    #
    # dataframe = pd.DataFrame(symbol_tick)
    #
    # # Sort it by date column
    # dataframe['timestamp'] = pd.to_datetime(dataframe['timestamp'])
    # dataframe.sort_values(by='timestamp', inplace=True)
    #
    # # Resample it according to the interval
    # actual_interval = str(time_frame) + 'min'
    #
    # dataframe.set_index('date', inplace=True)
    # dataframe = dataframe.resample(actual_interval).agg(
    #     {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    #
    # # Now convert it into JSON format
    # # Convert DataFrame to JSON format with datetime format
    # json_data = dataframe.reset_index().to_dict(orient='records')
    #
    # interval_map = symbols_interval_data.get(symbol, {})
    # interval_map[time_frame] = [json_data]


def mytrade_callback_sandbox(tick_data):
    global symbol_ticks
    global symbols_interval_data
    default_log.debug(f"Tick > {tick_data}")

    symbol = tick_data["symbol"]
    symbol_tick = symbol_ticks.get(symbol, [])

    # default_log.debug(f"Symbol = {symbol} | symbol_tick = {symbol_tick}")
    symbol_tick.append(tick_data)
    symbol_ticks[symbol] = symbol_tick

    # Get the intervals of symbol
    symbol_intervals = symbols_interval_data.get(symbol, {})

    time_frames = symbol_intervals.keys()
    default_log.debug(f"Timeframes for symbol={symbol}={time_frames}")
    for time_frame in time_frames:
        thread = threading.Thread(target=process_symbol_ticks, args=(symbol, time_frame))
        thread.start()


# TODO: uncomment this when testing using real data
# @td_app_live.trade_callback
def mytrade_callback(tick_data):
    global symbol_ticks
    default_log.debug(f"Tick > {tick_data}")

    symbol = tick_data.symbol
    symbol_tick = symbol_ticks.get(symbol, [])

    # default_log.debug(f"Symbol = {symbol} | symbol_tick = {symbol_tick}")
    symbol_tick.append(tick_data)
    symbol_ticks[symbol] = symbol_tick

    # Get the intervals of symbol
    symbol_intervals = symbols_interval_data.get(symbol, {})

    time_frames = symbol_intervals.keys()
    default_log.debug(f"Timeframes for symbol={symbol}={time_frames}")
    for time_frame in time_frames:
        thread = threading.Thread(target=process_symbol_ticks, args=(symbol, time_frame))
        thread.start()


# @td_app_live.one_min_bar_callback
# def my_onemin_bar(symbol_id, tick_data):
#     global symbol_ticks
#     global symbols_interval_data
#     default_log.debug(f"one min > ", tick_data)
#
#     symbol = tick_data.symbol
#     symbol_tick = symbol_ticks.get(symbol, [])
#     symbol_tick.append({
#         'symbol': tick_data.symbol,
#         'timestamp': tick_data.timestamp,
#         'open': tick_data.open,
#         'high': tick_data.high,
#         'low': tick_data.low,
#         'close': tick_data.close
#     })
#
#     symbol_ticks[symbol] = symbol_tick
#
#     default_log.debug(f"Saving tick data ={symbol_tick} for symbol={symbol}")
#
#     # Get the intervals of symbol
#     symbol_intervals = symbols_interval_data.get(symbol, {})
#
#     time_frames = symbol_intervals.keys()
#     for time_frame in time_frames:
#         thread = threading.Thread(target=process_symbol_ticks, args=(symbol, time_frame))
#         thread.start()


# @td_app_live.five_min_bar_callback
# def my_five_min_bar(symbol_id, tick_data):
#     default_log.debug("five min > ", tick_data)


def get_truedata_historical_data(
        trading_symbol: str,
        time_frame: int = None,
):
    global symbols
    global symbol_ticks
    global symbols_interval_data
    global td_app_live

    default_log.debug(f"inside get_historical_data with trading_symbol={trading_symbol} and "
                      f"time_frame={time_frame}")

    if trading_symbol not in symbols:
        symbols.append(trading_symbol)

        if not sandbox_mode:
            td_app_live.start_live_data(symbols)
            # Add extra n ticks to the symbol_ticks
            symbol_initial_ticks = get_extra_ticks_for_symbol(trading_symbol, time_frame)
            default_log.debug(f"Adding initial ticks for symbol={trading_symbol}: {symbol_initial_ticks}")
            symbol_ticks[trading_symbol] = symbol_initial_ticks

        symbols_interval_data[trading_symbol] = {time_frame: []}
        symbols_interval_data[trading_symbol][time_frame] = []
        default_log.debug(f"[NEW] Symbol interval data: {symbols_interval_data}")
        return []

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
    # global symbol_ticks
    # default_log.debug(f"inside get_historical_data with trading_symbol={trading_symbol} and "
    #                   f"time_frame={time_frame}")
    #
    # hist_data = symbol_ticks.get(trading_symbol, [])
    # default_log.debug(f"historical data sent for symbol={trading_symbol} and time_frame={time_frame}: "
    #                   f"{hist_data}")
    #
    # return hist_data


def get_extra_ticks_for_symbol(symbol: str, time_frame: int):
    global td_app_hist

    if td_app_hist is None:
        td_app_hist = TD(truedata_username, truedata_password, live_port=None, historical_api=True,
                         log_level=logging.DEBUG, log_format="%(message)s")

    default_log.debug(f"inside get_extra_ticks_for_symbol for symbol={symbol} and time_frame={time_frame}")
    no_of_ticks_to_get = 60 * time_frame
    tick_data = td_app_hist.get_n_historical_bars(symbol, no_of_bars=no_of_ticks_to_get, bar_size='tick', bidask=True)
    ticks = []
    for tick in tick_data:
        ticks.append(
            {
                'symbol': symbol,
                'ltp': tick["ltp"],
                'timestamp': tick["time"]
            }
        )

    default_log.debug(f"Tick data for symbol={symbol}: {ticks}")
    return ticks


if __name__ == "__main__":
    get_extra_ticks_for_symbol("ICICIBANK", 5)
