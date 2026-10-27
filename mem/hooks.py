import re

from . import attempts, git, index, judge, rules, transcript, vault

# the app swaps hook context over 10,000 characters for a file path and a preview that the agent never opens, and
# what is left under it covers the few short headers taken without asking the room
CAP = 9500
TOOL_KEYS = ("file_path", "path", "pattern", "command", "glob", "notebook_path")
SQUASH = 3000
SAID = 400
EVENTS = ("<task-notification>", "<agent-message ", "<cross-session-message ", "<side-sessions-event>")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
POINTER = (
    "open notes with memory_show or mem show, several titles at once, search with memory_search or mem search, save "
    "with memory_save or mem save and log a mistake with memory_lesson or mem lesson. the memory skill holds the "
    "policy for saving and lessons"
)
MORE = "and {} more with no room here, memory_search finds them"
MISSED = "last week the user had to point out {} mistakes that a rule in memory already covered"
LESSON = (
    "if this message points out something you did wrong, first log it with mem lesson --by user as the general "
    "behavior behind it, then go on"
)
TAKEN = (
    "no notes came by meaning with this message, a game or another program holds the gpu memory the judge needs, so "
    "search memory yourself if this message needs notes"
)
ASKED = (
    "asked before in this project. if this is the same question, stop this agent with TaskStop and use what came "
    "back, or say what's different this time"
)


