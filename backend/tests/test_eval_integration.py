"""End-to-end integration test for the unified evaluation session workflow."""

from datetime import datetime
import pytest
from unittest.mock import AsyncMock, patch

from app.pipeline.classifier import ClassificationResult


@pytest.fixture
async def project_with_data(auth_client, app):
    """Create project and seed with test patients + notes."""
    resp = await auth_client.post("/api/v1/projects", json={
        "name": "EvalTestProject",
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
    })
    assert resp.status_code == 201
    project_id = resp.json()["id"]

    # Get the overridden test database session from the app fixture
    from app.common.database import get_session
    from app.connectors.models import Patient, Note

    # Access the dependency override directly from the app
    override_func = app.dependency_overrides[get_session]
    async for db in override_func():
        for i in range(5):
            p = Patient(
                id=f"eval-pat-{i}",
                project_id=project_id,
                patient_id_ext=f"EXT-{i}",
            )
            db.add(p)
            await db.flush()

            n1 = Note(
                id=f"eval-note-{i}-0",
                project_id=project_id,
                patient_id=p.id,
                text_id=f"T{i}0",
                note_date=datetime(2024, 1, 15),
                text="Patient presents with troponin elevation at 2.4 ng/mL. ECG shows ST changes.",
            )
            n2 = Note(
                id=f"eval-note-{i}-1",
                project_id=project_id,
                patient_id=p.id,
                text_id=f"T{i}1",
                note_date=datetime(2024, 1, 16),
                text="Follow-up visit. Patient stable. No acute complaints.",
            )
            db.add_all([n1, n2])
        await db.commit()
        break  # Only iterate once

    return project_id


