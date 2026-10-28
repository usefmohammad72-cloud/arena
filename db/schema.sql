PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS persons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    national_code TEXT UNIQUE NOT NULL,
    first_name    TEXT,
    last_name     TEXT
);

CREATE TABLE IF NOT EXISTS records (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id              INTEGER NOT NULL REFERENCES persons(id),
    period_month           TEXT NOT NULL,
    deputy                 TEXT,
    cost_center            TEXT,
    main_cost_center       TEXT,
    legal_article          TEXT,
    has_second_salary      TEXT,
    employment_status      TEXT,
    contract_subject       TEXT,
    program_name_raw       TEXT,
    program_name_resolved  TEXT,
    skill_card_bonus       REAL DEFAULT 0,
    employer_insurance     REAL DEFAULT 0,
    non_continuous_bonus   REAL DEFAULT 0,
    monthly_wage           REAL DEFAULT 0,
    yearly_paid_total      REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_records_deputy ON records(deputy);
CREATE INDEX IF NOT EXISTS idx_records_center ON records(cost_center);
CREATE INDEX IF NOT EXISTS idx_records_period ON records(period_month);

CREATE TABLE IF NOT EXISTS pricing_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    deputy              TEXT NOT NULL,
    legal_article       TEXT NOT NULL,
    category            TEXT NOT NULL,
    job_title           TEXT,
    cost_center_filter  TEXT,
    amount              REAL,
    priority            INTEGER DEFAULT 0,
    valid_from          TEXT NOT NULL,
    valid_to            TEXT,
    created_by          TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rules_lookup
    ON pricing_rules(deputy, legal_article, category, cost_center_filter);

CREATE TABLE IF NOT EXISTS deputies_structure (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    deputy  TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS centers_structure (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    center_name    TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    supply_type    TEXT,
    deputy         TEXT,
    monthly_quota  REAL,
    UNIQUE(center_name, supply_type)
);
CREATE INDEX IF NOT EXISTS idx_centers_deputy ON centers_structure(deputy);

CREATE TABLE IF NOT EXISTS center_name_mappings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    wrong_text     TEXT NOT NULL UNIQUE,
    correct_center TEXT NOT NULL,
    approved_by    TEXT,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calculated_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id           INTEGER NOT NULL REFERENCES records(id),
    ceiling_status      TEXT,
    applied_rule_id     INTEGER REFERENCES pricing_rules(id),
    yearly_paid_total   REAL,
    exempted_ceiling    REAL,
    six_month_ceiling   REAL,
    payment_list_status TEXT,
    manager_approved    INTEGER DEFAULT 0,
    calculated_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(record_id)
);

CREATE TABLE IF NOT EXISTS employment_monthly (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    national_code      TEXT NOT NULL,
    period_month       TEXT NOT NULL,
    first_name         TEXT,
    last_name          TEXT,
    employment_status  TEXT,
    main_cost_center   TEXT,
    uploaded_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(national_code, period_month)
);
CREATE INDEX IF NOT EXISTS idx_employment_nc ON employment_monthly(national_code);

CREATE TABLE IF NOT EXISTS monthly_payments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    national_code  TEXT NOT NULL,
    period_month   TEXT NOT NULL,
    amount         REAL NOT NULL DEFAULT 0,
    source         TEXT NOT NULL DEFAULT 'manual'
                    CHECK(source IN ('manual','auto','approved')),
    record_id      INTEGER REFERENCES records(id),
    note           TEXT,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(national_code, period_month)
);
CREATE INDEX IF NOT EXISTS idx_payments_nc ON monthly_payments(national_code);
CREATE INDEX IF NOT EXISTS idx_payments_period ON monthly_payments(period_month);

CREATE TABLE IF NOT EXISTS specialists_equipment_bonus (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    center_name  TEXT NOT NULL,
    supply_type  TEXT NOT NULL DEFAULT '',
    specialists  REAL DEFAULT 0,
    equipment    REAL DEFAULT 0,
    bonus        REAL DEFAULT 0,
    UNIQUE(center_name, supply_type)
);

CREATE TABLE IF NOT EXISTS manual_monthly_ceilings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    center_name  TEXT NOT NULL,
    supply_type  TEXT NOT NULL DEFAULT '',
    period_month TEXT NOT NULL,
    amount       REAL NOT NULL DEFAULT 0,
    note         TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(center_name, supply_type, period_month)
);
CREATE INDEX IF NOT EXISTS idx_mmc_period ON manual_monthly_ceilings(period_month);
CREATE INDEX IF NOT EXISTS idx_mmc_center ON manual_monthly_ceilings(center_name);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('bt1_month_factor', '5');

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('مدیر سامانه','کارشناس','ناظر'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT,
    action      TEXT,
    details     TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);