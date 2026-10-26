"""Scores the labeled prompt cases in the vault's system/recall-eval.jsonl with the real judge and shows where they
fall against the gates in mem/judge.py. No unrelated note may reach the body gate."""

import json
import time

from mem import hooks, index, judge, transcript, vault

db = index.connect()
notes = [r for r in index.list_notes(db, None, None, 1000) if r["type"] != "rules"]
lines = (vault.vault_path() / "system" / "recall-eval.jsonl").read_text(encoding="utf-8").splitlines()
cases = [c for c in map(json.loads, lines) if c["kind"] == "prompt"]
batches = [[r for r in notes if vault.in_scope(r["project"], c["project"]) and not hooks.belongs(r, c["project"])] for c in cases]
pairs = sum(map(len, batches))
rows = []

# the judges of live prompts wait for this run instead of loading a second model next to it, and the judge scores
# at least 2 notes a second
with judge.gpu_turn(time.monotonic() + 600), judge.ranker(seconds=30 + pairs / 2) as rank:
    for i, (case, batch) in enumerate(zip(cases, batches), 1):
        reply = case.get("context", "").strip()
        reply = "" if reply == transcript.NO_REPLY else reply[-transcript.REPLY_CHARS:]
        scores = rank(hooks.query_of(case["text"], reply), [hooks.doc_of(db, r) for r in batch])
        for score, r in zip(scores, batch):
            label = "needed" if r["slug"] in case["needed"] else "related" if r["slug"] in case["related"] else "unrelated"
            rows.append((score, label, case["id"], r["slug"]))
        if i % 20 == 0:
            print(f"{i}/{len(cases)} cases", flush=True)

for label in ("needed", "related", "unrelated"):
    got = sorted((r for r in rows if r[1] == label), reverse=True)
    bodies = sum(s >= judge.BODY_GATE for s, *_ in got)
    titles = sum(judge.TITLE_GATE <= s < judge.BODY_GATE for s, *_ in got)
    print(f"{label} {len(got)}, {bodies} as bodies, {titles} as titles")
    for score, _, case_id, slug in got[:8]:
        print(f"  {score:.3f} {case_id} {slug}")
