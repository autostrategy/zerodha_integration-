import datetime
import json
import threading
from typing import Optional

import pytz
import asyncio
import pandas as pd
from config import default_log, sandbox_mode, indices_list, endpoint, accesskey, NIFTY_INDEX_SYMBOL, \
    BANKNIFTY_INDEX_SYMBOL

import websocket

# to install this library.

try:
    import thread
except ImportError:
    import _thread as thread
import time

symbol_ticks = dict()
symbols_interval_data = dict()

symbols = []

counter = 0
dataframe = pd.DataFrame()

global_feedata_websocket = None
nfo_expiry_date_dict = dict()
subscribed_nfo_symbols = ["NIFTY"]
historical_data = dict()


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
            symbol = company_data["InstrumentIdentifier"]
            symbol = "NIFTY" if symbol == "NIFTY-I" else symbol
            symbol = "BANKNIFTY" if symbol == "BANKNIFTY-I" else symbol

            ltp = company_data["LastTradePrice"]
            epoch_timestamp = company_data.timestamp if type(company_data) != dict else company_data["LastTradeTime"]
            utc_timestamp = datetime.datetime.utcfromtimestamp(epoch_timestamp).replace(
                tzinfo=datetime.timezone.utc)

            # Convert UTC to IST
            ist = pytz.timezone('Asia/Kolkata')
            timestamp_ist = utc_timestamp.astimezone(ist)
            timestamp = timestamp_ist

            data[timestamp] = [timestamp, symbol, ltp]
    else:
        for company_data in symbol_tick:
            symbol = company_data.symbol if type(company_data) != dict else company_data["InstrumentIdentifier"]

            symbol = "NIFTY" if symbol == "NIFTY-I" else symbol
            symbol = "BANKNIFTY" if symbol == "BANKNIFTY-I" else symbol

            ltp = company_data.ltp if type(company_data) != dict else company_data["LastTradePrice"]
            epoch_timestamp = company_data.timestamp if type(company_data) != dict else company_data["LastTradeTime"]
            utc_timestamp = datetime.datetime.utcfromtimestamp(epoch_timestamp).replace(
                tzinfo=datetime.timezone.utc)

            # Convert UTC to IST
            ist = pytz.timezone('Asia/Kolkata')
            timestamp_ist = utc_timestamp.astimezone(ist)
            timestamp = timestamp_ist

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


def tick_callback(tick_data):
    # This is the callback function that will be called when tick data is received
    # You can process the tick data here or perform any other actions
    global symbol_ticks
    global symbols_interval_data

    default_log.debug(f"Tick data received: {tick_data}")

    symbol = tick_data["InstrumentIdentifier"]
    symbol = "NIFTY" if symbol == "NIFTY-I" else symbol
    symbol = "BANKNIFTY" if symbol == "BANKNIFTY-I" else symbol

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


def add_previous_tick_data(symbol: str, previous_tick_data):
    global symbol_ticks
    default_log.debug(f"inside add_previous_tick_data with symbol={symbol} and tick data={previous_tick_data}")

    default_log.debug(f"Adding initial ticks for symbol={symbol}: {previous_tick_data}")
    custom_tick_data = []
    for tick in previous_tick_data:
        prev_data = {
            'InstrumentIdentifier': symbol,
            'LastTradeTime': tick['LastTradeTime'],
            'LastTradePrice': tick['LastTradePrice']
        }

        custom_tick_data.append(prev_data)

    symbol_tick = symbol_ticks.get(symbol, [])
    if len(symbol_tick) > 0:
        # Append data to the start
        symbol_tick[:0] = custom_tick_data
        symbol_ticks[symbol] = symbol_tick
    else:
        symbol_ticks[symbol] = custom_tick_data


