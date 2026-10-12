"""Storage primitives for HTTP simulator ingestion; no freshness or API policy implied."""

import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone


VITAL_FIELDS = ('heart_rate', 'systolic_bp', 'diastolic_bp', 'temperature_c', 'spo2')


class ReadingConflict(ValueError):
    """A retransmitted reading id has a different target or payload."""


@dataclass(frozen=True)
class WritePolicy:
    max_attempts: int = 3
    delay_s: float = 0.05

    def __post_init__(self):
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError('max_attempts must be a positive integer')
        if not math.isfinite(self.delay_s) or self.delay_s < 0:
            raise ValueError('Invalid write delay')


def _identifier(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Identifiers must be nonempty strings')
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('measured_at must be an ISO timestamp with timezone')
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError('Missing timezone')
        return stamp.timestamp()
    except (ValueError, OverflowError, OSError):
        raise ValueError('Invalid measured_at timestamp') from None


class VitalReadings:
    def __init__(self, db, *, write_policy=WritePolicy(), sleep=time.sleep):
        self.db, self.write_policy, self.sleep = db, write_policy, sleep

    def save(self, *, reading_id, profile_id, data, scenario=None):
        """Idempotent insert. Returns inserted/duplicate; transient DB locks alone retry.

        reading_id is an internal repository requirement, not a new public API field.
        Retransmissions must reuse it. No medical ranges/profile policy is decided here.
        """
        _identifier(reading_id)
        _identifier(profile_id)
        if scenario is not None:
            _identifier(scenario)
        if not isinstance(data, dict):
            raise ValueError('Reading must be an object')
        for field in VITAL_FIELDS:
            if field != 'heart_rate' and data.get(field) is None:
                continue
            expected = (int, float) if field == 'temperature_c' else (int,)
            if type(data.get(field)) not in expected or not math.isfinite(data[field]):
                raise ValueError(f'Invalid {field} type or nonfinite value')
        measured_at = data.get('measured_at')
        measured_epoch = _timestamp(measured_at)
        received_epoch = self.db.clock()
        if measured_epoch > received_epoch:
            raise ValueError('Future measurement is not accepted')
        received_at = datetime.fromtimestamp(received_epoch, timezone.utc).isoformat()
        values = tuple(data.get(f) for f in VITAL_FIELDS)

        for attempt in range(1, self.write_policy.max_attempts + 1):
            try:
                with self.db.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    previous = conn.execute('SELECT * FROM vital_readings WHERE reading_id=?',
                                            (reading_id,)).fetchone()
                    if previous is not None:
                        same = (previous['profile_id'] == profile_id and previous['scenario'] == scenario
                                and previous['measured_at_epoch'] == measured_epoch
                                and tuple(previous[f] for f in VITAL_FIELDS) == values)
                        if not same:
                            raise ReadingConflict('reading_id already used for another payload')
                        return {'status': 'duplicate', 'id': previous['id'], 'reading_id': reading_id, 'attempts': attempt}
                    cursor = conn.execute('''INSERT INTO vital_readings
                        (reading_id,profile_id,scenario,heart_rate,systolic_bp,diastolic_bp,
                         temperature_c,spo2,measured_at,measured_at_epoch,received_at,received_at_epoch)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (reading_id, profile_id, scenario, *values, measured_at, measured_epoch,
                         received_at, received_epoch))
                    row_id = cursor.lastrowid
                return {'status': 'inserted', 'id': row_id, 'reading_id': reading_id, 'attempts': attempt}
            except sqlite3.OperationalError as error:
                code = getattr(error, 'sqlite_errorcode', 0) & 0xff
                if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or attempt == self.write_policy.max_attempts:
                    raise
                self.sleep(self.write_policy.delay_s * attempt)

    def latest(self, profile_id, *, max_age_s, scenario=None):
        """Newest measured value in exactly one profile/scenario stream.

        max_age_s must be supplied by the caller; no team freshness threshold chosen.
        Returns None for absent/stale/future data. Database errors propagate.
        """
        _identifier(profile_id)
        if scenario is not None:
            _identifier(scenario)
        if not math.isfinite(max_age_s) or max_age_s < 0:
            raise ValueError('max_age_s must be finite and nonnegative')
        with self.db.connect() as conn:
            row = conn.execute('''SELECT * FROM vital_readings
                WHERE profile_id=? AND scenario IS ?
                ORDER BY measured_at_epoch DESC, id DESC LIMIT 1''', (profile_id, scenario)).fetchone()
        if row is None:
            return None
        age = self.db.clock() - row['measured_at_epoch']
        if not 0 <= age <= max_age_s:
            return None
        return {'id': row['id'], 'reading_id': row['reading_id'], 'profile_id': row['profile_id'],
                'scenario': row['scenario'], 'origin': 'simulator',
                'data': {**{f: row[f] for f in VITAL_FIELDS}, 'measured_at': row['measured_at']},
                'received_at': row['received_at'], 'measured_age_s': age}
