-- ============================================================
-- Flame in Freefall - evidence database (SQLite)
-- Design rules: one row = one burn (run); every value keeps its
-- raw form + normalized form + source; missing stays NULL.
-- Run:  sqlite3 flame.db < schema.sql
-- ============================================================
PRAGMA foreign_keys = ON;

-- ---------- 1. LOOKUP / DICTIONARY TABLES ----------
CREATE TABLE regimes (
  regime_id   INTEGER PRIMARY KEY,
  code        TEXT NOT NULL UNIQUE,
  description TEXT
);
INSERT INTO regimes (code, description) VALUES
  ('solid_spread',   'Flame spread over solid fuel (sheets, rods, slabs)'),
  ('droplet',        'Burning fuel droplets (spherical, cool flames)'),
  ('gas_flame',      'Gas-jet / coflow flames, stability, blow-off'),
  ('soot_smoke',     'Soot, smoke point, particle size'),
  ('large_fire',     'Large-scale spacecraft fires (Saffire-type)'),
  ('other',          'Anything that does not fit yet');

CREATE TABLE metrics (
  metric_id       INTEGER PRIMARY KEY,
  code            TEXT NOT NULL UNIQUE,      -- e.g. flame_spread_rate
  name            TEXT NOT NULL,
  regime_id       INTEGER REFERENCES regimes(regime_id),
  canonical_unit  TEXT NOT NULL,             -- everything is converted to this
  risk_direction  TEXT CHECK (risk_direction IN ('higher_worse','lower_worse','neutral')),
  is_outcome      INTEGER NOT NULL DEFAULT 0 CHECK (is_outcome IN (0,1)),  -- 1 = result, 0 = reading
  description     TEXT
);
INSERT INTO metrics (code, name, regime_id, canonical_unit, risk_direction) VALUES
  ('flame_spread_rate',   'Flame spread rate',            1, 'mm/s',   'higher_worse'),
  ('burn_time',           'Burn duration',                NULL,'s',    'higher_worse'),
  ('flame_length',        'Flame length',                 NULL,'mm',   'higher_worse'),
  ('flame_temperature',   'Peak flame temperature',       NULL,'K',    'higher_worse'),
  ('heat_release_rate',   'Heat release rate',            5, 'W',      'higher_worse'),
  ('burn_rate_constant',  'Droplet burning-rate constant',2, 'mm2/s',  'higher_worse'),
  ('extinction_diameter', 'Droplet diameter at extinction',2, 'mm',    'neutral'),
  ('limiting_oxygen',     'Limiting oxygen (flammability limit)', 1, 'pct O2', 'lower_worse'),
  ('co_yield',            'Carbon monoxide yield',        1, 'g/g',    'higher_worse'),
  ('smoke_point',         'Smoke point',                  4, 'mm',     'neutral'),
  ('soot_particle_size',  'Soot particle size',           4, 'nm',     'neutral');

-- gas-composition measurements (initial/final) seen in the BASS-II experimental table
INSERT INTO metrics (code, name, regime_id, canonical_unit, risk_direction) VALUES
  ('o2_final_pct',   'Final O2 in test chamber',   1, 'pct', 'neutral'),
  ('co2_initial_pct','Initial CO2 in chamber',     1, 'pct', 'neutral'),
  ('co2_final_pct',  'Final CO2 in chamber',       1, 'pct', 'neutral'),
  ('co_initial_ppm', 'Initial CO in chamber',      1, 'ppm', 'neutral'),
  ('co_final_ppm',   'Final CO in chamber',        1, 'ppm', 'higher_worse');

-- outcome metrics are the ones that count as 'quantitative results' in ranking
UPDATE metrics SET is_outcome = 1 WHERE code IN
  ('flame_spread_rate','burn_time','flame_length','flame_temperature','heat_release_rate',
   'burn_rate_constant','extinction_diameter','limiting_oxygen','co_yield','smoke_point','soot_particle_size');

