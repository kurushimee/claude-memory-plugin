import difflib
import hashlib
import re
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from . import git, vault

DIM = 384
VEC_MAX = 0.36
FTS_MAX = -2.0
RRF_K = 60
STALE_DAYS = 90
OLD_LEFTOVER_DAYS = 30
DUPE_SIM = 0.92
NEAR_TITLE = 0.9
STOP = set(
    """the and for with from into this that these those there their they them then than when where which what who why
    how are was were been being have has had does did done will would could should can may might must not nor but yet
    also just like only same such some any all each every both few more most much very really quite sure well still
    here now one two new old get got put set let see say said make made need want use used using run ran try tried
    users kurus appdata local roaming temp tmp src lib bin dist build node_modules venv git cmd echo cat type dir head
    tail grep find python python3 npm npx bun node exe main index test tests com org http https www file files path
    json yaml toml txt lock log out output true false null none select update delete insert order limit sort uniq awk
    sed tee xargs mkdir touch chmod pwd""".split()
)

SCHEMA = """
create table if not exists notes(
  slug text primary key, path text, type text, project text, status text, title text,
  tags text, created text, updated text, hash text, mtime real,
  injected integer default 0, last_injected text);
create virtual table if not exists fts using fts5(slug unindexed, title, body, tags, links, tokenize='trigram');
create table if not exists injected(session_id text, agent_id text, slug text, source text, at text, compacted_at text);
"""
VEC_SCHEMA = f"create virtual table if not exists vec using vec0(slug text primary key, embedding float[{DIM}] distance_metric=cosine)"


def connect(vec=False):
    db = sqlite3.connect(vault.mem_dir() / "index.sqlite", timeout=10)
    db.execute("pragma journal_mode=wal")
    db.executescript(SCHEMA)
    if vec:
        import sqlite_vec

        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute(VEC_SCHEMA)
    db.row_factory = sqlite3.Row
    return db


MODEL = "Qdrant/bge-small-en-v1.5-onnx-Q"
MODEL_FILES = ["model_optimized.onnx", "tokenizer.json"]
_model = None


def model_dir():
    snapshots = vault.MODELS / f"models--{MODEL.replace('/', '--')}" / "snapshots"
    found = sorted(snapshots.glob("*/model_optimized.onnx"))
    if found:
        return found[-1].parent
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(MODEL, cache_dir=str(vault.MODELS), allow_patterns=MODEL_FILES))


def model():
    global _model
    if _model is None:
        import onnxruntime
        from tokenizers import Tokenizer

        folder = model_dir()
        tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        tok.enable_truncation(512)
        tok.enable_padding()
        opts = onnxruntime.SessionOptions()
        opts.log_severity_level = 3
        session = onnxruntime.InferenceSession(str(folder / "model_optimized.onnx"), opts, providers=["CPUExecutionProvider"])
        _model = tok, session
    return _model


def embed(texts):
    try:
        import numpy as np

        tok, session = model()
        enc = tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        cls = session.run(None, feed)[0][:, 0]
        return (cls / np.linalg.norm(cls, axis=1, keepdims=True)).tolist()
    except Exception as e:
        vault.log(f"embedder unavailable, text search only: {e!r}")
        return None


def index(db):
    rows = {r["slug"]: r for r in db.execute("select slug, hash, mtime from notes")}
    seen, changed = set(), []
    for path in vault.note_files():
        slug = path.stem
        seen.add(slug)
        mtime = path.stat().st_mtime
        row = rows.get(slug)
        if row and row["mtime"] == mtime:
            continue
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        if row and row["hash"] == digest:
            db.execute("update notes set mtime=? where slug=?", (mtime, slug))
            continue
        note = vault.read_note(path)
        upsert(db, note, digest, mtime)
        changed.append(note)
    gone = set(rows) - seen
    for slug in gone:
        remove(db, slug)
    db.commit()
    if changed or gone or not (vault.mem_dir() / "scopes").exists():
        write_scopes(db)
    if changed:
        embed_notes(db, changed)
    return changed, gone


def write_scopes(db):
    """the folders that have notes, read by mem-gate"""
    rows = db.execute("select distinct project from notes where status='active' and project!='global' order by project")
    (vault.mem_dir() / "scopes").write_text("".join(r[0] + "\n" for r in rows), encoding="utf-8", newline="\n")


