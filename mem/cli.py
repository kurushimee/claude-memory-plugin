import argparse
import json
import os
import sys
import traceback

from . import git, index, vault

HOOKS = ("brief", "recall", "compacted")


def main():
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse(sys.argv[1:])
    if args.cmd in HOOKS:
        return run_hook(args.cmd)
    try:
        run(args)
    except SystemExit:
        raise
    except Exception as e:
        try:
            vault.log(f"{args.cmd} failed: {traceback.format_exc()}")
        except Exception:
            pass
        raise SystemExit(f"mem {args.cmd} failed: {e!r}")


def parse(argv):
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
    sub.add_parser("show", help="print a note").add_argument("slug")
    s = sub.add_parser("save", help="write a note, body from stdin or --body")
    s.add_argument("--type", required=True, choices=vault.TYPES)
    s.add_argument("--title", required=True)
    s.add_argument("--tags", nargs="*", default=[])
    s.add_argument("--links", nargs="*", default=[])
    s.add_argument("--project")
    s.add_argument("--body")
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
            note = vault.find(args.slug)
            print(note.path.as_posix())
            print(note.path.read_text(encoding="utf-8"))
        case "save":
            body = args.body if args.body is not None else sys.stdin.read()
            project = args.project or vault.project_of(os.getcwd())
            note = save_note(args.type, args.title, body, args.tags, args.links, project)
            print(f"saved {note.slug} at {note.path.as_posix()}")
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


def save_note(type, title, body, tags, links, project):
    if type not in vault.TYPES:
        raise SystemExit(f"type must be one of {', '.join(vault.TYPES)}")
    slug = vault.slugify(title)
    if links:
        body = body.rstrip() + "\n\nrelated " + " ".join(f"[[{l}]]" for l in links)
    note = vault.Note(slug=slug, type=type, title=title, body=body, project=project, tags=list(tags))
    if note.path.exists():
        note.created = vault.read_note(note.path).created
    vault.write_note(note)
    index.index(index.connect(vec=True))
    git.commit([note.path], f"save {slug}")
    return note


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
        out.append("maybe relevant, open with mem show <slug>")
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
        "log_tail": log.read_text(encoding="utf-8").splitlines()[-10:] if log.exists() else [],
    }


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
    if r["log_tail"]:
        out.append("log tail\n" + "\n".join(r["log_tail"]))
    return "\n".join(out)


def pane(session, cwd):
    db = index.connect(vec=True)
    project = vault.project_of(cwd)
    health = index.health(db, project)
    leftovers = index.list_notes(db, project, ("leftovers",), k=50)
    injected = index.injected_rows(db, session)
    return {
        "project": project,
        "vault": vault.vault_path().as_posix(),
        "health": {k: v for k, v in health.items() if not isinstance(v, list)},
        "leftovers": [row_json(db, r) | {"age_days": index.days_ago(r["created"])} for r in leftovers],
        "injected": [
            {"slug": r["slug"], "title": r["title"], "path": r["path"], "source": r["source"], "at": r["at"]} for r in injected
        ],
        "counts": {
            "notes": db.execute("select count(*) from notes where status='active'").fetchone()[0],
            "open": len(leftovers),
            "recalled": len({r["slug"] for r in injected}),
        },
    }
