from datetime import datetime

import pandas as pd

from config import zerodha_api_key, zerodha_access_token, default_log
from kiteconnect import KiteConnect

from flask import Flask, jsonify, request
import threading
import random
import string

app = Flask(__name__)

kite = KiteConnect(api_key=zerodha_api_key)

access_token = zerodha_access_token

kite.set_access_token(access_token)

all_1min_data = []
counter = 0


def store_all_data(
        instrument_token: int
):
    global all_1min_data

    default_log.debug(f"inside store all one minute data with instrument_token={instrument_token}")

    from_date = datetime(2023, 11, 30, 9, 30)
    to_date = datetime(2023, 11, 30, 15, 30)

    historical_data = kite.historical_data(
        instrument_token=instrument_token,
        from_date=from_date,
        to_date=to_date,
        interval='minute'
    )

    sorted_historical_data = sorted(historical_data, key=lambda x: x['date'])

    all_1min_data.extend(sorted_historical_data)

    return True


# class CustomJSONEncoder(json.JSONEncoder):
#     def default(self, obj):
#         if isinstance(obj, datetime):
#             # Convert datetime to a string with the desired format
#             return obj.strftime('%Y-%m-%d %H:%M:%S %Z')  # Adjust the format as needed
#         return super().default(obj)


class Order:
    def __init__(self, order_id, symbol, quantity, exchange, transaction_type, order_type, product, validity,
                 price=None, trigger_price=None, average_price=None):
        self.order_id = order_id
        self.symbol = symbol
        self.exchange = exchange
        self.transaction_type = transaction_type
        self.quantity = quantity
        self.price = price
        self.trigger_price = trigger_price
        self.order_type = order_type
        self.product = product
        self.validity = validity
        self.average_price = average_price
        self.status = "PUT ORDER REQ RECEIVED"
        if order_type == "MARKET":
            self.status_timer = threading.Timer(2, self.update_status)

    def update_status(self):
        statuses = [
            "COMPLETE"
        ]
        self.status = random.choice(statuses)
        print(f"Order {self.order_id} - Status updated to {self.status}")


class TradingSandbox:
    def __init__(self):
        self.orders = {}
        self.lock = threading.Lock()

    def place_order(self, symbol, quantity, exchange, transaction_type, order_type, product, validity, price=None,
                    trigger_price=None, average_price=None):
        with self.lock:
            order_id = self.generate_order_id()
            if price is not None:
                order = Order(order_id, symbol, quantity, exchange, transaction_type, order_type, product, validity,
                              price=price)
                # For non-market orders, set initial status to "OPEN"
                order.status = "OPEN"
            elif trigger_price is not None:
                order = Order(order_id, symbol, quantity, exchange, transaction_type, order_type, product, validity,
                              trigger_price=trigger_price)
                # For non-market orders, set initial status to "OPEN"
                order.status = "OPEN"
            else:
                order = Order(order_id, symbol, quantity, exchange, transaction_type, order_type, product, validity,
                              average_price=average_price)

            self.orders[order_id] = order
            print(f"Order placed: {order_id} - {transaction_type} {quantity} {symbol} at price: {price} and "
                  f"trigger_price: {trigger_price} and average_price: {average_price}")

            # Start the timer to update the status after 15 seconds
            if order_type == "MARKET":
                order.status_timer.start()

            return order

    def execute_orders(self):
        with self.lock:
            for order_id, order in list(self.orders.items()):
                order.status_timer.cancel()  # Cancel the timer, as the order is being executed
                order.status = "EXECUTED"
                print(f"Order executed: {order_id} - {order.action} {order.quantity} {order.symbol} at "
                      f"price={order.price} and trigger_price={order.trigger_price}")
                del self.orders[order_id]

    def generate_order_id(self):
        return ''.join(random.choices(string.digits, k=10))

    def get_all_orders(self):
        with self.lock:
            json_orders = []
            for order_id, order in self.orders.items():
                order_data = {
                    'order_id': order.order_id,
                    'tradingsymbol': order.symbol,
                    'exchange': order.exchange,
                    'transaction_type': order.transaction_type,
                    'quantity': order.quantity,
                    'price': order.price,
                    'trigger_price': order.trigger_price,
                    'order_type': order.order_type,
                    'product': order.product,
                    'validity': order.validity,
                    'average_price': order.average_price,
                    'status': order.status
                }
                json_orders.append(order_data)
            return json_orders

    def update_order_status_by_candle_data(self, order_id, candle_high, candle_low):
        # Get order details by id
        order = self.orders.get(order_id)
        print(f"inside update_order_status_by_candle_data(order_id={order_id}, "
              f"candle_high={candle_high} and candle_low={candle_low})")

        # Check order type
        order_type = order.order_type

        print(f"for order_id={order_id} order_type={order_type}")

        # Check transaction_type
        transaction_type = order.transaction_type

        print(f"for order_id={order_id} order_type={order_type} and "
              f"transaction_type={transaction_type}")

        if order_type == "SL-M":
            # Check the transaction type for checking the direction to check SL hit
            if transaction_type == "BUY":
                if candle_high > order.trigger_price:
                    print(
                        f"[SL {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] transaction_type={transaction_type} | "
                        f"candle_high={candle_high} > trigger_price={order.trigger_price}")
                    order.status = "COMPLETE"
            else:
                if candle_low < order.trigger_price:
                    print(
                        f"[SL {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] transaction_type={transaction_type} | "
                        f"candle_low={candle_low} < trigger_price={order.trigger_price}")
                    order.status = "COMPLETE"
        else:
            if transaction_type == "BUY":
                if candle_low < order.price:
                    print(
                        f"[LIMIT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] transaction_type={transaction_type} | "
                        f"candle_low={candle_low} < price={order.price}")
                    order.status = "COMPLETE"
            else:
                if candle_high > order.price:
                    print(
                        f"[LIMIT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] transaction_type={transaction_type} | "
                        f"candle_low={candle_low} < price={order.price}")
                    order.status = "COMPLETE"

        self.orders[order_id] = order


