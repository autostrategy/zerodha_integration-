import os

from pathlib import Path
import logging
import json
from dateutil.relativedelta import relativedelta

# Flask
fastapi_host = "0.0.0.0"
fastapi_port = 5000
debug = True
reload = True

# For a good understanding on config See: https://www.toptal.com/python/in-depth-python-logging#:~:text=There%20are
# %20six%20log%20levels,particularity%20will%20be%20addressed%20next. Logging

from logging.config import dictConfig

common_date_format = "%d-%m-%Y %H:%M"

max_retries = 10


def get_expiration_duration():
    return relativedelta(days=7)


# Use secrets.json if running on server
secrets_path = os.getenv('SECRETS_PATH', '/home/ubuntu/secrets.json')  # Default is /home/ubuntu/secrets.json
# postgres
postgres_username = 'postgres'
postgres_password = 'qaswerfd'
postgres_db_name = "zerodha_integration_db"
postgres_host = "127.0.0.1"
postgres_port = 5432
secret_key = 'hft-secret'
security_password_salt = 'hft-secret-salt'
root_url = f'http://localhost:{fastapi_port}'
redis_password = None
redis_username = 'dhv2712@gmail.com'
redis_host = 'redis-16380.c15.us-east-1-4.ec2.cloud.redislabs.com'
redis_port = 16380
redis_hset_name = 'redis_user_tokens'
frontend_url = 'http://localhost:5000'
reset_password_url = 'http://localhost:5000/auth/process-reset-password-request'
log_file = 'app.log'  # TODO: Create a directory, set owner and group and set log file path to
# /var/log/project-name/app.log
default_logger = 'console'
no_of_candles_to_consider = 10
status_query_wait_time = 30
config_threshold_percent = 0.3
# instrument_tokens_map = {"TCS": 16326146, "INFY": 408065, "ICICIBANK": 1270529,
#                          "MRF": 16273154, "AXISBANK": 1510401,
#                          "HDFCBANK": 16234754, "NIPPON": 139046660,
#                          "3MINDIA": 121345, "CROMPTON": 16223490, "NIFTY50": 256265, "BANKNIFTY": 260105}
# instrument_tokens_map = {"ICICIBANK": 1270529, "AXISBANK": 1510401, "INFY": 408065, "TECHM": 3465729, "BANKNIFTY": 260105, "NIFTY": 256265}
instrument_tokens_map = {"BANKNIFTY": 260105, "NIFTY": 256265}
# instrument_tokens_map = {"AXISBANK": 1510401}
# instrument_tokens_map = {"NIFTY": 256265}
# symbol_tokens_map = {256265: "NIFTY"}
# symbol_tokens_map = {1510401: "AXISBANK"}
# symbol_tokens_map = {1270529: "ICICIBANK", 1510401: "AXISBANK", 408065: "INFY", 3465729: "TECHM", 969473: "WIPRO"}
# symbol_tokens_map = {1270529: "ICICIBANK", 1510401: "AXISBANK", 408065: "INFY", 3465729: "TECHM", 260105: "BANKNIFTY", 256265: "NIFTY"}
symbol_tokens_map = {260105: "BANKNIFTY", 256265: "NIFTY"}
time_stamps = ["1", "3", "5", "15"]
# time_stamps = ["1"]
indices_list = ["NIFTY", "BANKNIFTY", "SP500", "SENSEX"]
trade1_loss_percent = 0.5
trade2_loss_percent = 0.25
trade3_loss_percent = 0.25
provide_ticker_data = False
use_truedata = False
use_global_feed = True
sandbox_mode = False

KITE_API_URL = "https://api.kite.trade"
KITE_API_LOGIN_URL = "https://kite.zerodha.com"
homepage_url = "http://localhost:3000"
buffer_for_entry_trade = 0.001
buffer_for_tp_trade = 0.001

initial_start_range = 0
initial_end_range = 5

NIFTY_INDEX_SYMBOL = "23DEC"
BANKNIFTY_INDEX_SYMBOL = "23DEC"


secrets_file = Path(secrets_path)

if secrets_file.is_file():
    secrets = ''
    with open(secrets_file) as f:
        secrets = json.loads(f.read())

        postgres_username = secrets['postgres_username']
        postgres_password = secrets['postgres_password']
        postgres_db_name = secrets['postgres_db_name']
        postgres_host = secrets['postgres_host']
        postgres_port = secrets['postgres_port']
        secret_key = secrets['secret_key']
        root_url = secrets['root_url']
        security_password_salt = secrets['security_password_salt']
        redis_password = secrets['redis_password']
        redis_host = secrets['redis_host']
        redis_port = secrets['redis_port']
        redis_username = secrets['redis_username']
        reset_password_url = secrets['reset_password_url']
        frontend_url = secrets['frontend_url']
        default_logger = secrets.get('default_logger', 'console')
        log_file = secrets.get('log_file', 'app.log')
        zerodha_api_key = secrets['zerodha_api_key']
        zerodha_access_token = secrets['zerodha_access_token']
        zerodha_api_secret = secrets['zerodha_api_secret']
        truedata_username = secrets['truedata_username']
        truedata_password = secrets['truedata_password']
        realtime_port = secrets['realtime_port']
        accesskey = secrets['accesskey']
        endpoint = secrets['endpoint']

redis_url = f"redis://{redis_username}:{redis_password}@{redis_host}:{redis_port}"

sqlalchemy_database_uri = f"postgresql://{postgres_username}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db_name}"

dir_path = os.path.dirname(os.path.realpath(__file__))
dir_path = Path(dir_path)
# For a good understanding on config See: https://www.toptal.com/python/in-depth-python-logging#:~:text=There%20are
# %20six%20log%20levels,particularity%20will%20be%20addressed%20next. Logging
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s: [%(filename)s:%(lineno)s in %(funcName)s()] %(message)s',
        },
        'info': {
            'format': '[%(asctime)s]: %(message)s',
        }
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': log_file,
            'when': 'D',
            'interval': 7
        },
        'debugfilehandler': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': log_file,
            'formatter': 'default',
            'when': 'D',
            'interval': 7
        },
        'consoledebughandler': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'default'
        },
        'consolehandler': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'info'
        }
    },
    'loggers': {
        'app': {
            'handlers': ['debugfilehandler', 'consolehandler'],
            'level': 'DEBUG',
            'propogate': True,
        },
        'console': {
            'handlers': ['consoledebughandler', 'debugfilehandler'],
            'level': 'DEBUG',
            'propogate': True
        },
        'consoleonly': {
            'handlers': ['consoledebughandler'],
            'level': 'DEBUG',
            'propogate': True
        }
    }
}
dictConfig(LOGGING_CONFIG)
default_log = logging.getLogger(default_logger)
