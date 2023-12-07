import logging

import pytz
import pandas as pd
from kiteconnect import KiteConnect
from datetime import datetime, timedelta
from config import zerodha_api_key, zerodha_access_token, zerodha_api_secret

from kiteconnect.exceptions import InputException
from optionchain_stream import OptionChain

logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":

    kite = KiteConnect(api_key=zerodha_api_key)

    # Redirect the user to the login url obtained
    # from kite.login_url(), and receive the request_token
    # from the registered redirect url after the login flow.
    # Once you have the request_token, obtain the access_token
    # as follows.

    access_token = zerodha_access_token
    data = kite.generate_session("GnvzLglqRn76J4eVuiIMZK2bVdVLNzKf", api_secret=zerodha_api_secret)
    # kite.set_access_token(data["access_token"])
    kite.set_access_token(access_token)

    # kite.historical_data()

    # Place an order
    try:

        positions = kite.positions()

        logging.info(f"All positions: {positions}")
        # Get instruments
        # kite_instruments = kite.instruments(exchange="NFO")
        # logging.info(f"Kite Instruments: {kite_instruments}")
        #
        # df = pd.DataFrame(kite_instruments)
        #
        # df.to_csv("instrument_tokens_of_zerodha_nfo.csv")
        # order_history = kite.order_history("231120501311410")
        #
        # logging.info(f"Order History={order_history}")
        #
        # OptionStream = OptionChain("TCS", "2023-11-30", "w3j0a5u2wuvitqd9", access_token=access_token)
        # # OptionStream = OptionChain("ONGC", "2021-02-25", "w3j0a5u2wuvitqd9", access_token=access_token)
        # for data in OptionStream.create_option_chain():
        #     logging.info(f"Option Chain={data}")
        # exchange = "NSE"
        # tradingsymbol = "NIFTY50"
        # instrument_type = "EQ"  # EQ for equity (common stock)
        #
        # # Fetch instruments
        # # instruments = kite.ltp(exchange + ":" + tradingsymbol + instrument_type)
        # # instruments = kite.ltp('NSE:NIFTY20NOVFUT')
        # option_instrument_token = "256265"
        # options = kite.ltp(['NSE:' + option_instrument_token])
        # print(f"Options = {options}")
        # # print("Instruments for", tradingsymbol + ":", instruments)
        #
        # # current_datetime = datetime.now()
        # # current_datetime = current_datetime.astimezone(pytz.timezone("Asia/Kolkata"))
        current_datetime = datetime(2023, 11, 28, 13, 25, 0).astimezone(pytz.timezone("Asia/Kolkata"))
        start_datetime = datetime(2023, 11, 28, 13, 0, 0).astimezone(pytz.timezone("Asia/Kolkata"))
        # # start_datetime = start_datetime.astimezone(pytz.timezone("Asia/Kolkata"))
        # # start_datetime = datetime.now() - timedelta(minutes=1)
        #
        # logging.info(f"From Date: {start_datetime} and To Date: {current_datetime}")
        kite_historical_data = kite.historical_data(
            instrument_token=1270529,
            from_date=current_datetime,
            to_date=start_datetime,
            interval='5minute'
        )

        logging.info(f"historical data: {kite_historical_data}")

        #
        # data = pd.DataFrame(kite_historical_data)
        # # order_id = kite.place_order(variety=kite.VARIETY_REGULAR,
        # #                             tradingsymbol="INFY",
        # #                             exchange=kite.EXCHANGE_NSE,
        # #                             transaction_type=kite.TRANSACTION_TYPE_BUY,
        # #                             quantity=1,
        # #                             order_type=kite.ORDER_TYPE_MARKET,
        # #                             product=kite.PRODUCT_CNC,
        # #                             validity=kite.VALIDITY_DAY)
        #
        # # data.to_csv("ICICIBANK.csv")

        # logging.info("Order placed. ID is: {}".format(order_id))
    # except InputException as e:
    #     logging.info(f"Input exception: {e}")
    except Exception as e:
        logging.info("Error occured: {}".format(e))

    # Fetch all orders
    # kite.orders()
    #
    # Get instruments
    # df = pd.DataFrame(kite.instruments())
    #
    # df.to_csv("instrument_tokens_of_zerodha.csv")

    # Place an mutual fund order
    # kite.place_mf_order(
    #     tradingsymbol="INF090I01239",
    #     transaction_type=kite.TRANSACTION_TYPE_BUY,
    #     amount=5000,
    #     tag="mytag"
    # )
    #
    # # Cancel a mutual fund order
    # kite.cancel_mf_order(order_id="order_id")
    #
    # # Get mutual fund instruments
    # kite.mf_instruments()
