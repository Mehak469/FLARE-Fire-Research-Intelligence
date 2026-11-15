"""Grounded-answer evaluation (spec 9.2). Cases live in tests/ask_eval.yaml; results are written to docs/eval_report.md."""
from __future__ import annotations
import yaml
from .. import config
from . import ask as askmod


def run_eval(conn, cases_path=None, client=None, write_report: bool = True) -> dict:
    with open(cases_path or config.ROOT / "tests" / "ask_eval.yaml", encoding="utf-8") as fh:
        cases = yaml.safe_load(fh)["cases"]
    results, failed = [], 0
    for c in cases:
        res = askmod.ask(conn, c["question"], client=client, use_llm=client is not None)
        problems = []
        if "mode" in c and res["mode"] != c["mode"]:
            problems.append(f"mode {res['mode']!r}, expected {c['mode']!r}")
        if c.get("insufficient") is not None and res["insufficient"] != c["insufficient"]:
            problems.append(f"insufficient={res['insufficient']}, expected {c['insufficient']}")
        blob = " ".join([res["summary"]] + [x["text"] for x in res["claims"]])
        for needle in c.get("must_contain", []):
            if needle.lower() not in blob.lower():
                problems.append(f"missing text {needle!r}")
        for needle in c.get("must_not_contain", []):
            if needle.lower() in blob.lower():
                problems.append(f"forbidden text {needle!r}")
        ids = {e["id"] for e in res["evidence"]}
        for cl in res["claims"]:
            if not cl["evidence_ids"] or any(i not in ids for i in cl["evidence_ids"]):
                problems.append("uncited claim or unknown evidence id")
                break
        results.append({"id": c["id"], "category": c["category"], "question": c["question"], "mode": res["mode"], "ok": not problems, "problems": problems})
        failed += 1 if problems else 0
    summary = f"{len(results) - failed}/{len(results)} evaluation cases passed"
    if write_report:
        lines = ["# Ask evaluation report", "", summary, "", "| id | category | mode | result | problems |", "|---|---|---|---|---|"]
        lines += [f"| {r['id']} | {r['category']} | {r['mode']} | {'PASS' if r['ok'] else 'FAIL'} | {'; '.join(r['problems'])} |" for r in results]
        (config.ROOT / "docs" / "eval_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"results": results, "failed": failed, "summary": summary}
