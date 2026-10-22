import json
import re

from . import git, index, vault

CAP = 7000
BODIES_IN_BRIEF = 6
STOP = set(
    """users kurus appdata local roaming temp tmp src lib bin dist build node_modules venv the and for with from
    into git cmd echo cat type dir head tail grep find python python3 npm npx bun node uv run exe main index test
    tests com org http https www file files path json yaml toml txt lock log out output true false null none
    select where from into update delete insert order limit""".split()
)
POINTER = (
    "the memory skill holds the policy, load it when in doubt. save with memory_save or mem save, "
    "search with memory_search or mem search, open a note with memory_show or mem show <slug>"
)


def safe(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception as e:
        vault.log(f"{fn.__name__} failed: {e!r}")
        return default


def line(row):
    return f"- {row['title']} ({row['slug']})"


def block(db, row, extra=""):
    tags = f" [{row['tags']}]" if row["tags"] else ""
    return f"## {row['title']} ({row['slug']}){tags}\n{index.body_of(db, row['slug'])}{extra}"


def brief_text(db, project, session="", agent="", source="startup", is_sub=False):
    out = [f"memory brief for {project}"]
    shown = []
    feedback = safe(index.list_notes, db, project, ("feedback",), 12, default=[])
    if feedback:
        out.append("how to work, from feedback, newest first")
        out += [block(db, r) for r in feedback]
        shown += [r["slug"] for r in feedback]
    leftovers = safe(index.list_notes, db, project, ("leftovers",), 15, default=[])
    if leftovers:
        out.append("open leftovers")
        out += [block(db, r, f"\nopen for {index.days_ago(r['created'])}d") for r in leftovers]
        shown += [r["slug"] for r in leftovers]
    notes = safe(index.list_notes, db, project, ("facts", "projects"), 30, default=[])
    if notes:
        out.append("project and global notes, the rest as titles, open with mem show <slug>")
        for i, r in enumerate(notes):
            if i < BODIES_IN_BRIEF:
                out.append(block(db, r))
                shown.append(r["slug"])
            else:
                out.append(line(r))
    if source == "compact" and session:
        before = safe(index.before_compaction, db, session, agent, default=[])
        if before:
            out.append("reminded of these before the squash, the summary may have dropped them, re-read what matters")
            out += [f"- {title} ({slug})" for slug, title in before]
        safe(index.stamp_compacted, db, session, agent)
    if not is_sub:
        health = safe(index.health, db, project)
        if health:
            out.append("health: " + health["line"])
    out.append(POINTER)
    return "\n\n".join(out)[:CAP], shown


def brief(payload):
    event = payload.get("hook_event_name", "SessionStart")
    source = payload.get("source", "startup")
    session = payload.get("session_id", "")
    agent = payload.get("agent_id") or ""
    is_sub = event == "SubagentStart" or bool(agent)
    project = vault.project_of(payload.get("cwd", ""))
    if not is_sub and source in ("startup", "resume", "clear"):
        safe(git.sync)
    db = index.connect(vec=True)
    changed, _ = safe(index.index, db, default=([], set()))
    if not is_sub:
        for note in changed:
            safe(git.commit, [note.path], f"edit {note.slug}")
    text, shown = brief_text(db, project, session, agent, source, is_sub)
    safe(index.record_injected, db, session, agent, shown, "brief")
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def keywords(tool_input):
    parts = [v for k, v in tool_input.items() if isinstance(v, str) and k in ("file_path", "path", "pattern", "command", "glob", "notebook_path")]
    words = re.findall(r"[a-z0-9.]{3,}", re.sub(r"[\\/_-]", " ", " ".join(parts).lower()))
    seen = []
    for w in words:
        w = w.rsplit(".", 1)[0] if "." in w[1:] else w
        if len(w) >= 3 and w not in STOP and w not in seen:
            seen.append(w)
    return " ".join(seen[:12])


def touches_memory(tool_input):
    blob = json.dumps(tool_input).replace("\\\\", "/")
    return "mem " in blob or "mem.exe" in blob or "memory_" in blob or vault.vault_path().as_posix() in blob


def recall(payload):
    event = payload.get("hook_event_name", "")
    session = payload.get("session_id", "")
    agent = payload.get("agent_id") or ""
    project = vault.project_of(payload.get("cwd", ""))
    if event == "UserPromptSubmit":
        db = index.connect(vec=True)
        safe(index.index, db)
        hits, maybe = index.search(db, payload.get("prompt", ""), project=project, k=3)
        source, cap = "prompt", 3
    else:
        tool_input = payload.get("tool_input") or {}
        if touches_memory(tool_input):
            return None
        query = keywords(tool_input)
        if not query:
            return None
        db = index.connect(vec=False)
        hits, maybe = index.search(db, query, project=project, k=2, vector=False)
        source, cap = "tool", 2
    seen = index.injected_slugs(db, session, agent)
    hits = [r for r in hits if r["slug"] not in seen][:cap]
    picked = {r["slug"] for r in hits}
    maybe = [r for r in maybe if r["slug"] not in seen and r["slug"] not in picked][:5]
    if not hits and not maybe:
        return None
    out = [f"memory recall, {len(hits)} notes"] + [block(db, r) for r in hits]
    if maybe:
        out.append("maybe relevant, open with mem show <slug>")
        out += [line(r) for r in maybe]
    index.record_injected(db, session, agent, [r["slug"] for r in hits], source)
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n\n".join(out)[:CAP]}}


def compacted(payload):
    db = index.connect(vec=False)
    index.stamp_compacted(db, payload.get("session_id", ""), payload.get("agent_id") or "")
    return None
