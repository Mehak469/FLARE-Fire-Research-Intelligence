"""PDF -> pages -> chunks. Chunks never cross pages, so page citations stay exact. No OCR (scanned pages are flagged)."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from ..core import db as dbm


def _clean(t: str) -> str:
    t = re.sub(r"-\n(?=[a-z])", "", t)          # rejoin words hyphenated at line ends
    return re.sub(r"\s+", " ", t).strip()


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            sp = text.rfind(" ", i + size // 2, j)
            j = sp if sp > i else j
        out.append(text[i:j].strip())
        if j >= len(text):
            break
        i = max(j - overlap, i + 1)
    return [c for c in out if c]


def ingest_pdf(conn, path: Path, source_key: str, title: str | None = None, url: str | None = None, doi: str | None = None,
               investigation: str | None = None, source_type: str = "journal_paper", authors: str | None = None,
               pub_year: int | None = None, retrieved_on: str = "2026-11-14") -> dict:
    from pypdf import PdfReader
    path = Path(path)
    reader = PdfReader(str(path))
    report = {"pages": len(reader.pages), "pages_without_text": [], "chunks": 0}
    conn.execute("""INSERT INTO sources(source_key,source_type,title,url,doi,authors,pub_year,local_file,sha256,retrieved_on)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_key) DO UPDATE SET title=excluded.title, url=excluded.url, doi=excluded.doi, sha256=excluded.sha256,
                      local_file=excluded.local_file, retrieved_on=excluded.retrieved_on""",
                 (source_key, source_type, title or path.stem, url, doi, authors, pub_year, str(path),
                  hashlib.sha256(path.read_bytes()).hexdigest(), retrieved_on))
    sid = dbm.scalar(conn, "SELECT source_id FROM sources WHERE source_key=?", (source_key,))
    inv_id = None
    if investigation:
        inv_id = dbm.scalar(conn, "SELECT investigation_id FROM investigations WHERE name=?", (investigation,))
        if inv_id is None:
            raise ValueError(f"investigation {investigation!r} not found")
        conn.execute("INSERT OR IGNORE INTO investigation_sources(investigation_id,source_id) VALUES (?,?)", (inv_id, sid))
    conn.execute("DELETE FROM doc_chunks WHERE source_id=?", (sid,))
    conn.execute("DELETE FROM doc_pages WHERE source_id=?", (sid,))
    idx = 0
    for pno, page in enumerate(reader.pages, start=1):
        text = _clean(page.extract_text() or "")
        if len(text) < 20:
            report["pages_without_text"].append(pno)
            dbm.add_flag(conn, "sources", sid, "page_without_text", f"page {pno} has no extractable text (scanned? OCR is not done)", "warn")
            continue
        conn.execute("INSERT INTO doc_pages(source_id,page,text) VALUES (?,?,?)", (sid, pno, text))
        for ch in chunk_text(text):
            conn.execute("INSERT INTO doc_chunks(source_id,investigation_id,section,page,chunk_index,text) VALUES (?,?,?,?,?,?)",
                         (sid, inv_id, None, pno, idx, ch))
            idx += 1; report["chunks"] += 1
    conn.commit()
    return report
