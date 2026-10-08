from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from src.db.database import Database
from src.db.seed import seed_profiles
from src.db.vital_readings import ReadingConflict, VitalReadings, WritePolicy
from src.schemas import VitalData


NOW = 1791424800.0


def data(age=0):
    return dict(heart_rate=72, systolic_bp=125, diastolic_bp=80,
                temperature_c=36.5, spo2=98,
                measured_at=datetime.fromtimestamp(NOW-age, timezone.utc).isoformat())


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / 'test.db', clock=lambda: NOW)


def save(repo, reading_id='r1', profile_id='p1', scenario='heat', **changes):
    return repo.save(reading_id=reading_id, profile_id=profile_id, scenario=scenario,
                     data=data() | changes)


def test_insert_schema_compatible_and_reopen(db):
    result = save(VitalReadings(db))
    assert result == {'status':'inserted','reading_id':'r1','attempts':1}
    reopened = VitalReadings(Database(db.path, clock=lambda: NOW))
    latest = reopened.latest('p1', scenario='heat', max_age_s=30)
    assert VitalData.model_validate(latest['data']).model_dump() == data()
    assert latest['origin'] == 'simulator' and latest['measured_age_s'] == 0


def test_retransmission_does_not_refresh_age(db):
    repo = VitalReadings(db)
    save(repo)
    db.clock = lambda: NOW+15
    assert save(repo)['status'] == 'duplicate'
    latest = repo.latest('p1', scenario='heat', max_age_s=30)
    assert latest['measured_age_s'] == 15
    assert latest['received_at'] == data()['measured_at']
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM vital_readings').fetchone()[0] == 1


@pytest.mark.parametrize('changed', [dict(heart_rate=80), dict(measured_at=data(15)['measured_at'])])
def test_conflicting_payload_rejected(db, changed):
    repo = VitalReadings(db)
    save(repo)
    with pytest.raises(ReadingConflict):
        save(repo, **changed)
    assert repo.latest('p1', scenario='heat', max_age_s=30)['data'] == data()


def test_reading_id_cannot_move_profiles_or_scenarios(db):
    repo = VitalReadings(db)
    save(repo)
    for profile, scenario in [('p2','heat'),('p1','fall')]:
        with pytest.raises(ReadingConflict):
            save(repo, profile_id=profile, scenario=scenario)


def test_measurement_order_not_arrival_order(db):
    repo = VitalReadings(db)
    save(repo, reading_id='new')
    save(repo, reading_id='late', measured_at=data(15)['measured_at'])
    assert repo.latest('p1', scenario='heat', max_age_s=30)['reading_id'] == 'new'


def test_timestamp_timezone_equivalence_duplicate(db):
    repo = VitalReadings(db)
    save(repo)
    stamp = datetime.fromtimestamp(NOW, timezone.utc).astimezone(timezone(timedelta(hours=9))).isoformat()
    assert save(repo, measured_at=stamp)['status'] == 'duplicate'


@pytest.mark.parametrize('age,limit,found', [(30,30,True),(31,30,False),(0,0,True)])
def test_freshness_is_caller_policy(db, age, limit, found):
    repo = VitalReadings(db)
    save(repo, measured_at=data(age)['measured_at'])
    assert (repo.latest('p1', scenario='heat', max_age_s=limit) is not None) is found


def test_profile_scenario_and_null_stream_isolation(db):
    repo = VitalReadings(db)
    save(repo)
    save(repo, reading_id='none', scenario=None, heart_rate=80)
    assert repo.latest('p1', scenario='heat', max_age_s=30)['data']['heart_rate'] == 72
    assert repo.latest('p1', max_age_s=30)['data']['heart_rate'] == 80
    assert repo.latest('p1', scenario='fall', max_age_s=30) is None
    assert repo.latest('p2', scenario='heat', max_age_s=30) is None


@pytest.mark.parametrize('changes', [dict(measured_at=None),dict(measured_at='2026-10-08T10:00:00'),
    dict(measured_at='not-a-time'),dict(measured_at=data(-1)['measured_at']),
    dict(heart_rate=True),dict(heart_rate='72'),dict(temperature_c=float('nan')),
    dict(temperature_c=float('inf')),dict(spo2=None)])
def test_bad_input_not_written(db, changes):
    repo = VitalReadings(db)
    with pytest.raises(ValueError):
        save(repo, **changes)
    assert repo.latest('p1', scenario='heat', max_age_s=30) is None


def test_busy_lock_retries_after_release(db):
    db.busy_timeout_s = 0
    delays = []
    with db.connect() as blocker:
        blocker.execute('BEGIN IMMEDIATE')
        def release(delay):
            delays.append(delay)
            blocker.rollback()
        repo = VitalReadings(db, sleep=release)
        assert save(repo)['attempts'] == 2
    assert delays == [0.05]


def test_busy_lock_exhaustion_does_not_claim_success(db):
    db.busy_timeout_s = 0
    with db.connect() as blocker:
        blocker.execute('BEGIN IMMEDIATE')
        repo = VitalReadings(db, write_policy=WritePolicy(max_attempts=2, delay_s=0))
        with pytest.raises(sqlite3.OperationalError):
            save(repo)
    assert repo.latest('p1', scenario='heat', max_age_s=30) is None


def test_non_lock_database_error_is_not_retried(db):
    sleeps = []
    repo = VitalReadings(db, sleep=sleeps.append)
    with db.connect() as conn:
        conn.execute('DROP TABLE vital_readings')
    with pytest.raises(sqlite3.OperationalError):
        save(repo)
    assert sleeps == []


def test_concurrent_duplicate_write_and_read(db):
    repo = VitalReadings(db)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(save, repo) for _ in range(8)]
        results = [f.result() for f in futures]
        snapshots = list(pool.map(lambda _: repo.latest('p1',scenario='heat',max_age_s=30), range(4)))
    assert sum(r['status']=='inserted' for r in results) == 1
    assert all(s['reading_id']=='r1' for s in snapshots)


def test_explicit_demo_profile_refresh_only(db):
    db.seed_profiles([dict(profile_id='profile-01',age=82,lives_alone=True,
        has_condition=True,mobility_limited=True)])
    seed_profiles(db)
    assert db.get_profile('profile-01')['age'] == 82
    seed_profiles(db, overwrite=True)
    assert db.get_profile('profile-01')['age'] == 84
    assert db.get_profile('profile-02')['age'] == 78
    assert db.get_profile('profile-03')['lives_alone'] is True


@pytest.mark.parametrize('age', [-1,float('nan'),float('inf')])
def test_invalid_age_limit(db, age):
    with pytest.raises(ValueError):
        VitalReadings(db).latest('p1', max_age_s=age)