def upsert(db, note, digest, mtime):
    db.execute(
        """insert into notes(slug, path, type, project, status, title, tags, created, updated, hash, mtime)
           values(?,?,?,?,?,?,?,?,?,?,?)
           on conflict(slug) do update set path=excluded.path, type=excluded.type, project=excluded.project,
             status=excluded.status, title=excluded.title, tags=excluded.tags, created=excluded.created,
             updated=excluded.updated, hash=excluded.hash, mtime=excluded.mtime""",
        (note.slug, note.path.as_posix(), note.type, note.project, note.status, note.title,
         " ".join(note.tags), note.created, note.updated, digest, mtime),
    )
    db.execute("delete from fts where slug=?", (note.slug,))
    db.execute(
        "insert into fts(slug, title, body, tags, links) values(?,?,?,?,?)",
        (note.slug, note.title, note.body, " ".join(note.tags), " ".join(note.links)),
    )


def remove(db, slug):
    db.execute("delete from notes where slug=?", (slug,))
    db.execute("delete from fts where slug=?", (slug,))
    db.execute("delete from injected where slug=?", (slug,))
    if vec_loaded(db):
        db.execute("delete from vec where slug=?", (slug,))


def vec_loaded(db):
    try:
        db.execute("select vec_version()")
        return True
    except sqlite3.OperationalError:
        return False


def embed_notes(db, notes):
    vecs = embed([n.text() for n in notes])
    if vecs is None or not vec_loaded(db):
        return
    from sqlite_vec import serialize_float32

    for note, vec in zip(notes, vecs):
        db.execute("delete from vec where slug=?", (note.slug,))
        db.execute("insert into vec(slug, embedding) values(?, ?)", (note.slug, serialize_float32(vec)))
    db.commit()


def tokens(text):
    found = []
    for t in re.findall(r"[a-z0-9_./-]+", text.lower()):
        if len(t) >= 3 and t not in STOP and t not in found:
            found.append(t)
    return [t for t in found if not any(t != u and t in u for u in found)][:12]


def fts_query(text):
    return " OR ".join('"' + t.replace('"', "") + '"' for t in tokens(text))


def search(db, query, project=None, type=None, k=8, vector=True):
    cands = defaultdict(dict)
    q = fts_query(query)
    if q:
        for slug, rank in db.execute(
            "select slug, bm25(fts) from fts where fts match ? order by bm25(fts) limit ?", (q, k * 3)
        ):
            cands[slug]["fts"] = rank
    if vector and vec_loaded(db):
        qv = embed([query])
        if qv:
            from sqlite_vec import serialize_float32

            for slug, dist in db.execute(
                "select slug, distance from vec where embedding match ? and k = ?", (serialize_float32(qv[0]), k * 3)
            ):
                cands[slug]["vec"] = dist
    score = defaultdict(float)
    for key in ("fts", "vec"):
        order = sorted((s for s in cands if key in cands[s]), key=lambda s: cands[s][key])
        for i, s in enumerate(order):
            score[s] += 1 / (RRF_K + i)
    hits, maybe = [], []
    for slug in sorted(score, key=lambda s: -score[s]):
        row = note_row(db, slug, project, type)
        if row is None:
            continue
        c = cands[slug]
        is_hit = c.get("vec", 9) <= VEC_MAX or c.get("fts", 0) <= FTS_MAX
        (hits if is_hit and len(hits) < k else maybe).append(row)
    linked = linked_rows(db, hits[:3], {r["slug"] for r in hits + maybe}, project)
    return hits, (linked + maybe)[:5]


def by_meaning(db, rows, text):
    """rows closest in meaning to the text first, rows without a vector last"""
    total = db.execute("select count(*) from vec").fetchone()[0] if vec_loaded(db) else 0
    qv = embed([text]) if total else None
    if not qv:
        return rows
    from sqlite_vec import serialize_float32

    near = dict(db.execute("select slug, distance from vec where embedding match ? and k = ?", (serialize_float32(qv[0]), total)))
    return sorted(rows, key=lambda r: near.get(r["slug"], float("inf")))


def note_row(db, slug, project=None, type=None):
    row = db.execute("select * from notes where slug=? and status='active'", (slug,)).fetchone()
    if row is None:
        return None
    if project and not vault.in_scope(row["project"], project):
        return None
    if type and row["type"] != type:
        return None
    return row