def add_historical_data(symbol: str, time_frame: str, hist_data):
    global historical_data
    default_log.debug(f"inside add_historical_data with symbol={symbol} and tick data={hist_data} "
                      f"and time_frame={time_frame}")

    default_log.debug(f"Adding historical_data for symbol={symbol}: {hist_data}")
    custom_historical_data = []
    for hist in hist_data:
        # Convert epochs to datetime object
        epoch_timestamp = hist.timestamp if type(hist) != dict else hist["LastTradeTime"]
        utc_timestamp = datetime.datetime.utcfromtimestamp(epoch_timestamp).replace(
            tzinfo=datetime.timezone.utc)

        # Convert UTC to IST
        ist = pytz.timezone('Asia/Kolkata')
        timestamp_ist = utc_timestamp.astimezone(ist)
        timestamp = timestamp_ist

        prev_data = {
            'InstrumentIdentifier': symbol,
            'timestamp': timestamp,
            'open': hist['Open'],
            'high': hist['High'],
            'low': hist['Low'],
            'close': hist['Close']
        }

        custom_historical_data.append(prev_data)

    key = (symbol, int(time_frame))
    historical_data[key] = custom_historical_data


async def SubscribeRealTimeData(symbol: str):
    global global_feedata_websocket

    ExchangeName = "NSE" if symbol not in indices_list else "NFO"
    InstIdentifier = "NIFTY-I" if symbol == "NIFTY" else symbol
    InstIdentifier = "BANKNIFTY-I" if symbol == "BANKNIFTY" else InstIdentifier
    Unsubscribe = "false"
    strMessage = '{"MessageType":"SubscribeRealtime","Exchange":"' + ExchangeName + '","Unsubscribe":"' + Unsubscribe + '","InstrumentIdentifier":"' + InstIdentifier + '"}'
    await global_feedata_websocket.send(strMessage)
    print("Message sent : " + strMessage)


def run_subscribe_realtime_in_thread(symbol):
    # Create an event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the asynchronous function
    loop.run_until_complete(SubscribeRealTimeData(symbol))


# Function to convert date strings to datetime objects
def parse_date(date_str):
    return datetime.datetime.strptime(date_str, '%d%b%Y')


def Authenticate(ws):
    print("Authenticating...")
    ws.send('{"MessageType":"Authenticate","Password":"' + accesskey + '"}')


def SubscribeRealtime(ws, instrument_identifier: str):
    default_log.debug(f"inside SubscribeRealtime with instrument_identifier={instrument_identifier}")

    ExchangeName = "NSE" if instrument_identifier not in indices_list else "NFO"
    # InstIdentifier = "NIFTY-I" if instrument_identifier == "NIFTY" else instrument_identifier

    InstIdentifier = "NIFTY-I" if instrument_identifier == "NIFTY" else instrument_identifier
    InstIdentifier = "BANKNIFTY-I" if instrument_identifier == "BANKNIFTY" else InstIdentifier

    Unsubscribe = "false"  # GFDL : To stop data subscription for this symbol, send this value as "true"

    strMessage = '{"MessageType":"SubscribeRealtime","Exchange":"' + ExchangeName + '","Unsubscribe":"' + Unsubscribe + '","InstrumentIdentifier":"' + InstIdentifier + '"}'
    default_log.debug('Message : ' + strMessage)
    ws.send(strMessage)


