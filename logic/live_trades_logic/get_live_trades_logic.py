from config import default_log
from data.dbapi.thread_details_dbapi.read_queries import get_thread_details_with_live_trade_sent
from data.enums.signal_type import SignalType
from logic.live_trades_logic.dtos.alert_trade_details_dto import AlertTradeDetailsDTO
from logic.live_trades_logic.dtos.trade_details_dto import TradeDetailDTO
from standard_responses.dbapi_exception_response import DBApiExceptionResponse


def get_live_trades_details():
    default_log.debug(f"inside get_live_trades_details")

    # Get all thread details which have at least one trade been sent
    thread_details = get_thread_details_with_live_trade_sent()

    if type(thread_details) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while fetching all thread_details with at least one trade. Error: "
                          f"{thread_details.error}")
        return None

    alert_trade_details = []

    # Loop through every thread_details
    for thread_detail in thread_details:
        signal_type = SignalType[thread_detail.signal_type]
        # Check if entry trade has been sent
        entry_trade_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.trade1_quantity,
            trade_time=thread_detail.entry_trade_datetime,
            order_id=thread_detail.signal_trade_order_id
        )

        # alert_trades_list.append(trade_detail_dto)

        # Check if extension 1 trade has been sent
        extension1_trade_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.extension1_quantity,
            trade_time=thread_detail.extension1_trade_datetime,
            order_id=thread_detail.extension1_order_id
        )
        # alert_trades_list.append(trade_detail_dto)

        # Check if extension 2 trade has been sent
        extension2_trade_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.extension2_quantity,
            trade_time=thread_detail.extension2_trade_datetime,
            order_id=thread_detail.extension2_order_id
        )
        # alert_trades_list.append(trade_detail_dto)

        # Check if SL trade has been sent
        sl_trade_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.cover_sl_quantity,
            trade_time=thread_detail.sl_trade_datetime,
            order_id=thread_detail.cover_sl_trade_order_id
        )
        # alert_trades_list.append(trade_detail_dto)

        # Check if TAKE PROFIT trade has been sent
        take_profit_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.extension_quantity,
            trade_time=thread_detail.tp_datetime,
            order_id=thread_detail.tp_order_id
        )

        # Check if STOP LOSS trade has been sent
        stop_loss_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.extension_quantity,
            trade_time=thread_detail.sl_datetime,
            order_id=thread_detail.sl_order_id
        )

        # Check if REVERSE 1 trade has been sent
        reverse1_trade_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.reverse1_trade_quantity,
            trade_time=thread_detail.reverse1_trade_datetime,
            order_id=thread_detail.reverse1_trade_order_id
        )
        # alert_trades_list.append(trade_detail_dto)

        # Check if REVERSE 2 trade has been sent
        reverse2_trade_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.reverse2_trade_quantity,
            trade_time=thread_detail.reverse2_trade_datetime,
            order_id=thread_detail.reverse2_trade_order_id
        )
        # alert_trades_list.append(trade_detail_dto)

        # Check if REVERSE TAKE PROFIT trade has been sent
        reverse_tp_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.total_reverse_trade_quantity,
            trade_time=thread_detail.reverse_trade_tp_order_datetime,
            order_id=thread_detail.reverse_trade_tp_order_id
        )

        # Check if REVERSE STOP LOSS trade has been sent
        reverse_sl_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.total_reverse_trade_quantity,
            trade_time=thread_detail.reverse_trade_sl_order_datetime,
            order_id=thread_detail.reverse_trade_sl_order_id
        )

        # Check if REVERSE BEYOND trade has been sent
        reverse_beyond_detail_dto = TradeDetailDTO(
            signal_type=signal_type,
            quantity=thread_detail.reverse_cover_sl_quantity,
            trade_time=thread_detail.reverse_cover_sl_trade_datetime,
            order_id=thread_detail.reverse_cover_sl_trade_order_id
        )

        new_alert_trade_details = AlertTradeDetailsDTO(
            alert_time=thread_detail.alert_time,
            entry_trade_details=entry_trade_detail_dto,
            extension1_trade_details=extension1_trade_detail_dto,
            extension2_trade_details=extension2_trade_detail_dto,
            sl_trade_details=sl_trade_detail_dto,
            reverse1_trade_details=reverse1_trade_detail_dto,
            reverse2_trade_details=reverse2_trade_detail_dto,
            take_profit_trade_details=take_profit_detail_dto,
            stop_loss_trade_details=stop_loss_detail_dto,
            reverse_take_profit_trade_details=reverse_tp_detail_dto,
            reverse_stop_loss_trade_details=reverse_sl_detail_dto,
            reverse_beyond_details=reverse_beyond_detail_dto
        )

        alert_trade_details.append(new_alert_trade_details)

    default_log.debug(f"Returning {len(alert_trade_details)} Alert Trade Details: {alert_trade_details}")

    return alert_trade_details