def linked_rows(db, rows, skip, project):
    out = []
    for row in rows:
        links = db.execute("select links from fts where slug=?", (row["slug"],)).fetchone()
        for slug in (links[0].split() if links and links[0] else []):
            if slug not in skip:
                linked = note_row(db, slug, project)
                if linked is not None:
                    skip.add(slug)
                    out.append(linked)
    return out


def list_notes(db, project=None, types=None, k=20, status="active"):
    sql = "select * from notes where status=?"
    args = [status]
    if types:
        sql += " and type in (" + ",".join("?" * len(types)) + ")"
        args += list(types)
    rows = db.execute(sql + " order by updated desc, created desc", args).fetchall()
    return [r for r in rows if not project or vault.in_scope(r["project"], project)][:k]


def body_of(db, slug):
    row = db.execute("select body from fts where slug=?", (slug,)).fetchone()
    return row[0] if row else ""


def named(db, name):
    """the note a slug or a title names. a title copied out of the index with a small slip still finds its note"""
    name = " ".join(name.split())
    # a sync conflict's copy shares its note's title under a longer slug
    row = db.execute(
        "select * from notes where slug=? or lower(title)=lower(?) order by slug=? desc, length(slug)", (name, name, name)
    ).fetchone()
    if row:
        return row
    titles = {r["title"].lower(): r for r in db.execute("select * from notes order by length(slug) desc")}
    near = difflib.get_close_matches(name.lower(), titles, n=1, cutoff=NEAR_TITLE)
    return titles[near[0]] if near else None


def injected_slugs(db, session, agent):
    """notes whose body this session already got by itself"""
    rows = db.execute(
        "select slug from injected where session_id=? and coalesce(agent_id,'')=? and compacted_at is null",
        (session, agent or ""),
    )
    return {r[0] for r in rows}


def injected_rows(db, session):
    return db.execute(
        """select i.slug, i.source, max(i.at) as at, n.title, n.path from injected i join notes n using(slug)
           where i.session_id=? group by i.slug order by at desc""",
        (session,),
    ).fetchall()


def record_injected(db, session, agent, slugs, source):
    now = datetime.now().isoformat(timespec="seconds")
    for slug in slugs:
        db.execute(
            "insert into injected(session_id, agent_id, slug, source, at) values(?,?,?,?,?)",
            (session, agent or None, slug, source, now),
        )
        db.execute("update notes set injected=injected+1, last_injected=? where slug=?", (now, slug))
    db.commit()


def reached_file(session, agent):
    """the folders a session already reached and the notes its calls' subjects already brought, a plain file so
    mem-gate can read it"""
    return vault.mem_dir() / "reached" / f"{session}+{agent or ''}"


def reached(session, agent):
    path = reached_file(session, agent)
    return set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()


def record_reached(session, agent, names):
    path = reached_file(session, agent)
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.writelines(n + "\n" for n in names)


def prune_reached():
    """drops the reached and turn files of sessions idle for a week"""
    cutoff = time.time() - 7 * 86400
    for path in [*(vault.mem_dir() / "reached").glob("*"), *(vault.mem_dir() / "turns").glob("*")]:
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def stamp_compacted(db, session, agent):
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "update injected set compacted_at=? where session_id=? and coalesce(agent_id,'')=? and compacted_at is null",
        (now, session, agent or ""),
    )
    db.commit()
    reached_file(session, agent).unlink(missing_ok=True)


def before_compaction(db, session, agent):
    return db.execute(
        """select distinct i.slug, n.title from injected i join notes n using(slug)
           where i.session_id=? and coalesce(i.agent_id,'')=? and n.status='active'
           order by i.at desc""",
        (session, agent or ""),
    ).fetchall()


def days_ago(iso):
    try:
        return (date.today() - date.fromisoformat(str(iso)[:10])).days
    except ValueError:
        return 0


def dupe_pairs(db):
    if not vec_loaded(db):
        return []
    import numpy as np

    rows = db.execute("select v.slug, v.embedding from vec v join notes n using(slug) where n.status='active'").fetchall()
    if len(rows) < 2:
        return []
    slugs = [r[0] for r in rows]
    m = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    sim = m @ m.T
    pairs = []
    for i in range(len(slugs)):
        for j in range(i + 1, len(slugs)):
            if sim[i, j] >= DUPE_SIM:
                pairs.append((slugs[i], slugs[j], round(float(sim[i, j]), 3)))
    return pairs


STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2})\b)?")


def stamp(text):
    """the date and time a log line or a pass heading starts with, midnight when it has no time"""
    m = STAMP.match(text)
    return f"{m[1]} {m[2] or '00:00'}" if m else None


def passes():
    log = vault.vault_path() / "system" / "log.md"
    if not log.exists():
        return []
    return re.findall(r"^## (\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)", log.read_text(encoding="utf-8"), re.M)


def last_pass():
    done = passes()
    return days_ago(done[-1][:10]) if done else None


def errors_since_pass():
    """the errors logged since the last pass, since the pass read the ones before it"""
    log = vault.mem_dir() / "mem.log"
    if not log.exists():
        return 0
    done = passes()
    since = stamp(done[-1]) if done else ""
    return sum(1 for line in log.read_text(encoding="utf-8").splitlines() if (at := stamp(line)) and at >= since)


def lessons_week(db):
    """the incidents logged in the last week, how many the user had to point out, how many hit a rule that already
    had one, and how many of those the user had to point out, the numbers that should fall to zero"""
    week = []
    for r in db.execute("select slug from notes where type='rules' and status='active'"):
        found = vault.incidents(body_of(db, r[0]))
        week += [(who, i > 0) for i, (day, who, _) in enumerate(found) if days_ago(day) <= 7]
    return {
        "lessons_week": len(week),
        "lessons_by_user": sum(1 for who, _ in week if who == "user"),
        "lessons_repeats": sum(1 for _, repeat in week if repeat),
        "lessons_missed": sum(1 for who, repeat in week if who == "user" and repeat),
    }


def dead_links(db):
    """links to notes that don't exist, as (slug, link)"""
    slugs = {r[0] for r in db.execute("select slug from notes")}
    return [(s, link) for s in sorted(slugs) for link in vault.links(body_of(db, s)) if link not in slugs]


def long_bodies(db):
    """notes too long for a hook to carry next to others"""
    rows = db.execute("select slug from notes where type!='rules' and status='active'")
    return [r[0] for r in rows if len(body_of(db, r[0])) > vault.BODY_MAX]


def health(db, project):
    leftovers = list_notes(db, project, ("leftovers",), k=100)
    old = [r for r in leftovers if days_ago(r["created"]) > OLD_LEFTOVER_DAYS]
    stale = [
        r for r in db.execute("select * from notes where status='active' and type!='leftovers' and injected=0")
        if days_ago(r["updated"]) > STALE_DAYS
    ]
    conflicts = [p.as_posix() for p in vault.vault_path().glob("*/*-conflict.md")]
    lessons = lessons_week(db)
    dupes = dupe_pairs(db)
    dead = dead_links(db)
    long = long_bodies(db)
    days = last_pass()
    errors = errors_since_pass()
    unpushed = git.unpushed()
    problems = [
        (len(old), f"leftovers older than {OLD_LEFTOVER_DAYS}d"), (len(dupes), "dupe pairs"),
        (len(stale), "stale candidates"), (len(conflicts), "conflicts"), (errors, "hook errors"),
        (unpushed, "unpushed commits"), (len(dead), "dead links"), (len(long), f"bodies over {vault.BODY_MAX} characters"),
    ]
    line = ", ".join([
        f"{len(leftovers)} open leftovers",
        *(f"{n} {what}" for n, what in problems if n),
        f"{lessons['lessons_week']} lessons this week ({lessons['lessons_by_user']} spotted by the user, "
        f"{lessons['lessons_repeats']} repeats of a rule)",
        "last cleanup " + (f"{days}d ago" if days is not None else "never"),
    ])
    return {
        "line": line, "open": len(leftovers), "open_old": len(old), "dupes": len(dupes), "stale": len(stale),
        "conflicts": len(conflicts), "errors": errors, "unpushed": unpushed, "dead": len(dead), "long": len(long),
        "days_since_pass": days, **lessons, "dupe_pairs": dupes, "stale_slugs": [r["slug"] for r in stale],
        "old_leftovers": [r["slug"] for r in old], "conflict_files": conflicts, "dead_links": dead, "long_bodies": long,
    }
