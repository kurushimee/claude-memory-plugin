"""The rulebook in rules/. Each note is one general behavior grown out of real mistakes. Its title is the rule, its
body says why, what to check and lists the incidents behind it, and its triggers name the tool calls where mem-gate
brings it up again."""

import json
import re
import time

from . import git, index, vault

CAP = {"global": 20, "project": 15}
TITLE_MAX = 140
CLOSEST = 3
FOR_TURN = 5
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
    when = list(when)
    if error := triggers_error(when):
        raise SystemExit(error)
    db = index.connect(vec=True)
    index.index(db)
    if rule:
        return strengthen(db, rule, incident(what, by, place), by, sharpen, check, when)
    if new:
        return add(db, new, incident(what, by, place), why, check, when, scope)
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


def strengthen(db, slug, entry, by, sharpen, check, when):
    path = vault.vault_path() / "rules" / f"{slug}.md"
    if not path.exists():
        raise SystemExit(f"no rule {slug}, mem lesson without --rule lists the closest ones")
    note = vault.read_note(path)
    note.body = note.body.rstrip() + "\n" + entry
    if sharpen:
        note.title = sharpen
    if check:
        note.body = with_section(note.body, "check", check)
    note.when = list(dict.fromkeys(note.when + when))
    note.updated = vault.today()
    save(note, f"lesson {slug}")
    out = [f"strengthened {slug}, {len(vault.incidents(note.body))} incidents now"]
    if by == "user" and not (sharpen or check or when):
        out.append(
            "the user had to point out something this rule already covers, so it didn't catch this case in time. "
            f"make it catch it with mem lesson again on --rule {slug} with --sharpen, --check or --when"
        )
    return "\n".join(out + [CODE_FIX])


def add(db, title, entry, why, check, when, scope):
    if not why or not check:
        raise SystemExit("a new rule needs --why and --check")
    if len(title) > TITLE_MAX:
        raise SystemExit(f"the title is the rule and stays under {TITLE_MAX} characters, say it more generally")
    slug = vault.slugify(title)
    if (vault.vault_path() / "rules" / f"{slug}.md").exists():
        raise SystemExit(f"rule {slug} exists, strengthen it with --rule {slug}")
    count = sum(1 for r in index.list_notes(db, None, ("rules",), 500) if r["project"] == scope)
    cap = CAP["global" if scope == "global" else "project"]
    if count >= cap:
        raise SystemExit(
            f"{scope} has {count} rules, the cap is {cap}. fold this lesson into the closest rule with --rule and "
            "--sharpen, or merge two rules first"
        )
    body = f"why {why}\n\ncheck {check}\n\nincidents\n{entry}"
    save(vault.Note(slug=slug, type="rules", title=title, body=body, project=scope, when=when), f"rule {slug}")
    return f"added rule {slug}\n{CODE_FIX}"


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
    rows = index.by_meaning(db, in_scope(db, place), what)[:CLOSEST]
    out = ["closest rules"]
    for r in rows:
        check = vault.section(index.body_of(db, r["slug"]), "check")
        out += [f"{line(db, r)} [{r['slug']}]", f"  check {check}"]
    out += [
        f'if one covers it, strengthen it with mem lesson "<what>" --by {by} --rule <slug>, and when it missed this '
        'case add --sharpen "<title>", --check "<check>" or --when "Tool:regex"',
        "if none does, write the general behavior behind it, not this one case, with --new \"<title>\" --why \"...\" "
        '--check "..." --when "Tool:regex", plus --scope <project> when it only holds there',
        counts(db, place),
    ]
    return "\n".join(out)


def counts(db, place):
    rows = index.list_notes(db, None, ("rules",), 500)
    out = f"global has {sum(1 for r in rows if r['project'] == 'global')} of {CAP['global']} rules"
    if place != "global":
        here = sum(1 for r in rows if r["project"] == place)
        out += f", {place} has {here} of {CAP['project']}"
    return out