sandbox = TradingSandbox()


@app.route('/orders/regular', methods=['POST'])
def place_order():
    data = request.get_json()
    symbol = data['tradingsymbol']
    exchange = data['exchange']
    transaction_type = data['transaction_type']
    quantity = data['quantity']
    order_type = data['order_type']
    product = data['product']
    validity = data['validity']

    if 'price' in data:
        price = data['price']
        order = sandbox.place_order(symbol, quantity, exchange, transaction_type, order_type, product, validity,
                                    price=price)
        return jsonify({'order_id': order.order_id, 'status': 'PUT ORDER REQ RECEIVED'})

    if 'trigger_price' in data:
        trigger_price = data['trigger_price']
        order = sandbox.place_order(symbol, quantity, exchange, transaction_type, order_type, product, validity,
                                    trigger_price=trigger_price)
        return jsonify({'order_id': order.order_id, 'status': 'PUT ORDER REQ RECEIVED'})

    if 'average_price' in data:
        average_price = data['average_price']
        order = sandbox.place_order(symbol, quantity, exchange, transaction_type, order_type, product, validity,
                                    average_price=average_price)
        return jsonify({'order_id': order.order_id, 'status': 'PUT ORDER REQ RECEIVED'})


@app.route('/orders', methods=['GET'])
def all_orders():
    orders = sandbox.get_all_orders()
    if len(orders) > 0:
        return jsonify({"data": orders})
    else:
        return jsonify({'error': 'Orders not found'}), 404


@app.route('/orders/<order_id>', methods=['GET'])
def order_status(order_id):
    with sandbox.lock:
        order = sandbox.orders.get(order_id)
        if order:
            return jsonify({'data': order.order_id, 'average_price': order.average_price, 'status': order.status})
        else:
            return jsonify({'data': 'Order not found'}), 404


@app.route('/orders/regular', methods=['PUT'])
def modify_order():
    with sandbox.lock:
        data = request.get_json()
        order_id = data['order_id']

        order = sandbox.orders.get(order_id)

        if not order:
            print(f"Order not found with id={order_id}")
            return jsonify({'error': 'Order not found'}), 404

        # Modify order values based on the received JSON payload
        if 'trigger_price' in data:
            order.trigger_price = data['trigger_price']
        if 'quantity' in data:
            order.quantity = data['quantity']
        if 'price' in data:
            order.price = data['price']
        if 'validity' in data:
            order.validity = data['validity']

        # For non-market orders, set status to "MODIFIED"
        if order.order_type != "MARKET":
            order.status = "MODIFIED"

        sandbox.update_order_status_by_candle_data(order_id, data["candle_high"], data["candle_low"])

        return jsonify({'order_id': order.order_id, 'status': 'Order modified successfully'})


@app.route('/orders/regular/<order_id>', methods=['DELETE'])
def cancel_order(order_id):
    with sandbox.lock:
        order = sandbox.orders.get(order_id)
        if order:
            # Cancel the order
            if order.order_type == "MARKET":
                order.status_timer.cancel()  # Cancel the timer if it's a MARKET order
            order.status = 'CANCELLED'
            print(f"Order cancelled: {order_id}")
            return jsonify({'order_id': order.order_id, 'status': 'Order cancelled successfully'})
        else:
            return jsonify({'error': 'Order not found'}), 404


@app.route('/get-all-data/<interval>', methods=['GET'])
def get_all_data(interval):
    global counter
    global all_1min_data

    interval = int(interval)
    with sandbox.lock:
        default_log.debug(f"Counter: {counter}")
        if (counter % interval) == 0:
            data_to_send = [all_1min_data[counter]]
            counter += 1
            default_log.debug(f"Data sent: {data_to_send}")
            return data_to_send
        else:
            # Resample the data
            no_of_data_to_get = counter % interval

            startIdx = (counter - no_of_data_to_get)

            default_log.debug(f"No of data to get={no_of_data_to_get} and startIdx={startIdx}")
            data_to_resample = all_1min_data[startIdx:counter + 1]

            default_log.debug(f"Data to resample: {data_to_resample}")

            dataframe = pd.DataFrame(data_to_resample)

            # Sort it by date column
            dataframe['date'] = pd.to_datetime(dataframe['date'])
            dataframe.sort_values(by='date', inplace=True)

            # Resample it according to the interval
            actual_interval = str(interval) + 'min'

            dataframe.set_index('date', inplace=True)
            dataframe = dataframe.resample(actual_interval).agg(
                {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

            # Now convert it into JSON format
            # Convert DataFrame to JSON format with datetime format
            json_data = dataframe.reset_index().to_dict(orient='records')

            default_log.debug(f"Returning data for interval={interval}: {json_data}")

            counter += 1
            return json_data


if __name__ == '__main__':
    # status = store_all_data(instrument_token=1270529)
    # Start a background thread to execute orders
    execute_thread = threading.Thread(target=lambda: sandbox.execute_orders())
    execute_thread.start()

    # Run the Flask app
    app.run(debug=True, threaded=True, port=3000)
