"""Trusted routing context for one project database."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """Identify a validated project without exposing its database credentials."""

    project_id: str
    routing_version: int = 1

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("project_id must not be empty")
        if self.routing_version < 1:
            raise ValueError("routing_version must be positive")
