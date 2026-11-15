# Decisions and deviations from the build specification

Rule R2: when real data or the environment contradicted the spec, the data/environment won. Each entry says what, why, and what to revisit.

| # | Decision | Why | Revisit when |
|---|---|---|---|
| D1 | **The supplied data is investigation-level**, not run-level. Only 10 BASS-II test rows exist at run level (typed from screenshots, unverified). | `investigations.csv/json` hold 20 records (ranges, objectives, fuels, hardware, links). No experimental tables or papers were supplied. | Load the full BASS-II CSV, SAFFIRE tables, and papers. |
| D2 | **Two kinds of evidence are modeled and counted separately**: declared tested ranges per investigation (`investigation_conditions`) and individual runs (`runs`). | With D1, a run-only design would show an empty map. Mixing them would overstate evidence. | Once many runs are loaded, run-level coverage should dominate. |
| D3 | **Regime per investigation comes from `config/regime_map.yaml`** (our classification, not a NASA field). | Needed so droplets, solid spread, gas flames and smoke are never pooled. | A domain expert disagrees with an assignment. |
| D4 | **Coverage default is two axes (gravity x oxygen)**. Evidence with an unknown value on a chosen axis is reported as UNMAPPED, never counted as a gap. | 10 of 20 investigations state no oxygen range; every loaded run lacks pressure and airflow velocity. A 4-axis map would show false gaps. | More ranges or run metadata become available. |
| D5 | **One-ended ranges** (e.g. airflow "up to 40 cm/s") only claim the stated point. | A missing lower end must not be treated as 0. | The source states the other end. |
| D6 | **Ranking adaptation**: condition match uses declared ranges, refined by runs when loaded; unknown counts as no match and is listed. Evidence strength is 0 without runs. | The spec formula assumed many runs per investigation. | Run data arrives; revisit weights. |
| D7 | **Retrieval = SQLite FTS5 candidate search + token-overlap relevance gate** (not a BM25 threshold). | BM25 scores are tiny and unstable on a small corpus; an overlap gate is deterministic and testable. | Corpus grows (papers): consider hybrid embeddings (P2). |
| D8 | **All answers from investigation text are labeled `configuration_only`**. Stronger labels require curated findings or measurements. | The text describes what was studied and ranges declared, not results. | Curated findings are imported. |
| D9 | **PDF library is `pypdf`** (spec said PyMuPDF). | PyMuPDF is not installed in the build environment; pypdf is pure Python and tested. | Better extraction needed: swap behind `pdf_text.py`. |
| D10 | **No pydantic**; plain dicts and dataclass-free functions. | Not installed in the build environment; the core needs no web framework. | The FastAPI layer wants typed schemas. |
| D11 | **BASS-II `gravity_g = 0.0`** is set from the investigation's platform (ISS), flagged in notes. | The table has no gravity column. | The PSI Description page says otherwise. |
| D12 | **Provenance of `investigations.json`**: compiled by a third party from NASA PSI records; every value is stored `unverified`, each investigation keeps its PSI URL and DOI. The file's own `data_status: verified` is stored as `third_party_status` and is NOT our verification. | We cannot confirm their checking. | A person checks records at the PSI links and runs `cli verify --record`. |
| D13 | **Live LLM clients (Anthropic, OpenAI-compatible) are implemented but were never called** (no network in the build sandbox). The offline extractive mode is the default and is fully tested. | Cannot test network calls here. | You configure a key and run one live check. |
| D14 | **UI pages were executed against a stand-in for Streamlit/Plotly**, not the real packages. | Not installed in the build sandbox. | First real run: look at every page once (see README). |
