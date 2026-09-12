from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    request_id: str
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class MessageResponse(BaseModel):
    message: str


class PageInfo(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int