-- ---------- 2. PROVENANCE ----------
CREATE TABLE sources (
  source_id    INTEGER PRIMARY KEY,
  source_key   TEXT UNIQUE,          -- short stable key used by curated CSV files, e.g. 'psi-25' or 'link-2018'
  source_type  TEXT NOT NULL CHECK (source_type IN
                ('psi_file','ntrs_report','journal_paper','presentation','other')),
  title        TEXT,
  citation     TEXT,
  ntrs_id      TEXT,                 -- e.g. 20180005168
  url          TEXT,
  local_file   TEXT,                 -- path inside /raw
  sha256       TEXT,                 -- checksum proves the file never changed
  retrieved_on TEXT,                 -- ISO date
  doi          TEXT,
  authors      TEXT,
  pub_year     INTEGER
);

CREATE TABLE investigations (
  investigation_id INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,  -- short code: 'BASS-II', 'SAFFIRE-III', 'FLEX-2'
  full_name   TEXT,
  psi_id      TEXT,                  -- 'PSI-25'
  doi         TEXT,
  program     TEXT,                  -- BASS, Saffire, FLEX, ACME, SAME...
  platform    TEXT,                  -- ISS, Cygnus...
  regime_id   INTEGER REFERENCES regimes(regime_id),
  start_year  INTEGER,
  summary     TEXT,
  psi_url     TEXT,
  safety_area TEXT,                  -- prevention;suppression;detection (as listed)
  fuel_type   TEXT,                  -- solid;liquid;gas
  fuel_detail TEXT,
  hardware    TEXT,
  sensors     TEXT,
  objective   TEXT,
  variables   TEXT,
  habitats    TEXT,
  earth_application TEXT,
  relevance_note    TEXT,
  gravity_label     TEXT,            -- as written: 'microgravity'
  third_party_status TEXT,           -- status claimed by the compiling third party; NOT our verification
  qa_status   TEXT NOT NULL DEFAULT 'unverified'
               CHECK (qa_status IN ('unverified','auto_checked','human_verified','rejected')),
  notes       TEXT
);

-- Declared tested range per investigation (from the investigation record, not per run)
CREATE TABLE investigation_conditions (
  cond_id          INTEGER PRIMARY KEY,
  investigation_id INTEGER NOT NULL REFERENCES investigations(investigation_id) ON DELETE CASCADE,
  quantity         TEXT NOT NULL CHECK (quantity IN ('o2_pct','pressure_kpa','flow_cm_s')),
  min_value        REAL,
  max_value        REAL,
  unit             TEXT NOT NULL,
  source_id        INTEGER REFERENCES sources(source_id),
  source_ref       TEXT,
  qa_status        TEXT NOT NULL DEFAULT 'unverified'
                    CHECK (qa_status IN ('unverified','auto_checked','human_verified','rejected')),
  UNIQUE (investigation_id, quantity),
  CHECK (min_value IS NOT NULL OR max_value IS NOT NULL),
  CHECK (min_value IS NULL OR max_value IS NULL OR min_value <= max_value)
);

CREATE TABLE investigation_sources (
  investigation_id INTEGER NOT NULL REFERENCES investigations(investigation_id),
  source_id        INTEGER NOT NULL REFERENCES sources(source_id),
  PRIMARY KEY (investigation_id, source_id)
);

-- ---------- 3. MATERIALS (with alias resolution) ----------
CREATE TABLE materials (
  material_id    INTEGER PRIMARY KEY,
  canonical_name TEXT NOT NULL UNIQUE,   -- 'SIBAL (cotton-fiberglass)'
  category       TEXT,                   -- fabric, polymer, liquid_fuel, gas...
  composition    TEXT,
  notes          TEXT
);
CREATE TABLE material_aliases (
  alias        TEXT PRIMARY KEY COLLATE NOCASE,  -- every spelling seen in sources
  material_id  INTEGER NOT NULL REFERENCES materials(material_id)
);

