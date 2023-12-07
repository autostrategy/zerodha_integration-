from typing import Optional
from pydantic import BaseModel

from data.dbapi.thread_details_dbapi.dtos.single_event_detail_dto import SingleEventDetailDTO


class AllEventDetailsResponse(BaseModel):
    error: bool
    error_message: Optional[str]
    data: Optional[list[SingleEventDetailDTO]]
