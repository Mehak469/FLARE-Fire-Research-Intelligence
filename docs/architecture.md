# Architecture

```
NASA PSI files / papers / curated CSV
        |  ingest/ (mapping-driven loaders, validators, checksums, quote validation)
        v
SQLite db/flame.db  (runs, samples, measurements, investigations + declared ranges, doc_pages/chunks + FTS5, findings, flags, logs)
        |  core/ (pure Python, no UI imports)
        |    coverage  explore  compare  ranking  retrieval  validators  ask  llm
        v
Streamlit UI (Explore | Compare | Ask | Data quality)      FastAPI (thin, optional)
```

Rules enforced in code and tests: the UI never reads raw files; only `core/` touches the database; only `core/ask.py` calls an LLM; all SQL is parameterized; every displayed number is computed live; blanks stay missing; flags are shown, not fixed silently.

Ask pipeline: policy check (no safety certification or fire prediction) -> requested metric present? -> structured gravity question -> retrieval (investigation text, paper chunks, curated findings, declared ranges, named runs) -> evidence pack with ids -> LLM (optional) -> validators (ids exist, numbers appear in cited evidence, labels not stronger than evidence, no safe/unsafe claims) -> extractive fallback -> log.
