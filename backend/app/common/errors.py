"""Shared HTTP error helpers for routers."""

from typing import NoReturn

from fastapi import HTTPException, status


def raise_not_found(detail: str = "Not found") -> NoReturn:
    """Raise a 404 HTTPException with the given detail message."""
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
