import re
import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pytz
from kiteconnect import KiteConnect

from config import zerodha_api_key, symbol_tokens_map, use_global_feed, \
    zerodha_access_token, zerodha_api_secret
from typing_extensions import Union

from config import default_log, instrument_tokens_map
from data.enums.signal_type import SignalType
import requests

from external_services.global_datafeed.get_data import get_global_data_feed_historical_data, get_use_simulation_status

provide_historical_data = False
provide_minute_data = True
kite_access_token = ""

TOKEN_FILE_PATH = 'access_token.txt'


def get_access_token():
    global kite_access_token
    default_log.debug(f"inside get_access_token")
    try:
        with open(TOKEN_FILE_PATH, 'r') as file:
            access_token = file.read().strip()
            default_log.debug(f"Using the following access_token={access_token}")
            kite_access_token = access_token
    except FileNotFoundError:
        kite_access_token = ""
        return ""


def save_access_token(access_token):
    default_log.debug(f"Saving Access Token ({access_token}) to {TOKEN_FILE_PATH}")
    with open(TOKEN_FILE_PATH, 'w') as file:
        file.write(access_token)

    default_log.debug(f"Saved Access Token ({access_token}) to {TOKEN_FILE_PATH}")


def get_access_token_from_request_token(request_token: str):
    global kite_access_token
    default_log.debug(f"inside get_access_token_from_request_token with request_token={request_token}")

    try:
        kite_connect = KiteConnect(api_key=zerodha_api_key)

        data = kite_connect.generate_session(request_token=request_token, api_secret=zerodha_api_secret)

        default_log.debug(f"Session data retrieved: {data}")
        access_token = data["access_token"]
        default_log.debug(f"Access token retrieved from request_token={request_token} is {access_token} "
                          f"now setting the access token ({access_token}) to kite_access_token global variable")
        kite_access_token = access_token
        save_access_token(access_token)
        return access_token
    except Exception as e:
        default_log.debug(f"An error occurred while getting access token for request_token={request_token}. "
                          f"Error: {e}")
        return None


class KiteSandbox:
    TRANSACTION_TYPE_SELL = 'SELL'
    TRANSACTION_TYPE_BUY = 'BUY'

    PRODUCT_NRML = "Normal"
    ORDER_TYPE_MARKET = "MARKET"
    EXCHANGE_NSE = "NSE"
    EXCHANGE_NFO = "NFO"

    VARIETY_REGULAR = "regular"

    def __init__(self):
        self.url = "http://localhost:3030"

    def place_order(self, variety, **order_params):
        default_log.debug(f"inside place order with variety={variety} and order_params={order_params}")
        order_body = order_params

        place_order_url = self.url + f'/orders/{variety}'

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        response = requests.post(url=place_order_url, json=order_body, headers=headers)

        data = response.json()
        return data['order_id']

    def modify_order(self, variety, **order_params):
        default_log.debug(f"inside modify_order with variety={variety} and order_params={order_params}")
        modify_order_body = order_params

        modify_order_url = self.url + f'/orders/{variety}'

        headers = {
            "Content-Type": "application/json"
        }

        response = requests.put(url=modify_order_url, json=modify_order_body, headers=headers)

        data = response.json()
        return data['order_id']

    def order_history(self, order_id):
        default_log.debug(f"inside order_history with order_id={order_id}")

        order_details_url = self.url + f'/orders/{order_id}'

        response = requests.get(url=order_details_url)

        data = response.json()
        return [data]

    def cancel_order(self, variety, order_id):
        default_log.debug(f"inside cancel_order with order_id={order_id}")

        order_cancel_url = self.url + f'/orders/{variety}/{order_id}'

        response = requests.delete(url=order_cancel_url)

        data = response.json()
        return data["order_id"]

    def extract_minutes_from_string(self, input_string):
        # Using regular expression to find the first sequence of digits
        match = re.search(r'\d+', input_string)

        if match:
            return int(match.group())
        else:
            return 1

    def historical_data(self, instrument_token: int, from_date: datetime, to_date: datetime, interval: str = ""):
        default_log.debug(f"inside historical_data with "
                          f"instrument_token={instrument_token} "
                          f"from_date={from_date} "
                          f"to_date={to_date} "
                          f"interval={interval} ")

        if use_global_feed:
            symbol = symbol_tokens_map.get(instrument_token, None)

            if symbol is None:
                inst_token = str(instrument_token)
                symbol = get_symbol_for_instrument_token(inst_token)
                default_log.debug(f"Symbol Details fetched for instrument_token ({inst_token}) => {symbol}")
            time_frame = extract_integer_from_string(interval)

            hist_data = get_global_data_feed_historical_data(
                            trading_symbol=symbol,
                            time_frame=int(time_frame),
                            from_time=from_date,
                            to_time=to_date
                        )

            default_log.debug(
                f"[LIVE] Gobal Data Feed historical data returned for symbol={symbol} and time_frame={interval} "
                f"from {from_date} to {to_date}: {hist_data}")

            if len(hist_data) == 0:
                default_log.debug(f"data not found on truedata from_date={from_date} and to_date={to_date}")
                return []

            sorted_historical_data = sorted(hist_data, key=lambda x: x['timestamp'])

            return [sorted_historical_data[-1]]

        if provide_minute_data:
            actual_interval = self.extract_minutes_from_string(interval)
            historical_data_url = self.url + f'/get-all-data/{actual_interval}'

            response = requests.get(historical_data_url)

            default_log.debug(f"Historical Data returned: {response.json()}")

            data = response.json()
            for dt in data:
                # Given date and time string
                date_string = dt['date']

                # Convert string to datetime object
                datetime_object = datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S %Z")

                # Set the timezone to Asia/Kolkata
                dt['date'] = datetime_object.astimezone(pytz.timezone("Asia/Kolkata"))
            default_log.debug(f"Returning formatted historical data={data}")
            return data

        if provide_historical_data:

            # Read the CSV File Data
            df = pd.read_csv("external_services/zerodha/INFY.csv")

            # Convert 'date' column to datetime
            df['date'] = pd.to_datetime(df['date']).dt.tz_convert('Asia/Kolkata')

            # Convert from_date and to_date to the same timezone
            from_date = from_date.astimezone(pytz.timezone("Asia/Kolkata"))
            to_date = to_date.astimezone(pytz.timezone("Asia/Kolkata"))

            filtered_df = df.loc[(df['date'] >= from_date) & (df['date'] <= to_date)].reset_index(drop=True).to_dict(
                orient='records')

            return filtered_df

        else:

            try:
                kite = get_official_kite_account_api()

                from_date = from_date.replace(second=0).strftime('%Y-%m-%d %H:%M:%S')
                to_date = to_date.replace(second=0).strftime('%Y-%m-%d %H:%M:%S')

                hist_data = kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=from_date,
                    to_date=to_date,
                    interval=interval
                )

                if len(hist_data) == 0:
                    default_log.debug(f"data not found on zerodha from_date={from_date} and to_date={to_date}")
                    return []

                filtered_data = [data for data in hist_data if
                                 data["date"].replace(second=0).strftime('%Y-%m-%d %H:%M:%S') == from_date]

                if not filtered_data:
                    default_log.debug(f"No data matching the specified from_date={from_date}")
                    return []

                default_log.debug(
                    f"[LIVE] Historical Data retrieved from_date={from_date} and to_data={to_date}: {hist_data}")

                return hist_data
            except Exception as e:
                default_log.debug(
                    f"An error occurred while fetching data from zerodha. Error: {e}")
                return []


