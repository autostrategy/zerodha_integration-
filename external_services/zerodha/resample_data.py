import pandas as pd

file_path = "candlestick_data_new.csv"
df = pd.read_csv(file_path)
# Assuming your data is in a DataFrame named 'df' with columns: 'timestamp', 'open', 'high', 'low', 'close'
# Convert 'timestamp' column to datetime if it's not already
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Set 'timestamp' as the DataFrame index
df.set_index('timestamp', inplace=True)

# Resample the data for different intervals and compute high and low
sample_intervals = [1, 3, 5, 10, 15, 30]  # in minutes

for interval in sample_intervals:
    resampled_data = df.resample(f'{interval}T').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()

    # Display or use the resampled data as needed
    print(f'Resampled Data for {interval}-minute interval:')
    print(resampled_data)
    print('\n')
