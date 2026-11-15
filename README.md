# FLARE: Fire Lab & Research Intelligence Engine
NASA Space Apps 2026, challenge **Flame in Freefall**. An evidence-first tool that shows where NASA's loaded combustion research covers Moon and Mars conditions, where it is silent, and answers questions only from cited sources.

## Quick start (Windows)
1. Install Python 3.10+ (tick "Add Python to PATH"), then in this folder: `pip install -r requirements.txt`
2. Double-click **build_db.bat** (creates `db/flame.db`; a prebuilt one is included).
3. Double-click **run_app.bat**. The dashboard opens in your browser.
4. Double-click **run_tests.bat** to run the 100+ automated tests.
Mac/Linux: `./run_app.sh`, `./run_tests.sh`.

## What is real in this data (read this)
- **20 investigation records** (BASS, BASS-II, SAFFIRE I-III, SAME, FLEX, ACME...) with declared oxygen/pressure/airflow ranges where known, objectives, fuels, hardware and PSI/DOI links. They were **compiled by a third party** from NASA PSI and are stored `unverified`. Verify at the PSI link, credit the compiler, or re-derive them.
- **10 BASS-II test rows** (typed from screenshots; unverified). The full table, SAFFIRE tables, papers and curated findings are **not loaded yet**.
- Therefore the system can show coverage, compare designs and ranges, and answer questions about **what was studied**. It cannot state experimental **results** until papers/outcome tables are loaded, and it says so.
- All 20 loaded investigations are labeled microgravity: **nothing loaded covers Moon or Mars gravity**. The map shows this as a gap.

## Screens
Explore (coverage map, filters, profiles, ranking) | Compare (investigations or runs) | Ask (cited answers, insufficient-evidence, refusals) | Data quality (flags, verification, sources).

## Add more data
```
python -m flare.cli ingest-table config/mappings/bass2.yaml data/staging/<full BASS-II csv>
python -m flare.cli ingest-pdf paper.pdf --source-key link-2018 --title "..." --investigation BASS-II --doi ...
python -m flare.cli import-findings data/curated/findings.csv   # each quote must appear on the cited page
python -m flare.cli validate
python -m flare.cli verify --investigation BASS-II --labels B1,B6 --by YOURNAME --apply --accept-flags   # after checking the source
python -m flare.cli eval        # grounded-answer evaluation (14 cases)
```
New investigation tables: copy `config/mappings/bass2.yaml`, change the column names.

## LLM (optional)
Default is offline (no key, no network): answers show retrieved evidence verbatim. To enable synthesis set `LLM_PROVIDER`, `LLM_MODEL` and the API key in `.env`. Every LLM answer is validated against the evidence and falls back to the offline answer on failure.

## Verification status of this build
- Core, ingestion, search, comparison, ranking, Ask and validators: **covered by automated tests** (see `run_tests.bat`).
- UI pages: executed in tests against a stand-in for Streamlit/Plotly; **not yet opened in a real browser**. Look at each page once.
- Live LLM clients, FastAPI, Dockerfile: written, **never run** (no network/packages in the build sandbox).
See `docs/DECISIONS.md` and `docs/OPEN_QUESTIONS.md`.

*FLARE is a research-evidence tool. It does not certify materials as safe or unsafe and does not predict fire risk.*
