"""Unit tests for per-project Redis queue naming/connection wiring and ACL
credential storage (see app.queues / app.database.redis_acl).

Note: the test suite backs Redis with fakeredis (see conftest.py), which does
not enforce real ACL restrictions. These tests verify wiring - correct queue
names, one explicit job_id per enqueue, and credential storage/retrieval -
not actual cross-project key-access denial (that requires a real Redis server;
see docs/CEDARS_admin_manual.md).
"""
import pytest

from app import queues
from app.database import get_global_engine
from app.database.redis_acl import (get_project_redis_credentials,
                                    redis_acl_username)

GOOD_PASSWORD = "Abcdef12!!"


@pytest.fixture()
def project_id(client):
    client.post("/api/v1/auth/register", json={
        "username": "AdminUser", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    return client.post("/api/v1/projects", json={"name": "Cohort"}).json()["id"]


def test_queue_names_are_project_scoped(project_id):
    assert queues.task_queue_name(project_id) == f"task-{project_id}"
    assert queues.ops_queue_name(project_id) == f"ops-{project_id}"


def test_invalid_project_id_rejected():
    with pytest.raises(ValueError):
        queues.task_queue_name("../etc/passwd")


def test_enqueue_assigns_queue_prefixed_job_id(project_id):
    job = queues.get_ops_queue(project_id).enqueue(sum, [1, 2])
    assert job.get_id().startswith(f"{queues.ops_queue_name(project_id)}-")


def test_redis_credentials_are_provisioned_on_project_creation(project_id):
    username, secret = get_project_redis_credentials(get_global_engine(), project_id)
    assert username == redis_acl_username(project_id)
    assert secret


def test_missing_credentials_raise(project_id):
    with pytest.raises(RuntimeError):
        get_project_redis_credentials(get_global_engine(), "no-such-project")
