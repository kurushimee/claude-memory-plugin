"""prints what recall would inject for sample prompts and tool inputs against the real vault, for re-tuning the cut offs in index.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mem import hooks, index  # noqa: E402
from sqlite_vec import serialize_float32  # noqa: E402

PROMPTS = [
    "the mod sure is quite ugly",
    "what time is it",
    "fix the typo in the readme",
    "write me a poem about cats",
    "godot keeps hanging when i run the tests",
    "which godot build do i use for this project",
    "how should research notes be written",
    "the gpu is busy with another job",
]
TOOL_INPUTS = [
    {"file_path": "F:/radiance-cascades/godot/project.godot"},
    {"file_path": "F:/radiance-cascades/research/notes.md"},
    {"file_path": "F:/claude-memory-plugin/mem/index.py"},
    {"command": "git status -sb && git log --oneline | head -3"},
    {"command": "cd /f/radiance-cascades && godot --headless --script res://tools/capture.gd"},
    {"command": "winget install Obsidian.Obsidian"},
    {"pattern": "cascade", "path": "F:/radiance-cascades"},
]

db = index.connect(vec=True)
index.index(db)


def scores(text, vector):
    out = {}
    q = index.fts_query(text)
    if q:
        for slug, rank in db.execute("select slug, bm25(fts) from fts where fts match ? order by bm25(fts) limit 5", (q,)):
            out.setdefault(slug, {})["fts"] = rank
    if vector:
        qv = index.embed([text])[0]
        for slug, dist in db.execute("select slug, distance from vec where embedding match ? and k = 5", (serialize_float32(qv),)):
            out.setdefault(slug, {})["vec"] = dist
    return out


def show(label, text, vector, k, fts_max):
    hits, maybe = index.search(db, text, k=k, vector=vector, fts_max=fts_max)
    raw = scores(text, vector)
    print(f"\n{label}  tokens={' '.join(index.tokens(text))}")
    for row in hits:
        s = raw.get(row["slug"], {})
        print(f"  inject  {row['slug']:44} vec={s.get('vec', 9):.3f} fts={s.get('fts', 0):7.2f}")
    for row in maybe:
        s = raw.get(row["slug"], {})
        print(f"  maybe   {row['slug']:44} vec={s.get('vec', 9):.3f} fts={s.get('fts', 0):7.2f}")


print(f"cut offs  vec<={index.VEC_MAX}  fts<={index.FTS_MAX} (tool)  fts<={index.FTS_MAX_PROMPT} (prompt)")
for p in PROMPTS:
    show(f"prompt  {p!r}", p, True, 3, index.FTS_MAX_PROMPT)
for ti in TOOL_INPUTS:
    show(f"tool    {ti!r}", hooks.keywords(ti), False, 1, index.FTS_MAX)
