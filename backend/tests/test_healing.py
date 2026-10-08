"""First iteration: storage, seeding, faults and common Vital recovery."""
import asyncio
from datetime import datetime, timezone

import pytest

from src.db.database import Database, cache_key
from src.db.seed import seed_profiles
from src.healing.faults import Faults
from src.healing.retry import RetryPolicy, RecoveryError, with_healing


NOW = 1791424800.0


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / 'app.db', clock=lambda: NOW)


def vital(age=0, heart_rate=72):
    return {'heart_rate': heart_rate, 'systolic_bp': 125,
            'temperature_c': 36.5, 'spo2': 98,
            'measured_at': datetime.fromtimestamp(NOW-age, timezone.utc).isoformat()}


def validate(data):
    # Fixture validator, not a clinical rule or final team schema.
    if not isinstance(data, dict) or type(data.get('heart_rate')) is not int:
        raise ValueError('Invalid fixture')


def options(db, **overrides):
    return dict(db=db, run_id='run', step='vital', fetch=lambda: vital(), validate=validate,
                policy=RetryPolicy(delay_s=0, timeout_s=1, max_cache_age_s=60),
                cache_key=cache_key('vital', 'profile-01', 'normal'), use_cache=True,
                require_measured_at=True) | overrides


def call(db, **overrides):
    return asyncio.run(with_healing(**options(db, **overrides)))


def test_live_persists_and_reopens(db):
    result = call(db)
    assert result['source'] == 'mock' and result['attempts'] == 1
    reopened = Database(db.path, clock=lambda: NOW)
    assert reopened.load_cache(cache_key('vital','profile-01','normal'), 60)['data'] == vital()
    assert reopened.logs('run')[0]['status'] == 'success'


def test_environment_path(tmp_path, monkeypatch):
    target = tmp_path / 'nested' / 'env.db'
    monkeypatch.setenv('DB_PATH', str(target))
    assert Database().path == target
    assert target.is_file()


def test_seed_is_idempotent_and_returns_booleans(db):
    seed_profiles(db)
    seed_profiles(db)
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM profiles').fetchone()[0] == 3
    p = db.get_profile('profile-01')
    assert p['age'] == 84 and p['lives_alone'] is True
    assert db.get_profile('missing') is None


def test_retry_recovers_without_leaking_exception(db):
    calls = []
    async def fetch():
        calls.append(1)
        if len(calls) < 2:
            raise TimeoutError('secret key and sensitive profile')
        return vital()
    assert call(db, fetch=fetch)['attempts'] == 2
    logs = db.logs('run')
    assert [r['status'] for r in logs] == ['retry', 'success']
    assert logs[-1]['recovery'] == 'retry'
    assert 'secret' not in str(logs)


def test_injected_failure_uses_cache_and_preserves_measurement_age(db):
    call(db, fetch=lambda: vital(age=30), run_id='prime')
    result = call(db, fault=['vital'], fetch=lambda: pytest.fail('Provider bypassed'))
    assert result['source'] == 'cache' and result['measured_age_s'] == 30
    assert result['data']['measured_at'] == vital(age=30)['measured_at']
    assert [r['status'] for r in db.logs('run')] == ['retry', 'retry', 'fail', 'fallback']


@pytest.mark.parametrize('state', ['empty','expired','corrupt','invalid','old-measurement','no-time','future-time'])
def test_unusable_cache_is_rejected(db, state):
    key = cache_key('vital','profile-01','normal')
    if state != 'empty':
        data = vital(age=61) if state == 'old-measurement' else vital()
        if state == 'invalid':
            data = {}
        if state == 'no-time':
            data.pop('measured_at')
        if state == 'future-time':
            data = vital(age=-1)
        db.save_cache(key, data)
    with db.connect() as conn:
        if state == 'expired':
            conn.execute('UPDATE cache SET saved_at=?', (NOW-61,))
        if state == 'corrupt':
            conn.execute("UPDATE cache SET value='{broken'")
    with pytest.raises(RecoveryError) as error:
        call(db, fault=['vital'])
    assert error.value.attempts == 3
    assert db.logs('run')[-1]['status'] == 'fail'