-- ---------- 4. RUNS (one row = one burn) ----------
CREATE TABLE runs (
  run_id           INTEGER PRIMARY KEY,
  investigation_id INTEGER NOT NULL REFERENCES investigations(investigation_id),
  run_label        TEXT NOT NULL,          -- label used in the source: 'Test 3'
  run_date         TEXT,
  -- conditions (normalized units; NULL = not stated in source)
  gravity_g        REAL CHECK (gravity_g IS NULL OR gravity_g BETWEEN 0 AND 1.5),
  o2_pct           REAL CHECK (o2_pct IS NULL OR o2_pct BETWEEN 0 AND 100),
  pressure_kpa     REAL CHECK (pressure_kpa IS NULL OR pressure_kpa > 0),
  diluent_gas      TEXT,                   -- N2, He, CO2...
  flow_cm_s        REAL CHECK (flow_cm_s IS NULL OR flow_cm_s >= 0),
  flow_mode        TEXT CHECK (flow_mode IN ('opposed','concurrent','quiescent','mixed','unknown')),
  temperature_k    REAL,
  ignition_method  TEXT,
  -- categorical outcomes
  ignited          INTEGER CHECK (ignited IN (0,1)),
  extinguished     INTEGER CHECK (extinguished IN (0,1)),
  extinction_mode  TEXT CHECK (extinction_mode IN
                    ('quench','blowoff','fuel_depleted','oxygen_depleted','radiative','other','unknown')),
  -- provenance + quality
  source_id        INTEGER REFERENCES sources(source_id),
  source_ref       TEXT,                   -- 'Table 2, p.14'
  raw_record       TEXT,                   -- original row as JSON/text, for audit
  qa_status        TEXT NOT NULL DEFAULT 'unverified'
                    CHECK (qa_status IN ('unverified','auto_checked','human_verified','rejected')),
  notes            TEXT,
  UNIQUE (investigation_id, run_label)
);
CREATE INDEX idx_runs_conditions ON runs (gravity_g, o2_pct, pressure_kpa, flow_cm_s);
CREATE INDEX idx_runs_inv ON runs (investigation_id);

-- one run can hold several samples (e.g., an array of fabrics)
CREATE TABLE samples (
  sample_id    INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  material_id  INTEGER NOT NULL REFERENCES materials(material_id),
  geometry     TEXT CHECK (geometry IN ('sheet','rod','slab','droplet','cylinder','other')),
  thickness_mm REAL, width_mm REAL, length_mm REAL, diameter_mm REAL, mass_g REAL,
  notes        TEXT
);
CREATE INDEX idx_samples_material ON samples (material_id);
CREATE INDEX idx_samples_run ON samples (run_id);

-- Settings and source columns that are not conditions or results
-- (fan display, flow restrictor, frame counts, day-of-year...). Keeps runs clean.
CREATE TABLE run_attributes (
  attr_id    INTEGER PRIMARY KEY,
  run_id     INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  key        TEXT NOT NULL,
  value_text TEXT,                -- exactly as written in the source
  value_num  REAL,                -- only if it is a single clean number
  unit_raw   TEXT,
  source_ref TEXT,
  UNIQUE (run_id, key)
);

-- ---------- 5. MEASUREMENTS (tall table: any metric, any regime) ----------
CREATE TABLE measurements (
  measurement_id INTEGER PRIMARY KEY,
  run_id         INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  sample_id      INTEGER REFERENCES samples(sample_id),
  metric_id      INTEGER NOT NULL REFERENCES metrics(metric_id),
  value_si       REAL,                 -- converted to metrics.canonical_unit
  qualifier      TEXT NOT NULL DEFAULT '=' CHECK (qualifier IN ('=','<','>','~')),
  uncertainty    REAL,
  value_raw      TEXT,                 -- exactly as written: '0.8', '< 0.5'
  unit_raw       TEXT,                 -- exactly as written: 'mm/s', 'cm/s'
  method         TEXT,                 -- video analysis, thermocouple...
  source_id      INTEGER REFERENCES sources(source_id),
  source_ref     TEXT,
  extracted_by   TEXT NOT NULL DEFAULT 'manual' CHECK (extracted_by IN ('manual','script','llm')),
  qa_status      TEXT NOT NULL DEFAULT 'unverified'
                  CHECK (qa_status IN ('unverified','auto_checked','human_verified','rejected'))
);
CREATE INDEX idx_meas_metric ON measurements (metric_id, run_id);
CREATE UNIQUE INDEX uq_meas ON measurements (run_id, COALESCE(sample_id,0), metric_id, COALESCE(source_ref,''));

