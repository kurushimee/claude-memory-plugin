"""Scores the labeled prompt cases in the vault's system/recall-eval.jsonl with the real judge and shows where they
fall against the gates in mem/judge.py. No unrelated note may reach the body gate."""

import json

from mem import hooks, index, judge, vault

db = index.connect()
notes = index.list_notes(db, None, None, 1000)
lines = (vault.vault_path() / "system" / "recall-eval.jsonl").read_text(encoding="utf-8").splitlines()
cases = [c for c in map(json.loads, lines) if c["kind"] == "prompt"]
rows = []

with judge.ranker(seconds=30 + 5 * len(cases)) as rank:
    for i, case in enumerate(cases, 1):
        reply = case.get("context", "").strip()
        reply = "" if reply == hooks.NO_REPLY else reply[-hooks.REPLY_CHARS:]
        batch = [r for r in notes if vault.in_scope(r["project"], case["project"]) and not hooks.belongs(r, case["project"])]
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
