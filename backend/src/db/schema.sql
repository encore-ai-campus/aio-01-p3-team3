CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, saved_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL, step TEXT NOT NULL, attempt INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('success','retry','fallback','fail','error')),
    error TEXT, recovery TEXT, elapsed_ms INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS logs_run ON run_logs(run_id, id);
CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY, age INTEGER NOT NULL,
    lives_alone INTEGER NOT NULL, has_condition INTEGER NOT NULL,
    mobility_limited INTEGER NOT NULL
);
-- Internal simulator storage contract; independent of the pending HTTP request model.
CREATE TABLE IF NOT EXISTS vital_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reading_id TEXT NOT NULL UNIQUE,
    profile_id TEXT NOT NULL,
    scenario TEXT,
    heart_rate INTEGER NOT NULL,
    systolic_bp INTEGER NOT NULL,
    diastolic_bp INTEGER NOT NULL,
    temperature_c REAL NOT NULL,
    spo2 INTEGER NOT NULL,
    measured_at TEXT NOT NULL,
    measured_at_epoch REAL NOT NULL,
    received_at TEXT NOT NULL,
    received_at_epoch REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS readings_latest
    ON vital_readings(profile_id, scenario, measured_at_epoch DESC, id DESC);
