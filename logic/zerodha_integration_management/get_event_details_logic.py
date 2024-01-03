from config import default_log
from data.dbapi.thread_details_dbapi.read_queries import fetch_all_event_details
from logic.zerodha_integration_management.dtos.all_event_details_response_dto import AllEventDetailsResponse
from standard_responses.dbapi_exception_response import DBApiExceptionResponse


def get_all_event_details() -> AllEventDetailsResponse:
    default_log.debug(f"inside logic.get_all_event_details")

    # Fetch event details
    event_details = fetch_all_event_details()

    if type(event_details) == DBApiExceptionResponse:
        default_log.debug(f"An error occurred while fetching event details: {event_details.error}")
        return AllEventDetailsResponse(error=True, error_message="An error occurred while fetching all event details")

    return AllEventDetailsResponse(error=False, data=event_details)

