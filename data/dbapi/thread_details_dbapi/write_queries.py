from config import default_log
from data.dbapi.thread_details_dbapi.dtos.event_thread_details_dto import EventThreadDetailsDTO
from decorators.handle_generic_exception import dbapi_exception_handler
from data.db.init_db import get_db
from data.models.thread_details import ThreadDetails


@dbapi_exception_handler
def add_thread_event_details(dto: EventThreadDetailsDTO, session=None, commit=True):
    default_log.debug(f"inside add_thread_event_details(dto={dto})")

    db = session if session else next(get_db())

    new_thread_details = ThreadDetails(
        alert_time=dto.alert_time,
        symbol=dto.symbol,
        time_frame=dto.time_frame,
        signal_type=dto.signal_type,
        configuration_type=dto.configuration_type,
        signal_candle_high=dto.signal_candle_high,
        adjusted_high=dto.adjusted_high,
        signal_candle_low=dto.signal_candle_low,
        adjusted_low=dto.adjusted_low,
        event1_occur_time=dto.event1_occur_time,
        event2_breakpoint=dto.event2_breakpoint,
        event2_occur_time=dto.event2_occur_time,
        event3_occur_time=dto.event3_occur_time,
        lowest_point=dto.lowest_point,
        highest_point=dto.highest_point,
        signal_trade_order_id=dto.signal_trade_order_id,
        tp_order_id=dto.tp_order_id,
        sl_order_id=dto.sl_order_id,
        tp_value=dto.tp_value,
        tp_datetime=dto.tp_datetime,
        sl_value=dto.sl_value,
        sl_datetime=dto.sl_datetime,
        is_completed=dto.is_completed,
        entry_price=dto.entry_price,
        trade1_quantity=dto.trade1_quantity,
        extension_quantity=dto.extension_quantity,
        extension1_order_id=dto.extension1_order_id,
        extension2_order_id=dto.extension2_order_id,
        extension1_quantity=dto.extension1_quantity,
        extension2_quantity=dto.extension2_quantity,
        cover_sl=dto.cover_sl,
        cover_sl_quantity=dto.cover_sl_quantity,
        cover_sl_trade_order_id=dto.cover_sl_trade_order_id,
        reverse1_trade_quantity=dto.reverse1_trade_quantity,
        reverse2_trade_quantity=dto.reverse2_trade_quantity,
        total_reverse_trade_quantity=dto.total_reverse_trade_quantity,
        reverse1_trade_order_id=dto.reverse1_trade_order_id,
        reverse2_trade_order_id=dto.reverse2_trade_order_id,
        reverse_trade_tp_order_id=dto.reverse_trade_tp_order_id,
        reverse_trade_sl_order_id=dto.reverse_trade_sl_order_id,
        reverse1_entry_price=dto.reverse1_entry_price,
        reverse2_entry_price=dto.reverse2_entry_price,
        extended_sl=dto.extended_sl,
        trade_alert_status=dto.trade_alert_status
    )

    db.add(new_thread_details)

    if commit:
        default_log.debug("Committing thread event details")
        db.commit()
    else:
        default_log.debug("Flushing thread event details")
        db.flush()

    default_log.debug(f"Returning new thread details id for symbol={dto.symbol} having timeframe={dto.time_frame}: "
                      f"{new_thread_details.id}")
    return new_thread_details.id


