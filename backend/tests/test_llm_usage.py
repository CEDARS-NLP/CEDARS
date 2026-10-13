"""LLM usage ledger: scope capture, cost at call time, and the project report."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.llm.client import complete
from app.llm.usage import LlmUsage, UsageScope, add_usage


def _fake_response(prompt=1000, completion=100):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
        ),
    )


async def _project(client, email="usage@test.com"):
    await client.post(
        "/api/v1/auth/register", json={"email": email, "name": "U", "password": "testpass123"}
    )
    await client.post("/api/v1/auth/login", json={"email": email, "password": "testpass123"})
    resp = await client.post("/api/v1/projects", json={"name": "Usage Project"})
    return resp.json()["id"]


async def test_scope_records_calls_made_inside_it(client, session_factory):
    project_id = await _project(client)
    with patch("app.llm.client.litellm.acompletion", new=AsyncMock(return_value=_fake_response())):
        with UsageScope(project_id, "query_suggestion", ref_id="s1") as scope:
            await complete(provider="openai", model="gpt-4o-mini", messages=[])
        await complete(provider="openai", model="gpt-4o-mini", messages=[])  # outside: not recorded

    async with session_factory() as db:
        assert scope.flush(db) == 1
        await db.commit()
        row = (await db.execute(select(LlmUsage))).scalars().one()
    assert (row.project_id, row.source, row.ref_id) == (project_id, "query_suggestion", "s1")
    assert (row.prompt_tokens, row.completion_tokens) == (1000, 100)
    assert row.estimated_cost == (1000 * 0.15 + 100 * 0.60) / 1e6  # priced when the call ran


async def test_report_totals_groups_and_unpriced_calls(client, session_factory):
    project_id = await _project(client)
    async with session_factory() as db:
        for source, provider, model, usage in [
            ("evaluation_sample", "openai", "gpt-4o", {"prompt_tokens": 1_000_000, "completion_tokens": 0}),
            ("evaluation_sample", "openai", "gpt-4o", {"prompt_tokens": 1_000_000, "completion_tokens": 0}),
            ("bulk_prediction", "ollama", "llama3", {"prompt_tokens": 500, "completion_tokens": 50}),
        ]:
            add_usage(db, project_id=project_id, source=source, provider=provider, model=model, usage=usage)
        await db.commit()

    resp = await client.get(f"/api/v1/projects/{project_id}/llm-usage")

    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["calls"] == 3
    assert body["totals"]["prompt_tokens"] == 2_000_500
    assert body["totals"]["estimated_cost"] == 5.0  # 2M tokens of gpt-4o at $2.50/M
    assert body["totals"]["unpriced_calls"] == 1  # the local model has no price
    assert [g["key"] for g in body["by_source"]] == ["evaluation_sample", "bulk_prediction"]
    assert {g["key"] for g in body["by_model"]} == {"gpt-4o", "llama3"}
    assert len(body["by_day"]) == 1 and body["by_day"][0]["tokens"] == 2_000_550


async def test_report_is_scoped_to_the_project(client, session_factory):
    mine = await _project(client)
    resp = await client.post("/api/v1/projects", json={"name": "Other"})
    other = resp.json()["id"]
    async with session_factory() as db:
        add_usage(db, project_id=other, source="pipeline_run", provider="openai",
                  model="gpt-4o", usage={"prompt_tokens": 10, "completion_tokens": 1})
        await db.commit()

    body = (await client.get(f"/api/v1/projects/{mine}/llm-usage")).json()

    assert body["totals"]["calls"] == 0
    assert body["totals"]["estimated_cost"] is None


async def test_report_requires_login(client):
    assert (await client.get("/api/v1/projects/x/llm-usage")).status_code == 401
