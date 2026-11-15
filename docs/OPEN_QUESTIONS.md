# Open questions (answer these; nothing here was guessed)

1. **Moon/Mars cabin atmosphere**: oxygen percent and total pressure from an official NASA source. Enter them in `config/reference_conditions.yaml` (currently null / TODO_CONFIRM). Until then the presets filter by gravity only.
2. **Full BASS-II table**: only 10 rows are loaded. Download the experimental table CSV from PSI-25 and run `python -m flare.cli ingest-table config/mappings/bass2.yaml <file>`. Note: the PSI page showed 130 rows; other teams report 129 in the CSV. Check the difference.
3. **BASS-II columns to the right** of "Final CO (ppm)": any spread rate, pressure or airflow velocity columns? Add them to `config/mappings/bass2.yaml`.
4. **Airflow velocity**: fan display / air display / flow restrictor are instrument settings. Is there a calibration to cm/s in the Read Me or papers? If so, add a documented conversion; otherwise airflow stays NULL.
5. **Material for tests B3, B5, B7**: their fuel text omits "PMMA". It is assumed from the series and flagged. Confirm in the Read Me.
6. **Meaning of the "m" suffix** on some sample numbers (153m, 157m...). Kept as text.
7. **Where are BASS-II outcomes (spread rates)?** Other teams point to a 2018 paper (Link et al., Sci. Rep. 8:120). Unverified by us. Obtain papers, ingest them, and write curated findings.
8. **SAFFIRE I/II/III**: obtain tables and papers; ingest with `ingest-pdf`; curate findings with page and exact quote.
9. **Credit and licensing of `investigations.json/csv`**: it came from another team's compilation of PSI records. Check the source repository's license and the competition rules, credit it in your README, or re-derive the fields yourself from the PSI pages (each record links to its PSI page and DOI).
10. **Judging criteria and submission format**: confirm in the official Space Apps guides.
11. **Duplicate PSI id**: two investigations share PSI-47 in the supplied file. Check whether that is correct.
