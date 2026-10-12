# [변경 기록]
# 2026-10-12 해든 (팀 합의): diastolic_bp 삭제에 맞춤. 부분 저장 테스트에서 빼고, 예전 DB의 diastolic_bp 열이 지워지는지 확인 추가.
#   되돌리기(rollback) 테스트는 이제 diastolic_bp 열이 있는 DB에서 이전이 일어나므로 그 DB로 시작함.

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import main
from src.db.database import Database
from src.db.vital_service import VitalService
from src.db.vital_readings import ReadingConflict


def reading(**kwargs):
    return dict(profile_id='p1', reading_id='r1', heart_rate=75,
                measured_at=datetime.now(timezone.utc).isoformat(), **kwargs)


def test_partial_duplicate_and_null(tmp_path):
    service = VitalService(Database(tmp_path / 'db'))
    data = reading(systolic_bp=120)
    row_id = service.save_vital_reading(data)
    assert service.save_vital_reading({**data, 'spo2': None}) == row_id
    latest = service.get_latest_vital_reading('p1', max_age_seconds=30)
    assert 'diastolic_bp' not in latest
    assert latest['systolic_bp'] == 120 and latest['spo2'] is None
    with pytest.raises(ReadingConflict):
        service.save_vital_reading({**data, 'systolic_bp': 121})
    assert service.get_latest_vital_reading('p1', scenario='heat', max_age_seconds=30) is None


def test_old_database_upgrade_preserves_rows_and_sequence(tmp_path):
    path = tmp_path / 'old.db'
    schema = Path('src/db/schema.sql').read_text()
    schema = schema.replace(
        'systolic_bp INTEGER,', 'systolic_bp INTEGER NOT NULL,').replace(
        'temperature_c REAL,', 'temperature_c REAL NOT NULL,').replace(
        'spo2 INTEGER,', 'spo2 INTEGER NOT NULL,')
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)
        conn.execute("INSERT INTO vital_readings VALUES(7,'old','p1',NULL,75,120,36.5,98,"
                     "'2026-10-08T00:00:00+00:00',1,'received',2)")
        conn.execute("UPDATE sqlite_sequence SET seq=40 WHERE name='vital_readings'")
        conn.execute("INSERT INTO cache VALUES('key','{}',1)")
    db = Database(path)
    with db.connect() as conn:
        old = dict(conn.execute('SELECT * FROM vital_readings').fetchone())
        assert old['id'] == 7 and old['received_at'] == 'received'
        assert 'diastolic_bp' not in old and old['systolic_bp'] == 120
        assert conn.execute('SELECT count(*) FROM cache').fetchone()[0] == 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='readings_latest'").fetchone()
    assert VitalService(db).save_vital_reading(reading()) == 41
    Database(path)  # repeated initialization is idempotent


@pytest.fixture
def api(tmp_path):
    db = Database(tmp_path / 'api.db')
    main.app.dependency_overrides[main.get_db] = lambda: db
    try:
        yield TestClient(main.app, raise_server_exceptions=False), db
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)


def test_api_partial_real_storage(api):
    client, db = api
    payload = reading(scenario='heat', diastolic_bp=82)      # 예전 시뮬레이터가 보내도 무시하고 저장
    payload.pop('reading_id')
    response = client.post('/vitals/readings', json=payload)
    assert response.status_code == 200 and response.json()['status'] == 'stored'
    data = VitalService(db).get_latest_vital_reading('p1', scenario='heat', max_age_seconds=30)
    assert data['heart_rate'] == 75 and 'diastolic_bp' not in data
    assert data['temperature_c'] is None


def test_migration_rolls_back_on_copy_failure(tmp_path, monkeypatch):
    path = tmp_path / 'rollback.db'
    schema_path = Path('src/db/schema.sql')
    schema = schema_path.read_text()
    old = schema.replace('    systolic_bp INTEGER,\n', '    systolic_bp INTEGER,\n    diastolic_bp INTEGER,\n')
    with sqlite3.connect(path) as conn:
        conn.executescript(old)
        conn.execute("INSERT INTO vital_readings VALUES(7,'old','p1',NULL,75,120,80,36.5,98,"
                     "'stamp',1,'received',2)")
    original = Path.read_text
    def broken_schema(self, *args, **kwargs):
        text = original(self, *args, **kwargs)
        return text.replace('heart_rate INTEGER NOT NULL', 'heart_rate INTEGER CHECK(heart_rate<0)')
    monkeypatch.setattr(Path, 'read_text', broken_schema)
    with pytest.raises(sqlite3.IntegrityError):
        Database(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT id FROM vital_readings').fetchone()[0] == 7
        assert 'diastolic_bp' in {r[1] for r in conn.execute('PRAGMA table_info(vital_readings)')}   # 실패하면 그대로
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='readings_latest'").fetchone()


def test_diastolic_column_is_dropped_keeping_rows(tmp_path):
    """팀 합의 10/12: diastolic_bp 열이 있는 예전 DB는 열만 지우고 값은 그대로 옮긴다."""
    path = tmp_path / 'with_diastolic.db'
    schema = Path('src/db/schema.sql').read_text()
    old = schema.replace('    systolic_bp INTEGER,\n', '    systolic_bp INTEGER,\n    diastolic_bp INTEGER,\n')
    with sqlite3.connect(path) as conn:
        conn.executescript(old)
        conn.execute("INSERT INTO vital_readings VALUES(7,'old','p1',NULL,75,120,80,36.5,98,"
                     "'2026-10-08T00:00:00+00:00',1,'received',2)")
    db = Database(path)
    with db.connect() as conn:
        row = dict(conn.execute('SELECT * FROM vital_readings').fetchone())
        assert 'diastolic_bp' not in row and row['id'] == 7 and row['systolic_bp'] == 120 and row['spo2'] == 98
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='readings_latest'").fetchone()
    assert VitalService(db).save_vital_reading(reading()) == 8
    Database(path)  # 두 번 불러도 그대로


def test_api_invalid_and_storage_error_not_success(api, monkeypatch):
    client, db = api
    payload = reading()
    payload.pop('reading_id')
    assert client.post('/vitals/readings', json={**payload, 'heart_rate': 0}).status_code == 422
    def fail(self, data):
        raise sqlite3.OperationalError('test storage failure')
    monkeypatch.setattr(VitalService, 'save_vital_reading', fail)
    assert client.post('/vitals/readings', json=payload).status_code == 500
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM vital_readings').fetchone()[0] == 0
