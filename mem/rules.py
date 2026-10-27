"""The rulebook in rules/. Each note is one general behavior grown out of real mistakes. Its title is the rule, its
body says why, what to check and lists the incidents behind it with the project each happened in, so the index shows
how widely a rule holds."""

import json
import time

from . import git, index, vault

TITLE_MAX = 140
WHAT_MAX = 200
CHECK_MAX = 800  # the agent reruns the whole check before each step it covers
CLOSEST = 3
CODE_FIX = "if a tool, script or harness let this happen, fix that code too in this turn, so it can't happen the same way again"
HEADER = (
    "rules, each grew out of real mistakes. the count says how often it bit and in how many projects, and one that bit "
    "in many holds for any task"
)


def spread(db, row):
    """how often a rule bit and in how many projects"""
    found = vault.incidents(index.body_of(db, row["slug"]))
    return len(found), len({where for _, _, where in found if where not in ("", "global")})


def ranked(db, rows):
    """the rules that bit in the most places first, then the ones that bit most often"""
    return sorted(rows, key=lambda r: spread(db, r)[::-1], reverse=True)


def in_scope(db, project):
    return ranked(db, index.list_notes(db, project, ("rules",), 500))


def line(db, row):
    hits, places = spread(db, row)
    where = f" in {places} {'project' if places == 1 else 'projects'}" if places else ""
    return f"- {row['title']} ({hits} {'time' if hits == 1 else 'times'}{where})"


def turn_file(session, agent):
    """what mem-gate saw this turn, a plain file it appends to"""
    return vault.mem_dir() / "turns" / f"{session}+{agent or ''}.jsonl"


def start_turn(session, agent):
    """starts a fresh turn for mem-gate's cues"""
    path = turn_file(session, agent)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"start": int(time.time())}) + "\n", encoding="utf-8", newline="\n")


def lesson(what, by, place, rule=None, new=None, sharpen=None, why=None, check=None, scope="global"):
    """logs a mistake, as an incident of an existing rule or as a new rule, and with neither says which rules are
    closest"""
    what = " ".join(what.split())
    if len(what) > WHAT_MAX:
        raise vault.Refused(f"say what went wrong in one line under {WHAT_MAX} characters, the check holds the detail")
    db = index.connect(vec=True)
    index.index(db)
    if rule:
        return strengthen(rule, incident(what, by, place), by, sharpen, check, place)
    if new:
        return add(new, incident(what, by, place), why, check, scope)
    return closest(db, what, by, place)


def incident(what, by, place):
    return f"- {vault.today()} {by} in {place}, {what}"


def strengthen(slug, entry, by, sharpen, check, place):
    path = vault.vault_path() / "rules" / f"{slug}.md"
    if not path.exists():
        raise vault.Refused(f"no rule {slug}, mem lesson without --rule lists the closest ones")
    if by == "user" and not (sharpen or check):
        raise vault.Refused(
            "the user had to point this out, so the rule didn't catch this case in time. log it in one call that also "
            "makes the rule catch it, with --sharpen or --check"
        )
    note = vault.read_note(path)
    if check:
        old = vault.section(note.body, "check")
        check = check_within(f"{old}. {check}" if old else check, path)
        note.body = with_section(note.body, "check", check)
    note.body = note.body.rstrip() + "\n" + entry
    if sharpen:
        note.title = sharpen
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
    return "\n".join(out + [CODE_FIX])


def add(title, entry, why, check, scope):
    if not why or not check:
        raise vault.Refused("a new rule needs --why and --check")
    if len(title) > TITLE_MAX:
        raise vault.Refused(f"the title is the rule and stays under {TITLE_MAX} characters, say it more generally")
    check_within(check)
    slug = vault.slugify(title)
    if (vault.vault_path() / "rules" / f"{slug}.md").exists():
        raise vault.Refused(f"rule {slug} exists, strengthen it with --rule {slug}")
    body = f"why {why}\n\ncheck {check}\n\nincidents\n{entry}"
    save(vault.Note(slug=slug, type="rules", title=title, body=body, project=scope), f"rule {slug}")
    return "\n".join([f"added rule {slug}", CODE_FIX])


def check_within(check, path=None):
    if len(check) <= CHECK_MAX:
        return check
    where = f"the check in {path.as_posix()}" if path else "it"
    raise vault.Refused(
        f"the check would have {len(check)} characters, past {CHECK_MAX}, and the agent reruns all of it before every "
        f"step it covers. rewrite {where} shorter so it still catches every incident, then log the lesson again"
    )


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
        'case add --sharpen "<title>" or --check "<a sentence the check gains>". one from another project moves to '
        "global",
        "if none does, write the general behavior behind it, not this one case, with --new \"<title>\" --why \"...\" "
        '--check "...", plus --scope <project> when it only bites in that project\'s setup, its code, design, tools '
        "or look",
    ]
    return "\n".join(out)
