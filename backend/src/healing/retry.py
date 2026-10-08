"""Common query recovery, independent of agents, schemas and SDKs."""
import asyncio
import inspect
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from src.healing.faults import Faults


class InvalidResult(ValueError):
    """Explicitly invalid service response / validator rejection."""


class RecoveryError(RuntimeError):
    def __init__(self, step, attempts):
        super().__init__(f'{step}: recovery exhausted after {attempts} attempts')
        self.step, self.attempts = step, attempts


@dataclass(frozen=True)
class RetryPolicy:
    # Provisional default: TOTAL 3 calls, not 3 retries. Team can override.
    max_attempts: int = 3
    timeout_s: float = 15
    delay_s: float = 0.5
    max_cache_age_s: float = 300

    def __post_init__(self):
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError('max_attempts must be a positive integer')
        if any(not math.isfinite(v) for v in (self.timeout_s, self.delay_s, self.max_cache_age_s)):
            raise ValueError('Policy values must be finite')
        if self.timeout_s <= 0 or self.delay_s < 0 or self.max_cache_age_s < 0:
            raise ValueError('Invalid recovery policy')


async def _invoke(fetch):
    if inspect.iscoroutinefunction(fetch):
        return await fetch()
    value = await asyncio.to_thread(fetch)
    return await value if inspect.isawaitable(value) else value


def _validate(data, validator):
    if isinstance(data, dict) and (data.get('status') == 'failed' or data.get('success') is False):
        raise InvalidResult('Service returned failure')
    try:
        accepted = validator(data)
    except ValueError:
        raise InvalidResult('Validation rejected response') from None
    if accepted is False:
        raise InvalidResult('Validation rejected response')


def _measured_age(data, now):
    if not isinstance(data, dict) or not isinstance(data.get('measured_at'), str):
        raise InvalidResult('Missing measurement timestamp')
    try:
        stamp = datetime.fromisoformat(data['measured_at'])
        if stamp.tzinfo is None:
            raise ValueError('Timezone required')
        age = now - stamp.astimezone(timezone.utc).timestamp()
    except (ValueError, OverflowError):
        raise InvalidResult('Invalid measurement timestamp') from None
    if age < 0:
        raise InvalidResult('Future measurement timestamp')
    return age


async def with_healing(*, db, run_id, step, fetch, validate,
                       policy=RetryPolicy(), fault=(), fault_target=None,
                       use_cache=False, cache_key=None, require_measured_at=False,
                       source='mock', retryable=(TimeoutError, ConnectionError, InvalidResult)):
    """validate is synchronous: raise ValueError/InvalidResult or return False to reject.

    Unexpected programming/configuration errors propagate without retries.
    SDK-specific transient exceptions can be supplied in retryable.
    CancelledError propagates. Sync timeout does not terminate a running thread.
    """
    if use_cache and not cache_key:
        raise ValueError('Cache key required')
    if source != 'mock':
        raise ValueError('Only mock source supported by this iteration')
    faults = fault if isinstance(fault, Faults) else Faults(fault)
    start = time.monotonic()
    elapsed = lambda: round((time.monotonic() - start) * 1000)
    for attempt in range(1, policy.max_attempts + 1):
        try:
            faults.check(fault_target or step)
            data = await asyncio.wait_for(_invoke(fetch), policy.timeout_s)
            _validate(data, validate)
            age = _measured_age(data, db.clock()) if require_measured_at else None
            if age is not None and age > policy.max_cache_age_s:
                raise InvalidResult('Stale measurement')
        except retryable as error:
            db.log(run_id, step, attempt, 'retry' if attempt < policy.max_attempts else 'fail',
                   error=type(error).__name__, elapsed_ms=elapsed())
            if attempt < policy.max_attempts:
                await asyncio.sleep(policy.delay_s * attempt)
            continue
        except Exception as error:
            db.log(run_id, step, attempt, 'error', error=type(error).__name__, elapsed_ms=elapsed())
            raise
        # Storage errors must propagate, never cause another provider call.
        if use_cache:
            db.save_cache(cache_key, data)
        db.log(run_id, step, attempt, 'success', recovery='retry' if attempt > 1 else None, elapsed_ms=elapsed())
        return {'data': data, 'source': source, 'attempts': attempt, 'measured_age_s': age}

    cached = db.load_cache(cache_key, policy.max_cache_age_s) if use_cache else None
    if cached is not None:
        try:
            _validate(cached['data'], validate)
            age = _measured_age(cached['data'], db.clock()) if require_measured_at else None
            if age is not None and age > policy.max_cache_age_s:
                raise InvalidResult('Stale measurement')
        except InvalidResult:
            pass
        else:
            db.log(run_id, step, attempt, 'fallback', recovery='cache', elapsed_ms=elapsed())
            return {**cached, 'source': 'cache', 'attempts': attempt, 'measured_age_s': age}
    raise RecoveryError(step, attempt) from None
