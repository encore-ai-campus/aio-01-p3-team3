"""Vital lookup recovery. Freshness and Mock fallback are explicit caller policies."""
import asyncio
import json
import math
import sqlite3
import time

from src.db.database import cache_key
from src.healing.faults import Faults
from src.healing.retry import InvalidResult, RecoveryError, RetryPolicy, _invoke, _measured_age, _validate


class VitalDatabaseError(RuntimeError):
    """Storage unavailable. Carries safe in-memory diagnostics when SQLite logs fail."""
    def __init__(self, events):
        super().__init__('Vital database unavailable')
        self.events = events


class VitalUnavailable(RecoveryError):
    def __init__(self, attempts, events):
        super().__init__('vital', attempts)
        self.events = events


async def get_vitals_with_healing(*, db, run_id, profile_id, scenario,
                                 fetch_latest, validate, freshness_seconds,
                                 policy=RetryPolicy(), fault=(), mock_fetch=None,
                                 mock_on_db_error=False,
                                 retryable=(TimeoutError, ConnectionError, InvalidResult)):
    """fetch_latest returns VitalData dict or None. Async and sync callbacks supported.

    None means no recent data: do not repeat the lookup. Query service failures retry.
    Cache age is policy.max_cache_age_s; current lookup freshness is separately supplied.
    DB errors skip same-DB cache. Mock only runs when a caller supplies it and allows it.
    Public source remains mock/cache. Diagnostic events contain error types, not messages.
    """
    if not math.isfinite(freshness_seconds) or freshness_seconds < 0:
        raise ValueError('Invalid freshness threshold')
    faults = fault if isinstance(fault, Faults) else Faults(fault)
    key = cache_key('vital', profile_id, scenario if scenario is not None else '_')
    if scenario is None:
        key = json.dumps(['vital', profile_id, None], ensure_ascii=False)
    start = time.monotonic()
    events = []
    database_failed = False

    def record(attempt, status, *, error=None, recovery=None):
        event = dict(run_id=run_id, step='vital', attempt=attempt, status=status,
                     error=error, recovery=recovery, elapsed_ms=round((time.monotonic()-start)*1000))
        event['persisted'] = True
        try:
            db.log(**{k:v for k,v in event.items() if k != 'persisted'})
        except (sqlite3.Error, OSError):
            event['persisted'] = False
        events.append(event)

    def result(data, source, attempt, recovery=None):
        return dict(data=data, source=source, attempts=attempt, recovery=recovery,
                    events=events, log_persisted=all(e['persisted'] for e in events),
                    database_failed=database_failed)

    for attempt in range(1, policy.max_attempts+1):
        try:
            faults.check('vital')
            data = await asyncio.wait_for(_invoke(fetch_latest), policy.timeout_s)
            if data is None:
                record(attempt, 'fail', error='NoRecentReading')
                break
            _validate(data, validate)
            if _measured_age(data, db.clock()) > freshness_seconds:
                record(attempt, 'fail', error='NoRecentReading')
                break
        except retryable as error:
            record(attempt, 'retry' if attempt < policy.max_attempts else 'fail', error=type(error).__name__)
            if attempt < policy.max_attempts:
                await asyncio.sleep(policy.delay_s*attempt)
            continue
        except (sqlite3.Error, OSError) as error:
            code = getattr(error, 'sqlite_errorcode', 0) & 0xff
            temporary = code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            if temporary and attempt < policy.max_attempts:
                record(attempt, 'retry', error=type(error).__name__)
                await asyncio.sleep(policy.delay_s*attempt)
                continue
            # SQLite is not a remote service. Cache shares this failed storage.
            database_failed = True
            record(attempt, 'fail', error=type(error).__name__)
            break
        try:
            db.save_cache(key, data)
        except (sqlite3.Error, OSError) as error:
            database_failed = True
            record(attempt, 'fail', error=type(error).__name__)
            break
        record(attempt, 'success', recovery='retry' if attempt > 1 else None)
        return result(data, 'mock', attempt, 'retry' if attempt > 1 else None)

    if not database_failed:
        try:
            cached = db.load_cache(key, policy.max_cache_age_s)
        except (sqlite3.Error, OSError) as error:
            database_failed = True
            record(attempt, 'fail', error=type(error).__name__)
        else:
            if cached is not None:
                try:
                    _validate(cached['data'], validate)
                    if _measured_age(cached['data'], db.clock()) > policy.max_cache_age_s:
                        raise InvalidResult('Expired cached measurement')
                except InvalidResult:
                    pass
                else:
                    record(attempt, 'fallback', recovery='cache')
                    return result(cached['data'], 'cache', attempt, 'cache')

    if mock_fetch is not None and (not database_failed or mock_on_db_error):
        try:
            data = await asyncio.wait_for(_invoke(mock_fetch), policy.timeout_s)
            _validate(data, validate)
        except (ValueError, TimeoutError, ConnectionError) as error:
            record(attempt, 'fail', error=type(error).__name__)
        else:
            # Do not overwrite measurement cache with a fallback fixture.
            record(attempt, 'fallback', recovery='mock')
            return result(data, 'mock', attempt, 'mock')
    if database_failed:
        raise VitalDatabaseError(events) from None
    raise VitalUnavailable(attempt, events) from None