@dbapi_exception_handler
def update_thread_event_details(dto: EventThreadDetailsDTO, thread_detail_id: int, session=None, commit=True):
    default_log.debug(f"inside update_thread_event_details(dto={dto}, thread_detail_id={thread_detail_id})")

    db = session if session else next(get_db())

    thread_detail = db.query(ThreadDetails).filter(ThreadDetails.id == thread_detail_id).first()

    if thread_detail is None:
        default_log.debug(f"Thread details not found for id={thread_detail_id}")
        return None

    if dto.alert_time is not None:
        default_log.debug(f"Updating alert time to={dto.alert_time}")
        thread_detail.alert_time = dto.alert_time

    if dto.symbol is not None:
        default_log.debug(f"Updating symbol to={dto.symbol}")
        thread_detail.symbol = dto.symbol

    if dto.time_frame is not None:
        default_log.debug(f"Updating time_frame to={dto.time_frame}")
        thread_detail.time_frame = dto.time_frame

    if dto.signal_type is not None:
        default_log.debug(f"Updating signal_type to={dto.signal_type}")
        thread_detail.signal_type = dto.signal_type

    if dto.configuration_type is not None:
        default_log.debug(f"Updating signal_type to={dto.configuration_type}")
        thread_detail.configuration_type = dto.configuration_type

    if dto.signal_candle_high is not None:
        default_log.debug(f"Updating signal_candle_high to={dto.signal_candle_high}")
        thread_detail.signal_candle_high = dto.signal_candle_high

    if dto.signal_candle_low is not None:
        default_log.debug(f"Updating signal_candle_low to={dto.signal_candle_low}")
        thread_detail.signal_candle_low = dto.signal_candle_low

    if dto.adjusted_high is not None:
        default_log.debug(f"Updating adjusted_high to={dto.adjusted_high}")
        thread_detail.adjusted_high = dto.adjusted_high

    if dto.adjusted_low is not None:
        default_log.debug(f"Updating adjusted_low to={dto.adjusted_low}")
        thread_detail.adjusted_low = dto.adjusted_low

    if dto.event1_occur_time is not None:
        default_log.debug(f"Updating event1_occur_time to={dto.event1_occur_time}")
        thread_detail.event1_occur_time = dto.event1_occur_time

    if dto.event2_breakpoint is not None:
        default_log.debug(f"Updating event2_breakpoint to={dto.event2_breakpoint}")
        thread_detail.event2_breakpoint = dto.event2_breakpoint

    if dto.event2_occur_time is not None:
        default_log.debug(f"Updating event2_occur_time to={dto.event2_occur_time}")
        thread_detail.event2_occur_time = dto.event2_occur_time

    if dto.event3_occur_time is not None:
        default_log.debug(f"Updating event3_occur_time to={dto.event3_occur_time}")
        thread_detail.event3_occur_time = dto.event3_occur_time

    if dto.lowest_point is not None:
        default_log.debug(f"Updating lowest_point to={dto.lowest_point}")
        thread_detail.lowest_point = dto.lowest_point

    if dto.highest_point is not None:
        default_log.debug(f"Updating highest_point to={dto.highest_point}")
        thread_detail.highest_point = dto.highest_point

    if dto.tp_value is not None:
        default_log.debug(f"Updating tp_value to={dto.tp_value}")
        thread_detail.tp_value = dto.tp_value

    if dto.tp_datetime is not None:
        default_log.debug(f"Updating tp_datetime to={dto.tp_datetime}")
        thread_detail.tp_datetime = dto.tp_datetime

    if dto.sl_value is not None:
        default_log.debug(f"Updating sl_value to={dto.sl_value}")
        thread_detail.sl_value = dto.sl_value

    if dto.sl_datetime is not None:
        default_log.debug(f"Updating sl_datetime to={dto.sl_datetime}")
        thread_detail.sl_datetime = dto.sl_datetime

    if dto.signal_trade_order_id is not None:
        default_log.debug(f"Updating signal_trade_order_id to={dto.signal_trade_order_id}")
        thread_detail.signal_trade_order_id = dto.signal_trade_order_id

    if dto.sl_order_id is not None:
        default_log.debug(f"Updating sl_order_id to={dto.sl_order_id}")
        thread_detail.sl_order_id = dto.sl_order_id

    if dto.tp_order_id is not None:
        default_log.debug(f"Updating tp_order_id to={dto.tp_order_id}")
        thread_detail.tp_order_id = dto.tp_order_id

    if dto.is_completed is not None:
        default_log.debug(f"Updating is_completed to={dto.is_completed}")
        thread_detail.is_completed = dto.is_completed

    if dto.entry_price is not None:
        default_log.debug(f"Updating entry_price to={dto.entry_price}")
        thread_detail.entry_price = dto.entry_price

    if dto.trade1_quantity is not None:
        default_log.debug(f"Updating trade1_quantity to={dto.trade1_quantity}")
        thread_detail.trade1_quantity = dto.trade1_quantity

    if dto.extension_quantity is not None:
        default_log.debug(f"Updating extension_quantity to={dto.extension_quantity}")
        thread_detail.extension_quantity = dto.extension_quantity

    if dto.extension1_order_id is not None:
        default_log.debug(f"Updating extension1_order_id to={dto.extension1_order_id}")
        thread_detail.extension1_order_id = dto.extension1_order_id

    if dto.extension2_order_id is not None:
        default_log.debug(f"Updating extension2_order_id to={dto.extension2_order_id}")
        thread_detail.extension2_order_id = dto.extension2_order_id

    if dto.extension1_quantity is not None:
        default_log.debug(f"Updating extension1_quantity to={dto.extension1_quantity}")
        thread_detail.extension1_quantity = dto.extension1_quantity

    if dto.extension2_quantity is not None:
        default_log.debug(f"Updating extension2_quantity to={dto.extension2_quantity}")
        thread_detail.extension2_quantity = dto.extension2_quantity

    if dto.cover_sl is not None:
        default_log.debug(f"Updating cover_sl to={dto.cover_sl}")
        thread_detail.cover_sl = dto.cover_sl

    if dto.reverse1_trade_quantity is not None:
        default_log.debug(f"Updating reverse1_trade_quantity to={dto.reverse1_trade_quantity}")
        thread_detail.reverse1_trade_quantity = dto.reverse1_trade_quantity

    if dto.reverse2_trade_quantity is not None:
        default_log.debug(f"Updating reverse2_trade_quantity to={dto.reverse2_trade_quantity}")
        thread_detail.reverse2_trade_quantity = dto.reverse2_trade_quantity

    if dto.total_reverse_trade_quantity is not None:
        default_log.debug(f"Updating total_reverse_trade_quantity to={dto.total_reverse_trade_quantity}")
        thread_detail.total_reverse_trade_quantity = dto.total_reverse_trade_quantity

    if dto.reverse1_trade_order_id is not None:
        default_log.debug(f"Updating reverse1_trade_order_id to={dto.reverse1_trade_order_id}")
        thread_detail.reverse1_trade_order_id = dto.reverse1_trade_order_id

    if dto.reverse2_trade_order_id is not None:
        default_log.debug(f"Updating reverse2_trade_order_id to={dto.reverse2_trade_order_id}")
        thread_detail.reverse2_trade_order_id = dto.reverse2_trade_order_id

    if dto.reverse_trade_stop_loss is not None:
        default_log.debug(f"Updating reverse_trade_stop_loss to={dto.reverse_trade_stop_loss}")
        thread_detail.reverse_trade_stop_loss = dto.reverse_trade_stop_loss

    if dto.reverse_trade_take_profit is not None:
        default_log.debug(f"Updating reverse_trade_take_profit to={dto.reverse_trade_take_profit}")
        thread_detail.reverse_trade_take_profit = dto.reverse_trade_take_profit

    if dto.reverse_trade_tp_order_id is not None:
        default_log.debug(f"Updating reverse_trade_tp_order_id to={dto.reverse_trade_tp_order_id}")
        thread_detail.reverse_trade_tp_order_id = dto.reverse_trade_tp_order_id

    if dto.reverse_trade_sl_order_id is not None:
        default_log.debug(f"Updating reverse_trade_sl_order_id to={dto.reverse_trade_sl_order_id}")
        thread_detail.reverse_trade_sl_order_id = dto.reverse_trade_sl_order_id

    if dto.reverse1_entry_price is not None:
        default_log.debug(f"Updating reverse1_entry_price to={dto.reverse1_entry_price}")
        thread_detail.reverse1_entry_price = dto.reverse1_entry_price

    if dto.reverse2_entry_price is not None:
        default_log.debug(f"Updating reverse2_entry_price to={dto.reverse2_entry_price}")
        thread_detail.reverse1_entry_price = dto.reverse2_entry_price

    if dto.cover_sl_quantity is not None:
        default_log.debug(f"Updating cover_sl_quantity to={dto.cover_sl_quantity}")
        thread_detail.cover_sl_quantity = dto.cover_sl_quantity

    if dto.cover_sl_trade_order_id is not None:
        default_log.debug(f"Updating cover_sl_trade_order_id to={dto.cover_sl_trade_order_id}")
        thread_detail.cover_sl_trade_order_id = dto.cover_sl_trade_order_id

    if dto.extended_sl is not None:
        default_log.debug(f"Updating extended_sl to={dto.extended_sl}")
        thread_detail.extended_sl = dto.extended_sl

    if dto.trade_alert_status is not None:
        default_log.debug(f"Updating trade_alert_status to={dto.trade_alert_status}")
        thread_detail.trade_alert_status = dto.trade_alert_status

    if dto.extended_sl_timestamp is not None:
        default_log.debug(f"Updating extended_sl_timestamp to={dto.extended_sl_timestamp}")
        thread_detail.extended_sl_timestamp = dto.extended_sl_timestamp

    db.add(thread_detail)

    if commit:
        default_log.debug("Committing thread event details")
        db.commit()
    else:
        default_log.debug("Flushing thread event details")
        db.flush()

    return thread_detail.id
