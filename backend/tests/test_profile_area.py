import asyncio
import sqlite3
from pathlib import Path

from src.db.database import Database
from src.db.seed import seed_profiles
from src.orchestrator import monitoring


def test_existing_profile_migration_and_seed_preserve(tmp_path):
    path = tmp_path / 'old.db'
    schema = Path('src/db/schema.sql').read_text(encoding='utf-8').replace(',\n    area TEXT', '')
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)
        conn.execute("INSERT INTO profiles VALUES('profile-01',60,0,0,0)")
    db = Database(path)
    assert db.get_profile('profile-01')['area'] is None
    seed_profiles(db)
    assert db.get_profile('profile-01')['age'] == 60
    assert db.get_profile('profile-01')['area'] == '서울시 강남구'
    with db.connect() as conn:
        conn.execute("UPDATE profiles SET area='사용자 지정 지역' WHERE profile_id='profile-01'")
    seed_profiles(Database(path))
    assert db.get_profile('profile-01')['area'] == '사용자 지정 지역'


def test_monitoring_uses_single_profile_lookup(tmp_path, monkeypatch):
    db = Database(tmp_path / 'new.db')
    seed_profiles(db)
    calls = []
    original = db.get_profile
    def get_profile(profile_id):
        calls.append(profile_id)
        return original(profile_id)
    monkeypatch.setattr(db, 'get_profile', get_profile)
    async def vital(**kwargs):
        return {'vital': None, 'error': None, 'source': 'mock'}
    async def iot(**kwargs):
        return {'indoor_environment': None, 'devices': None, 'cctv': None, 'errors': []}
    monkeypatch.setattr(monitoring, 'run_vital', vital)
    monkeypatch.setattr(monitoring, 'run_iot', iot)
    result = asyncio.run(monitoring.run_monitoring(db=db, run_id='run', profile_id='profile-02', scenario='normal'))
    assert result.area == '서울시 송파구'
    assert calls == ['profile-02']
    assert asyncio.run(monitoring._profile(db, 'missing'))['area'] is None
    def broken(_):
        raise sqlite3.OperationalError('storage failure')
    monkeypatch.setattr(db, 'get_profile', broken)
    failed = asyncio.run(monitoring._profile(db, 'profile-02'))
    assert failed['area'] is None and failed['vulnerability'] == '상'
