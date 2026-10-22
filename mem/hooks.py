import json
import re

from . import git, index, judge, vault

BUDGET = {"feedback": 6000, "leftovers": 2500, "notes": 3000}
TOOL_KEYS = ("file_path", "path", "pattern", "command", "glob", "notebook_path")
TITLES = 30
TRANSCRIPT_TAIL = 256 * 1024
REPLY_CHARS = 800
NO_REPLY = "No response requested."
EVENTS = ("<task-notification>", "<agent-message ", "<cross-session-message ")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
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


def section(db, rows, budget, extra=lambda r: ""):
    out, shown, used = [], [], 0
    for i, r in enumerate(rows):
        b = block(db, r, extra(r))
        if used + len(b) > budget:
            out += [line(x) for x in rows[i:]]
            break
        out.append(b)
        shown.append(r["slug"])
        used += len(b)
    return out, shown


def belongs(row, project):
    """the brief carries only what fits any task here, the project's own notes and notes tagged always"""
    if "always" in (row["tags"] or "").split() or row["project"] != "global":
        return True
    return project == "global" and row["type"] == "leftovers"


GROUPS = (
    ("how to work, from feedback, newest first, the rest as titles", ("feedback",), "feedback"),
    ("open leftovers", ("leftovers",), "leftovers"),
    ("notes, the rest as titles, open with mem show <slug>", ("facts", "projects"), "notes"),
)


def sections(db, rows):
    out, shown = [], []
    for header, types, budget in GROUPS:
        part = [r for r in rows if r["type"] in types][:40]
        if not part:
            continue
        extra = (lambda r: f"\nopen for {index.days_ago(r['created'])}d") if budget == "leftovers" else (lambda r: "")
        blocks, slugs = section(db, part, BUDGET[budget], extra)
        out += [header, *blocks]
        shown += slugs
    return out, shown


def brief_text(db, project, session="", agent="", source="startup", is_sub=False):
    seen = safe(index.injected_slugs, db, session, agent, default=set()) if source == "resume" else set()
    in_scope = [r for r in safe(index.list_notes, db, project, None, 500, default=[]) if r["slug"] not in seen]
    blocks, shown = sections(db, [r for r in in_scope if belongs(r, project)])
    out = [f"memory brief for {project}", *blocks]
    others = [r for r in in_scope if not belongs(r, project)][:TITLES]
    if others:
        out += ["other notes here, titles only, open one with mem show <slug> when it fits the task", *map(line, others)]
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
    return "\n\n".join(out), shown, [r["slug"] for r in others]


def brief(payload):
    event = payload.get("hook_event_name", "SessionStart")
    source = payload.get("source", "startup")
    session = payload.get("session_id", "")
    agent = payload.get("agent_id") or ""
    is_sub = event == "SubagentStart" or bool(agent)
    project = vault.project_of(payload.get("cwd", ""))
    if not is_sub and source in ("startup", "resume", "clear"):
        safe(git.sync)
        safe(index.prune_reached)
    db = index.connect(vec=True)
    safe(index.index, db)
    if not is_sub:
        for path in safe(git.edited, default=[]):
            safe(git.commit, [path], f"edit {path.stem}")
    text, shown, listed = brief_text(db, project, session, agent, source, is_sub)
    safe(index.record_injected, db, session, agent, shown, "brief")
    safe(index.record_injected, db, session, agent, listed, index.MENTION)
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def tool_text(name, tool_input):
    parts = [tool_input[k][:300] for k in TOOL_KEYS if isinstance(tool_input.get(k), str)]
    return " ".join([name, *parts])


def touches_memory(text):
    if re.search(r"\bmem(\.exe)? |memory_", text):
        return True
    home = vault.vault_path().as_posix()
    return any(vault.in_scope(home, p) for p in vault.paths_in(text))


def places_in(project, text):
    """the folders outside the session's own project that the paths in text lead into"""
    return {vault.project_of(p) for p in vault.paths_in(text)} - {project, "global"}