-- ---------- 6. FINDINGS + DOCUMENT CHUNKS (explanation layer) ----------
CREATE TABLE findings (
  finding_id       INTEGER PRIMARY KEY,
  investigation_id INTEGER REFERENCES investigations(investigation_id),
  statement        TEXT NOT NULL,      -- one plain-language claim
  evidence_label   TEXT NOT NULL DEFAULT 'published_finding' CHECK (evidence_label IN
                    ('configuration','measured_observation','published_finding',
                     'interpretation','hypothesis','unknown')),
  topic            TEXT,               -- e.g. airflow_effect, oxygen_limit, extinction
  quote            TEXT,               -- exact supporting text from the source
  limitations      TEXT,
  confidence       TEXT CHECK (confidence IN ('low','medium','high')),
  source_id        INTEGER NOT NULL REFERENCES sources(source_id),
  source_ref       TEXT NOT NULL,      -- no claim without a page/table pointer
  page             INTEGER,
  qa_status        TEXT NOT NULL DEFAULT 'unverified'
                    CHECK (qa_status IN ('unverified','auto_checked','human_verified','rejected')),
  verified_by      TEXT,
  verified_on      TEXT
);
CREATE TABLE finding_runs (
  finding_id INTEGER NOT NULL REFERENCES findings(finding_id) ON DELETE CASCADE,
  run_id     INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  PRIMARY KEY (finding_id, run_id)
);
-- Full text of each page (used to validate quotes); investigation records use page 1
CREATE TABLE doc_pages (
  source_id INTEGER NOT NULL REFERENCES sources(source_id),
  page      INTEGER NOT NULL,
  text      TEXT NOT NULL,
  PRIMARY KEY (source_id, page)
);
CREATE TABLE doc_chunks (
  chunk_id         INTEGER PRIMARY KEY,
  source_id        INTEGER NOT NULL REFERENCES sources(source_id),
  investigation_id INTEGER REFERENCES investigations(investigation_id),
  section          TEXT,               -- 'objective', 'variables'... (investigation text) or NULL (papers)
  page             INTEGER,
  chunk_index      INTEGER NOT NULL,
  text             TEXT NOT NULL,
  embedding        BLOB,
  UNIQUE (source_id, page, chunk_index)
);

-- Full-text search (BM25) over paper text and findings
CREATE VIRTUAL TABLE doc_chunks_fts USING fts5(text, content='doc_chunks', content_rowid='chunk_id');
CREATE TRIGGER doc_chunks_ai AFTER INSERT ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(rowid, text) VALUES (new.chunk_id, new.text);
END;
CREATE TRIGGER doc_chunks_ad AFTER DELETE ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, text) VALUES ('delete', old.chunk_id, old.text);
END;
CREATE VIRTUAL TABLE findings_fts USING fts5(statement, topic, content='findings', content_rowid='finding_id');
CREATE TRIGGER findings_ai AFTER INSERT ON findings BEGIN
  INSERT INTO findings_fts(rowid, statement, topic) VALUES (new.finding_id, new.statement, new.topic);
END;
CREATE TRIGGER findings_ad AFTER DELETE ON findings BEGIN
  INSERT INTO findings_fts(findings_fts, rowid, statement, topic)
    VALUES ('delete', old.finding_id, old.statement, old.topic);
END;

-- Every question asked of the assistant, for audit and evaluation
CREATE TABLE ask_log (
  ask_id        INTEGER PRIMARY KEY,
  asked_at      TEXT NOT NULL DEFAULT (datetime('now')),
  question      TEXT NOT NULL,
  evidence_ids  TEXT,                 -- JSON list of evidence ids given to the model
  answer_json   TEXT,                 -- final structured answer
  validation    TEXT,                 -- 'passed' | 'failed:<reason>' | 'insufficient'
  mode          TEXT                  -- 'llm' | 'extractive'
);

