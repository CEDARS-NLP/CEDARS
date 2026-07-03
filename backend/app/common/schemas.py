"""Shared Pydantic response schemas."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated list response: items plus offset/limit metadata."""

    items: list[T]
    total: int
    limit: int
    offset: int
