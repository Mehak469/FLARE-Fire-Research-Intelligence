"""Validation of LLM answers against the evidence pack (spec section 6.6)."""
from __future__ import annotations
import re

NUM = re.compile(r"\d+(?:\.\d+)?")
PSI_ID = re.compile(r"\bPSI-\d+\b", re.I)
FORMULA = re.compile(r"\b(O2|CO2|CO|N2|H2O)\b", re.I)
FORBIDDEN = [re.compile(r"\b(un)?safe\b", re.I), re.compile(r"\bwill (ignite|burn|catch fire)\b", re.I),
             re.compile(r"\bprobability of (a )?fire\b", re.I), re.compile(r"\b(guarantee|certif(y|ied))\b", re.I)]
LABELS = {"direct_experimental", "published_interpretation", "configuration_only"}


def allowed_label_rank(item: dict) -> int:
    """How strong a claim this evidence can support: 2 direct experimental, 1 published interpretation, 0 configuration."""
    kind = item["kind"]
    if kind == "measurement":
        return 2
    if kind == "finding":
        return 2 if item.get("evidence_label") == "measured_observation" else 1
    if kind == "chunk" and item.get("is_paper"):
        return 1
    return 0


def label_rank(label: str) -> int:
    return {"direct_experimental": 2, "published_interpretation": 1, "configuration_only": 0}[label]


def evidence_label_for(item: dict) -> str:
    return {2: "direct_experimental", 1: "published_interpretation", 0: "configuration_only"}[allowed_label_rank(item)]


def validate_answer(ans: dict, pack: list[dict]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    by_id = {p["id"]: p for p in pack}
    if not isinstance(ans, dict) or not {"insufficient", "summary", "claims", "limitations"} <= set(ans):
        return False, ["missing required keys"]
    if ans["insufficient"]:
        if ans["claims"]:
            reasons.append("insufficient=true but claims are present")
        return (not reasons), reasons
    if not ans["claims"]:
        reasons.append("no claims given and insufficient=false")
    for i, c in enumerate(ans["claims"]):
        ids = c.get("evidence_ids") or []
        if not ids:
            reasons.append(f"claim {i}: no evidence ids"); continue
        unknown = [x for x in ids if x not in by_id]
        if unknown:
            reasons.append(f"claim {i}: unknown evidence ids {unknown}"); continue
        label = c.get("evidence_label")
        if label not in LABELS:
            reasons.append(f"claim {i}: bad evidence_label {label!r}"); continue
        if label_rank(label) > max(allowed_label_rank(by_id[x]) for x in ids):
            reasons.append(f"claim {i}: label {label} is stronger than the cited evidence supports")
        text = c.get("text", "")
        ev_text = " ".join((by_id[x]["text"] + " " + by_id[x].get("citation", "")) for x in ids)
        ev_body = " ".join(by_id[x]["text"] for x in ids)
        ev_cites = " ".join(by_id[x].get("citation", "") for x in ids)
        for pid in PSI_ID.findall(text):          # PSI ids may come from the citation, but must really be there
            if pid.lower() not in ev_cites.lower() and pid.lower() not in ev_body.lower():
                reasons.append(f"claim {i}: id {pid} not found in cited evidence")
        plain = FORMULA.sub(" ", PSI_ID.sub(" ", text))
        ev_nums = set(NUM.findall(ev_body))      # numbers must appear in the evidence text itself
        bad = [n for n in NUM.findall(plain) if n not in ev_nums]
        if bad:
            reasons.append(f"claim {i}: numbers {bad} not found in cited evidence")
        for pat in FORBIDDEN:
            m = pat.search(text)
            if m and not pat.search(ev_text):
                reasons.append(f"claim {i}: forbidden statement {m.group(0)!r}")
    return (not reasons), reasons