def get_zerodha_account_equity(kite: KiteConnect):
    default_log.debug(f"inside get_zerodha_account_equity")
    try:
        kite_account_margins = kite.margins()

        kite_account_equity = kite_account_margins['equity']['available']['live_balance']

        default_log.debug(f"Current Equity: {kite_account_equity}")

        return kite_account_equity
    except Exception as e:
        default_log.debug(f"An error occurred while fetching zerodha account equity. Error: {e}")
        return 0


def store_access_token_of_kiteconnect(access_token: str):
    default_log.debug(f"inside store_access_token_of_kiteconnect with access_token={access_token}")
    global kite_access_token

    save_access_token(access_token)
    kite_access_token = access_token


def check_open_position_status_and_close():
    global kite_access_token
    default_log.debug(f"inside check_open_position_status_and_close")

    # Check if simulation is going on
    # if yes then no need to do anything
    simulation_mode = get_use_simulation_status()

    if simulation_mode:
        default_log.debug(f"As simulation is going on as simulation_mode={simulation_mode} "
                          f"So ignoring checking open positions and closing")
        return

    kite = get_kite_account_api()

    cancel_all_open_orders(kite)

    # Fetch open positions
    positions = kite.positions()['net']

    # Close all open positions
    for position in positions:
        symbol = position['tradingsymbol']
        quantity = position['quantity']
        exchange = position['exchange']

        # Figure out the transaction type by quantity
        if quantity < 0:
            default_log.debug(f"BUYING {-quantity} stocks of {symbol} having exchange={exchange}")
            quantity = -quantity
            transaction_type = "BUY"
        elif quantity > 0:
            default_log.debug(f"SELLING {quantity} stocks of {symbol} having exchange={exchange}")
            quantity = quantity
            transaction_type = "SELL"
        else:
            default_log.debug(f"Not closing position of trading_symbol={symbol} having exchange={exchange}"
                              f"as quantity={quantity}")
            continue

        # Place a market order to buy the entire quantity to close the sell position
        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_NRML,
        )

    kite_access_token = ""
    try:
        default_log.debug(f"Removing access_token.txt file")
        os.remove("access_token.txt")
    except Exception as e:
        default_log.debug(f"An error occurred while removing access_token.txt file. Error: {e}")