-- ---------- 7. DERIVED RESULTS (rebuildable, never hand-edited) ----------
CREATE TABLE risk_scores (
  score_id       INTEGER PRIMARY KEY,
  model_version  TEXT NOT NULL,
  material_id    INTEGER REFERENCES materials(material_id),
  gravity_class  TEXT, o2_bin TEXT, pressure_bin TEXT, flow_bin TEXT,
  score          REAL,
  ci_low         REAL, ci_high REAL,
  n_runs         INTEGER NOT NULL,
  n_investigations INTEGER NOT NULL,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- 8. DATA FLAGS + AUDIT LOG ----------
-- Anything an ingest or validator is unsure about. Flags are shown in the UI, never silently fixed.
CREATE TABLE data_flags (
  flag_id    INTEGER PRIMARY KEY,
  table_name TEXT NOT NULL,
  row_id     INTEGER NOT NULL,
  flag       TEXT NOT NULL,          -- short code, e.g. 'negative_gas'
  detail     TEXT,
  severity   TEXT NOT NULL DEFAULT 'warn' CHECK (severity IN ('info','warn','error')),
  created_by TEXT NOT NULL DEFAULT 'ingest',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  resolved   INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0,1))
);
CREATE INDEX idx_flags_row ON data_flags (table_name, row_id);