def GetHistory(
        ws,
        instrument_identifier: str,
        from_time_in_epochs: str = None,
        to_time_in_epochs: str = None,
        time_frame: str = None,
        periodicity: str = "MINUTE"
):
    default_log.debug(f"inside GetHistory function with instrument_identifier={instrument_identifier} and "
                      f"from_time_in_epochs={from_time_in_epochs}, to_time_in_epochs={to_time_in_epochs}, "
                      f"time_frame={time_frame} and periodicity={periodicity}")

    ExchangeName = "NSE" if instrument_identifier not in indices_list else "NFO"
    # InstIdentifier = "NIFTY-I" if instrument_identifier == "NIFTY" else instrument_identifier

    InstIdentifier = "NIFTY-I" if instrument_identifier == "NIFTY" else instrument_identifier
    InstIdentifier = "BANKNIFTY-I" if instrument_identifier == "BANKNIFTY" else InstIdentifier

    Periodicity = periodicity
    Period = time_frame if time_frame is not None else "0"

    # current_time = datetime.datetime.now()
    # to_time_in_epochs = str(int(current_time.timestamp()))
    user_tag = f"{Periodicity},{time_frame}"

    from_time_string = f'"From":{from_time_in_epochs}'
    to_time_string = f'"To":{to_time_in_epochs}'

    isShortIdentifier = "false" if instrument_identifier in indices_list else "true"
    # strMessage = '{"MessageType":"GetHistory","Period":"' + Period + '","UserTag":"' + user_tag + '","From":"' + from_time_in_epochs + '","To": "' + to_time_in_epochs + '","Exchange":"' + ExchangeName + '","InstrumentIdentifier":"' + InstIdentifier + '","Periodicity":"' + Periodicity + '","isShortIdentifier":"' + isShortIdentifier + '"}'
    # strMessage = '{"MessageType":"GetHistory","From":"' + from_time_in_epochs + '","Exchange":"' + ExchangeName + '","InstrumentIdentifier":"' + InstIdentifier + '","Periodicity":"' + Periodicity + '","isShortIdentifier":"' + isShortIdentifier + '"}'

    if periodicity == "MINUTE":
        strMessage = '{"MessageType":"GetHistory","Max":"10","Period":"' + str(Period) + '","UserTag":"' + str(user_tag) + '","Exchange":"' + str(ExchangeName) + '","InstrumentIdentifier":"' + str(InstIdentifier) + '","Periodicity":"' + str(Periodicity) + '","isShortIdentifier":"' + str(isShortIdentifier) + '"'
    else:
        strMessage = '{"MessageType":"GetHistory","UserTag":"' + str(
            user_tag) + '","Exchange":"' + str(ExchangeName) + '","InstrumentIdentifier":"' + str(
            InstIdentifier) + '","Periodicity":"' + str(Periodicity) + '","isShortIdentifier":"' + str(
            isShortIdentifier) + '"'

    # Adding from and to time
    if periodicity == "MINUTE":
        strMessage += f',{from_time_string},{to_time_string}' + "}"
    else:
        strMessage += f',{from_time_string}' + "}"

    default_log.debug(f'Message : {strMessage}')
    ws.send(strMessage)


def GetExpiryDates(ws, index_symbol: str):
    default_log.debug(f"inside GetExpiryDates with index_symbol={index_symbol}")
    ExchangeName = "NFO"
    strMessage = '{"MessageType":"GetExpiryDates","Product":"' + index_symbol + '", "Exchange":"' + ExchangeName + '"}'
    ws.send(strMessage)