def get_instrument_token_for_symbol(symbol: str, exchange: str = "NSE"):
    default_log.debug(f"inside get_instrument_token_for_symbol with symbol={symbol} and "
                      f"exchange={exchange}")

    try:
        file_path = f"instrument_tokens_of_zerodha_{datetime.now().date()}.csv"
        instrument_tokens_df = pd.read_csv(file_path)

        if exchange == "NSE":
            instrument_filtered_by_exchange = instrument_tokens_df[
                (instrument_tokens_df['exchange'] == exchange) & (instrument_tokens_df['segment'] == exchange)]
            instruments_filtered_by_trading_symbol = instrument_filtered_by_exchange[
                instrument_tokens_df['tradingsymbol'] == symbol]

        else:
            instrument_tokens_filtered_by_exchange = instrument_tokens_df[
                (instrument_tokens_df['exchange'] == "NSE") & (instrument_tokens_df['segment'] == "INDICES")]

            if symbol == "NIFTY":
                symbol = "NIFTY 50"
            elif symbol == "BANKNIFTY":
                symbol = "NIFTY BANK"

            instruments_filtered_by_trading_symbol = instrument_tokens_filtered_by_exchange[
                instrument_tokens_filtered_by_exchange['tradingsymbol'].str.contains(symbol)]

        if not instruments_filtered_by_trading_symbol.empty:
            instrument_token = instruments_filtered_by_trading_symbol.iloc[0]['instrument_token']
            default_log.debug(f"Instrument token found for symbol={symbol} and exchange={exchange}: {instrument_token}")
            return int(instrument_token)
        else:
            default_log.debug(f"Instrument token not found for symbol={symbol} and exchange={exchange}")
            return None

    except Exception as e:
        default_log.debug(f"An error occurred while instrument token id for symbol={symbol} and "
                          f"exchange={exchange}. Error: {e}")
        return None


def get_symbol_for_instrument_token(instrument_token: str):
    default_log.debug(f"inside get_symbol_for_instrument_token with instrument_token={instrument_token}")
    instrument_token = int(instrument_token)
    try:
        file_path = f"instrument_tokens_of_zerodha_{datetime.now().date()}.csv"
        instrument_tokens_df = pd.read_csv(file_path)

        row_matching_instrument_token_df = instrument_tokens_df[
            (instrument_tokens_df['instrument_token'] == instrument_token)]

        if not row_matching_instrument_token_df.empty:
            trading_symbol = row_matching_instrument_token_df.iloc[0]['tradingsymbol']
            default_log.debug(f"Trading Symbol found for instrument_token={instrument_token}: {trading_symbol}")
            return str(trading_symbol)
        else:
            default_log.debug(f"Trading Symbol not found for instrument_token={instrument_token}")
            return None

    except Exception as e:
        default_log.debug(f"An error occurred while fetching trading_symbol for instrument_token={instrument_token}. "
                          f"Error: {e}")
        return None


def round_value(symbol: str, price, exchange: str = "NSE"):
    instrument_token = instrument_tokens_map.get(symbol, None)
    if instrument_token is None:
        # Get the instrument token for the instrument_tokens csv file
        instrument_token = get_instrument_token_for_symbol(symbol=symbol, exchange=exchange)
        default_log.debug(f"instrument token received for symbol={symbol} and exchange={exchange}: {instrument_token}")

    default_log.debug(f'inside round_value with Price {price} '
                      f'and instrument_token={instrument_token} and symbol={symbol}')

    # Get the mintick of instrument_token
    file_path = f"instrument_tokens_of_zerodha_{datetime.now().date()}.csv"

    # Read the CSV file
    df = pd.read_csv(file_path)

    # Filter the data based on the tradingsymbol and exchange
    filtered_row = df[(df['tradingsymbol'] == symbol) & (df['exchange'] == exchange)]

    # Check if a match is found
    if not filtered_row.empty:
        # Extract the tick_size from the matched row
        tick_size = filtered_row['tick_size'].values[0]
        default_log.debug(f'Tick size for trading_symbol={symbol} and exchange={exchange}: {tick_size}')

        mintick = tick_size
        default_log.debug(f'Tick size for {symbol} is: {mintick}')
    else:
        default_log.debug(
            f'No match found for instrument_token={instrument_token}'
            f'and symbol={symbol} and exchange={exchange}. Cannot determine tick '
            f'size.')
        return None

    price = round(price, 2)
    # Check if price is divisible by tick size
    if price % float(mintick) == 0:
        default_log.debug(f"Price ({price}) is divisible by tick size ({mintick})")
        default_log.debug(f'Return  price {price} according to tick size {mintick} for '
                          f'instrument_token={instrument_token} and symbol={symbol}')
        return round(price, 2)

    s = '{:f}'.format(mintick)
    if not '.' in s:
        return round(price, 2)
    min_len = len(s) - s.index('.') - 1
    price = round(price, min_len)

    min_dec = s.split('.')
    remainder = price % float(str("0.") + str(min_dec[1]))
    if remainder != 0:
        price = price - remainder
    default_log.debug(f'Return  price {price} according to tick size {mintick} for '
                      f'instrument_token={instrument_token} and symbol={symbol}')
    return price


def get_indices_data():
    try:
        file_path = f"instrument_tokens_of_zerodha_{datetime.now().date()}.csv"

        kite = get_official_kite_account_api()

        # Check if the file already exists
        if os.path.exists(file_path):
            default_log.debug("Instrument data file already exists. Skipping data retrieval.")
            return

        # Get instruments
        kite_instruments = kite.instruments()
        # default_log.debug(f"Kite Instruments: {kite_instruments}")

        df = pd.DataFrame(kite_instruments)

        df.to_csv(file_path)
        default_log.debug(f"Downloaded Instrument data file: {file_path}")
    except Exception as e:
        default_log.debug(f"Error occurred while getting instruments token data from zerodha: {e}")


def extract_alpha_characters(symbol):
    result = ''.join(char for char in symbol if char.isalpha())
    return result


