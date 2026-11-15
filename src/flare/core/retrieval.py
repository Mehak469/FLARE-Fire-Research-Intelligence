"""Retrieval over investigation text, paper chunks and curated findings (FTS5 + token-overlap gate).

User text is NEVER passed to MATCH raw: it is lowercased, reduced to [a-z0-9] tokens, stopwords removed,
and rebuilt as an OR of prefix terms (so FTS operators in a question have no effect).
"""
from __future__ import annotations
import re
from . import db as dbm

STOPWORDS = set("""a an and are as at be by can did do does for from has have how i in is it its of on or that the their there these this to was were
what when where which who whom why will with would about into than then also any all some such tell show me us we you your our""".split())
MIN_OVERLAP = 0.34   # share of query terms a passage must contain to count as relevant


def stem(tok: str) -> str:
    return tok[:7] if len(tok) > 7 else tok


def tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = []
    for t in toks:
        if t in STOPWORDS or (len(t) < 3 and not t.isdigit() and t not in ("o2", "ii", "co")):
            continue
        out.append(stem(t))
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t); uniq.append(t)
    return uniq


def fts_query(toks: list[str]) -> str:
    return " OR ".join(f"{t}*" for t in toks)


def _overlap(toks: list[str], passage: str) -> float:
    if not toks:
        return 0.0
    ptoks = {stem(t) for t in re.findall(r"[a-z0-9]+", passage.lower())}
    hit = sum(1 for t in toks if any(p.startswith(t) for p in ptoks))
    return hit / len(toks)


def search_chunks(conn, question: str, k: int = 8, investigation_ids: list[int] | None = None) -> list[dict]:
    toks = tokens(question)
    if not toks:
        return []
    sql = ("SELECT c.chunk_id, c.text, c.section, c.page, c.source_id, c.investigation_id, i.name AS investigation, "
           "s.title AS source_title, s.url AS source_url, s.doi AS source_doi, bm25(doc_chunks_fts) AS bm "
           "FROM doc_chunks_fts f JOIN doc_chunks c ON c.chunk_id=f.rowid JOIN sources s ON s.source_id=c.source_id "
           "LEFT JOIN investigations i ON i.investigation_id=c.investigation_id WHERE doc_chunks_fts MATCH ?")
    params: list = [fts_query(toks)]
    if investigation_ids:
        sql += " AND c.investigation_id IN (%s)" % ",".join("?" * len(investigation_ids))
        params += list(investigation_ids)
    sql += " ORDER BY bm LIMIT 60"
    rows = dbm.q(conn, sql, params)
    items = []
    for r in rows:
        ov = _overlap(toks, r["text"])
        if ov < MIN_OVERLAP:
            continue
        cite = r["source_title"] or "source"
        if r["source_url"]:
            cite += f" ({r['source_url']})"
        if r["page"] and r["section"] is None:
            cite += f", page {r['page']}"
        items.append({"id": f"C{r['chunk_id']}", "kind": "chunk", "investigation": r["investigation"], "section": r["section"],
                      "text": r["text"], "citation": cite, "source_id": r["source_id"], "page": r["page"], "score": round(ov, 3), "bm25": r["bm"],
                      "is_paper": r["section"] is None})
    items.sort(key=lambda x: (-x["score"], x["bm25"]))
    return items[:k]


def search_findings(conn, question: str, k: int = 5) -> list[dict]:
    toks = tokens(question)
    if not toks:
        return []
    rows = dbm.q(conn, "SELECT f.finding_id, f.statement, f.evidence_label, f.topic, f.page, f.qa_status, f.source_ref, f.quote, s.title AS source_title, "
                       "s.url AS source_url, i.name AS investigation, bm25(findings_fts) AS bm "
                       "FROM findings_fts x JOIN findings f ON f.finding_id=x.rowid JOIN sources s ON s.source_id=f.source_id "
                       "LEFT JOIN investigations i ON i.investigation_id=f.investigation_id "
                       "WHERE findings_fts MATCH ? AND f.qa_status <> 'rejected' ORDER BY bm LIMIT 30", (fts_query(toks),))
    items = []
    for r in rows:
        ov = _overlap(toks, r["statement"] + " " + (r["topic"] or ""))
        if ov < MIN_OVERLAP:
            continue
        cite = f"{r['source_title']}, {r['source_ref']}" + (f" ({r['source_url']})" if r["source_url"] else "")
        items.append({"id": f"F{r['finding_id']}", "kind": "finding", "investigation": r["investigation"], "text": r["statement"],
                      "evidence_label": r["evidence_label"], "citation": cite, "page": r["page"], "quote": r["quote"],
                      "qa_status": r["qa_status"], "score": round(ov, 3), "bm25": r["bm"]})
    items.sort(key=lambda x: (-x["score"], x["bm25"]))
    return items[:k]


def mentioned_investigations(conn, question: str) -> list[dict]:
    """Investigations whose code or PSI id appears in the question (word-bounded, case-insensitive)."""
    found = []
    q = question.lower()
    for inv in dbm.q(conn, "SELECT investigation_id, name, psi_id FROM investigations ORDER BY LENGTH(name) DESC"):
        pat = r"(?<![a-z0-9])" + re.escape(inv["name"].lower()) + r"(?![a-z0-9-])"
        pat2 = r"(?<![a-z0-9])" + re.escape((inv["psi_id"] or "~~").lower()) + r"(?![a-z0-9])"
        if re.search(pat, q) or re.search(pat2, q):
            found.append(inv)   # the lookahead above already stops 'BASS' matching inside 'BASS-II'
    return found
