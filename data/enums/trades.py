from enum import Enum


class Trades(Enum):
    ALL_3_TRADES = 1
    FIRST_2_TRADES = 2
    LAST_TRADE = 3
    COVER_SL_TRADE = 4
    NO_TRADE = 5
