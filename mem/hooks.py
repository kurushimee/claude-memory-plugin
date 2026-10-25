import re

from . import attempts, git, index, judge, rules, transcript, vault

# the app swaps hook context over 10,000 characters for a file path and a preview that the agent never opens, and
# what is left under it covers the few short headers taken without asking the room
CAP = 9500
TOOL_KEYS = ("file_path", "path", "pattern", "command", "glob", "notebook_path")
TITLES = 30
SQUASH = 3000
SAID = 400
EVENTS = ("<task-notification>", "<agent-message ", "<cross-session-message ", "<side-sessions-event>")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
POINTER = (
    "the memory skill holds the policy, load it when in doubt. save with memory_save or mem save, "
    "search with memory_search or mem search, open a note with memory_show or mem show <slug>, "
    "log a mistake with memory_lesson or mem lesson"
)
LESSON = (
    "if this message points out something you did wrong, first log it with mem lesson --by user as the general "
    "behavior behind it, then go on"
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


def listing(room, head, lines, budget=CAP):
    """the head and as many lines as fit in the budget and the room"""
    if not lines or not room.fits(head):
        return []
    out, start = [head], room.left
    for text in lines:
        if start - room.left + len(text) > budget or not room.fits(text):
            break
        out.append(text)
    return out


def line(row):
    return f"- {row['title']} ({row['slug']})"


def block(db, row, extra=""):
    tags = f" [{row['tags']}]" if row["tags"] else ""
    return f"## {row['title']} ({row['slug']}){tags}\n{index.body_of(db, row['slug'])}{extra}"


def age(row):
    return f"\nopen for {index.days_ago(row['created'])}d" if row["type"] == "leftovers" else ""


def section(db, rows, room):
    """bodies while they fit, then titles while they fit, then how many are left"""
    out, shown = [], []
    for i, r in enumerate(rows):
        if len(out) == len(shown) and room.fits(b := block(db, r, age(r))):
            out.append(b)
            shown.append(r["slug"])
        elif room.fits(t := line(r)):
            out.append(t)
        else:
            out.append(room.take(f"and {len(rows) - i} more, mem search finds them"))
            break
    return out, shown


def belongs(row, project):
    """the brief carries only what fits any task here, the project's own notes and notes tagged always"""
    if "always" in (row["tags"] or "").split() or row["project"] != "global":
        return True
    return project == "global" and row["type"] == "leftovers"


GROUPS = (
    ("open leftovers", ("leftovers",)),
    ("notes, the rest as titles, open with mem show <slug>", ("facts", "projects")),
)


def rule_lines(db, rows, room):
    """every rule in scope, one line each and never cut, since the caps on the rulebook keep them few and short"""
    if not rows:
        return []
    return [room.take(rules.HEADER), *(room.take(rules.line(db, r)) for r in rules.ranked(db, rows))]


def sections(db, rows, room):
    out, shown = [], []
    for header, types in GROUPS:
        part = [r for r in rows if r["type"] in types][:40]
        if part and room.fits(header):
            blocks, slugs = section(db, part, room)
            out += [header, *blocks]
            shown += slugs
    return out, shown


def squashed(db, project, session, agent, transcript_path, room):
    """what the squash summary may have dropped, the notes reminded of before it, what subagents already brought back
    and the user's own words"""
    before = safe(index.before_compaction, db, session, agent, default=[])
    asked = safe(attempts.of_session, project, session, default=[])
    said = [] if agent else transcript.user_messages(transcript_path)
    safe(index.stamp_compacted, db, session, agent)
    return [
        *listing(room, "reminded of these before the squash, the summary may have dropped them, re-read what matters",
                 [f"- {title} ({slug})" for slug, title in before], SQUASH),
        *listing(room, "asked of subagents this session, check what came back before asking again",
                 [attempts.line(e, 300) for e in reversed(asked)], SQUASH),
        *listing(room, "the user's own words this session, newest first, the summary may have reworded them",
                 ["- " + s[:SAID] for s in reversed(said)], SQUASH),
    ]


def brief_text(db, project, session="", agent="", source="startup", is_sub=False, transcript_path=""):
    seen = safe(index.injected_slugs, db, session, agent, default=set()) if source == "resume" else set()
    in_scope = [r for r in safe(index.list_notes, db, project, None, 500, default=[]) if r["slug"] not in seen]
    notes = [r for r in in_scope if r["type"] != "rules"]
    head = f"memory brief for {project}"
    tail = [POINTER]
    if not is_sub and (health := safe(index.health, db, project)):
        tail.insert(0, "health: " + health["line"])
    room = Room(CAP - sum(len(t) + 2 for t in [head, *tail]))
    rule_part = rule_lines(db, [r for r in in_scope if r["type"] == "rules"], room)
    squash = squashed(db, project, session, agent, transcript_path, room) if source == "compact" and session else []
    blocks, shown = sections(db, [r for r in notes if belongs(r, project)], room)
    others = [r for r in notes if not belongs(r, project)][:TITLES]
    titles = listing(room, "other notes here, titles only, open one with mem show <slug> when it fits the task", [line(r) for r in others])
    listed = [r["slug"] for r in others[: max(0, len(titles) - 1)]]
    text = "\n\n".join([head, *rule_part, *blocks, *titles, *squash, *tail])
    return text, shown, listed


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
    text, shown, listed = brief_text(db, project, session, agent, source, is_sub, payload.get("transcript_path", ""))
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


def entry(db, session, agent, project, places, source, room):
    try:
        db.execute("begin immediate")
        rows, scopes = entered(db, project, places, index.injected_slugs(db, session, agent), index.reached_projects(session, agent))
        index.record_reached(session, agent, scopes)
        if not rows:
            return []
        names = ", ".join(sorted({r["project"] for r in rows}))
        head = room.take(f"memory for {names}, this session just reached it")
        rule_part = rule_lines(db, [r for r in rows if r["type"] == "rules"], room)
        blocks, shown = sections(db, [r for r in rows if r["type"] != "rules"], room)
        index.record_injected(db, session, agent, shown, source)
    finally:
        db.commit()
    return [head, *rule_part, *blocks]


def doc_of(db, row):
    return f"{row['title']}\n{row['tags'] or ''}\n{index.body_of(db, row['slug'])[:1000]}"


def query_of(prompt, reply):
    return (f"previous reply: {reply}\n" if reply else "") + f"user message: {prompt[:1500]}"


def judged(db, session, agent, project, query, room):
    """the notes in scope whose body this session lacks, judged against the prompt. a body needs a strict
    score, a title a loose one, since a title that misses costs one line. rules come in through their own lines,
    since they are about how to work, not about the subject of a message"""
    seen = index.injected_slugs(db, session, agent)
    rows = [r for r in index.list_notes(db, project, None, 500) if r["type"] != "rules" and r["slug"] not in seen]
    if not rows:
        return []
    # a judge short on time stops early, so it reads the likeliest notes first
    rows = index.by_meaning(db, rows, query)
    scores = judge.scores(query, [doc_of(db, r) for r in rows])
    if not scores:
        return []
    ranked = sorted(zip(scores, rows), key=lambda pair: pair[0], reverse=True)
    mentioned = index.mentioned_slugs(db, session, agent)
    bodies, titles = [], []
    for r in [r for s, r in ranked if s >= judge.BODY_GATE][:3]:
        (bodies if room.fits(block(db, r)) else titles).append(r)
    titles += [r for s, r in ranked if judge.TITLE_GATE <= s < judge.BODY_GATE and r["slug"] not in mentioned][:5]
    titles = [r for r in titles if room.fits(line(r))]
    index.record_injected(db, session, agent, [r["slug"] for r in bodies], "prompt")
    index.record_injected(db, session, agent, [r["slug"] for r in titles], index.MENTION)
    out = [room.take("memory that fits this message"), *(block(db, r) for r in bodies)] if bodies else []
    if titles:
        out += [room.take("maybe related, titles only, open one with mem show <slug> if it fits"), *map(line, titles)]
    return out


def stop_line(transcript_path):
    interrupted, denied = transcript.stops(transcript_path)
    if not (interrupted or denied):
        return ""
    what = "stopped your last turn" if interrupted else f"denied {denied} of your tool calls in the last turn"
    return (
        f"the user {what}. before anything else work out what you did that they didn't want, and if it was your "
        "mistake log it with mem lesson --by user"
    )


def turn_lines(db, project, cued, query, transcript_path, room):
    out = [room.take(t) for t in (stop_line(transcript_path), LESSON) if t]
    picked = rules.for_turn(db, project, cued, query)
    if picked:
        out += [room.take("rules for this turn, from the last turn's calls and this message"), *(room.take(rules.line(db, r)) for r in picked)]
    return out


def recall(payload):
    """a folder's notes come in the first time the session reaches it, and a prompt also gets the rules for the turn
    and the notes in scope judged by meaning"""
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
        cued = safe(rules.start_turn, session, agent, default=[])
    if typed:
        path = payload.get("transcript_path")
        query = query_of(text, transcript.last_reply(path))
        out += safe(turn_lines, db, project, cued, query, path, room, default=[])
    if places:
        out += entry(db, session, agent, project, places, source, room)
    if typed:
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
