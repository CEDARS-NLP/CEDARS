"""End-to-end integration test for the agentic pipeline workflow.

Workflow: create event config → generate patterns → run sample →
check stats/tasks → commit → run full → verify run history.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_pipeline_api import EVENT_CONFIG_BODY, create_project, register_and_login
from tests.test_pipeline_orchestration import _seed_patients


MOCK_PATTERNS = {
    "keywords": ["troponin", "myocardial infarction", "chest pain"],
    "regex_patterns": [r"troponin\s+(?:level|elevation)"],
    "exclusion_patterns": ["rule-out", "family history"],
}


class TestPipelineE2E:
    """Full workflow test covering the agentic pipeline from config to run."""

    async def test_full_workflow(self, app, client):
        # 1. Setup: register, create project, seed patients
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=5)

        # 2. Create event config
        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json=EVENT_CONFIG_BODY,
        )
        assert resp.status_code == 201
        ec = resp.json()
        eid = ec["id"]
        assert ec["is_committed"] is False
        assert ec["name"] == EVENT_CONFIG_BODY["name"]

        # 3. Generate search patterns (mocked LLM)
        with patch(
            "app.pipeline.pattern_generator.generate_search_patterns",
            new_callable=AsyncMock,
            return_value=MOCK_PATTERNS,
        ):
            resp = await client.post(
                f"/api/v1/projects/{pid}/pipeline/events/{eid}/generate-patterns",
            )
            assert resp.status_code == 200
            ec = resp.json()
            assert ec["search_patterns"]["keywords"] == MOCK_PATTERNS["keywords"]

        # 4. Run sample
        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 3},
        )
        assert resp.status_code == 200
        run = resp.json()
        run_id = run["id"]
        assert run["run_type"] == "sample"
        assert run["total_patients"] == 3
        assert run["status"] == "queued"

        # 5. Check run stats
        resp = await client.get(
            f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/stats",
        )
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total"] == 3
        assert stats["queued"] == 3

        # 6. Check tasks
        resp = await client.get(
            f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/tasks",
        )
        assert resp.status_code == 200
        tasks = resp.json()
        assert len(tasks) == 3
        assert all(t["status"] == "queued" for t in tasks)

        # 7. Check metrics (no reviews yet)
        resp = await client.get(
            f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/metrics",
        )
        assert resp.status_code == 200
        metrics = resp.json()
        assert metrics["total_reviewed"] == 0
        assert metrics["precision"] is None

        # 8. Cancel the sample run so we can start fresh
        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/cancel",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # 9. Commit the event config
        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit",
            json={"confidence_threshold": 0.7},
        )
        assert resp.status_code == 200
        ec = resp.json()
        assert ec["is_committed"] is True
        assert ec["confidence_threshold"] == 0.7

        # 10. Cannot modify committed config
        resp = await client.put(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 400
        assert "committed" in resp.json()["detail"].lower()

        # 11. Run full pipeline
        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-full",
        )
        assert resp.status_code == 200
        full_run = resp.json()
        assert full_run["run_type"] == "full"
        assert full_run["total_patients"] == 5  # all patients

        # 12. List runs — should see both sample (cancelled) and full
        resp = await client.get(
            f"/api/v1/projects/{pid}/pipeline/runs?event_config_id={eid}",
        )
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 2
        run_types = {r["run_type"] for r in runs}
        assert run_types == {"sample", "full"}

        # 13. Get single run detail
        resp = await client.get(
            f"/api/v1/projects/{pid}/pipeline/runs/{full_run['id']}",
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == full_run["id"]

    async def test_concurrent_run_blocked(self, app, client):
        """Decision #35: cannot have two active runs for the same event config."""
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=5)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json=EVENT_CONFIG_BODY,
        )
        eid = resp.json()["id"]

        # First run succeeds
        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        assert resp.status_code == 200

        # Second run blocked
        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        assert resp.status_code == 400
        assert "active" in resp.json()["detail"].lower()

    async def test_full_run_requires_committed(self, app, client):
        """Full runs require committed config."""
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=3)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json=EVENT_CONFIG_BODY,
        )
        eid = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-full",
        )
        assert resp.status_code == 400
        assert "committed" in resp.json()["detail"].lower()