CREATE TABLE edit_log (
  log_id     INTEGER PRIMARY KEY,
  table_name TEXT NOT NULL, row_id INTEGER NOT NULL, field TEXT NOT NULL,
  old_value  TEXT, new_value TEXT,
  actor      TEXT NOT NULL, reason TEXT,
  at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- VIEWS (the dashboard talks to these, not to raw tables)
-- ============================================================
-- Bin definitions are modelling choices: change them HERE only.
CREATE VIEW v_run_bins AS
SELECT r.run_id, r.investigation_id, r.qa_status,
  CASE WHEN r.gravity_g IS NULL THEN 'unknown'
       WHEN r.gravity_g < 0.01 THEN 'micro'
       WHEN r.gravity_g BETWEEN 0.10 AND 0.25 THEN 'lunar'
       WHEN r.gravity_g BETWEEN 0.30 AND 0.45 THEN 'mars'
       WHEN r.gravity_g >= 0.9 THEN 'earth' ELSE 'other' END AS gravity_class,
  CASE WHEN r.o2_pct IS NULL THEN 'unknown'
       WHEN r.o2_pct < 21 THEN 'lt21'
       WHEN r.o2_pct < 25 THEN '21-25'
       WHEN r.o2_pct < 30 THEN '25-30'
       WHEN r.o2_pct < 40 THEN '30-40' ELSE 'gte40' END AS o2_bin,
  CASE WHEN r.pressure_kpa IS NULL THEN 'unknown'
       WHEN r.pressure_kpa < 60 THEN 'lt60'
       WHEN r.pressure_kpa < 95 THEN '60-95'
       WHEN r.pressure_kpa < 110 THEN '95-110' ELSE 'gte110' END AS pressure_bin,
  CASE WHEN r.flow_cm_s IS NULL THEN 'unknown'
       WHEN r.flow_cm_s = 0 THEN 'quiescent'
       WHEN r.flow_cm_s < 10 THEN '0-10'
       WHEN r.flow_cm_s < 30 THEN '10-30' ELSE 'gte30' END AS flow_bin
FROM runs r WHERE r.qa_status <> 'rejected';

-- Flat view for the explorer table
CREATE VIEW v_run_flat AS
SELECT r.run_id, i.name AS investigation, i.program, i.platform,
       r.run_label, m.canonical_name AS material, s.geometry, s.thickness_mm,
       r.gravity_g, r.o2_pct, r.pressure_kpa, r.flow_cm_s, r.flow_mode,
       r.ignited, r.extinguished, r.extinction_mode, r.qa_status,
       src.title AS source_title, r.source_ref
FROM runs r
JOIN investigations i ON i.investigation_id = r.investigation_id
LEFT JOIN samples s ON s.run_id = r.run_id
LEFT JOIN materials m ON m.material_id = s.material_id
LEFT JOIN sources src ON src.source_id = r.source_id
WHERE r.qa_status <> 'rejected';

-- Wide view for the solid-spread regime (pivot of the tall table)
CREATE VIEW v_solid_spread AS
SELECT r.run_id, i.name AS investigation, ma.canonical_name AS material,
       s.thickness_mm, r.gravity_g, r.o2_pct, r.pressure_kpa, r.flow_cm_s, r.flow_mode,
       MAX(CASE WHEN me.metric_id = (SELECT metric_id FROM metrics WHERE code='flame_spread_rate')
                THEN me.value_si END) AS spread_mm_s,
       MAX(CASE WHEN me.metric_id = (SELECT metric_id FROM metrics WHERE code='burn_time')
                THEN me.value_si END) AS burn_time_s
FROM runs r
JOIN investigations i ON i.investigation_id = r.investigation_id
JOIN samples s ON s.run_id = r.run_id
JOIN materials ma ON ma.material_id = s.material_id
LEFT JOIN measurements me ON me.run_id = r.run_id AND (me.sample_id IS NULL OR me.sample_id = s.sample_id)
WHERE r.qa_status <> 'rejected'
GROUP BY r.run_id, s.sample_id;

-- Evidence coverage: how many runs per condition cell (zero = a GAP)
CREATE VIEW v_coverage_gaps AS
WITH g(gravity_class) AS (VALUES ('micro'),('lunar'),('mars'),('earth')),
     o(o2_bin)        AS (VALUES ('lt21'),('21-25'),('25-30'),('30-40'),('gte40')),
     p(pressure_bin)  AS (VALUES ('lt60'),('60-95'),('95-110'),('gte110')),
     f(flow_bin)      AS (VALUES ('quiescent'),('0-10'),('10-30'),('gte30')),
     cells AS (SELECT * FROM g, o, p, f)
SELECT c.gravity_class, c.o2_bin, c.pressure_bin, c.flow_bin,
       COUNT(b.run_id)                    AS n_runs,
       COUNT(DISTINCT b.investigation_id) AS n_investigations,
       SUM(CASE WHEN b.qa_status = 'human_verified' THEN 1 ELSE 0 END) AS n_verified
FROM cells c
LEFT JOIN v_run_bins b
  ON b.gravity_class = c.gravity_class AND b.o2_bin = c.o2_bin
 AND b.pressure_bin = c.pressure_bin  AND b.flow_bin = c.flow_bin
GROUP BY c.gravity_class, c.o2_bin, c.pressure_bin, c.flow_bin;

-- Data-quality dashboard: how complete are the key fields?
CREATE VIEW v_data_quality AS
SELECT i.name AS investigation, COUNT(*) AS n_runs,
       SUM(r.o2_pct IS NULL)       AS missing_o2,
       SUM(r.pressure_kpa IS NULL) AS missing_pressure,
       SUM(r.flow_cm_s IS NULL)    AS missing_flow,
       SUM(r.gravity_g IS NULL)    AS missing_gravity,
       SUM(r.qa_status='human_verified') AS verified
FROM runs r JOIN investigations i ON i.investigation_id = r.investigation_id
GROUP BY i.name;

-- One row per investigation for the explorer cards
CREATE VIEW v_investigation_stats AS
SELECT i.investigation_id, i.name, i.program, i.platform, i.psi_url,
       (SELECT code FROM regimes WHERE regime_id = i.regime_id) AS regime,
       COUNT(DISTINCT r.run_id) AS n_runs,
       COUNT(DISTINCT CASE WHEN r.qa_status = 'human_verified' THEN r.run_id END) AS n_verified_runs,
       COUNT(DISTINCT CASE WHEN m.is_outcome = 1 THEN r.run_id END) AS n_runs_with_outcome,
       (SELECT COUNT(*) FROM findings f WHERE f.investigation_id = i.investigation_id
          AND f.qa_status <> 'rejected') AS n_findings,
       (SELECT COUNT(*) FROM investigation_sources s WHERE s.investigation_id = i.investigation_id) AS n_sources
FROM investigations i
LEFT JOIN runs r ON r.investigation_id = i.investigation_id AND r.qa_status <> 'rejected'
LEFT JOIN measurements me ON me.run_id = r.run_id
LEFT JOIN metrics m ON m.metric_id = me.metric_id
GROUP BY i.investigation_id;

-- Runs that cannot be placed on every coverage axis (unknown gravity/O2/pressure/flow).
-- The UI MUST show these next to the coverage map; otherwise missing metadata looks like missing evidence.
CREATE VIEW v_unmapped_runs AS
SELECT run_id, investigation_id, gravity_class, o2_bin, pressure_bin, flow_bin
FROM v_run_bins
WHERE 'unknown' IN (gravity_class, o2_bin, pressure_bin, flow_bin);
