"""File-backed SQLite storage for recovery. No domain/API dependencies."""

import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def cache_key(kind: str, profile_id: str, scenario: str) -> str:
    """JSON encoding avoids delimiter collisions between identifiers."""
    if not all(isinstance(v, str) and v.strip() for v in (kind, profile_id, scenario)):
        raise ValueError('Cache identifiers must be nonempty strings')
    return json.dumps([kind, profile_id, scenario], ensure_ascii=False)


class Database:
    def __init__(self, path=None, *, clock=time.time, busy_timeout_s=5):
        if not math.isfinite(busy_timeout_s) or busy_timeout_s < 0:
            raise ValueError('Invalid database busy timeout')
        self.path = Path(path or os.getenv('DB_PATH') or Path(__file__).resolve().parents[2] / 'data' / 'app.db')
        self.clock = clock
        self.busy_timeout_s = busy_timeout_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=self.busy_timeout_s)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_cache(self, key, data):
        value = json.dumps(data, ensure_ascii=False, allow_nan=False)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, value, self.clock()))

    def load_cache(self, key, max_age_s):
        if not math.isfinite(max_age_s) or max_age_s < 0:
            raise ValueError('Invalid cache age')
        with self.connect() as db:
            row = db.execute('SELECT value,saved_at FROM cache WHERE key=?', (key,)).fetchone()
        if row is None or not 0 <= self.clock() - row['saved_at'] <= max_age_s:
            return None
        try:
            data = json.loads(row['value'])
        except (ValueError, TypeError):
            return None
        return {'data': data, 'saved_at': row['saved_at']}

    def log(self, run_id, step, attempt, status, *, error=None, recovery=None, elapsed_ms=0):
        # Callers pass controlled error codes/class names, never raw exception messages.
        with self.connect() as db:
            db.execute('''INSERT INTO run_logs
                (run_id,step,attempt,status,error,recovery,elapsed_ms,created_at)
                VALUES (?,?,?,?,?,?,?,?)''', (run_id, step, attempt, status,
                error, recovery, elapsed_ms, datetime.now(timezone.utc).isoformat()))

    def logs(self, run_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM run_logs WHERE run_id=? ORDER BY id', (run_id,))]

    def seed_profiles(self, profiles, *, overwrite=False):
        with self.connect() as db:
            for profile in profiles:
                query = '''INSERT INTO profiles VALUES (?,?,?,?,?)
                    ON CONFLICT(profile_id) DO UPDATE SET age=excluded.age,
                    lives_alone=excluded.lives_alone, has_condition=excluded.has_condition,
                    mobility_limited=excluded.mobility_limited''' if overwrite else (
                    'INSERT OR IGNORE INTO profiles VALUES (?,?,?,?,?)')
                db.execute(query,
                    (profile['profile_id'], profile['age'], int(profile['lives_alone']),
                     int(profile['has_condition']), int(profile['mobility_limited'])))

    def get_profile(self, profile_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM profiles WHERE profile_id=?', (profile_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for name in ('lives_alone', 'has_condition', 'mobility_limited'):
            result[name] = bool(result[name])
        return result
