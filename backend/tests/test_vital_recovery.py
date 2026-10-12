import asyncio
from datetime import datetime, timezone
import sqlite3

import pytest

from src.db.database import Database, cache_key
from src.db.vital_service import VitalService
from src.healing.retry import RetryPolicy
from src.healing.vital import VitalDatabaseError, VitalUnavailable, get_vitals_with_healing
from src.schemas import VitalData

NOW = 1791424800.0


def data(age=0):
    return dict(heart_rate=72,systolic_bp=125,temperature_c=36.5,spo2=98,
                measured_at=datetime.fromtimestamp(NOW-age, timezone.utc).isoformat())


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path/'app.db', clock=lambda: NOW)


def call(db, **changes):
    args = dict(db=db,run_id='run',profile_id='p1',scenario='heat',fetch_latest=lambda:data(),
        validate=VitalData.model_validate,freshness_seconds=30,
        policy=RetryPolicy(delay_s=0,timeout_s=1,max_cache_age_s=120))
    return asyncio.run(get_vitals_with_healing(**(args|changes)))


def test_adapter_returns_same_row_id_and_keeps_none(db):
    service = VitalService(db)
    reading = dict(profile_id='p1',reading_id='r1',scenario='heat',**data())
    first = service.save_vital_reading(reading)
    assert type(first) is int
    assert service.save_vital_reading(reading) == first
    assert service.get_latest_vital_reading('p1',scenario='heat',max_age_seconds=30) == {**data(), 'diastolic_bp': None}
    assert service.get_latest_vital_reading('absent',max_age_seconds=30) is None


def test_normal_lookup_primes_cache(db):
    assert call(db)['source']=='mock'
    assert db.load_cache(cache_key('vital','p1','heat'),120)['data']==data()


def test_injected_query_failure_recovers_cache(db):
    call(db,run_id='prime')
    result = call(db,fault=['vital'])
    assert result['source']=='cache' and result['recovery']=='cache'
    assert [e['status'] for e in result['events']]==['retry','retry','fail','fallback']


def test_none_not_retried_and_mock_requires_opt_in(db):
    calls=[]
    def fetch():
        calls.append(1)
        return None
    with pytest.raises(VitalUnavailable) as error:
        call(db,fetch_latest=fetch)
    assert len(calls)==1
    assert error.value.events[-1]['error']=='NoRecentReading'
    result=call(db,fetch_latest=fetch,mock_fetch=lambda:data())
    assert result['source']=='mock' and result['recovery']=='mock'
    assert db.load_cache(cache_key('vital','p1','heat'),120) is None


@pytest.mark.parametrize('age', [30,31])
def test_current_freshness_separate_from_cache_policy(db, age):
    if age==30:
        assert call(db,fetch_latest=lambda:data(age))['recovery'] is None
    else:
        with pytest.raises(VitalUnavailable):
            call(db,fetch_latest=lambda:data(age))
    # A prior valid measurement cache may outlive the 30s current-data limit.
    db.save_cache(cache_key('vital','p1','heat'),data(60))
    assert call(db,fetch_latest=lambda:None)['source']=='cache'


def test_stale_cache_rejected_even_if_just_saved(db):
    db.save_cache(cache_key('vital','p1','heat'),data(121))
    with pytest.raises(VitalUnavailable):
        call(db,fault=['vital'])


def test_timeout_is_query_error_not_db_error(db):
    calls=[]
    def fail():
        calls.append(1)
        raise TimeoutError('private message')
    with pytest.raises(VitalUnavailable) as error:
        call(db,fetch_latest=fail)
    assert len(calls)==3
    assert 'private' not in str(error.value.events)


def test_db_failure_skips_cache_and_retains_memory_events(db,monkeypatch):
    def fail(*args,**kwargs):
        raise sqlite3.OperationalError('disk unavailable private detail')
    monkeypatch.setattr(db,'log',fail)
    monkeypatch.setattr(db,'load_cache',lambda *args:pytest.fail('Same DB cache must not be read'))
    with pytest.raises(VitalDatabaseError) as error:
        call(db,fetch_latest=fail)
    assert error.value.events[0]['persisted'] is False
    assert 'private' not in str(error.value.events)
    result=call(db,fetch_latest=fail,mock_fetch=lambda:data(),mock_on_db_error=True)
    assert result['database_failed'] and not result['log_persisted']
    assert result['recovery']=='mock'


def test_mock_not_used_for_db_failure_without_permission(db):
    def fail():
        raise sqlite3.OperationalError('DB failed')
    with pytest.raises(VitalDatabaseError):
        call(db,fetch_latest=fail,mock_fetch=lambda:pytest.fail('Mock not enabled for DB error'))


def test_cache_storage_failure_is_not_success(db,monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError('disk full')
    monkeypatch.setattr(db,'save_cache',fail)
    with pytest.raises(VitalDatabaseError):
        call(db)


def test_cache_read_failure_keeps_db_error(db,monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError('DB unavailable')
    monkeypatch.setattr(db,'load_cache',fail)
    with pytest.raises(VitalDatabaseError):
        call(db,fetch_latest=lambda:None)


def test_unexpected_bug_and_cancellation_propagate(db):
    def bug():
        raise TypeError('bug')
    with pytest.raises(TypeError):
        call(db,fetch_latest=bug)
    async def cancel():
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        call(db,fetch_latest=cancel)


def test_missing_timestamp_fixture_can_be_explicit_mock_fallback(db):
    fixture=data()
    fixture.pop('measured_at')
    result=call(db,fetch_latest=lambda:None,mock_fetch=lambda:fixture)
    assert result['data']==fixture and result['recovery']=='mock'


def test_mock_fixture_does_not_cross_scenario_cache(db):
    call(db)
    with pytest.raises(VitalUnavailable):
        call(db,scenario='fall',fault=['vital'])


def test_log_failure_marked_without_hiding_valid_reading(db,monkeypatch):
    def fail(*args,**kwargs):
        raise sqlite3.OperationalError('log unavailable')
    monkeypatch.setattr(db,'log',fail)
    result=call(db)
    assert result['source']=='mock' and result['log_persisted'] is False


def test_sqlite_lock_only_is_retried(db):
    calls=[]
    def fetch():
        calls.append(1)
        if len(calls)==1:
            error=sqlite3.OperationalError('busy')
            error.sqlite_errorcode=sqlite3.SQLITE_BUSY
            raise error
        return data()
    assert call(db,fetch_latest=fetch)['attempts']==2


def test_general_stream_cache_is_not_sentinel_scenario(db):
    call(db,scenario=None)
    assert call(db,scenario=None,fault=['vital'])['source']=='cache'
    with pytest.raises(VitalUnavailable):
        call(db,scenario='_',fault=['vital'])