def entered(db, project, places, seen, reached):
    """notes of the places that the session's own brief did not carry and no earlier call brought, and the
    folders those notes belong to"""
    rows, scopes = {}, set()
    for place in places:
        for r in index.list_notes(db, place, None, 500):
            if r["project"] in reached or r["project"] == "global" or vault.in_scope(r["project"], project):
                continue
            scopes.add(r["project"])
            if r["slug"] not in seen:
                rows[r["slug"]] = r
    return list(rows.values()), scopes


def entry(db, session, agent, project, places, source):
    try:
        db.execute("begin immediate")
        rows, scopes = entered(db, project, places, index.injected_slugs(db, session, agent), index.reached_projects(session, agent))
        index.record_reached(session, agent, scopes)
        if not rows:
            return []
        blocks, shown = sections(db, rows)
        index.record_injected(db, session, agent, shown, source)
    finally:
        db.commit()
    names = ", ".join(sorted({r["project"] for r in rows}))
    return [f"memory for {names}, this session just reached it", *blocks]


def last_reply(transcript_path):
    """the end of the assistant's last reply, so the judge knows what a short prompt is about"""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - TRANSCRIPT_TAIL))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return ""
    for raw in reversed(lines):
        if '"assistant"' not in raw:
            continue
        try:
            content = json.loads(raw).get("message", {}).get("content")
        except ValueError:
            continue
        texts = [c.get("text", "") for c in content if c.get("type") == "text"] if isinstance(content, list) else []
        reply = "\n".join(texts).strip()
        if reply and reply != NO_REPLY:
            return reply[-REPLY_CHARS:]
    return ""


def doc_of(db, row):
    return f"{row['title']}\n{row['tags'] or ''}\n{index.body_of(db, row['slug'])[:1000]}"


def query_of(prompt, reply):
    return (f"previous reply: {reply}\n" if reply else "") + f"user message: {prompt[:1500]}"


def judged(db, session, agent, project, prompt, reply):
    """the notes in scope whose body this session lacks, judged against the prompt. a body needs a strict
    score, a title a loose one, since a title that misses costs one line"""
    seen = index.injected_slugs(db, session, agent)
    rows = [r for r in index.list_notes(db, project, None, 500) if r["slug"] not in seen]
    if not rows or not prompt.strip():
        return []
    scores = judge.scores(query_of(prompt, reply), [doc_of(db, r) for r in rows])
    if not scores:
        return []
    ranked = sorted(zip(scores, rows), key=lambda pair: pair[0], reverse=True)
    mentioned = index.mentioned_slugs(db, session, agent)
    bodies = [r for s, r in ranked if s >= judge.BODY_GATE][:3]
    titles = [r for s, r in ranked if judge.TITLE_GATE <= s < judge.BODY_GATE and r["slug"] not in mentioned][:5]
    index.record_injected(db, session, agent, [r["slug"] for r in bodies], "prompt")
    index.record_injected(db, session, agent, [r["slug"] for r in titles], index.MENTION)
    out = ["memory that fits this message", *(block(db, r) for r in bodies)] if bodies else []
    if titles:
        out += ["maybe related, titles only, open one with mem show <slug> if it fits", *map(line, titles)]
    return out


def recall(payload):
    """a folder's notes come in the first time the session reaches it, and a prompt also gets the notes in
    scope judged by meaning"""
    event = payload.get("hook_event_name", "")
    session = payload.get("session_id", "")
    agent = payload.get("agent_id") or ""
    project = vault.project_of(payload.get("cwd", ""))
    if event == "UserPromptSubmit":
        # the app puts its reminders, recent project folders among them, in front of what the user wrote
        source, text = "prompt", REMINDER.sub("", payload.get("prompt", "")).strip()
    else:
        source, text = "tool", tool_text(payload.get("tool_name", ""), payload.get("tool_input") or {})
        if touches_memory(text):
            return None
    places = places_in(project, text)
    if source == "tool" and not places:
        return None
    db = index.connect(vec=source == "prompt")
    if source == "prompt":
        safe(index.index, db)
        db.commit()
    out = entry(db, session, agent, project, places, source) if places else []
    # background task events and messages from subagents or other sessions arrive as prompts too, often, and are no
    # reason to load the model
    if source == "prompt" and not text.lstrip().startswith(EVENTS):
        out += safe(judged, db, session, agent, project, text, last_reply(payload.get("transcript_path")), default=[])
    if not out:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n\n".join(out)}}
