from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from logic.live_trades_logic.dtos.trade_details_dto import TradeDetailDTO


class AlertTradeDetailsDTO(BaseModel):
    alert_time: Optional[datetime]
    entry_trade_details: Optional[TradeDetailDTO]
    extension1_trade_details: Optional[TradeDetailDTO]
    extension2_trade_details: Optional[TradeDetailDTO]
    sl_trade_details: Optional[TradeDetailDTO]
    reverse1_trade_details: Optional[TradeDetailDTO]
    reverse2_trade_details: Optional[TradeDetailDTO]
    take_profit_trade_details: Optional[TradeDetailDTO]
    stop_loss_trade_details: Optional[TradeDetailDTO]
    reverse_take_profit_trade_details: Optional[TradeDetailDTO]
    reverse_stop_loss_trade_details: Optional[TradeDetailDTO]
    reverse_beyond_details: Optional[TradeDetailDTO]
