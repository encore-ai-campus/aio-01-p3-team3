"""보호자가 토글로 바꾼 에어컨·인덕션 상태 저장 (어르신별)."""
from datetime import datetime, timezone

DEVICES = ('aircon', 'induction')
STATES = ('on', 'off')


class DeviceStates:
    def __init__(self, db):
        self.db = db

    def all(self, profile_id):
        """{기기: 'on'|'off'}. 바꾼 적 없는 기기는 들어 있지 않다."""
        with self.db.connect() as conn:
            rows = conn.execute('SELECT device, state FROM device_states WHERE profile_id=?', (profile_id,)).fetchall()
        return {row['device']: row['state'] for row in rows}

    def set(self, profile_id, device, state):
        if device not in DEVICES or state not in STATES:
            raise ValueError('Unsupported device or state')
        with self.db.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO device_states (profile_id, device, state, updated_at) VALUES (?,?,?,?)',
                         (profile_id, device, state, datetime.now(timezone.utc).isoformat(timespec='seconds')))

    def clear(self, profile_id):
        with self.db.connect() as conn:
            conn.execute('DELETE FROM device_states WHERE profile_id=?', (profile_id,))
