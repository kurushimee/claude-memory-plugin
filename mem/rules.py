"""The rulebook in rules/. Each note is one general behavior grown out of real mistakes. Its title is the rule, its
body says why, what to check and lists the incidents behind it, and its triggers name the tool calls where mem-gate
brings it up again."""

import json
import re
import time

from . import git, index, vault

TITLE_MAX = 140
WHAT_MAX = 200
CHECK_MAX = 800  # every cue carries the whole check
CLOSEST = 3
FOR_TURN = 5
EXAMPLES = 3
CALLS = ("calls.old.jsonl", "calls.jsonl")
# mem-gate runs the triggers with Go's RE2, which has no lookaround and no backreferences
NOT_RE2 = re.compile(r"\(\?<?[=!]|\\[1-9]")
CODE_FIX = "if a tool, script or harness let this happen, fix that code too in this turn, so it can't happen the same way again"
HEADER = "rules, each grew out of real mistakes, the count is how often it bit. a call that fits one brings it back with what to check"


def hits(db, row):
    return len(vault.incidents(index.body_of(db, row["slug"])))


def ranked(db, rows):
    """the rules that bit most often first"""
    return sorted(rows, key=lambda r: -hits(db, r))


def in_scope(db, project):
    return ranked(db, index.list_notes(db, project, ("rules",), 500))


def line(db, row):
    n = hits(db, row)
    return f"- {row['title']} ({n} {'time' if n == 1 else 'times'})"


def turn_file(session, agent):
    """what mem-gate saw this turn, a plain file it appends to"""
    return vault.mem_dir() / "turns" / f"{session}+{agent or ''}.jsonl"


def start_turn(session, agent):
    """starts a fresh turn for mem-gate and returns the rules the last turn's tool calls brought up"""
    path = turn_file(session, agent)
    cued = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                cued.append(json.loads(raw)["cued"])
            except (ValueError, KeyError, TypeError):
                continue
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"start": int(time.time())}) + "\n", encoding="utf-8", newline="\n")
    return cued


def for_turn(db, project, cued, query):
    """the rules the last turn's calls brought up, then the ones closest in meaning to the message"""
    rows = in_scope(db, project)
    by_slug = {r["slug"]: r for r in rows}
    picked = [by_slug[s] for s in dict.fromkeys(cued) if s in by_slug][:FOR_TURN]
    for r in index.by_meaning(db, rows, query)[:CLOSEST]:
        if len(picked) < FOR_TURN and r not in picked:
            picked.append(r)
    return picked


def lesson(what, by, place, rule=None, new=None, sharpen=None, why=None, check=None, when=(), scope="global"):
    """logs a mistake, as an incident of an existing rule or as a new rule, and with neither says which rules are
    closest"""
    what = " ".join(what.split())
    if len(what) > WHAT_MAX:
        raise vault.Refused(f"say what went wrong in one line under {WHAT_MAX} characters, the check holds the detail")
    when = list(when)
    if error := triggers_error(when):
        raise vault.Refused(error)
    db = index.connect(vec=True)
    index.index(db)
    if rule:
        return strengthen(db, rule, incident(what, by, place), by, sharpen, check, when, place)
    if new:
        return add(new, incident(what, by, place), why, check, when, scope)
    return closest(db, what, by, place)


def incident(what, by, place):
    return f"- {vault.today()} {by} in {place}, {what}"


def triggers_error(when):
    for w in when:
        tool, _, pattern = w.partition(":")
        if not tool or not pattern:
            return f"{w} needs the form Tool:regex, like Bash|PowerShell:godot|harness"
        if NOT_RE2.search(w):
            return f"{w} uses lookaround or a backreference, which mem-gate can't run"
        try:
            re.compile(tool)
            re.compile(pattern)
        except re.error as e:
            return f"{w} is not a valid regex, {e}"
    return None


def strengthen(db, slug, entry, by, sharpen, check, when, place):
    path = vault.vault_path() / "rules" / f"{slug}.md"
    if not path.exists():
        raise vault.Refused(f"no rule {slug}, mem lesson without --rule lists the closest ones")
    if by == "user" and not (sharpen or check or when):
        raise vault.Refused(
            "the user had to point this out, so the rule didn't catch this case in time. log it in one call that also "
            "makes the rule catch it, with --sharpen, --check or --when"
        )
    note = vault.read_note(path)
    if check:
        old = vault.section(note.body, "check")
        check = check_within(f"{old}. {check}" if old else check, path)
        note.body = with_section(note.body, "check", check)
    note.body = note.body.rstrip() + "\n" + entry
    if sharpen:
        note.title = sharpen
    added = [w for w in dict.fromkeys(when) if w not in note.when]
    note.when += added
    note.updated = vault.today()
    # a rule that bit in a second project holds beyond its own
    moved = note.project != "global" and place != "global" and not vault.in_scope(note.project, place)
    out = [f"strengthened {slug}, {len(vault.incidents(note.body))} incidents now"]
    if moved:
        out.append(
            f"moved it to global, it bit in {note.project} and in {place}. if its title names either one, give it a "
            "title said for any project with --sharpen"
        )
        note.project = "global"
    save(note, f"lesson {slug}")
    out += reach_lines(added, note.project)
    return "\n".join(out + [CODE_FIX])


