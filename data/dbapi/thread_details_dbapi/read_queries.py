from datetime import date, datetime

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
        ThreadDetails.is_completed == False
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
    start_of_day = datetime.combine(current_date, datetime.min.time())
    end_of_day = datetime.combine(current_date, datetime.max.time())

    thread_details = (
        db.query(ThreadDetails)
        .filter(ThreadDetails.event1_occur_time >= start_of_day)
        .filter(ThreadDetails.event1_occur_time <= end_of_day)
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
            date_time=thread_detail.event1_occur_time,
            symbol=thread_detail.symbol,
            time_frame=thread_detail.time_frame,
            event_one=event_one,
            event_two=event_two,
            event_three=event_three,
            take_profit=thread_detail.tp_value,
            stop_loss=thread_detail.sl_value,
            quantity=int(thread_detail.trade1_quantity) if thread_detail.trade1_quantity is not None else None,
            extension_quantity_one=thread_detail.extension1_quantity,
            extension_quantity_two=thread_detail.extension2_quantity,
            trade_status="COMPLETED" if thread_detail.is_completed else "PENDING"
        )

        retval.append(event_detail)

    default_log.debug(f"returning {len(retval)} event details")
    return retval