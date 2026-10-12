"""Transactional upgrade of the known original Vital table; preserve unrelated tables."""
from pathlib import Path


def migrate_vital_readings(conn):
    conn.execute('BEGIN IMMEDIATE')
    columns = {r['name']: r for r in conn.execute('PRAGMA table_info(vital_readings)')}
    if not columns:
        conn.commit()
        return
    expected = {'id', 'reading_id', 'profile_id', 'scenario', 'heart_rate',
                'systolic_bp', 'temperature_c', 'spo2', 'measured_at',
                'measured_at_epoch', 'received_at', 'received_at_epoch'}
    if set(columns) not in (expected, expected | {'diastolic_bp'}):
        raise RuntimeError('Unsupported vital_readings schema; migration refused')
    if 'diastolic_bp' in columns and all(not columns[f]['notnull'] for f in
                                        ('systolic_bp', 'temperature_c', 'spo2')):
        conn.commit()
        return
    # Refuse custom dependencies rather than silently losing an index or trigger.
    custom = conn.execute("SELECT name FROM sqlite_master WHERE tbl_name='vital_readings' "
                          "AND type IN ('index','trigger') AND sql IS NOT NULL "
                          "AND name!='readings_latest'").fetchall()
    if custom:
        raise RuntimeError('Custom Vital dependencies require explicit migration')
    sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='vital_readings'").fetchone()
    conn.execute('ALTER TABLE vital_readings RENAME TO vital_readings_old')
    schema = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
    table = schema[schema.index('CREATE TABLE IF NOT EXISTS vital_readings'):]
    conn.execute(table.split(';', 1)[0])
    names = ','.join(columns)
    conn.execute(f'INSERT INTO vital_readings ({names}) SELECT {names} FROM vital_readings_old')
    conn.execute('DROP TABLE vital_readings_old')
    conn.execute('CREATE INDEX readings_latest ON vital_readings'
                 '(profile_id,scenario,measured_at_epoch DESC,id DESC)')
    if sequence:
        conn.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='vital_readings'",
                     (sequence['seq'],))
        if not conn.execute("SELECT 1 FROM sqlite_sequence WHERE name='vital_readings'").fetchone():
            conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('vital_readings',?)",
                         (sequence['seq'],))
    conn.commit()