def add(title, entry, why, check, when, scope):
    if not why or not check:
        raise vault.Refused("a new rule needs --why and --check")
    if len(title) > TITLE_MAX:
        raise vault.Refused(f"the title is the rule and stays under {TITLE_MAX} characters, say it more generally")
    check_within(check)
    slug = vault.slugify(title)
    if (vault.vault_path() / "rules" / f"{slug}.md").exists():
        raise vault.Refused(f"rule {slug} exists, strengthen it with --rule {slug}")
    body = f"why {why}\n\ncheck {check}\n\nincidents\n{entry}"
    save(vault.Note(slug=slug, type="rules", title=title, body=body, project=scope, when=when), f"rule {slug}")
    return "\n".join([f"added rule {slug}", *reach_lines(when, scope), CODE_FIX])


def check_within(check, path=None):
    if len(check) <= CHECK_MAX:
        return check
    where = f"the check in {path.as_posix()}" if path else "it"
    raise vault.Refused(
        f"the check would have {len(check)} characters, past {CHECK_MAX}, and every cue carries all of it. rewrite "
        f"{where} shorter so it still catches every incident, then log the lesson again"
    )


def recent_calls():
    """the tool calls mem-gate logged lately, with the places each one reached"""
    out = []
    for name in CALLS:
        path = vault.mem_dir() / name
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
    return out


def reach(when, project, calls):
    """the texts of the calls in the rule's scope that a trigger fits, and how many calls were in its scope"""
    tool, _, pattern = when.partition(":")
    here = [c for c in calls if any(vault.in_scope(project, p) for p in c.get("places") or [])]
    return [c["text"] for c in here if fits(tool, pattern, c["tool"], c["text"])], len(here)


def fits(trigger_tool, pattern, tool, text):
    """a trigger fits a call the way mem-gate matches it, the tool part against the whole tool name"""
    return bool(re.fullmatch(trigger_tool, tool, re.I) and re.search(pattern, text, re.I))


def reach_lines(when, project):
    """what each new trigger would have fit lately, so one that fires where the rule has nothing to say shows now"""
    calls = recent_calls()
    out = []
    for w in when:
        fits, total = reach(w, project, calls)
        if not total:
            continue
        out.append(f"{w} fits {len(fits)} of the last {total} calls in scope" + (", like" if fits else ""))
        out += [f"  {' '.join(text.split())[:120]}" for text in list(dict.fromkeys(reversed(fits)))[:EXAMPLES]]
    if any(line.startswith("  ") for line in out):
        out.append("narrow the rule's when line by hand if any of these is a call the rule has nothing to say about")
    return out


def with_section(body, word, text):
    paras = body.split("\n\n")
    new = f"{word} {text}"
    for i, para in enumerate(paras):
        if para.startswith(word + " "):
            paras[i] = new
            return "\n\n".join(paras)
    at = next((i for i, p in enumerate(paras) if p.startswith("incidents")), len(paras))
    return "\n\n".join(paras[:at] + [new] + paras[at:])


def save(note, message):
    vault.write_note(note)
    index.index(index.connect(vec=True))
    git.commit([note.path], message)


def closest(db, what, by, place):
    """the closest rules from every project, since one another project already has covers this case too"""
    rows = index.by_meaning(db, in_scope(db, None), what)[:CLOSEST]
    out = ["closest rules"]
    for r in rows:
        check = vault.section(index.body_of(db, r["slug"]), "check")
        where = "" if r["project"] == "global" else f" in {r['project']}"
        out += [f"{line(db, r)} [{r['slug']}]{where}", f"  check {check}"]
    out += [
        f'if one covers it, strengthen it with mem lesson "<what>" --by {by} --rule <slug>, and when it missed this '
        'case add --sharpen "<title>", --check "<a sentence the check gains>" or --when "Tool:regex". one from '
        "another project moves to global",
        "if none does, write the general behavior behind it, not this one case, with --new \"<title>\" --why \"...\" "
        '--check "..." --when "Tool:regex", plus --scope <project> only when it is about that project\'s own code or '
        "design",
    ]
    return "\n".join(out)