class TestUnifiedEvalSessionWorkflow:
    """Tests the full evaluation session workflow end-to-end."""

    async def test_full_workflow(self, auth_client, app, project_with_data):
        pid = project_with_data
        base = f"/api/v1/projects/{pid}/evaluation"

        # 1. Create session
        resp = await auth_client.post(f"{base}/sessions", json={
            "search_queries": [{"query": "troponin", "type": "include"}],
        })
        assert resp.status_code == 201
        session = resp.json()
        sid = session["id"]
        assert session["status"] == "draft"
        assert session["sample_size"] == 5

        # 2. Get funnel stats (before search execution)
        resp = await auth_client.get(f"{base}/sessions/{sid}/funnel")
        assert resp.status_code == 200
        funnel = resp.json()
        assert funnel["sample_patients"] == 5

        # 3. Execute search queries
        with patch("app.evaluation.service.parse_query") as mock_parse, \
             patch("app.evaluation.service.process_note") as mock_process:
            # Mock search to match notes containing "troponin"
            mock_parse.return_value = [["troponin"]]
            def fake_process(text, groups):
                if "troponin" in text.lower():
                    return [{"is_target": True, "is_negated": False, "matched_tokens": ["troponin"],
                             "start_pos": text.lower().index("troponin"), "end_pos": text.lower().index("troponin") + 8,
                             "sentence_number": 0, "text": text}]
                return []
            mock_process.side_effect = fake_process

            resp = await auth_client.post(f"{base}/sessions/{sid}/queries/execute")
        assert resp.status_code == 200
        funnel = resp.json()
        assert funnel["matched_patients"] > 0

        # 4. Update event config
        resp = await auth_client.put(f"{base}/sessions/{sid}/event-config", json={
            "event_name": "Myocardial Infarction",
            "event_description": "Confirmed MI with troponin elevation",
            "include_criteria": "Troponin elevation, ECG changes",
            "exclude_criteria": "Rule-out, family history only",
        })
        assert resp.status_code == 200
        assert resp.json()["event_name"] == "Myocardial Infarction"

        # 5. Run LLM classification. The endpoint enqueues an ARQ job and returns
        #    202; the actual classification happens in the worker via
        #    execute_sample_llm. We mock the enqueue (no Redis in tests) then drive
        #    the worker function directly, mirroring what the worker would do.
        mock_result = ClassificationResult(
            label="positive",
            confidence=0.92,
            reasoning="Troponin elevated at 2.4 ng/mL with ECG changes",
            event_date="2024-01-15",
            evidence=[{
                "note_id": "eval-note-0-0",
                "text": "troponin elevation at 2.4 ng/mL",
                "note_date": "2024-01-15",
            }],
            token_usage={"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
        )

        mock_pool = AsyncMock()
        with patch("arq.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            resp = await auth_client.post(f"{base}/sessions/{sid}/run-llm")
        assert resp.status_code == 202
        run_stats = resp.json()
        assert run_stats["status"] == "started"
        assert run_stats["matched_patients"] > 0
        # The endpoint should have enqueued the worker job.
        mock_pool.enqueue_job.assert_awaited_once()

        # Drive the worker job inline using the test database session.
        from app.common.database import get_session
        from app.evaluation import service as eval_service

        override_func = app.dependency_overrides[get_session]
        async for db in override_func():
            with patch.object(
                eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result
            ):
                worker_stats = await eval_service.execute_sample_llm(sid, pid, db_session=db)
            break
        assert worker_stats["patients_classified"] > 0

        # 6. Session should now be REVIEWING
        resp = await auth_client.get(f"{base}/sessions/{sid}")
        assert resp.json()["status"] == "reviewing"

        # 7. List results
        resp = await auth_client.get(f"{base}/sessions/{sid}/results")
        assert resp.status_code == 200
        results = resp.json()
        assert results["total"] > 0

        # 8. Submit judgment on first positive result
        positive_results = [r for r in results["results"] if r.get("finding_label") == "positive"]
        assert len(positive_results) > 0

        result_id = positive_results[0]["id"]
        resp = await auth_client.post(f"{base}/sessions/{sid}/results/{result_id}/judge", json={
            "judgment": "correct",
            "event_date_override": "2024-01-15",
        })
        assert resp.status_code == 200

        # 9. Check metrics
        resp = await auth_client.get(f"{base}/sessions/{sid}/metrics")
        assert resp.status_code == 200
        metrics = resp.json()
        assert metrics["total_reviewed"] >= 1

        # 10. Commit (mocked pipeline dispatch)
        with patch("app.evaluation.service.dispatch_full_pipeline_run", new_callable=AsyncMock) as mock_dispatch:
            from app.pipeline.models import PipelineRun, PipelineRunStatus

            mock_run = PipelineRun(
                id="mock-run-id",
                project_id=pid,
                event_config_id="fake-ec-id",
                run_type="full",
                status=PipelineRunStatus.QUEUED,
                total_patients=5,
                created_by="user-1",
            )
            mock_dispatch.return_value = mock_run

            resp = await auth_client.post(f"{base}/sessions/{sid}/commit", json={})

        assert resp.status_code == 200
        commit_data = resp.json()
        assert commit_data["pipeline_run_id"] == "mock-run-id"

        # 11. Session should be COMMITTED
        resp = await auth_client.get(f"{base}/sessions/{sid}")
        assert resp.json()["status"] == "committed"

    async def test_discard_and_create_new(self, auth_client, project_with_data):
        """Test that discarding a session allows creating a new one."""
        pid = project_with_data
        base = f"/api/v1/projects/{pid}/evaluation"

        # Create first session
        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": []})
        assert resp.status_code == 201
        sid1 = resp.json()["id"]

        # Can't create another while active
        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": []})
        assert resp.status_code == 409

        # Discard first
        resp = await auth_client.delete(f"{base}/sessions/{sid1}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

        # Now can create new
        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": []})
        assert resp.status_code == 201
        assert resp.json()["id"] != sid1


class TestSessionInputBounds:
    """Guard the search_queries list bound (evaluation/schemas.py)."""

    async def test_create_session_rejects_oversized_query_list(
        self, auth_client, project_with_data
    ):
        """A search_queries list past the cap is rejected with 422, not run.

        Each query fans out across every note of every sampled patient, so an
        unbounded list is a real DoS/memory vector — the cap must be enforced
        at the API boundary.
        """
        base = f"/api/v1/projects/{project_with_data}/evaluation"
        oversized = [{"query": f"term{i}", "type": "include"} for i in range(51)]

        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": oversized})
        assert resp.status_code == 422

    async def test_create_session_accepts_list_at_cap(
        self, auth_client, project_with_data
    ):
        """Exactly the cap (50) is still accepted."""
        base = f"/api/v1/projects/{project_with_data}/evaluation"
        at_cap = [{"query": f"term{i}", "type": "include"} for i in range(50)]

        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": at_cap})
        assert resp.status_code == 201
