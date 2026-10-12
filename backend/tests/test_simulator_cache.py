"""Sender payload -> ingestion API -> real SQLite -> Vital fault cache recovery."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from src import main, mcp_client
from src.agents.vital import run_vital
from src.db.database import Database, cache_key
from src.db.vital_service import VitalService


def test_heat_sender_ingestion_primes_cache_and_fault_uses_it(tmp_path, monkeypatch):
    # Separate interpreter keeps MCP's src package isolated from backend's src.
    mcp_dir = Path(__file__).resolve().parents[2] / 'mcp_server'
    script = "from src.vital_sender import build_vital_payload; import json; print(json.dumps(build_vital_payload('profile-02','heat')))"
    payload = json.loads(subprocess.check_output([sys.executable, '-c', script], cwd=mcp_dir, text=True))
    assert payload['scenario'] == 'heat'
    db = Database(tmp_path / 'cache.db')
    main.app.dependency_overrides[main.get_db] = lambda: db
    try:
        response = TestClient(main.app).post('/vitals/readings', json=payload)
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
    assert response.status_code == 200
    service = VitalService(db)
    assert service.get_latest_vital_reading('profile-02', scenario='heat', max_age_seconds=45)
    assert service.get_latest_vital_reading('profile-02', scenario='normal', max_age_seconds=45) is None
    async def unexpected_mock(*args, **kwargs):
        raise AssertionError('Cache demonstration must not call MCP Mock')
    monkeypatch.setattr(mcp_client, 'call_tool', unexpected_mock)
    async def exercise():
        normal = await run_vital(db=db, run_id='warm', profile_id='profile-02', scenario='heat')
        assert normal['error'] is None
        cached = db.load_cache(cache_key('vital', 'profile-02', 'heat'), 300)
        assert cached['data']['measured_at'] == payload['measured_at']
        broken = await run_vital(db=db, run_id='fault', profile_id='profile-02', scenario='heat', fault=['vital'])
        assert broken['source'] == 'cache' and broken['error'] is None
        assert broken['vital'] == normal['vital']
    asyncio.run(exercise())
    logs = db.logs('fault')
    assert [e['status'] for e in logs] == ['retry', 'retry', 'fail', 'fallback']
    assert logs[-1]['recovery'] == 'cache' and logs[-1]['attempt'] == 3
