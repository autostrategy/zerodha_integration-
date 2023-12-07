import pandas as pd


dataset = []


def get_tick_data():
    csv_file_name = "DAT_XLSX_NSXUSD_M1_202311.xlsx"
    df = pd.read_excel(csv_file_name)

    for index, row in df.iterrows():
        datetime_obj = row['timestamp']  # Replace 'timestamp' with the actual column name
        last_traded_price = row['open']  # Replace 'last_traded_price' with the actual column name
        tick_size = row['tick_size']  # Replace 'tick_size' with the actual column name

        result = {
            'instrument_token': 541120,
            'timestamp': datetime_obj,
            'last_price': last_traded_price,
            'tick_size': tick_size
        }

        dataset.append(result)

    print(dataset)
    return dataset


ticks = get_tick_data()

# columns in data frame
df_cols = ["Timestamp", "Token", "LTP"]

data_frame = pd.DataFrame(data=[], columns=df_cols, index=[])

data = dict()

for company_data in ticks:
    token = company_data["instrument_token"]
    ltp = company_data["last_price"]
    timestamp = company_data["timestamp"]

    data[timestamp] = [timestamp, token, ltp]

tick_df = pd.DataFrame(data.values(), columns=df_cols, index=data.keys())  #

data_frame = data_frame.append(tick_df)
ggframe = data_frame.set_index('Timestamp')

candles_minute = ggframe.groupby('Token').resample('1min').agg({'LTP': 'ohlc'}).dropna()
candles_3minute = ggframe.groupby('Token').resample('3min').agg({'LTP': 'ohlc'}).dropna()
candles_5minute = ggframe.groupby('Token').resample('5min').agg({'LTP': 'ohlc'}).dropna()
candles_10minute = ggframe.groupby('Token').resample('10min').agg({'LTP': 'ohlc'}).dropna()
candles_15minute = ggframe.groupby('Token').resample('15min').agg({'LTP': 'ohlc'}).dropna()
candles_30minute = ggframe.groupby('Token').resample('30min').agg({'LTP': 'ohlc'}).dropna()

candles.columns = ['open', 'high', 'low', 'close']

print(candles)