def safe(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception as e:
        vault.log(f"{fn.__name__} failed: {e!r}")
        return default


class Room:
    """what is left of the cap for one hook output"""

    def __init__(self, size=CAP):
        self.left = size

    def fits(self, text):
        if len(text) + 2 > self.left:
            return False
        self.take(text)
        return True

    def take(self, text):
        self.left -= len(text) + 2
        return text


def listing(room, head, lines, budget=CAP, more=""):
    """the head and as many lines as fit in the budget and the room as one block, and when more is given, how many
    had no room"""
    if not lines or not room.fits(head):
        return []
    out, start = [head], room.left
    for i, text in enumerate(lines):
        if start - room.left + len(text) > budget or not room.fits(text):
            if more:
                out.append(room.take(more.format(len(lines) - i)))
            break
        out.append(text)
    return ["\n".join(out)]


def line(row):
    open_for = f", open for {index.days_ago(row['created'])}d" if row["type"] == "leftovers" else ""
    return f"- {row['title']}{open_for}"


def block(db, row):
    tags = f" [{row['tags']}]" if row["tags"] else ""
    return f"## {row['title']} ({row['slug']}){tags}\n{index.body_of(db, row['slug'])}"


def working(db):
    """how to use memory, a vault file so a cleanup pass can sharpen it from the misses mem check reports"""
    path = vault.vault_path() / "system" / "working.md"
    out = [path.read_text(encoding="utf-8").strip()] if path.exists() else []
    if missed := index.lessons_week(db)["lessons_missed"]:
        out.append(MISSED.format(missed))
    return out


def groups(project, rows):
    notes = [r for r in rows if r["type"] in ("facts", "projects")]
    return [
        ("open leftovers", [r for r in rows if r["type"] == "leftovers"]),
        (f"notes for {project}", [r for r in notes if r["project"] != "global"]),
        ("global notes", [r for r in notes if r["project"] == "global"]),
    ]


def squashed(db, project, session, agent, transcript_path, room):
    """what the squash summary may have dropped, the notes opened or brought before it, what subagents already brought
    back and the user's own words"""
    brought = [title for _, title in safe(index.before_compaction, db, session, agent, default=[])]
    opened = [] if agent else [r["title"] for n in transcript.opened(transcript_path) if (r := index.named(db, n))]
    asked = safe(attempts.of_session, project, session, default=[])
    said = [] if agent else transcript.user_messages(transcript_path)
    safe(index.stamp_compacted, db, session, agent)
    return [
        *listing(room, "opened or brought before the squash, the summary may have dropped what they said, open again "
                 "what the work still needs", [f"- {t}" for t in dict.fromkeys(opened + brought)], SQUASH),
        *listing(room, "asked of subagents this session, check what came back before asking again",
                 [attempts.line(e, 300) for e in reversed(asked)], SQUASH),
        *listing(room, "the user's own words this session, newest first, the summary may have reworded them",
                 ["- " + s[:SAID] for s in reversed(said)], SQUASH),
    ]


def brief_text(db, project, session="", agent="", source="startup", is_sub=False, transcript_path=""):
    """the index, how to use memory and every rule and note title in scope, with no bodies, since a body pushed in
    that the task doesn't need teaches the agent that memory comes to it"""
    rows = safe(index.list_notes, db, project, None, 500, default=[])
    head = f"memory index for {project}"
    tail = [POINTER]
    if not is_sub and (health := safe(index.health, db, project)):
        tail.insert(0, "health: " + health["line"])
    room = Room(CAP - sum(len(t) + 2 for t in [head, *tail]))
    out = [head, *(room.take(t) for t in safe(working, db, default=[]))]
    ranked = rules.ranked(db, [r for r in rows if r["type"] == "rules"])
    out += listing(room, rules.HEADER, [rules.line(db, r) for r in ranked], more=MORE)
    for title, part in groups(project, rows):
        out += listing(room, title, [line(r) for r in part], more=MORE)
    if source == "compact" and session:
        out += squashed(db, project, session, agent, transcript_path, room)
    return "\n\n".join([*out, *tail])


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
    if is_sub:
        # a subagent never sends a prompt, so its whole run is one turn
        safe(rules.start_turn, session, agent)
    db = index.connect(vec=True)
    safe(index.index, db)
    if not is_sub:
        for path in safe(git.edited, default=[]):
            safe(git.commit, [path], f"edit {path.stem}")
    text = brief_text(db, project, session, agent, source, is_sub, payload.get("transcript_path", ""))
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


def entered(db, project, places, reached):
    """notes of the places that the session's own index did not name and no earlier call brought, and the folders
    those notes belong to"""
    rows, scopes = {}, set()
    for place in places:
        for r in index.list_notes(db, place, None, 500):
            if r["project"] in reached or r["project"] == "global" or vault.in_scope(r["project"], project):
                continue
            scopes.add(r["project"])
            rows[r["slug"]] = r
    return list(rows.values()), scopes


def entry(db, session, agent, project, places, room):
    try:
        db.execute("begin immediate")
        rows, scopes = entered(db, project, places, index.reached(session, agent))
        index.record_reached(session, agent, scopes)
    finally:
        db.commit()
    if not rows:
        return []
    names = ", ".join(sorted({r["project"] for r in rows}))
    head = f"memory for {names}, this session just reached it. open what the work there needs with memory_show"
    ranked = rules.ranked(db, [r for r in rows if r["type"] == "rules"])
    lines = [rules.line(db, r) for r in ranked] + [line(r) for r in rows if r["type"] != "rules"]
    return listing(room, head, lines, more=MORE)


def doc_of(db, row):
    return f"{row['title']}\n{row['tags'] or ''}\n{index.body_of(db, row['slug'])[:1000]}"


def query_of(prompt, reply):
    return (f"previous reply: {reply}\n" if reply else "") + f"user message: {prompt[:1500]}"


def judged(db, session, agent, project, query, room):
    """the notes in scope whose body this session lacks and that the judge finds the message is about. rules aren't
    judged, they're about how to work and not about the subject of a message"""
    seen = index.injected_slugs(db, session, agent)
    rows = [r for r in index.list_notes(db, project, None, 500) if r["type"] != "rules" and r["slug"] not in seen]
    if not rows:
        return []
    # a judge short on time stops early, so it reads the likeliest notes first
    rows = index.by_meaning(db, rows, query)
    try:
        scores = judge.scores(query, [doc_of(db, r) for r in rows])
    except judge.Taken:
        return [room.take(TAKEN)]
    ranked = sorted(zip(scores or [], rows), key=lambda pair: pair[0], reverse=True)
    picked = [r for s, r in ranked if s >= judge.BODY_GATE][:3]
    bodies = {r["slug"]: b for r in picked if room.fits(b := block(db, r))}
    if not bodies:
        return []
    index.record_injected(db, session, agent, list(bodies), "prompt")
    return [room.take("memory that fits this message"), *bodies.values()]


def stop_line(transcript_path):
    interrupted, denied = transcript.stops(transcript_path)
    if not (interrupted or denied):
        return ""
    what = "stopped your last turn" if interrupted else f"denied {denied} of your tool calls in the last turn"
    return (
        f"the user {what}. before anything else work out what you did that they didn't want, and if it was your "
        "mistake log it with mem lesson --by user"
    )


def recall(payload):
    """a prompt gets the notes in scope its message is about, judged by meaning, and a call that reaches another
    folder for the first time gets the titles of that folder's notes"""
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
    # background task events and messages from subagents or other sessions arrive as prompts too, often, and carry
    # paths out of reports, so they bring neither folders nor the model
    typed = source == "prompt" and bool(text) and not text.lstrip().startswith(EVENTS)
    places = places_in(project, text) if source == "tool" or typed else set()
    if source == "tool" and not places:
        return None
    db = index.connect(vec=source == "prompt")
    room = Room()
    out = []
    if source == "prompt":
        safe(index.index, db)
        db.commit()
        safe(rules.start_turn, session, agent)
    if typed:
        path = payload.get("transcript_path")
        out += [room.take(t) for t in (safe(stop_line, path, default=""), LESSON) if t]
    if places:
        out += entry(db, session, agent, project, places, room)
    if typed:
        query = query_of(text, transcript.last_reply(path))
        out += safe(judged, db, session, agent, project, query, room, default=[])
    if not out:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n\n".join(out)}}


def answer_of(response):
    """what a subagent that ran in the foreground brought back, nothing for one sent to the background"""
    if not isinstance(response, dict) or response.get("status") == "async_launched":
        return ""
    content = response.get("content")
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content if isinstance(content, str) else ""


def journal(payload):
    """an Agent call gets the same questions already asked in this project, and a subagent's report goes into the
    journal, the message of its SubagentHandback call or, without one, its last message when it stops"""
    project = vault.project_of(payload.get("cwd", ""))
    if payload.get("tool_name") == "SubagentHandback":
        attempts.answer(project, payload.get("agent_id") or "", (payload.get("tool_input") or {}).get("message") or "")
        return None
    if payload.get("hook_event_name") == "SubagentStop":
        attempts.answer(project, payload.get("agent_id") or "", payload.get("last_assistant_message") or "")
        return None
    asked = payload.get("tool_input") or {}
    response = payload.get("tool_response")
    question = asked.get("description") or asked.get("prompt", "")[:80]
    before = attempts.asked_before(project, question)
    agent = response.get("agentId", "") if isinstance(response, dict) else ""
    attempts.ask(project, payload.get("session_id", ""), agent, question, asked.get("prompt", ""), answer_of(response))
    if not before:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join([ASKED, *map(attempts.line, before)])}}