def on_message(ws, message):
    global nfo_expiry_date_dict
    default_log.debug("Response : " + message)
    # Authenticate : {"Complete":true,"Message":"Welcome!","MessageType":"AuthenticateResult"}
    allures = message.split(',')
    strComplete = allures[0].split(':')
    result = str(strComplete[1])
    if result == "true":
        print('AUTHENTICATED!!!')
    else:
        data = json.loads(message)

        # For Previous Tick Data
        if "Request" in data.keys():
            if "MessageType" in data["Request"].keys():
                message_type = data["Request"]["MessageType"]
                default_log.debug(f"MessageType: {message_type}")
                if message_type == "GetExpiryDates":

                    default_log.debug(f"Get Expiry Dates data received: {data}")
                    index_symbol = data["Request"]["Product"]

                    # Get the current date and the next Sunday
                    today = datetime.datetime.now()
                    next_sunday = today + datetime.timedelta(days=(6 - today.weekday()) % 7)
                    default_log.debug(f"Next Sunday Date: {next_sunday}")

                    # Find the closest date after the next Sunday  # Entry BUY: CE SELL: PE NIFTY1950023DECCE
                    # monday => next week sunday ke badh
                    # Find the closest date to the next Sunday

                    # Next Sunday Flow
                    closest_date = min(
                        (parse_date(item["Value"]) for item in data["Result"] if parse_date(item["Value"]) > next_sunday),
                        key=lambda x: abs(x - next_sunday),
                        default=None
                    )

                    # Current Week Flow
                    # closest_date = min(
                    #     (parse_date(item["Value"]) for item in data["Result"] if today < parse_date(item["Value"]) < next_sunday),
                    #     key=lambda x: abs(x - next_sunday),
                    #     default=None
                    # )

                    if index_symbol == "NIFTY":
                        # check if next THURSDAY date from the closest date comes in the next month or not
                        # if true then instead of storing expiry date as DATE+MONTH store it as MONTH
                        next_week_date = closest_date + datetime.timedelta(days=7)

                        if next_week_date.month != today.month:
                            default_log.debug(f"The next week date ({next_week_date}) is in the next month as of the "
                                              f"closest date ({closest_date}) so storing expiry_date as "
                                              f"MONTH without the date for index_symbol={index_symbol}")

                            # expiry_date = str(closest_date.strftime('%b')).upper()
                            expiry_date = NIFTY_INDEX_SYMBOL

                        else:
                            default_log.debug(f"The next week date ({next_week_date}) is in the same month as of the "
                                              f"closest date ({closest_date}) so storing expiry_date as "
                                              f"DATE+MONTH for index_symbol={index_symbol}")

                            expiry_date = str(closest_date.strftime('%d%b')).upper()

                            digits_list = [character for character in expiry_date if character.isnumeric()]
                            digit_string = ''
                            for digit in digits_list:
                                digit_string += digit
                            default_log.debug(f"Digit formed: {digit_string} from {expiry_date}")

                            expiry_date = NIFTY_INDEX_SYMBOL[:3] + digit_string

                        default_log.debug(f"NFO expiry date for {index_symbol} is {expiry_date}")

                    elif index_symbol == "BANKNIFTY":
                        # check if next WEDNESDAY/date from the closest date comes in the next month or not
                        # if true then instead of storing expiry date as DATE+MONTH store it as MONTH
                        next_week_date = closest_date + datetime.timedelta(days=7)

                        if next_week_date.month != today.month:
                            default_log.debug(f"The next week date ({next_week_date}) is in the next month as of the "
                                              f"closest date ({closest_date}) so storing expiry_date as "
                                              f"MONTH without the date for index_symbol={index_symbol}")

                            # expiry_date = str(closest_date.strftime('%b')).upper()
                            expiry_date = BANKNIFTY_INDEX_SYMBOL

                        else:
                            default_log.debug(f"The next week date ({next_week_date}) is in the same month as of the "
                                              f"closest date ({closest_date}) so storing expiry_date as "
                                              f"DATE+MONTH for index_symbol={index_symbol}")

                            expiry_date = str(closest_date.strftime('%d%b')).upper()

                            digits_list = [character for character in expiry_date if character.isnumeric()]
                            digit_string = ''
                            for digit in digits_list:
                                digit_string += digit
                            default_log.debug(f"Digit formed: {digit_string} from {expiry_date}")

                            expiry_date = NIFTY_INDEX_SYMBOL[:3] + digit_string

                        default_log.debug(f"NFO expiry date for {index_symbol} is {expiry_date}")
                    else:
                        expiry_date = str(closest_date.strftime('%d%b')).upper()
                        default_log.debug(f"NFO expiry date for {index_symbol} is {expiry_date}")

                    nfo_expiry_date_dict[index_symbol] = expiry_date

                    # Print the closest date
                    default_log.debug(f"NFO expiry date={nfo_expiry_date_dict.get(index_symbol) if closest_date else 'No date found'}")

                elif message_type == "GetHistory":
                    if "UserTag" in data["Request"].keys():
                        periodicity, time_frame = data["Request"]["UserTag"].split(",")

                        if periodicity == "MINUTE":  # for historical data
                            instrument_symbol = data["Request"]["InstrumentIdentifier"]

                            if instrument_symbol.find("-I") != -1:
                                instrument_symbol = instrument_symbol.split('-')[0]

                            time_frame = int(time_frame)
                            if len(data['Result']) > 0:
                                # Last data is initial data of GLOBAL DATA FEED i.e. from_time
                                add_historical_data(
                                    symbol=instrument_symbol,
                                    time_frame=str(time_frame),
                                    hist_data=[data["Result"][0]]
                                )

                        elif periodicity == "TICK":
                            InstIdentifier = data['Request']["InstrumentIdentifier"]
                            default_log.debug(f"Previous Tick data for symbol={InstIdentifier} is: {data['Result']}")
                            ticks = data["Result"]
                            if len(ticks) > 0:
                                no_of_ticks_to_get = 2 * (int(time_frame) * 60)
                                # if len(ticks) <= no_of_ticks_to_get:
                                #     default_log.debug(f"Getting previous {no_of_ticks_to_get} ticks for "
                                #                       f"symbol={InstIdentifier}: {data['Result'][:no_of_ticks_to_get]}")
                                #     add_previous_tick_data(symbol=InstIdentifier,
                                #                            previous_tick_data=data['Result'][:no_of_ticks_to_get])
                                # else:
                                default_log.debug(f"Getting previous ALL ticks for "
                                                  f"symbol={InstIdentifier}: {data['Result']}")
                                add_previous_tick_data(symbol=InstIdentifier,
                                                       previous_tick_data=data['Result'])

                # elif message_type == "HistoryTickResult":
                #
                #     if "UserTag" in data["Request"].keys():
                #         periodicity, time_frame = data["Request"]["UserTag"].split(",")
                #
                #         InstIdentifier = data['Request']["InstrumentIdentifier"]
                #         default_log.debug(f"Previous Tick data for symbol={InstIdentifier} is: {data['Result']}")
                #         ticks = data["Result"]
                #         if len(ticks) > 0:
                #             no_of_ticks_to_get = 2 * (int(time_frame) * 60)
                #             if len(ticks) <= no_of_ticks_to_get:
                #                 default_log.debug(f"Getting previous {no_of_ticks_to_get} ticks for "
                #                                   f"symbol={InstIdentifier}: {data['Result'][:no_of_ticks_to_get]}")
                #                 add_previous_tick_data(symbol=InstIdentifier,
                #                                        previous_tick_data=data['Result'][:no_of_ticks_to_get])

        elif "LastTradeTime" in data.keys():
            default_log.debug(f"Data: {data}")
            tick_callback(data)


