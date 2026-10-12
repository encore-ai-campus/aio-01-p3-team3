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
    mobility_limited INTEGER NOT NULL,
    area TEXT
);
-- Internal simulator storage contract; independent of the pending HTTP request model.
CREATE TABLE IF NOT EXISTS vital_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reading_id TEXT NOT NULL UNIQUE,
    profile_id TEXT NOT NULL,
    scenario TEXT,
    heart_rate INTEGER NOT NULL,
    systolic_bp INTEGER,
    temperature_c REAL,
    spo2 INTEGER,
    measured_at TEXT NOT NULL,
    measured_at_epoch REAL NOT NULL,
    received_at TEXT NOT NULL,
    received_at_epoch REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS readings_latest
    ON vital_readings(profile_id, scenario, measured_at_epoch DESC, id DESC);
-- 보호자가 화면 토글로 바꾼 기기 상태. 새 "상태 확인하기"를 실행하면 해당 어르신 것은 지워지고 시나리오 기본값으로 돌아간다.
CREATE TABLE IF NOT EXISTS device_states (
    profile_id TEXT NOT NULL,
    device TEXT NOT NULL CHECK(device IN ('aircon','induction')),
    state TEXT NOT NULL CHECK(state IN ('on','off')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, device)
);