def extract_integer_from_string(input_string):
    # Use regular expression to find the first sequence of digits in the string
    match = re.search(r'\d+', input_string)

    # Check if a match is found
    if match:
        # Convert the matched string to an integer
        result = int(match.group())
        return result
    else:
        # If no match is found, you may want to handle it accordingly
        return 1


def get_indices_symbol_for_trade(trading_symbol: str, price: float, transaction_type: SignalType):
    default_log.debug(f"inside get_indices_symbol_for_trade with "
                      f"trading_symbol={trading_symbol} "
                      f"price={price} "
                      f"transaction_type={transaction_type} ")

    clean_symbol = extract_alpha_characters(trading_symbol)

    default_log.debug(f"Clean symbol of trading_symbol={trading_symbol} is {clean_symbol}")

    # Get the nearest Thursday date in the current week
    today = datetime.now()

    if today.weekday() == 3:  # If today is Thursday, get next Thursday
        days_until_thursday = 7
    else:
        days_until_thursday = (3 - today.weekday() + 7) % 7

    nearest_thursday = today + timedelta(days=days_until_thursday)
    #
    # # Get the date of the previous Thursday
    # days_since_previous_thursday = (today.weekday() - 3 + 7) % 7
    # previous_thursday = today - timedelta(days=days_since_previous_thursday)
    #
    # # Calculate the days since the Thursday before that
    # days_since_two_thursdays_ago = days_since_previous_thursday + 7
    #
    # # Calculate the date of the Thursday before that
    # two_thursdays_ago = today - timedelta(days=days_since_two_thursdays_ago)

    # For price
    # Get the nearest 50 value for the current_candle_price (both above and below)
    if trading_symbol == "NIFTY":
        nearest_50_below = int(price // 50) * 50
        nearest_50_above = nearest_50_below + 50

        # Choose the nearest 50 value based on proximity
        if abs(price - nearest_50_below) < abs(price - nearest_50_above):
            nearest_price_value = nearest_50_below
        else:
            nearest_price_value = nearest_50_above
    else:  # if it is BANKNIFTY
        nearest_500_below = int(price // 500) * 500
        nearest_500_above = nearest_500_below + 500

        # Choose the nearest 50 value based on proximity
        if abs(price - nearest_500_below) < abs(price - nearest_500_above):
            nearest_price_value = nearest_500_below
        else:
            nearest_price_value = nearest_500_above

    # Entry BUY: CE SELL: PE NIFTY1950023DECCE

    # Convert the Thursday date in the format: ddMMM
    # Check if the next thursday falls under next month
    # if nearest thursday falls under next month then format the next thursday date as ddMMM
    # else format the next thursday date as YYMMDD (NIFTY2411119400CE 11th January 2024)

    if trading_symbol == "NIFTY":
        # For NIFTY the expiry day is Thursday
        # Calculate the days until the next Thursday
        current_date = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
        days_until_next_thursday = (3 - current_date.weekday() + 7) % 7

        default_log.debug(f"Days until next Thursday: {days_until_next_thursday}")

        if days_until_next_thursday < 4:
            # Calculate the next Thursday's date
            next_thursday_date = current_date + timedelta(days=(3 - current_date.weekday() + 7) % 7 + 7)
        else:
            # Calculate the next Thursday's date
            next_thursday_date = current_date + timedelta(days=days_until_next_thursday)

        next_to_next_thursday_date = next_thursday_date + timedelta(days=7)
        default_log.debug(f"Next to Next Thursday date is={next_to_next_thursday_date}")

        # Check if the next Thursday falls in the next month
        if next_thursday_date.month > current_date.month:
            # Format as YYMMM if next Thursday is in the next month
            default_log.debug(f"As next thursday date ({next_thursday_date}) is falls in the "
                              f"next month ({current_date.month + 1}) instead of the current_month "
                              f"({current_date.month}) so using the following format "
                              f"for timestamp => YYMMM")
            formatted_next_expiry_date = datetime.now().strftime("%y%b").upper()
        # Check if next Thursday date is the last thursday of the month
        elif next_to_next_thursday_date.month > current_date.month:
            default_log.debug(f"As next thursday date ({next_thursday_date}) is the last thursday "
                              f"of the current_month ({current_date.month}) so using the following format "
                              f"for timestamp => YYMMM")
            formatted_next_expiry_date = datetime.now().strftime("%y%b").upper()
        else:
            # Format as YYMMDD if next Thursday is in the same month
            formatted_next_expiry_date = next_thursday_date.strftime("%y%m%d").replace("0", "", 1)
    else:
        # For BANKNIFTY the expiry date is WEDNESDAY
        # Calculate the days until the next Thursday
        current_date = datetime.now().astimezone(pytz.timezone("Asia/Kolkata"))
        days_until_next_wednesday = (2 - current_date.weekday() + 7) % 7

        default_log.debug(f"Days until next Wednesday: {days_until_next_wednesday}")

        if days_until_next_wednesday < 3:
            # Calculate the next Thursday's date
            next_wednesday_date = current_date + timedelta(days=(2 - current_date.weekday() + 7) % 7 + 7)
        else:
            # Calculate the next Thursday's date
            next_wednesday_date = current_date + timedelta(days=days_until_next_wednesday)

        next_to_next_wednesday_date = next_wednesday_date + timedelta(days=7)
        default_log.debug(f"Next to Next Wednesday date is={next_to_next_wednesday_date}")

        # Check if the next Thursday falls in the next month
        if next_wednesday_date.month > current_date.month:
            # Format as YYMMM if next Wednesday is in the next month
            default_log.debug(f"As next wednesday date ({next_wednesday_date}) is falls in the "
                              f"next month ({current_date.month + 1}) instead of the current_month "
                              f"({current_date.month}) so using the following format "
                              f"for timestamp => YYMMM")
            formatted_next_expiry_date = datetime.now().strftime("%y%b").upper()
            # Check if next Thursday date is the last thursday of the month
        elif next_to_next_wednesday_date.month > current_date.month:
            default_log.debug(f"As next wednesday date ({next_wednesday_date}) is the last wednesday "
                              f"of the current_month ({current_date.month}) so using the following format "
                              f"for timestamp => YYMMM")
            formatted_next_expiry_date = datetime.now().strftime("%y%b").upper()
        else:
            # Format as YYMMDD if next Thursday is in the same month
            formatted_next_expiry_date = next_wednesday_date.strftime("%y%m%d").replace("0", "", 1)

    default_log.debug(f"Formatted Next Expiry Date for trading_symbol={trading_symbol} is {formatted_next_expiry_date}")

    # nearest_thursday_str = nearest_thursday.strftime("%d%b").upper()
    # previous_thursday_str = previous_thursday.strftime("%d%b").upper()
    # two_thursdays_ago_str = two_thursdays_ago.strftime("%d%b").upper()

    option_type = 'PE' if transaction_type == SignalType.SELL else 'CE'

    # Create the indices symbol
    # closest_expiry_date = get_nfo_closest_expiry_date(index_symbol=clean_symbol)
    indices_symbol = clean_symbol + formatted_next_expiry_date + str(nearest_price_value) + option_type

    nfo_filepath = f"instrument_tokens_of_zerodha_{datetime.now().date()}.csv"
    df = pd.read_csv(nfo_filepath)

    nfo_df = df[df['exchange'] == "NFO"]
    # Assuming 'indices_symbol' is a column in nfo_df
    match = nfo_df[nfo_df['tradingsymbol'].str.contains(indices_symbol)]

    # Check if there is a match
    if not match.empty:
        default_log.debug(f"Found a match in nfo_df! for = {indices_symbol}")
        default_log.debug(f"Returning indices symbol {indices_symbol} for trading_symbol={trading_symbol} and "
                          f"signal_type={transaction_type} and price={price}")
        return indices_symbol
    else:
        default_log.debug(f"No match found in nfo_df for {indices_symbol}")
        return None

    # indices_symbol_next_thursday = clean_symbol + nearest_thursday_str + str(nearest_50_value) + option_type
    # indices_symbol_previous_thursday = clean_symbol + previous_thursday_str + str(nearest_50_value) + option_type
    # indices_symbol_previous_two_thursday = clean_symbol + two_thursdays_ago_str + str(nearest_50_value) + option_type
    #
    # default_log.debug(f"Trading indices option symbol prepared={indices_symbol_next_thursday} and "
    #                   f"{indices_symbol_previous_thursday} ")
    #
    # nfo_filepath = f"instrument_tokens_of_zerodha_{datetime.now().date()}.csv"
    # df = pd.read_csv(nfo_filepath)
    #
    # nfo_df = df[df['exchange'] == "NFO"]
    # # Assuming 'indices_symbol' is a column in nfo_df
    # match = nfo_df[nfo_df['tradingsymbol'].str.contains(indices_symbol_next_thursday)]
    #
    # # Check if there is a match
    # if not match.empty:
    #     default_log.debug(f"Found a match in nfo_df! for = {indices_symbol_next_thursday}")
    #     # You can access the matched row(s) using 'match'
    #     # For example, you can print the entire matched row
    #     default_log.debug(match)
    #     return indices_symbol_next_thursday
    # else:
    #     default_log.debug(f"No match found in nfo_df for {indices_symbol_next_thursday}")
    #
    # match = nfo_df[nfo_df['tradingsymbol'].str.contains(indices_symbol_previous_thursday)]
    #
    # # Check if there is a match
    # if not match.empty:
    #     default_log.debug(f"Found a match in nfo_df! for {indices_symbol_previous_thursday}")
    #     # You can access the matched row(s) using 'match'
    #     # For example, you can print the entire matched row
    #     default_log.debug(match)
    #     return indices_symbol_previous_thursday
    # else:
    #     default_log.debug(f"No match found in nfo_df for {indices_symbol_previous_thursday}")
    #
    # match = nfo_df[nfo_df['tradingsymbol'].str.contains(indices_symbol_previous_two_thursday)]
    #
    # # Check if there is a match
    # if not match.empty:
    #     default_log.debug(f"Found a match in nfo_df! for {indices_symbol_previous_two_thursday}")
    #     # You can access the matched row(s) using 'match'
    #     # For example, you can print the entire matched row
    #     default_log.debug(match)
    #     return indices_symbol_previous_two_thursday
    # else:
    #     default_log.debug(f"No match found in nfo_df for {indices_symbol_previous_two_thursday}")
    #     return None


def get_official_kite_account_api():
    global kite_access_token
    kite = KiteConnect(api_key=zerodha_api_key)
    # access_token = zerodha_access_token
    access_token = kite_access_token if kite_access_token != "" else zerodha_access_token
    default_log.debug(f"Access token used: {access_token}")
    kite.set_access_token(access_token)
    return kite


# Get Kite Account
def get_kite_account_api():
    use_simulation = get_use_simulation_status()
    if use_simulation:
        kite = KiteSandbox()
    else:
        kite = KiteConnect(api_key=zerodha_api_key)
        # access_token = zerodha_access_token
        access_token = kite_access_token if kite_access_token != "" else zerodha_access_token
        default_log.debug(f"Access token used: {access_token}")
        kite.set_access_token(access_token)
    return kite


# Placing an zerodha order
def place_zerodha_order(
        kite: Union[KiteConnect, KiteSandbox],
        trading_symbol: str,
        transaction_type: SignalType,
        quantity: int,
        average_price: float = None,
        exchange: str = "NSE",
):
    default_log.debug("inside place_zerodha_order with "
                      f"trading_symbol={trading_symbol} "
                      f"transaction_type={transaction_type} "
                      f"quantity={quantity} "
                      f"exchange={exchange} "
                      f"average_price={average_price} ")

    try:
        # Place a Market Order
        order_params = {
            "tradingsymbol": trading_symbol,
            "exchange": exchange,
            "transaction_type": transaction_type.name,
            "quantity": int(quantity),
            "order_type": "MARKET",
            "product": "MIS",
            "validity": "DAY"
        }

        if average_price is not None:
            order_params["average_price"] = round(average_price, 2)

        default_log.debug(f"[MARKET] order_params={order_params}")

        order_id = kite.place_order(variety="regular", **order_params)

        default_log.debug(f"[MARKET] (symbol={trading_symbol}) Order ID returned: {order_id}")

        return order_id
    except Exception as e:
        default_log.debug(f"An error occurred while placing MARKET order symbol = {trading_symbol}: {e}")
        return None


# Placing a zerodha order with STOP LOSS
def place_zerodha_order_with_stop_loss(
        kite: Union[KiteConnect, KiteSandbox],
        trading_symbol: str,
        transaction_type: SignalType,
        quantity: int,
        stop_loss: float,
        exchange: str = "NSE"
):
    default_log.debug("inside place_zerodha_order_with_stop_loss with "
                      f"trading_symbol={trading_symbol} "
                      f"transaction_type={transaction_type} "
                      f"quantity={quantity} "
                      f"stop_loss={stop_loss} "
                      f"exchange={exchange} ")

    try:
        # Place a Market Order
        order_params = {
            "tradingsymbol": trading_symbol,  # Replace with the symbol you want to trade
            "exchange": exchange,  # Replace with the appropriate exchange
            "transaction_type": transaction_type.name,
            "quantity": int(quantity),
            "order_type": "SL-M",
            "trigger_price": stop_loss,
            "product": "MIS",  # CNC for delivery, MIS for intraday, etc.
            "validity": "DAY"
        }

        order_id = kite.place_order(variety="regular", **order_params)

        default_log.debug(f"[SL] (symbol={trading_symbol}) Order ID returned: {order_id}")

        return order_id
    except Exception as e:
        default_log.debug(f"An error occurred while placing SL order symbol = {trading_symbol}: {e}")
        return None


# Placing a zerodha order with TAKE PROFIT
def place_zerodha_order_with_take_profit(
        kite: Union[KiteConnect, KiteSandbox],
        trading_symbol: str,
        transaction_type: SignalType,
        quantity: int,
        take_profit: float,
        exchange: str = "NSE"
):
    default_log.debug("inside place_zerodha_order_with_take_profit with "
                      f"trading_symbol={trading_symbol} "
                      f"transaction_type={transaction_type} "
                      f"quantity={quantity} "
                      f"take profit={take_profit} "
                      f"exchange={exchange} ")

    try:
        # Place a Market Order
        order_params = {
            "tradingsymbol": trading_symbol,  # Replace with the symbol you want to trade
            "exchange": exchange,  # Replace with the appropriate exchange
            "transaction_type": transaction_type.name,
            "quantity": int(quantity),
            "order_type": "LIMIT",
            "price": take_profit,
            "product": "MIS",  # CNC for delivery, MIS for intraday, etc.
            "validity": "DAY"
        }

        order_id = kite.place_order(variety="regular", **order_params)

        default_log.debug(f"[LIMIT] (symbol={trading_symbol}) Order ID returned: {order_id}")

        return order_id
    except Exception as e:
        default_log.debug(f"An error occurred while placing LIMIT order symbol = {trading_symbol}: {e}")
        return None


# Updating a zerodha order with STOP LOSS
def update_zerodha_order_with_stop_loss(
        kite: Union[KiteConnect, KiteSandbox],
        zerodha_order_id: str,
        trading_symbol: str,
        transaction_type: SignalType,
        trade_quantity: int = None,  # this quantity is used to create new LIMIT order
        quantity: int = None,  # this quantity is used during extension trade
        stop_loss: float = None,
        candle_high: float = None,
        candle_low: float = None,
        exchange: str = "NSE"
):
    default_log.debug("inside update_zerodha_order_with_stop_loss with "
                      f"zerodha_order_id={zerodha_order_id} "
                      f"stop_loss={stop_loss} "
                      f"trading_symbol={trading_symbol} "
                      f"transaction_type={transaction_type} "
                      f"quantity={quantity} "
                      f"trade_quantity={trade_quantity} "
                      f"candle_high={candle_high} "
                      f"candle_low={candle_low} "
                      f"exchange={exchange} ")

    try:
        # Place a Market Order
        order_params = {
            "order_id": zerodha_order_id
        }

        if stop_loss is not None:
            order_params["trigger_price"] = stop_loss

        if (candle_low is not None) and (candle_high is not None):
            order_params["candle_high"] = float(candle_high)
            order_params["candle_low"] = float(candle_low)

        if quantity is not None:
            order_params["quantity"] = int(quantity)

        default_log.debug(f"[updated SL] order_params={order_params}")

        order_id = kite.modify_order(variety="regular", **order_params)

        default_log.debug(f"[SL UPDATE] Order ID returned: {order_id}")

        return order_id
    except Exception as e:
        default_log.debug(f"[SL] An error occurred while updating zerodha order with id={zerodha_order_id} "
                          f"with stop loss kite historical data: {e}")

        if e.args[0] == "Maximum allowed order modifications exceeded.":
            default_log.debug(f"[SL UPDATE] Maximum SL-M order modification reached so cancelling current SL-M order "
                              f"with id={zerodha_order_id} and creating new LIMIT order.")
            cancel_order(kite, zerodha_order_id)

            default_log.debug(f"[SL UPDATE] Cancelled SL-M order with id={zerodha_order_id} and "
                              f"now creating new SL-M order with stop_loss={stop_loss}")

            sl_order_id = place_zerodha_order_with_stop_loss(
                kite,
                trading_symbol=trading_symbol,
                transaction_type=transaction_type,
                quantity=int(trade_quantity),
                stop_loss=stop_loss,
                exchange=exchange
            )

            default_log.debug(f"[SL UPDATE] Placed new SL-M order with id={sl_order_id} as old sl order with "
                              f"id={zerodha_order_id} had reached maximum order modification limit")
            return sl_order_id

        default_log.debug(
            f"[SL UPDATE] An error occurred while updating zerodha SL-M order with id={zerodha_order_id} "
            f"with stop loss as={stop_loss}. Error: {e}")

        return None


# Updating a zerodha order with TAKE PROFIT
def update_zerodha_order_with_take_profit(
        kite: Union[KiteConnect, KiteSandbox],
        zerodha_order_id: str,
        trading_symbol: str,
        transaction_type: SignalType,
        take_profit: float = None,
        trade_quantity: int = None,  # this quantity is used to create new LIMIT order
        quantity: int = None,  # this quantity is used during extension trade
        candle_high: float = None,
        candle_low: float = None,
        exchange: str = "NSE"
):
    default_log.debug("inside update_zerodha_order_with_take_profit with "
                      f"zerodha_order_id={zerodha_order_id} "
                      f"take profit={take_profit} "
                      f"trading_symbol={trading_symbol} "
                      f"transaction_type={transaction_type} "
                      f"quantity={quantity} "
                      f"trade_quantity={trade_quantity} "
                      f"candle_high={candle_high} "
                      f"candle_low={candle_low} ")

    try:
        # Place a LIMIT Order
        order_params = {
            "order_id": zerodha_order_id
        }

        if take_profit is not None:
            order_params["price"] = take_profit

        if (candle_low is not None) and (candle_high is not None):
            order_params["candle_high"] = float(candle_high)
            order_params["candle_low"] = float(candle_low)

        if quantity is not None:
            order_params["quantity"] = int(quantity)

        default_log.debug(f"[TP UPDATE] order_params={order_params}")

        order_id = kite.modify_order(variety="regular", **order_params)

        default_log.debug(f"[TP UPDATE] Order ID returned: {order_id}")

        return order_id

    except Exception as e:
        default_log.debug(
            f"[TP UPDATE] An error occurred while updating zerodha LIMIT order with id={zerodha_order_id} "
            f"with take profit as={take_profit}. Error: {e}")

        if e.args[0] == "Maximum allowed order modifications exceeded.":
            default_log.debug(f"[TP UPDATE] Maximum LIMIT order modification reached so cancelling current LIMIT order "
                              f"with id={zerodha_order_id} and creating new LIMIT order.")
            cancel_order(kite, zerodha_order_id)

            default_log.debug(f"[TP UPDATE] Cancelled LIMIT order with id={zerodha_order_id} and "
                              f"now creating new LIMIT order with take_profit={take_profit}")

            tp_order_id = place_zerodha_order_with_take_profit(
                kite,
                trading_symbol=trading_symbol,
                transaction_type=transaction_type,
                quantity=int(trade_quantity),
                take_profit=take_profit,
                exchange=exchange
            )

            default_log.debug(f"[TP UPDATE] Placed new LIMIT order with id={tp_order_id} as old tp order with "
                              f"id={zerodha_order_id} had reached maximum order modification limit")
            return tp_order_id

        default_log.debug(
            f"[TP UPDATE] An error occurred while updating zerodha LIMIT order with id={zerodha_order_id} "
            f"with take profit as={take_profit}. Error: {e}")
        return None


def cancel_order(
        kite: Union[KiteConnect, KiteSandbox],
        zerodha_order_id: str
):
    default_log.debug(f"Inside cancel_order with zerodha_order_id={zerodha_order_id}")

    try:
        default_log.debug(f"Cancelling Zerodha order with id={zerodha_order_id}")

        kite.cancel_order(variety="regular", order_id=zerodha_order_id)

        default_log.debug(f"Cancelled Zerodha order having id={zerodha_order_id}")
    except Exception as e:
        default_log.debug(f"An error occurred while cancelling zerodha order with id={zerodha_order_id}. Error: {e}")
        return None


def get_status_of_zerodha_order(
        kite: Union[KiteConnect, KiteSandbox],
        zerodha_order_id: str
):
    default_log.debug(f"inside get_status_of_zerodha_order(zerodha_order_id={zerodha_order_id})")

    # Get order details
    order_details = kite.order_history(zerodha_order_id)

    # Check if the order exists and get its status
    if order_details:
        order_status = order_details[-1]["status"]
        default_log.debug(f"Zerodha order status for id={zerodha_order_id} found ")
        return order_status
    else:
        default_log.debug(f"Order details not found for Zerodha order id={zerodha_order_id}")
        return None


def get_historical_data(kite_connect: KiteConnect, instrument_token: int, from_date: Optional[datetime] = None,
                        to_date: Optional[datetime] = None, interval: str = ""):
    default_log.debug(f"inside historical_data with "
                      f"instrument_token={instrument_token} "
                      f"from_date={from_date} "
                      f"to_date={to_date} "
                      f"interval={interval} ")
    time_frame = extract_integer_from_string(interval)
    symbol = symbol_tokens_map.get(instrument_token, None)

    if symbol is None:
        inst_token = str(instrument_token)
        symbol = get_symbol_for_instrument_token(inst_token)
        default_log.debug(f"Symbol Details fetched for instrument_token ({inst_token}) => {symbol}")

    try:
        if use_global_feed:

            hist_data = get_global_data_feed_historical_data(
                            trading_symbol=symbol,
                            time_frame=int(time_frame),
                            from_time=from_date,
                            to_time=to_date
                        )

            default_log.debug(
                f"[LIVE] Global Data Feed historical data returned for symbol={symbol} and time_frame={interval} "
                f"from {from_date} to {to_date}: {hist_data}")

            if len(hist_data) == 0:
                default_log.debug(f"data not found on truedata from_date={from_date} and to_date={to_date}")
                return []

            sorted_historical_data = sorted(hist_data, key=lambda x: x['timestamp'])

        else:
            from_date = from_date.replace(second=0).strftime('%Y-%m-%d %H:%M:%S')
            to_date = to_date.replace(second=0).strftime('%Y-%m-%d %H:%M:%S')
            hist_data = kite_connect.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )

            if len(hist_data) == 0:
                default_log.debug(f"data not found on zerodha from_date={from_date} and to_date={to_date}")
                return []

            default_log.debug(
                f"[LIVE] Historical Data retrieved from_date={from_date} and to_date={to_date}: {hist_data} for "
                f"instrument_token={instrument_token} and interval={interval} ")

            sorted_historical_data = sorted(hist_data, key=lambda x: x['date'])

        default_log.debug(f"Sorted historical data for instrument_toke={instrument_token} and interval={interval}"
                          f"with from_date={from_date} and to_date={to_date}: "
                          f"{sorted_historical_data}")

        return [sorted_historical_data[-1]]
    except Exception as e:
        default_log.debug(
            f"An error occurred while fetching data from zerodha. Error: {e}")
        return []


def cancel_all_open_orders(kite: Union[KiteConnect, KiteSandbox]):
    default_log.debug(f"inside cancel_all_open_orders")

    # Get all order
    zerodha_orders = kite.orders()

    if len(zerodha_orders) == 0:
        default_log.debug("No orders found for the Zerodha Account")
        return

    # Filter OPEN, MODIFIED, TRIGGER_PENDING orders
    for order in zerodha_orders:
        order_status = order['status']
        order_id = order['order_id']
        if order_status in ['OPEN', 'MODIFIED', 'TRIGGER_PENDING']:
            default_log.debug(f"Order with id={order_id} is in {order_status} state "
                              f"so will have to cancel the order")

        cancel_order(kite, order_id)

    return


def get_zerodha_order_details(kite: Union[KiteConnect, KiteSandbox], zerodha_order_id: str):
    default_log.debug(f"inside get_zerodha_order_details with zerodha_order_id={zerodha_order_id}")

    try:
        zerodha_order_details = kite.order_history(zerodha_order_id)

        if len(zerodha_order_details) == 0:
            default_log.debug(f"Zerodha order details not found for id={zerodha_order_id}")
            return None

        default_log.debug(f"Zerodha order details fetched for id={zerodha_order_id} => {zerodha_order_details}")

        zerodha_latest_order_details = zerodha_order_details[-1]

        return zerodha_latest_order_details
    except Exception as e:
        default_log.debug(f"An error occurred while fetching zerodha order details. Error={e}")
        return None


if __name__ == "__main__":
    symbol = get_symbol_for_instrument_token(str(738561))

    default_log.debug(f"Symbol for instrument_token (738561) => {symbol}")