def on_error(ws, error):
    default_log.debug("Error")


def on_close(ws):
    default_log.debug("Reconnecting...")
    websocket.setdefaulttimeout(30)
    ws.connect(endpoint)


def on_open(ws):
    default_log.debug("Connected...")

    def run(*args):
        time.sleep(1)
        Authenticate(ws)

    thread.start_new_thread(run, ())


def initialize_websocket_server():
    global global_feedata_websocket
    default_log.debug(f"inside initialize_websocket_server")
    # websocket.enableTrace(True)
    ws = websocket.WebSocketApp(endpoint,
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    global_feedata_websocket = ws
    ws.run_forever()


def start_global_data_feed_server():
    # Start the initial subscription
    global symbols
    global global_feedata_websocket

    websocket_thread = threading.Thread(target=initialize_websocket_server)
    websocket_thread.start()

    time.sleep(5)  # sleep for 5 seconds till global data server is started and authenticated
    GetExpiryDates(ws=global_feedata_websocket, index_symbol="NIFTY")


def get_nfo_closest_expiry_date(index_symbol: str):
    global nfo_expiry_date_dict

    default_log.debug(f"inside get_nfo_closest_expiry_date with index_symbol={index_symbol} and "
                      f"nfo_expiry_date={nfo_expiry_date_dict}")
    default_log.debug(f"Returning Expiry Date={nfo_expiry_date_dict.get(index_symbol)} for index_symbol={index_symbol}")
    return nfo_expiry_date_dict.get(index_symbol)


def get_global_data_feed_historical_data(
        trading_symbol: str,
        time_frame: int = None,
        from_time: Optional[datetime.datetime] = None,
        to_time: Optional[datetime.datetime] = None
):
    global symbols
    global symbol_ticks
    global symbols_interval_data
    global global_feedata_websocket
    global subscribed_nfo_symbols
    global historical_data

    default_log.debug(f"inside get_global_data_feed_historical_data with trading_symbol={trading_symbol} and "
                      f"time_frame={time_frame}, from_time={from_time} and to_time={to_time}")

    if trading_symbol in indices_list:
        if trading_symbol not in subscribed_nfo_symbols:
            subscribed_nfo_symbols.append(trading_symbol)
            GetExpiryDates(ws=global_feedata_websocket, index_symbol=trading_symbol)
            default_log.debug(
                f"Fetching Expiry dates for index_symbol={trading_symbol} from Global Feed")

    if from_time is not None:
        key = (trading_symbol, int(time_frame))

        hist_data = historical_data.get(key, [])
        if len(hist_data) > 0:
            # Check if hist_data timestamp matched the to_time timestamp
            hist_data_timestamp = hist_data[0]['timestamp']
            if hist_data_timestamp == to_time.astimezone(pytz.timezone("Asia/Kolkata")):
                default_log.debug(f"Returning historical data for symbol={trading_symbol} and time_frame={time_frame} "
                                  f"where from_time={from_time} and to_time={to_time}. Data returned: {hist_data}")
                return hist_data

        # Get Historical Data using From Time and To Time
        from_time_in_epochs = str(int(from_time.timestamp()))
        to_time_in_epochs = str(int(to_time.timestamp()))
        GetHistory(
            ws=global_feedata_websocket,
            instrument_identifier=trading_symbol,
            time_frame=time_frame,
            from_time_in_epochs=from_time_in_epochs,
            to_time_in_epochs=to_time_in_epochs
        )

        # Wait till data is fetched and stored in the global historical_data variable
        # key = (trading_symbol, int(time_frame))

        return []

        # Get Historical Data using From Time and To Time
        # from_time_in_epochs = str(int(from_time.timestamp()))
        # to_time_in_epochs = str(int(to_time.timestamp()))
        # GetHistory(
        #     ws=global_feedata_websocket,
        #     instrument_identifier=trading_symbol,
        #     time_frame=time_frame,
        #     from_time_in_epochs=from_time_in_epochs,
        #     to_time_in_epochs=to_time_in_epochs
        # )
        #
        # # Wait till data is fetched and stored in the global historical_data variable
        # key = (trading_symbol, int(time_frame))
        # hist_data = historical_data.get(key, [])

        # if trading_symbol not in symbols:
        #     symbols.append(trading_symbol)
        #
        #     SubscribeRealtime(ws=global_feedata_websocket, instrument_identifier=trading_symbol)
        #     default_log.debug(f"Started subscribing to Global Feed about symbol={trading_symbol}")
        #
        #     symbols_interval_data[trading_symbol] = {time_frame: []}
        #     symbols_interval_data[trading_symbol][time_frame] = []
        #     default_log.debug(f"[NEW] Symbol interval data: {symbols_interval_data}")
        #
        # return hist_data

    # Get Tick Data
    if trading_symbol not in symbols:
        symbols.append(trading_symbol)

        if trading_symbol not in subscribed_nfo_symbols:
            GetExpiryDates(ws=global_feedata_websocket, index_symbol=trading_symbol)
            default_log.debug(f"Fetching Expiry dates for index_symbol={trading_symbol} to Global Feed about symbol={trading_symbol}")
        # TODO: uncomment while testing
        # if not sandbox_mode:
        # Subscribe to RealTime Data
        SubscribeRealtime(ws=global_feedata_websocket, instrument_identifier=trading_symbol)
        default_log.debug(f"Started subscribing to Global Feed about symbol={trading_symbol}")

        # LOGIC for getting previous ticks
        # Add previous ticks of the trading_symbol
        # Calculate the from_time in epochs

        seconds = int((2 * 60) * time_frame)
        start_time = datetime.datetime.now() - datetime.timedelta(seconds=seconds)
        start_time = start_time.astimezone(pytz.timezone("Asia/Kolkata"))
        default_log.debug(f"Start time for symbol={trading_symbol} and timeframe={time_frame} for getting"
                          f"previous tick data is: {start_time}")

        from_time_in_epochs = str(int(start_time.timestamp()))

        GetHistory(
            ws=global_feedata_websocket,
            instrument_identifier=trading_symbol,
            time_frame=time_frame,
            from_time_in_epochs=from_time_in_epochs,
            periodicity="TICK"
        )
        # threading.Thread(target=run_subscribe_realtime_in_thread, args=(trading_symbol,)).start()
        # default_log.debug(f"Started subscribing to Global Feed about symbol={trading_symbol}")
        # Add extra n ticks to the symbol_ticks
        # run_add_previous_tick_data_of_symbol(trading_symbol)

        # Todo: Uncomment
        # threading.Thread(target=run_subscribe_realtime_in_thread, args=(trading_symbol,)).start()
        # default_log.debug(f"Started subscribing to Global Feed about symbol={trading_symbol}")

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


if __name__ == "__main__":
    # start_global_data_feed_server()
    # check_flow("TCS")
    websocket_thread = threading.Thread(target=initialize_websocket_server)
    websocket_thread.start()

    time.sleep(5)  # sleep for 5 seconds
    from_time = datetime.datetime.now() - datetime.timedelta(minutes=10)
    default_log.debug(f"From time is: {from_time}")
    from_time = str(int(from_time.timestamp()))
    GetHistory(ws=global_feedata_websocket, instrument_identifier="TCS", from_time_in_epochs=from_time)

