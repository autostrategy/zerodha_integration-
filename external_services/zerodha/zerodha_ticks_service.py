#!python
import time
# import logging

import pandas as pd
import threading
from kiteconnect import KiteTicker
from config import zerodha_api_key, zerodha_access_token, default_log, instrument_tokens_map, symbol_tokens_map

# logging.basicConfig(level=logging.DEBUG)

# Initialise
kws = KiteTicker(zerodha_api_key, zerodha_access_token)

# columns in data frame
df_cols = ["date", "Token", "LTP"]

symbol_ticks = dict()
symbols_interval_data = dict()

websocket_obj = None
subscribed_tokens = []


def on_ticks(ws, ticks):
    global symbol_ticks

    default_log.debug(f"inside on_ticks with ticks: {ticks}")
    for company_data in ticks:
        token = company_data["instrument_token"]

        # Get the existing tick data
        symbol_ticks_data = symbol_ticks.get(token, [])

        # Add the new tick data to the existing tick data for that symbol
        symbol_ticks_data.append(company_data)
        symbol_ticks[token] = symbol_ticks_data

    for token in subscribed_tokens:
        symbol = symbol_tokens_map[token]

        # Get all intervals of token
        symbol_interval_data = symbols_interval_data.get(symbol, None)

        for interval in symbol_interval_data.keys():
            interval_data = symbols_interval_data.get(interval, [])

            if len(interval_data) == 0:
                thread = threading.Thread(target=prepare_interval_data_for_symbol, args=(interval, symbol))
                thread.start()


def on_connect(ws, response):
    # Callback on successful connect.
    # Store the websocket token to be using to subscribe globally
    global websocket_obj
    websocket_obj = ws


def on_close(ws, code, reason):
    # On connection close stop the event loop.
    # Reconnection will not happen after executing `ws.stop()`
    default_log.debug(f"Kite Ticker Stopped due to: {reason}")
    ws.stop()


def prepare_interval_data_for_symbol(interval: str, instrument_symbol: str):
    default_log.debug(f"inside prepare_interval_data_from_ticks with interval={interval} "
                      f"and instrument_symbol={instrument_symbol}")
    global df_cols
    global symbols_interval_data
    global symbol_ticks

    instrument_token = instrument_tokens_map[instrument_symbol]

    ticks = symbol_ticks.get(instrument_token, [])
    data = dict()

    interval_in_min = interval + 'min'

    # Loop through the ticks of the symbol
    for company_data in ticks:
        token = company_data["instrument_token"]
        ltp = company_data["last_price"]
        timestamp = company_data["exchange_timestamp"]

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

    # Get the last row
    last_row = candles_interval_data.iloc[-1]

    default_log.debug(f"Last Row: {last_row}")

    # Extract the relevant values for the columns 'open', 'high', 'low', 'close'
    last_row_json = {
        'date': last_row['date'],
        'open': last_row['open'],
        'high': last_row['high'],
        'low': last_row['low'],
        'close': last_row['close']
    }

    default_log.debug(f"last_row_json: {last_row_json}")

    # Store the json data for the symbol, interval
    json_data_for_symbol_interval = [last_row_json]

    symbols_interval_data[instrument_symbol][interval] = json_data_for_symbol_interval


# This function returns candlestick data
def get_candlestick_data_using_ticker(
        interval: str,
        symbol: str
):
    global symbols_interval_data
    global subscribed_tokens
    global websocket_obj

    token = instrument_tokens_map[symbol]

    # Check if symbol is subscribed
    if token not in subscribed_tokens:
        default_log.debug(f"Subscribing token={token} of symbol={symbol}")
        websocket_obj.subscribe([token])
        websocket_obj.set_mode(websocket_obj.MODE_FULL, [token])
        subscribed_tokens.append(token)
        symbols_interval_data[symbol] = {interval: []}
        symbols_interval_data[symbol][interval] = []
        return []

    symbol_intervals_data = symbols_interval_data.get(symbol)
    if symbol_intervals_data is None:
        default_log.debug(f"Ticker data not found for symbol={symbol} and interval={interval}")
        return []

    interval_data = symbol_intervals_data.get(interval, [])

    return interval_data


def start_kite_ticker():
    # Keep the program running
    # Assign the callbacks.
    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close

    # Infinite loop on the main thread. Nothing after this will run.
    # You have to use the pre-defined callbacks to manage subscriptions.
    kws.connect(threaded=True)


if __name__ == "__main__":
    # Keep the program running
    # Assign the callbacks.
    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close

    # Infinite loop on the main thread. Nothing after this will run.
    # You have to use the pre-defined callbacks to manage subscriptions.
    kws.connect(threaded=True)
