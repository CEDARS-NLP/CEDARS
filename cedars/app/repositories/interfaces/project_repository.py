"""Project repository interface."""

from abc import ABC, abstractmethod
from typing import Optional

from app.models.project import ProjectInfo
from app.models.query import Query
from app.models.result import Result


class ProjectRepositoryInterface(ABC):
    """Abstract interface for project and configuration data access."""

    # Project info operations
    @abstractmethod
    def get_info(self) -> Optional[dict]:
        """Get project info as a dictionary."""
        pass

    @abstractmethod
    def get_project_name(self) -> Optional[str]:
        """Get the project name."""
        pass

    @abstractmethod
    def get_version(self) -> Optional[str]:
        """Get the CEDARS version."""
        pass

    @abstractmethod
    def create_project(
        self,
        project_name: str,
        investigator_name: str,
        project_id: str,
        cedars_version: Optional[str] = None,
    ) -> bool:
        """Create a new project. Returns True if successful."""
        pass

    @abstractmethod
    def update_project_name(self, new_name: str) -> bool:
        """Update the project name."""
        pass

    # PINES configuration
    @abstractmethod
    def get_pines_url(self) -> Optional[str]:
        """Get the PINES API URL."""
        pass

    @abstractmethod
    def is_pines_enabled(self) -> bool:
        """Check if PINES API is enabled."""
        pass

    @abstractmethod
    def update_pines_url(self, url: str) -> bool:
        """Update the PINES API URL."""
        pass

    @abstractmethod
    def update_pines_status(self, enabled: bool) -> bool:
        """Enable or disable PINES API."""
        pass

    @abstractmethod
    def create_pines_info(self, pines_url: str, is_url_from_api: bool) -> bool:
        """Create PINES configuration."""
        pass

    # Query operations
    @abstractmethod
    def get_search_query(self, key: str = "query") -> Optional[str]:
        """Get the current search query value."""
        pass

    @abstractmethod
    def get_search_query_details(self) -> Optional[Query]:
        """Get full search query configuration."""
        pass

    @abstractmethod
    def save_query(
        self,
        query: str,
        exclude_negated: bool,
        hide_duplicates: bool,
        skip_after_event: bool,
        tag_query: dict,
        date_range: Optional[tuple],
    ) -> bool:
        """Save search query configuration."""
        pass

    # Results operations
    @abstractmethod
    def get_results(self, patient_id: str) -> Optional[Result]:
        """Get results for a patient."""
        pass

    @abstractmethod
    def results_exist(self, patient_id: str) -> bool:
        """Check if results exist for a patient."""
        pass

    @abstractmethod
    def upsert_results(self, patient_id: str, results: dict) -> bool:
        """Insert or update patient results."""
        pass

    @abstractmethod
    def get_all_results(self, columns: Optional[list[str]] = None) -> list[dict]:
        """Get all results, optionally with specific columns."""
        pass

    # Statistics
    @abstractmethod
    def get_stats(self) -> dict:
        """Get current project statistics."""
        pass

    # Database operations
    @abstractmethod
    def create_indices(self) -> None:
        """Create database indices."""
        pass

    @abstractmethod
    def drop_database(self, name: str) -> bool:
        """Drop a database/collection."""
        pass

    @abstractmethod
    def terminate_project(self) -> bool:
        """Terminate and clean up the project."""
        pass
