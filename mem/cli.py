import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import git, index, transcript, vault

HOOKS = ("brief", "recall", "journal")
SAVED = tuple(t for t in vault.TYPES if t != "rules")
FILE = re.compile(r"[\w./-]*\w\.[A-Za-z]\w{0,7}\b")
TRANSCRIPTS = Path.home() / ".claude" / "projects"
SESSIONS = 10  # a week of transcripts runs past a gigabyte
HANDBACK = ("wrap_up", "AskUserQuestion", "ExitPlanMode")
ASIDE = ("update_plan", "mark_chapter", "ToolSearch")  # calls around the work that do none of it


def main():
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:] and sys.argv[1] in HOOKS:
        return run_hook(sys.argv[1])
    args = parse(sys.argv[1:])
    try:
        run(args)
    except vault.Refused as e:
        raise SystemExit(str(e))
    except Exception as e:
        try:
            vault.log(f"{args.cmd} failed: {traceback.format_exc()}")
        except Exception:
            pass
        raise SystemExit(f"mem {args.cmd} failed: {e!r}")


def parse(argv):
    import argparse

    p = argparse.ArgumentParser(prog="mem", description="memory for claude on an obsidian vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="record where the vault is").add_argument("vault")
    sub.add_parser("index", help="incremental reindex")
    s = sub.add_parser("search", help="hybrid search, no query lists by recency")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--project")
    s.add_argument("--type", choices=vault.TYPES)
    s.add_argument("-k", type=int, default=8)
    s.add_argument("--json", action="store_true")
    sub.add_parser("show", help="print notes by slug or title").add_argument("names", nargs="+")
    s = sub.add_parser("save", help="write a note, body from stdin or --body")
    s.add_argument("--type", required=True, choices=SAVED)
    s.add_argument("--title", required=True)
    s.add_argument("--tags", nargs="*", default=[])
    s.add_argument("--links", nargs="*", default=[])
    s.add_argument("--project", default="global", help="a git root for that project's code, design, findings, tools and run recipes")
    s.add_argument("--body")
    s = sub.add_parser("lesson", help="log a mistake, first alone to see the closest rules, then with --rule or --new")
    s.add_argument("what", help="what went wrong, in one line")
    s.add_argument("--by", required=True, choices=("self", "user"), help="who spotted it")
    s.add_argument("--rule", help="slug of the rule this is another incident of")
    s.add_argument("--new", metavar="TITLE", help="a new rule, the general behavior, with --why and --check")
    s.add_argument("--sharpen", metavar="TITLE", help="a sharper title for the --rule")
    s.add_argument("--why")
    s.add_argument("--check", help="what to run or look at that catches it, added to an existing rule's check")
    s.add_argument("--scope", default="global", help="the project a new rule holds in, global by default")
    sub.add_parser("done", help="mark a leftover done").add_argument("slug")
    sub.add_parser("forget", help="delete a note").add_argument("slug")
    sub.add_parser("sync", help="pull then push the vault")
    for name in HOOKS:
        sub.add_parser(name, help="hook, reads the hook json on stdin")
    sub.add_parser("check", help="health report").add_argument("--json", action="store_true")
    sub.add_parser("log", help="recent errors").add_argument("-n", type=int, default=30)
    s = sub.add_parser("pane", help="json for the pane mod")
    s.add_argument("--session", required=True)
    s.add_argument("--cwd", default="")
    s.add_argument("--json", action="store_true")
    sub.add_parser("mcp", help="serve the memory tools over stdio")
    return p.parse_args(argv)


def run_hook(name):
    try:
        from . import hooks

        payload = json.loads(sys.stdin.read() or "{}")
        # run by hand, like in a cloud session, there is no hook payload to name the folder
        payload.setdefault("cwd", os.getcwd())
        result = getattr(hooks, name)(payload)
        if result:
            print(json.dumps(result))
    except BaseException:
        try:
            vault.log(f"hook {name} failed: {traceback.format_exc()}")
        except Exception:
            pass


def run(args):
    match args.cmd:
        case "init":
            vault.set_vault(args.vault)
            for t in vault.TYPES:
                (vault.vault_path() / t).mkdir(parents=True, exist_ok=True)
            print(f"vault set to {vault.vault_path()}")
        case "index":
            changed, gone = index.index(index.connect(vec=True))
            print(f"indexed {len(changed)} changed, {len(gone)} removed")
        case "search":
            db = index.connect(vec=True)
            index.index(db)
            if args.query:
                hits, maybe = index.search(db, args.query, args.project, args.type, args.k)
            else:
                hits, maybe = index.list_notes(db, args.project, (args.type,) if args.type else None, args.k), []
            print(json.dumps(search_json(db, hits, maybe)) if args.json else render_search(db, hits, maybe))
        case "show":
            print(show(args.names))
        case "save":
            body = args.body if args.body is not None else sys.stdin.read()
            print(saved(save_note(args.type, args.title, body, args.tags, args.links, args.project)))
        case "lesson":
            from . import rules

            place = vault.project_of(os.getcwd())
            print(rules.lesson(args.what, args.by, place, args.rule, args.new, args.sharpen, args.why, args.check, args.scope))
        case "done":
            set_done(args.slug)
            print(f"done {args.slug}")
        case "forget":
            forget_note(args.slug)
            print(f"forgot {args.slug}")
        case "sync":
            git.sync()
            print("synced")
        case "check":
            report = check_report()
            print(json.dumps(report, indent=1) if args.json else render_check(report))
        case "log":
            log = vault.mem_dir() / "mem.log"
            lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
            print("\n".join(lines[-args.n :]) or "no errors logged")
        case "pane":
            print(json.dumps(pane(args.session, args.cwd)))
        case "mcp":
            from .mcp_server import serve

            serve()


def show(names):
    """the full notes the slugs or titles name, each under its slug and path"""
    db = index.connect()
    index.index(db)
    out = []
    for name in names:
        row = index.named(db, name)
        if not row:
            raise vault.Refused(f"no note named {name}, memory_search finds notes by meaning")
        out.append(f"# {row['slug']} at {row['path']}\n{Path(row['path']).read_text(encoding='utf-8')}")
    return "\n\n".join(out)


def save_note(type, title, body, tags, links, project):
    if type not in SAVED:
        raise vault.Refused(f"type must be one of {', '.join(SAVED)}, rules change through mem lesson")
    slug = vault.slugify(title)
    if links:
        body = body.rstrip() + "\n\nrelated " + " ".join(f"[[{l}]]" for l in links)
    if missing := [l for l in vault.links(body) if l not in vault.slugs()]:
        raise vault.Refused(f"no note {', '.join(missing)}, link only to notes that exist")
    if len(body) > vault.BODY_MAX:
        raise vault.Refused(
            f"the body has {len(body)} characters, a note stays under {vault.BODY_MAX} so a hook can carry it next to "
            "others. keep only what a later task needs, or split it by subject"
        )
    note = vault.Note(slug=slug, type=type, title=title, body=body, project=project, tags=list(tags))
    # a save under another type moves the note, since the index holds one note per slug
    old = [p for t in vault.TYPES if (p := vault.vault_path() / t / f"{slug}.md").exists()]
    if old:
        note.created = vault.read_note(old[0]).created
    for path in old:
        path.unlink()
    vault.write_note(note)
    index.index(index.connect(vec=True))
    git.commit([note.path, *old], f"save {slug}")
    return note


def saved(note):
    return f"saved {note.slug} at {note.path.as_posix()}"


def set_done(slug):
    note = vault.find(slug)
    note.status = "done"
    note.updated = vault.today()
    vault.write_note(note)
    index.index(index.connect(vec=True))
    git.commit([note.path], f"done {slug}")


def forget_note(slug):
    note = vault.find(slug)
    note.path.unlink()
    index.index(index.connect(vec=True))
    git.commit([note.path], f"forget {slug}")


def row_json(db, row, body=False):
    out = {"slug": row["slug"], "title": row["title"], "path": row["path"], "type": row["type"], "project": row["project"]}
    if body:
        out["body"] = index.body_of(db, row["slug"])
    return out


def search_json(db, hits, maybe):
    return {"hits": [row_json(db, r, body=True) for r in hits], "maybe": [row_json(db, r) for r in maybe]}


def render_search(db, hits, maybe):
    from .hooks import block, line

    out = [block(db, r) for r in hits] or ["no hits"]
    if maybe:
        out.append("maybe relevant, open with memory_show")
        out += [line(r) for r in maybe]
    return "\n\n".join(out)


def check_report():
    db = index.connect(vec=True)
    changed, gone = index.index(db)
    health = index.health(db, None)
    files = sum(1 for _ in vault.note_files())
    rows = db.execute("select count(*) from notes").fetchone()[0]
    embedded = db.execute("select count(*) from vec").fetchone()[0]
    log = vault.mem_dir() / "mem.log"
    return {
        "vault": vault.vault_path().as_posix(),
        "remote": git.git("remote", "get-url", "origin").stdout.strip() if git.has_remote() else "",
        "notes": files,
        "indexed": rows,
        "embedded": embedded,
        "embedder": index.embed(["check"]) is not None,
        "reindexed": len(changed),
        "removed": len(gone),
        "health": health,
        "sessions": [session_report(db, p) for p in latest_sessions()],
        "behind": behind_code(),
        "dead_labels": dead_labels(),
        "log_tail": log.read_text(encoding="utf-8").splitlines()[-10:] if log.exists() else [],
    }


def latest_sessions():
    return sorted(TRANSCRIPTS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:SESSIONS]


def session_report(db, path):
    """how many turns opened memory before their first work call, and how many hand backs, a wrap_up, a question
    or a plan, had a rule opened after the last work call before them"""
    is_rule = {}

    def opens_rule(call):
        for name in transcript.shown(*call):
            if name not in is_rule:
                row = index.named(db, name)
                is_rule[name] = bool(row) and row["type"] == "rules"
            if is_rule[name]:
                return True
        return False

    def aside(call):
        return call[0].endswith(HANDBACK + ASIDE) or transcript.reads_memory(*call)

    worked = started = backs = checked = 0
    for calls in transcript.turns(path):
        work = [i for i, call in enumerate(calls) if not aside(call)]
        if not work:
            continue
        worked += 1
        started += any(transcript.reads_memory(*call) for call in calls[: work[0]])
        last = -1
        for i, call in enumerate(calls):
            if call[0].endswith(HANDBACK):
                backs += 1
                checked += any(map(opens_rule, calls[last + 1 : i]))
            elif not aside(call):
                last = i
    return {"session": path.stem, "folder": path.parent.name, "turns": worked, "started": started, "handbacks": backs, "checked": checked}


def behind_code():
    """notes naming a file of their project that a commit changed after the note last changed, so what the note says
    about it may no longer hold"""
    db = index.connect()
    root = vault.vault_path()
    noted = git.last_changes(root, None, *SAVED)
    edited = set(git.edited())
    projects = {}
    for r in db.execute("select slug, path, project from notes where status='active' and type!='rules' and project!='global'"):
        path = Path(r["path"])
        when = mtime(path) if path in edited else noted.get(path.relative_to(root).as_posix())
        if when:
            projects.setdefault(r["project"], []).append((r["slug"], when))
    out = []
    for project, notes in projects.items():
        changed = git.last_changes(project, min(when for _, when in notes))
        for slug, when in notes:
            names = set(FILE.findall(index.body_of(db, slug)))
            files = [f for f, at in changed.items() if at > when and any(names_file(n, f) for n in names)]
            if files:
                out.append({"slug": slug, "files": sorted(files)})
    return out


def mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def names_file(name, path):
    """a name in a note, bare, under the project or absolute, names a path in the repo by its tail"""
    return path == name or path.endswith("/" + name) or name.endswith("/" + path)


def dead_labels():
    """recall eval cases labeling a note that's gone, which the eval then stops testing without a word"""
    path = vault.vault_path() / "system" / "recall-eval.jsonl"
    cases = map(json.loads, path.read_text(encoding="utf-8").splitlines()) if path.exists() else []
    slugs = vault.slugs()
    return [f"{c['id']} {slug}" for c in cases for slug in c["needed"] + c["related"] if slug not in slugs]


def render_check(r):
    h = r["health"]
    out = [
        f"vault {r['vault']}",
        f"remote {r['remote'] or 'none'}",
        f"notes {r['notes']}, indexed {r['indexed']}, embedded {r['embedded']}, embedder {'ok' if r['embedder'] else 'unavailable'}",
        f"health {h['line']}",
    ]
    if h["old_leftovers"]:
        out.append("old leftovers " + ", ".join(h["old_leftovers"]))
    if h["dupe_pairs"]:
        out.append("dupe pairs " + ", ".join(f"{a} ~ {b} ({s})" for a, b, s in h["dupe_pairs"]))
    if h["stale_slugs"]:
        out.append("stale candidates " + ", ".join(h["stale_slugs"]))
    if h["conflict_files"]:
        out.append("conflicts " + ", ".join(h["conflict_files"]))
    if h["dead_links"]:
        out.append("dead links " + ", ".join(f"{s} -> {link}" for s, link in h["dead_links"]))
    if h["long_bodies"]:
        out.append("bodies over the cap " + ", ".join(h["long_bodies"]))
    if r["sessions"]:
        out.append(
            "latest sessions, the turns that opened memory before their first work call and the hand backs with a rule "
            "opened after the last work call. a miss is a turn or a hand back the way of working in system/working.md "
            "didn't reach"
        )
        out += [
            f"{s['folder']} {s['session'][:8]} started {s['started']}/{s['turns']}, rules before hand back {s['checked']}/{s['handbacks']}"
            for s in r["sessions"]
        ]
    if r["behind"]:
        out.append("notes naming files a commit changed after the note, check what each says against them")
        out += [f"{b['slug']} {', '.join(b['files'])}" for b in r["behind"]]
    if r["dead_labels"]:
        out.append("recall eval labels naming notes that are gone, point each at the note that took over or drop it " + ", ".join(r["dead_labels"]))
    if r["log_tail"]:
        out.append("log tail\n" + "\n".join(r["log_tail"]))
    return "\n".join(out)


def pane(session, cwd):
    db = index.connect(vec=True)
    project = vault.project_of(cwd)
    health = index.health(db, project)
    leftovers = index.list_notes(db, project, ("leftovers",), k=50)
    injected = index.injected_rows(db, session)
    opened = opened_rows(db, session)
    return {
        "project": project,
        "vault": vault.vault_path().as_posix(),
        "health": {k: v for k, v in health.items() if not isinstance(v, list)},
        "leftovers": [row_json(db, r) | {"age_days": index.days_ago(r["created"])} for r in leftovers],
        "opened": [row_json(db, r) for r in opened],
        "injected": [
            {"slug": r["slug"], "title": r["title"], "path": r["path"], "source": r["source"], "at": r["at"]} for r in injected
        ],
        "counts": {
            "notes": db.execute("select count(*) from notes where status='active'").fetchone()[0],
            "open": len(leftovers),
            "opened": len(opened),
            "recalled": len({r["slug"] for r in injected}),
        },
    }


def opened_rows(db, session):
    """the notes the agent opened this session, newest first"""
    path = next(TRANSCRIPTS.glob(f"*/{session}.jsonl"), None)
    rows = {}
    for name in reversed(transcript.opened(path)):
        if row := index.named(db, name):
            rows.setdefault(row["slug"], row)
    return list(rows.values())
