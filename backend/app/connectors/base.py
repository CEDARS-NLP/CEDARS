"""Abstract base class for data connectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class PreviewResult:
    """Result of previewing data from a connector."""

    columns: list[str]
    rows: list[dict[str, Any]]
    total_available: int | None = None


@dataclass
class FetchResult:
    """A batch of rows fetched from a connector."""

    rows: list[dict[str, Any]]
    has_more: bool = False
    offset: int = 0
    total_rows: int | None = None


class ConnectorBase(ABC):
    """Base class for all data connectors.

    Connectors know how to connect to a data source, preview data,
    and fetch rows in batches for ingestion.
    """

    @abstractmethod
    async def validate_config(self, config: dict) -> list[str]:
        """Validate connector configuration. Return list of error messages (empty = valid)."""

    @abstractmethod
    async def preview(self, config: dict, limit: int = 10) -> PreviewResult:
        """Preview rows from the data source without full ingestion."""

    @abstractmethod
    async def fetch(
        self, config: dict, batch_size: int = 1000, offset: int = 0
    ) -> FetchResult:
        """Fetch a batch of rows from the data source."""

    @abstractmethod
    def required_columns(self) -> list[str]:
        """Return column names required by this connector.

        At minimum, connectors must provide 'patient_id' and 'text'.
        """