@pytest.mark.parametrize('data', [{}, {'heart_rate': 72}, {'status':'failed'}, {'success':False}])
def test_invalid_live_response_never_saved(db, data):
    with pytest.raises(RecoveryError):
        call(db, fetch=lambda: data)
    assert db.load_cache(cache_key('vital','profile-01','normal'),60) is None


def test_cache_disabled_neither_reads_nor_writes(db, monkeypatch):
    monkeypatch.setattr(db, 'load_cache', lambda *a: pytest.fail('Cache read'))
    monkeypatch.setattr(db, 'save_cache', lambda *a: pytest.fail('Cache write'))
    assert call(db, use_cache=False)['source'] == 'mock'
    with pytest.raises(RecoveryError):
        call(db, use_cache=False, fault=['vital'])


def test_timeout_and_total_attempt_count(db):
    calls = []
    async def slow():
        calls.append(1)
        await asyncio.sleep(1)
    with pytest.raises(RecoveryError):
        call(db, fetch=slow, policy=RetryPolicy(delay_s=0, timeout_s=0.02, max_cache_age_s=60))
    assert len(calls) == 3


def test_programming_error_does_not_retry(db):
    def bad():
        raise TypeError('Programming bug')
    with pytest.raises(TypeError):
        call(db, fetch=bad)
    assert len(db.logs('run')) == 1 and db.logs('run')[0]['status'] == 'error'


def test_cancel_is_not_retried(db):
    async def cancel():
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        call(db, fetch=cancel)
    assert db.logs('run') == []


def test_async_callback_from_sync_factory(db):
    async def fetch():
        return vital()
    assert call(db, fetch=lambda: fetch())['source'] == 'mock'


def test_false_validator_retries(db):
    with pytest.raises(RecoveryError):
        call(db, validate=lambda data: False)
    assert len(db.logs('run')) == 3


def test_storage_failure_does_not_repeat_provider(db, monkeypatch):
    calls = []
    def fetch():
        calls.append(1)
        return vital()
    def fail(*args):
        raise OSError('Disk full')
    monkeypatch.setattr(db, 'save_cache', fail)
    with pytest.raises(OSError):
        call(db, fetch=fetch)
    assert len(calls) == 1


def test_parallel_fault_profile_and_scenario_isolation(db):
    async def check():
        requests = []
        for profile, scenario, rate in [('a','normal',70),('a','fall',118),('b','normal',80)]:
            requests.append(with_healing(**options(db, run_id=profile+scenario,
                cache_key=cache_key('vital',profile,scenario), fetch=lambda r=rate: vital(heart_rate=r))))
        await asyncio.gather(*requests)
        results = await asyncio.gather(
            with_healing(**options(db, run_id='faulted', fault=['vital'], cache_key=cache_key('vital','a','fall'))),
            with_healing(**options(db, run_id='clean', cache_key=cache_key('vital','b','normal'))))
        assert [r['source'] for r in results] == ['cache','mock']
        assert results[0]['data']['heart_rate'] == 118
        with pytest.raises(RecoveryError):
            await with_healing(**options(db, fault=['vital'], cache_key=cache_key('vital','b','fall')))
    asyncio.run(check())
    assert len(db.logs('clean')) == 1


@pytest.mark.parametrize('fault', ['vital', ['bad']])
def test_bad_fault_rejected_before_call(db, fault):
    with pytest.raises(ValueError):
        call(db, fault=fault)
    assert db.logs('run') == []


def test_fault_list_snapshot():
    raw = ['vital']
    faults = Faults(raw)
    raw.append('iot')
    assert faults.values == frozenset({'vital'})


@pytest.mark.parametrize('kwargs', [dict(max_attempts=0), dict(max_attempts=True),
    dict(timeout_s=0), dict(delay_s=-1), dict(max_cache_age_s=float('nan'))])
def test_bad_policy(kwargs):
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


def test_cache_key_collision_and_query_safety(db):
    assert cache_key('a:b','c','d') != cache_key('a','b:c','d')
    assert db.get_profile("'; DROP TABLE profiles;--") is None
    seed_profiles(db)
    assert db.get_profile('profile-01')
