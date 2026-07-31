-- Attendance system schema (spec.md §4.5, mở rộng cho phần bảo mật + audit)
-- SQLite. Mọi phép ghi đều đi qua code deterministic, không có mô hình can thiệp.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS students (
    student_id       TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    email            TEXT,
    device_hash      TEXT,               -- NULL cho đến lần check-in đầu
    device_locked_at INTEGER,            -- epoch ms, thời điểm khoá thiết bị
    pin_hash         TEXT,               -- PBKDF2 cho trang "dữ liệu của tôi"
    pin_salt         TEXT,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date             TEXT NOT NULL,      -- YYYY-MM-DD
    start_time       TEXT NOT NULL,      -- HH:MM
    room             TEXT,
    state            TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | open | closed
    opened_at        INTEGER,
    closed_at        INTEGER,
    call_index       INTEGER NOT NULL DEFAULT 1,  -- lượt điểm danh đang mở
    second_call_ts   INTEGER,            -- thời điểm gọi điểm danh lần 2
    late_after_min   INTEGER NOT NULL DEFAULT 10,
    UNIQUE (date, start_time)
);

-- Lớp 2: mã QR xoay vòng hiện trên máy chiếu.
-- Token là chuỗi ngẫu nhiên 128-bit lưu phía server (không phải mã dẫn xuất từ
-- thời gian), nên có thể thu hồi tức thì và đếm được số lượt dùng.
CREATE TABLE IF NOT EXISTS qr_tokens (
    token_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    token       TEXT NOT NULL UNIQUE,
    call_index  INTEGER NOT NULL,
    issued_at   INTEGER NOT NULL,        -- epoch ms
    expires_at  INTEGER NOT NULL,        -- epoch ms, hết hạn cứng
    revoked     INTEGER NOT NULL DEFAULT 0,
    use_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS attendance (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     TEXT NOT NULL REFERENCES students(student_id),
    session_id     INTEGER NOT NULL REFERENCES sessions(session_id),
    checkin_ts_ms  INTEGER NOT NULL,
    call_index     INTEGER NOT NULL,     -- 1 = đầu giờ, 2 = giữa giờ
    ip             TEXT,
    device_hash    TEXT,
    fp_hash        TEXT,                 -- băm riêng phần fingerprint, để bắt 2 profile cùng máy
    token_valid    INTEGER NOT NULL DEFAULT 0,
    token_id       INTEGER REFERENCES qr_tokens(token_id),
    status         TEXT NOT NULL,        -- present | late | absent
    source         TEXT NOT NULL DEFAULT 'web',  -- web | manual
    manual_reason  TEXT,                 -- vì sao phải nhập tay (chỉ khi source='manual')
    manual_by      TEXT,                 -- Labcoach nào nhập
    user_agent     TEXT,
    UNIQUE (student_id, session_id, call_index)
);

-- Lớp 3: một thiết bị chỉ điểm danh cho MỘT học viên.
-- Ràng buộc này được chốt ở tầng database, không chỉ ở tầng code: index UNIQUE
-- một phần (bỏ qua NULL) khiến hai học viên không thể cùng giữ một device_hash
-- kể cả khi có đường ghi nào đó quên kiểm tra.
CREATE UNIQUE INDEX IF NOT EXISTS idx_students_device_unique
    ON students(device_hash) WHERE device_hash IS NOT NULL;

-- Lịch sử buộc / nhả thiết bị. Cần cho khiếu nại: "vì sao buổi đó tôi không
-- điểm danh được" phải trả lời được bằng dữ liệu, không bằng trí nhớ.
CREATE TABLE IF NOT EXISTS device_bindings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT NOT NULL REFERENCES students(student_id),
    device_hash   TEXT NOT NULL,
    bound_at      INTEGER NOT NULL,
    released_at   INTEGER,              -- NULL = đang hiệu lực
    released_by   TEXT,                 -- username Labcoach đã nhả
    release_note  TEXT
);

CREATE TABLE IF NOT EXISTS anomaly_flags (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attendance_id INTEGER REFERENCES attendance(id) ON DELETE CASCADE,
    session_id    INTEGER REFERENCES sessions(session_id),
    student_id    TEXT REFERENCES students(student_id),
    rule_code     TEXT NOT NULL,         -- DEVICE_REUSE | IP_RATE_SPIKE | DEVICE_MISMATCH | EARLY_DEPARTURE | TOKEN_GRACE_USED
    severity      TEXT NOT NULL,         -- low | med | high
    detail        TEXT,
    created_at    INTEGER NOT NULL,
    resolved      INTEGER NOT NULL DEFAULT 0,
    resolved_by   TEXT,
    resolved_note TEXT,
    UNIQUE (attendance_id, rule_code)
);

CREATE TABLE IF NOT EXISTS risk_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT NOT NULL REFERENCES students(student_id),
    date          TEXT NOT NULL,
    risk_level    TEXT NOT NULL,         -- ok | watch | at_risk
    rule_trace    TEXT NOT NULL,         -- JSON: rule nào kích hoạt, để audit
    llm_diagnosis TEXT,                  -- NULL khi tầng mô hình tắt
    llm_message   TEXT,                  -- NULL khi tầng mô hình tắt
    sent          INTEGER NOT NULL DEFAULT 0,
    sent_at       INTEGER,
    created_at    INTEGER NOT NULL,
    UNIQUE (student_id, date)
);

-- ------------------------------------------------------------------
-- Bảng phục vụ xác thực / audit (ngoài §4.5)
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS admins (
    username      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    pw_hash       TEXT NOT NULL,         -- PBKDF2-HMAC-SHA256
    pw_salt       TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'labcoach',  -- labcoach | owner
    created_at    INTEGER NOT NULL,
    last_login_at INTEGER
);

-- Chống replay: một token chỉ dùng được 1 lần cho 1 học viên
CREATE TABLE IF NOT EXISTS token_usage (
    token_id    INTEGER NOT NULL REFERENCES qr_tokens(token_id) ON DELETE CASCADE,
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    used_at     INTEGER NOT NULL,
    PRIMARY KEY (token_id, student_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         INTEGER NOT NULL,
    actor      TEXT NOT NULL,            -- username admin, student_id, hoặc 'system'
    action     TEXT NOT NULL,
    target     TEXT,
    detail     TEXT,
    ip         TEXT
);

CREATE INDEX IF NOT EXISTS idx_att_session   ON attendance(session_id, call_index);
CREATE INDEX IF NOT EXISTS idx_att_student   ON attendance(student_id, session_id);
CREATE INDEX IF NOT EXISTS idx_att_device    ON attendance(session_id, device_hash);
CREATE INDEX IF NOT EXISTS idx_att_ip        ON attendance(session_id, ip, checkin_ts_ms);
CREATE INDEX IF NOT EXISTS idx_flag_student  ON anomaly_flags(student_id, created_at);
CREATE INDEX IF NOT EXISTS idx_flag_session  ON anomaly_flags(session_id);
CREATE INDEX IF NOT EXISTS idx_risk_date     ON risk_snapshots(date, risk_level);
CREATE INDEX IF NOT EXISTS idx_audit_ts      ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_token_session ON qr_tokens(session_id, call_index, issued_at);
CREATE INDEX IF NOT EXISTS idx_binding_student ON device_bindings(student_id, bound_at);
CREATE INDEX IF NOT EXISTS idx_binding_device  ON device_bindings(device_hash);
