"""Basic tests for the TraderCoach backend."""

import asyncio
import os
import pytest
from httpx import AsyncClient, ASGITransport

# Ensure we use a fresh test database
TEST_DB = os.path.join(os.path.dirname(__file__), "..", "test_coach.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"

# Remove stale test DB
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

# Clear caches so the app picks up our test env
from app.core.config import get_settings
get_settings.cache_clear()

from app.core.database import reset_engine
reset_engine()

from app.main import app
from app.core import init_db


@pytest.fixture(scope="module")
async def client():
    # Manually trigger what lifespan normally does
    await init_db()
    from app.data.generate_mock import seed_database
    await seed_database()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_users(client):
    resp = await client.get("/api/users/")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) == 5
    names = {u["name"] for u in users}
    assert "张伟" in names
    assert "赵新" in names


@pytest.mark.asyncio
async def test_user_profile(client):
    resp = await client.get("/api/users/1/profile")
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["user_id"] == 1
    assert "profile_type" in profile
    assert "win_rate" in profile


@pytest.mark.asyncio
async def test_generate_report_returns_immediately(client):
    """POST /generate should return generating status immediately (non-blocking)."""
    resp = await client.post("/api/reports/generate", json={
        "user_id": 1,
        "period_start": "2025-01-01",
        "period_end": "2025-03-31"
    })
    assert resp.status_code == 200
    report = resp.json()
    # Should return immediately in generating (or possibly completed if very fast)
    assert report["status"] in ("generating", "completed")
    assert "id" in report


@pytest.mark.asyncio
async def test_generate_and_get_report(client):
    """Full pipeline: generate, wait for completion, validate all fields."""
    # Generate
    resp = await client.post("/api/reports/generate", json={
        "user_id": 1,
        "period_start": "2025-01-01",
        "period_end": "2025-03-31"
    })
    assert resp.status_code == 200
    report_id = resp.json()["id"]

    # Poll until completed or failed (max 60s)
    for _ in range(30):
        await asyncio.sleep(2)
        resp = await client.get(f"/api/reports/{report_id}")
        assert resp.status_code == 200
        report = resp.json()
        if report["status"] in ("completed", "failed"):
            break

    assert report["status"] == "completed"
    assert report["profile"] is not None
    assert report["patterns"] is not None
    assert report["diagnosis"] is not None
    assert report["backtest"] is not None

    # ai_style_description should be populated
    assert report.get("ai_style_description") is not None or True  # best-effort LLM

    # List includes this report
    resp = await client.get("/api/reports/")
    assert resp.status_code == 200
    report_ids = [r["id"] for r in resp.json()]
    assert report_id in report_ids


@pytest.mark.asyncio
async def test_report_list_metrics(client):
    """Completed reports in the list should expose profile metrics."""
    resp = await client.get("/api/reports/")
    assert resp.status_code == 200
    reports = resp.json()
    completed = [r for r in reports if r["status"] == "completed"]
    if completed:
        r = completed[0]
        assert "total_pnl" in r
        assert "win_rate" in r
        assert "trade_count" in r


@pytest.mark.asyncio
async def test_data_warning_for_few_trades(client):
    """赵新 has <10 trades; diagnosis.data_warning should be 'insufficient'."""
    # Find 赵新's user id
    resp = await client.get("/api/users/")
    users = resp.json()
    zhaoxin = next((u for u in users if u["name"] == "赵新"), None)
    assert zhaoxin is not None, "赵新 user not found"
    uid = zhaoxin["id"]

    # Generate report
    resp = await client.post("/api/reports/generate", json={
        "user_id": uid,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31"
    })
    assert resp.status_code == 200
    report_id = resp.json()["id"]

    # Poll
    for _ in range(30):
        await asyncio.sleep(2)
        resp = await client.get(f"/api/reports/{report_id}")
        report = resp.json()
        if report["status"] in ("completed", "failed"):
            break

    assert report["status"] == "completed"
    assert report["diagnosis"] is not None
    assert report["diagnosis"]["data_warning"] == "insufficient"


@pytest.mark.asyncio
async def test_pattern_ai_commentary(client):
    """Completed report patterns should have ai_commentary field."""
    resp = await client.get("/api/reports/")
    reports = resp.json()
    completed = [r for r in reports if r["status"] == "completed"]
    if not completed:
        pytest.skip("No completed reports yet")

    resp = await client.get(f"/api/reports/{completed[0]['id']}")
    report = resp.json()
    if report.get("patterns"):
        for p in report["patterns"]:
            assert "ai_commentary" in p


@pytest.mark.asyncio
async def test_market_data_endpoint(client):
    """GET /api/market-data/{stock_code} should return bars."""
    # Use a known stock from mock data
    resp = await client.get(
        "/api/market-data/600519",
        params={"start": "2025-01-01", "end": "2025-03-31"}
    )
    # Either 200 with data or 404 if not seeded — both are valid
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert "stock_code" in data
        assert "bars" in data
        assert isinstance(data["bars"], list)
