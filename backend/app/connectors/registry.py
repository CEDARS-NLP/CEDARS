"""Connector registry — maps connector types to implementations."""

from app.connectors.base import ConnectorBase
from app.connectors.models import ConnectorType

_registry: dict[ConnectorType, type[ConnectorBase]] = {}


def register_connector(connector_type: ConnectorType, cls: type[ConnectorBase]) -> None:
    """Register a connector implementation."""
    _registry[connector_type] = cls


def get_connector(connector_type: ConnectorType) -> ConnectorBase:
    """Get a connector instance by type."""
    cls = _registry.get(connector_type)
    if cls is None:
        raise ValueError(f"Unknown connector type: {connector_type}")
    return cls()


def list_connector_types() -> list[str]:
    """List all registered connector type names."""
    return [ct.value for ct in _registry]


def _register_builtins() -> None:
    """Register built-in connectors."""
    from app.connectors.file_upload import FileUploadConnector

    register_connector(ConnectorType.FILE_UPLOAD, FileUploadConnector)

    try:
        from app.connectors.databricks import DatabricksConnector

        register_connector(ConnectorType.DATABRICKS, DatabricksConnector)
    except ImportError:
        pass  # databricks-sql-connector not installed


_register_builtins()
