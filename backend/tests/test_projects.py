"""Tests for project models and schemas."""

from app.projects.models import Project, ProjectMember, ProjectRole
from app.projects.schemas import (
    AddMemberRequest,
    CreateProjectRequest,
    ProjectMemberResponse,
    ProjectResponse,
    UpdateProjectRequest,
)


# --- ProjectRole Enum Tests ---


def test_project_role_enum_values():
    assert ProjectRole.ADMIN.value == "admin"
    assert ProjectRole.ANNOTATOR.value == "annotator"
    assert ProjectRole.VIEWER.value == "viewer"


def test_project_role_is_string():
    """ProjectRole values should be usable as plain strings."""
    assert ProjectRole.ADMIN == "admin"
    assert ProjectRole.ANNOTATOR == "annotator"
    assert ProjectRole.VIEWER == "viewer"


# --- Project Model Tests ---


def test_project_model_creation():
    project = Project(
        name="MI Study",
        description="Myocardial infarction detection",
        owner_id="user-123",
    )
    assert project.name == "MI Study"
    assert project.description == "Myocardial infarction detection"
    assert project.owner_id == "user-123"


def test_project_model_defaults():
    project = Project(name="Test Project", owner_id="user-123")
    assert project.id is not None
    assert project.description == ""
    assert project.settings == {}
    assert project.created_at is not None
    assert project.deleted_at is None


def test_project_model_with_settings():
    project = Project(
        name="Custom Project",
        owner_id="user-123",
        settings={"llm_provider": "openai", "model": "gpt-4o"},
    )
    assert project.settings == {"llm_provider": "openai", "model": "gpt-4o"}


# --- ProjectMember Model Tests ---


def test_project_member_creation():
    member = ProjectMember(
        project_id="proj-1",
        user_id="user-456",
        role=ProjectRole.ADMIN,
    )
    assert member.project_id == "proj-1"
    assert member.user_id == "user-456"
    assert member.role == ProjectRole.ADMIN


def test_project_member_defaults():
    member = ProjectMember(project_id="proj-1", user_id="user-456")
    assert member.id is not None
    assert member.role == ProjectRole.ANNOTATOR
    assert member.created_at is not None


# --- Schema Tests ---


def test_create_project_request():
    req = CreateProjectRequest(name="New Project")
    assert req.name == "New Project"
    assert req.description == ""


def test_create_project_request_with_description():
    req = CreateProjectRequest(name="Study", description="A clinical study")
    assert req.description == "A clinical study"


def test_update_project_request_partial():
    req = UpdateProjectRequest(name="Updated Name")
    assert req.name == "Updated Name"
    assert req.description is None
    assert req.settings is None


def test_project_response():
    resp = ProjectResponse(
        id="proj-1",
        name="Test",
        description="Desc",
        owner_id="user-1",
        settings={},
        created_at="2026-01-01T00:00:00Z",
        role="admin",
    )
    assert resp.id == "proj-1"
    assert resp.role == "admin"


def test_project_member_response():
    resp = ProjectMemberResponse(
        user_id="user-1",
        email="test@example.com",
        name="Test User",
        role="annotator",
    )
    assert resp.email == "test@example.com"


def test_add_member_request_defaults():
    req = AddMemberRequest(email="user@example.com")
    assert req.role == "annotator"


def test_add_member_request_custom_role():
    req = AddMemberRequest(email="admin@example.com", role="admin")
    assert req.role == "admin"
