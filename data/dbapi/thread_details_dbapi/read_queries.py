from datetime import date, datetime, timedelta

from config import default_log
from data.dbapi.thread_details_dbapi.dtos.event_detail_dto import EventDetailDTO
from data.dbapi.thread_details_dbapi.dtos.single_event_detail_dto import SingleEventDetailDTO
from decorators.handle_generic_exception import dbapi_exception_handler
from data.db.init_db import get_db
from data.models.thread_details import ThreadDetails


@dbapi_exception_handler
def get_all_incomplete_thread_details(session=None, close_session=True):
    default_log.debug("inside get_all_incomplete_thread_details")

    db = session if session else next(get_db())

    # current_date = date.today()

    # Adjust the time to midnight of the current date
    # start_of_day = datetime.combine(current_date, datetime.min.time())
    # end_of_day = datetime.combine(current_date, datetime.max.time())

    thread_details = db.query(
        ThreadDetails
    ).filter(
        ThreadDetails.is_completed == False,
        ThreadDetails.trade_alert_status != "NEXT DAY"
    ).order_by(
        ThreadDetails.id.asc()
    ).all()

    default_log.debug(f"{len(thread_details)} non completed threads retrieved")

    return thread_details


@dbapi_exception_handler
def get_all_continuity_thread_details(session=None, close_session=True):
    default_log.debug("inside get_all_incomplete_thread_details")

    db = session if session else next(get_db())

    # current_date = date.today()

    # Adjust the time to midnight of the current date
    # start_of_day = datetime.combine(current_date, datetime.min.time())
    # end_of_day = datetime.combine(current_date, datetime.max.time())

    thread_details = db.query(
        ThreadDetails
    ).filter(
        ThreadDetails.trade_alert_status == "NEXT DAY"
    ).order_by(
        ThreadDetails.id.asc()
    ).all()

    default_log.debug(f"{len(thread_details)} non completed threads retrieved")

    return thread_details


@dbapi_exception_handler
def fetch_all_event_details(session=None, close_session=True):
    default_log.debug("inside get_all_event_details")

    db = session if session else next(get_db())

    # Assuming db is your SQLAlchemy session
    current_date = date.today()

    # Adjust the time to midnight of the current date
    # start_of_day = datetime.combine(current_date, datetime.min.time())
    # start_of_day = start_of_day - timedelta(days=3)
    # end_of_day = datetime.combine(current_date, datetime.max.time())

    thread_details = (
        db.query(ThreadDetails)
        .order_by(ThreadDetails.id.desc())
        .all()
    )

    default_log.debug(f"found {len(thread_details)} events")

    retval = []
    for thread_detail in thread_details:
        event_one = EventDetailDTO(
            time=thread_detail.event1_occur_time,
            event1_candle_high=thread_detail.signal_candle_high,
            event1_candle_low=thread_detail.signal_candle_low,
            adjusted_high=thread_detail.adjusted_high,
            adjusted_low=thread_detail.adjusted_low
        )

        event_two = EventDetailDTO(
            time=thread_detail.event2_occur_time,
            event2_breakpoint=thread_detail.event2_breakpoint
        )

        event_three = EventDetailDTO(
            time=thread_detail.event3_occur_time,
            entry_price=thread_detail.entry_price
        )

        event_detail = SingleEventDetailDTO(
            date_time=thread_detail.alert_time,
            symbol=thread_detail.symbol,
            time_frame=thread_detail.time_frame,
            signal_type=thread_detail.signal_type,
            event_one=event_one,
            event_two=event_two,
            event_three=event_three,
            take_profit=thread_detail.tp_value,
            stop_loss=thread_detail.sl_value,
            quantity=int(thread_detail.trade1_quantity) if thread_detail.trade1_quantity is not None else None,
            extension_quantity_one=thread_detail.extension1_quantity,
            extension_quantity_two=thread_detail.extension2_quantity,
            extended_sl=thread_detail.extended_sl,
            extended_sl_timestamp=thread_detail.extended_sl_timestamp,
            cover_sl=thread_detail.cover_sl,
            cover_sl_quantity=thread_detail.cover_sl_quantity,
            reverse1_trade_quantity=thread_detail.reverse1_trade_quantity,
            reverse2_trade_quantity=thread_detail.reverse2_trade_quantity,
            reverse_trade_take_profit=thread_detail.reverse_trade_take_profit,
            reverse_trade_stop_loss=thread_detail.reverse_trade_stop_loss,
            reverse1_entry_price=thread_detail.reverse1_entry_price,
            reverse2_entry_price=thread_detail.reverse2_entry_price,
            trade_status=thread_detail.trade_alert_status
        )

        retval.append(event_detail)

    default_log.debug(f"returning {len(retval)} event details")
    return retval


@dbapi_exception_handler
def get_thread_details_with_live_trade_sent(session=None, close_session=True):
    default_log.debug(f"inside get_thread_details_with_live_trade_sent")

    db = session if session else next(get_db())

    query = """
        SELECT 
            * 
        FROM THREAD_DETAILS 
        WHERE 
            SIGNAL_TRADE_ORDER_ID IS NOT NULL OR 
            EXTENSION1_ORDER_ID IS NOT NULL OR
            EXTENSION2_ORDER_ID IS NOT NULL OR
            COVER_SL_TRADE_ORDER_ID IS NOT NULL OR 
            REVERSE1_TRADE_ORDER_ID IS NOT NULL OR 
            REVERSE2_TRADE_ORDER_ID IS NOT NULL 
        ORDER BY ID DESC
    """

    thread_details = db.execute(query).all()

    default_log.debug(f"{len(thread_details)} thread_details retrieved having at least one live trade sent")

    return thread_details
