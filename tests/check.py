import gc
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp(prefix="memcheck-"))
bare = tmp / "remote.git"
vault_dir = tmp / "vault"
os.environ["MEM_VAULT"] = str(vault_dir)


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
sh("git", "init", "-q", "-b", "main", str(vault_dir))
sh("git", "-C", str(vault_dir), "config", "user.email", "check@mem")
sh("git", "-C", str(vault_dir), "config", "user.name", "check")
sh("git", "-C", str(vault_dir), "remote", "add", "origin", str(bare))
(vault_dir / ".gitignore").write_text(".mem/\n")
sh("git", "-C", str(vault_dir), "add", ".gitignore")
sh("git", "-C", str(vault_dir), "commit", "-q", "-m", "init")
sh("git", "-C", str(vault_dir), "push", "-q", "-u", "origin", "main")

from mem import attempts, cli, git, hooks, index, judge, rules, vault  # noqa: E402

for t in vault.TYPES:
    (vault_dir / t).mkdir()
project = vault_dir.as_posix()

bare_env = subprocess.run(
    [sys.executable, "-c", "import sys, mem.cli; print(' '.join(m for m in ('fastembed', 'mcp', 'sqlite_vec', 'numpy') if m in sys.modules))"],
    cwd=ROOT, capture_output=True, text=True,
)
assert bare_env.stdout.strip() == "", f"heavy imports at start: {bare_env.stdout}"


def line_json(entry):
    """a transcript line the way the app writes it, with no spaces"""
    return json.dumps(entry, separators=(",", ":"))


def write_transcript(path, *entries):
    path.write_text("".join(line_json(e) + "\n" for e in entries), encoding="utf-8")
    return str(path)


def typed(text):
    return {"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": text}}


def said(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


gpu = cli.save_note("facts", "one gpu job at a time", "never start two gpu jobs at once on the 2070", ["gpu"], [], project)
godot = cli.save_note("facts", "godot runs must end themselves", "every godot run started for a test has to exit on its own, see [[one-gpu-job-at-a-time]]", ["godot", "testing"], [], project)
left = cli.save_note("leftovers", "finish the cascade probe debug view", "the probe view in radiance-cascades is half done, next step is wiring the toggle", [], [], project)
added = rules.lesson(
    "a two word prompt hid the biggest job of the day", "user", "global", new="never size the effort by how long the prompt is",
    why="a two word prompt can carry the biggest job of the day", check="size the work by what it asks for", when=["Bash|PowerShell:godot"],
)
assert added.startswith("added rule") and "fix that code too" in added, added
fb = vault.read_note(vault_dir / "rules" / "never-size-the-effort-by-how-long-the-prompt-is.md")
ghidra = cli.save_note("facts", "ghidra lives in the tools folder", "ghidra 12 sits at F:/tools/ghidra and rea is wired to it", ["reference"], [], "global")
elsewhere = tmp / "elsewhere"
elsewhere.mkdir()
away = cli.save_note("facts", "the elsewhere build needs ninja", "the elsewhere folder only builds with ninja on the path", ["build"], [], elsewhere.as_posix())
assert godot.path.exists() and godot.path.read_text(encoding="utf-8").startswith("---\ntitle: godot runs")
assert vault.read_note(godot.path).links == ["one-gpu-job-at-a-time"]
try:
    cli.save_note("rules", "a rule saved by hand", "body", [], [], "global")
    raise AssertionError("a rule got saved around mem lesson")
except vault.Refused:
    pass
refused = (("see [[no-such-note]]", [], "a dead link"), ("x", ["no-such-note"], "a dead link passed as links"), ("a" * (vault.BODY_MAX + 1), [], "a body over the cap"))
for body, links, why in refused:
    try:
        cli.save_note("facts", "a note that should not save", body, [], links, "global")
        raise AssertionError(f"{why} got saved")
    except vault.Refused:
        pass
assert not (vault_dir / "facts" / "a-note-that-should-not-save.md").exists()

db = index.connect(vec=True)
assert index.index(db) == ([], set())
assert db.execute("select count(*) from notes").fetchone()[0] == 6
assert index.embed(["check"]) is not None, "embedder unavailable, the vector checks need the model cached"
assert db.execute("select count(*) from vec").fetchone()[0] == 6

assert vault.project_of(str(elsewhere / "src")) == (elsewhere / "src").as_posix() and vault.project_of(str(Path.home())) == "global"
assert vault.in_scope(elsewhere.as_posix(), (elsewhere / "src").as_posix()) and not vault.in_scope(elsewhere.as_posix(), elsewhere.as_posix() + "2")
assert list(vault.paths_in("cd /f/x && cat src/a/b https://e.com/a/b")) == ["F:/x"]

hits, maybe = index.search(db, "casca", project=project, vector=False)
assert left.slug in [r["slug"] for r in hits + maybe], "trigram miss"
hits, maybe = index.search(db, "the thing that stops godot hanging", project=project)
assert hits and hits[0]["slug"] == godot.slug, [r["slug"] for r in hits]
assert gpu.slug in [r["slug"] for r in hits + maybe], "link hop miss"
assert index.by_meaning(db, index.list_notes(db, project), "test runs that never exit")[0]["slug"] == godot.slug
hits, maybe = index.search(db, "godot", project=project, type="leftovers", vector=False)
assert not hits or all(r["type"] == "leftovers" for r in hits)
listed = index.list_notes(db, project, ("leftovers",))
assert [r["slug"] for r in listed] == [left.slug]

closest = rules.lesson("left a capture running past its deadline", "self", project)
assert closest.startswith("closest rules") and f"[{fb.slug}]" in closest, closest
try:
    rules.lesson("sized a two word prompt as a small job", "user", project, rule=fb.slug)
    raise AssertionError("a user lesson got in without making the rule catch the case")
except vault.Refused as e:
    assert "didn't catch this case in time" in str(e), e
again = rules.lesson("sized a two word prompt as a small job", "user", project, rule=fb.slug, check="count what the prompt asks for")
assert "2 incidents now" in again, again
sharpened = "never size the effort of a task by the length of its prompt"
rules.lesson("treated a short prompt as a small job again", "user", project, rule=fb.slug, sharpen=sharpened, check="read what the prompt asks for, then size it", when=["Agent:research"])
fb = vault.read_note(fb.path)
grown = "size the work by what it asks for. count what the prompt asks for. read what the prompt asks for, then size it"
assert fb.title == sharpened and fb.slug == "never-size-the-effort-by-how-long-the-prompt-is" and vault.section(fb.body, "check") == grown, fb.body
assert [who for _, who in vault.incidents(fb.body)] == ["user"] * 3 and fb.when == ["Bash|PowerShell:godot", "Agent:research"]
triggers = json.loads((vault_dir / ".mem" / "triggers.json").read_text(encoding="utf-8"))
assert {(t["tool"], t["pattern"]) for t in triggers} == {("Bash|PowerShell", "godot"), ("Agent", "research")} and triggers[0]["title"] == sharpened
for bad in ("Bash:(?<=x)godot", "godot", "Bash:(unclosed"):
    try:
        rules.lesson("x", "self", project, rule=fb.slug, when=[bad])
        raise AssertionError(f"a trigger mem-gate can't run got in, {bad}")
    except vault.Refused:
        pass
too_long = (
    ({"what": "x" * (rules.WHAT_MAX + 1), "rule": fb.slug}, "a what past its cap"),
    ({"what": "x", "rule": fb.slug, "check": "y" * rules.CHECK_MAX}, "a check grown past its cap"),
    ({"what": "x", "new": "a rule with a long check", "why": "x", "check": "y" * (rules.CHECK_MAX + 1)}, "a new check past its cap"),
)
for args, why in too_long:
    try:
        rules.lesson(by="self", place=project, **args)
        raise AssertionError(f"{why} got in")
    except vault.Refused:
        pass
assert len(vault.incidents(vault.read_note(fb.path).body)) == 3, "a refused lesson still logged its incident"
far_rule = vault.Note(slug="captures-end-by-their-deadline", type="rules", title="captures end by their deadline", body="why a capture left running holds the gpu\n\ncheck give every capture a deadline\n\nincidents\n- 2026-10-25 self in x, left one running", project=elsewhere.as_posix())
vault.write_note(far_rule)
index.index(db)
assert f"[{far_rule.slug}] in {elsewhere.as_posix()}" in rules.lesson("left a capture running past its deadline", "self", project), "a rule another project has never came up"
for place in ("global", (elsewhere / "src").as_posix()):
    assert "moved it to global" not in rules.lesson("left a capture running", "self", place, rule=far_rule.slug), place
    assert vault.read_note(far_rule.path).project == elsewhere.as_posix(), f"a lesson from {place} moved a project rule"
assert "moved it to global" in rules.lesson("left a capture running again", "self", project, rule=far_rule.slug)
assert vault.read_note(far_rule.path).project == "global", "a rule that bit in a second project stayed in its first"
far_rule.path.unlink()
index.index(db)
calls_log = vault_dir / ".mem" / "calls.jsonl"
logged_calls = [
    {"tool": "Bash", "text": "Bash cmake --build build", "places": [project]},
    {"tool": "Bash", "text": "Bash ls", "places": [project]},
    {"tool": "Bash", "text": "Bash cmake --build far", "places": [elsewhere.as_posix()]},
]
calls_log.write_text("".join(json.dumps(c) + "\n" for c in logged_calls), encoding="utf-8")
fit_lines = rules.reach_lines(["Bash:cmake"], project)
assert fit_lines[:2] == ["Bash:cmake fits 1 of the last 2 calls in scope, like", "  Bash cmake --build build"] and fit_lines[-1].startswith("narrow"), fit_lines
calls_log.unlink()
health = index.health(db, project)
assert (health["lessons_week"], health["lessons_by_user"], health["lessons_repeats"]) == (3, 3, 2), health
assert "3 lessons this week (3 spotted by the user, 2 repeats of a rule)" in health["line"], health["line"]
assert not re.search(r"\b0 (dupe|stale|conflicts|hook|unpushed|dead|bodies)", health["line"]), health["line"]
dead_note = vault.Note(slug="points-nowhere", type="facts", title="points nowhere", body="see [[no-such-note]]", project=project)
long_note = vault.Note(slug="runs-long", type="facts", title="runs long", body="a" * (vault.BODY_MAX + 1), project=project)
for n in (dead_note, long_note):
    vault.write_note(n)
index.index(db)
health = index.health(db, project)
assert (health["dead"], health["long"]) == (1, 1) and "1 dead links" in health["line"] and f"1 bodies over {vault.BODY_MAX}" in health["line"], health["line"]
for n in (dead_note, long_note):
    n.path.unlink()
index.index(db)
mem_log, pass_log = vault_dir / ".mem" / "mem.log", vault_dir / "system" / "log.md"
logged = mem_log.read_text(encoding="utf-8") if mem_log.exists() else ""
pass_log.parent.mkdir(exist_ok=True)
pass_log.write_text("# maintenance log\n\n## 2026-10-25 11:00\n\nread the judge timeouts\n", encoding="utf-8")
mem_log.write_text("2026-10-25 judge timed out\n2026-10-25 10:59 x\n2026-10-25 11:00 x\n2026-10-26 08:00 x\n  a traceback line\n", encoding="utf-8")
assert index.errors_since_pass() == 2, "an error from before the last pass still counted, or one after it went uncounted"
mem_log.write_text(logged, encoding="utf-8")
pass_log.unlink()


def fake_scores(query, docs):
    """godot past the body gate, ghidra between the gates, the rest nowhere"""
    between = (judge.TITLE_GATE + judge.BODY_GATE) / 2
    return [judge.BODY_GATE if d.startswith(godot.title) else between if d.startswith(ghidra.title) else 0 for d in docs]


def context(result):
    return result["hookSpecificOutput"]["additionalContext"] if result else ""


real_scores, judge.scores = judge.scores, fake_scores
prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "s0", "cwd": project, "prompt": f"why does {elsewhere} fail to build"}
first = context(hooks.recall(prompt))
assert away.title in first and f"## {godot.title}" in first, first
assert f"- {ghidra.title} ({ghidra.slug})" in first and "ghidra 12 sits" not in first, "a title past the loose gate comes without its body"
assert hooks.LESSON in first and "rules for this turn" in first and sharpened in first, first
second = context(hooks.recall(prompt))
assert away.title not in second and f"## {godot.title}" not in second and ghidra.slug not in second, "a folder, a body or a title came twice"
assert hooks.LESSON in second, "the lesson line comes with every prompt the user typed"
index.stamp_compacted(db, "s0", "")
again = context(hooks.recall(prompt))
assert away.title in again and f"## {godot.title}" in again, "not brought again after compaction"
events = (
    f"<task-notification>\n<summary>godot run in {elsewhere} finished</summary>\n</task-notification>",
    '<agent-message from="a1">\ngodot run finished\n</agent-message>',
    '<cross-session-message from="s9">\ngodot run finished\n</cross-session-message>',
    "<side-sessions-event>the godot session finished its turn\n</side-sessions-event>",
)
for event in events:
    assert hooks.recall({**prompt, "session_id": "s0c", "prompt": event}) is None, "a background event brought a folder, a rule or the judge"
queries = []
judge.scores = lambda query, docs: queries.append(query)
quiet = context(hooks.recall({**prompt, "session_id": "s0b", "prompt": "godot keeps hanging"}))
assert godot.title not in quiet, "something came by meaning without the judge"
reminded = f"<system-reminder>\nrecent folders {elsewhere}\n</system-reminder>\nwhat now"
assert away.title not in context(hooks.recall({**prompt, "session_id": "s0d", "prompt": reminded})), "a path in an app reminder counted as the user's"
assert "recent folders" not in queries[-1] and "what now" in queries[-1], queries[-1]


def taken(query, docs):
    raise judge.Taken


judge.scores = taken
assert hooks.TAKEN in context(hooks.recall({**prompt, "session_id": "s0f", "prompt": "godot keeps hanging"})), "a judge with no room in VRAM went unsaid"

stopped = write_transcript(tmp / "stopped.jsonl", typed("render the probes"), said("rendering"), {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}})
assert "the user stopped your last turn" in context(hooks.recall({**prompt, "session_id": "s0e", "prompt": "no, wrong scene", "transcript_path": stopped}))
denied = write_transcript(tmp / "denied.jsonl", typed("clean up"), said("deleting"), {"type": "user", "toolDenialKind": "user-rejected", "message": {"role": "user", "content": []}}, typed("no, wrong scene"))
assert "denied 1 of your tool calls" in context(hooks.recall({**prompt, "session_id": "s0f", "prompt": "no, wrong scene", "transcript_path": denied}))
fine = write_transcript(tmp / "fine.jsonl", typed("clean up"), said("done"), {"type": "user", "toolDenialKind": "permission-rule", "message": {}})
assert "the user" not in context(hooks.recall({**prompt, "session_id": "s0g", "prompt": "thanks", "transcript_path": fine})).split("\n\n")[0]
judge.scores = real_scores

tool = {"hook_event_name": "PostToolUse", "session_id": "s1", "cwd": project, "tool_name": "Read", "tool_input": {"file_path": f"{elsewhere}/src/main.cpp"}}
got = context(hooks.recall(tool))
assert "this session just reached it" in got and away.title in got and godot.title not in got, got
assert hooks.recall({**tool, "tool_input": {"command": f"cat {elsewhere.as_posix()}/README.md"}}) is None, "entered twice"
assert hooks.recall({**tool, "tool_input": {"command": "grep -rn godot hanging tests"}}) is None, "tool calls match by scope only"
assert hooks.recall({**tool, "tool_input": {"command": "mem save --type facts --title x"}}) is None
assert hooks.recall({**tool, "tool_input": {"file_path": f"{project}/facts/x.md"}}) is None

gate_exe = tmp / "mem-gate.exe"
sh("go", "build", "-o", str(gate_exe), ".", cwd=ROOT / "mem-gate")


def gate(payload, *args):
    return subprocess.run([str(gate_exe), *args], input=json.dumps(payload), capture_output=True, text=True, check=True).stdout


def cue(payload):
    out = gate(payload, "cues")
    return context(json.loads(out)) if out else ""


bash_path = f"/{elsewhere.as_posix()[0].lower()}{elsewhere.as_posix()[2:]}/src"
gated = {**tool, "session_id": "g1", "tool_input": {"command": f"ls {bash_path}"}}
assert gate({**gated, "tool_input": {"command": "git status"}}) == ""
assert gate({**gated, "agent_id": "a1"}) == "", "a subagent's call brought notes, which the app hands to the main session"
assert away.title in gate(gated), "the gate kept back a folder entry"
assert gate(gated) == "", "the gate let a reached folder through"
assert gate({**gated, "tool_input": {"file_path": f"{project}/facts/x.md"}}) == ""

assert cli.parse(["save", "--type", "facts", "--title", "x"]).project == "global", "a save with no project landed in one"
try:
    cli.save_note("facts", "a note with a bad trigger", "x", [], [], "global", ["godot"])
    raise AssertionError("a note trigger mem-gate can't run got in")
except vault.Refused:
    pass
fx = cli.save_note("facts", "reshade fx compiles twice", "reshade's own fxc passes code the sdk fxc refuses, so both compile it", ["reshade"], [], "global", ["Bash|PowerShell:\\.fx\\b"])
assert vault.read_note(cli.save_note("facts", fx.title, "both fxc builds compile every .fx", ["reshade"], [], "global").path).when == fx.when, "a body rewrite dropped the triggers"
local = cli.save_note("facts", "the vault builds with make", "make all builds it", [], [], project, ["Bash:make"])
compiled = {"hook_event_name": "PostToolUse", "session_id": "t1", "cwd": elsewhere.as_posix(), "tool_name": "Bash", "tool_input": {"command": "fxc /T fx_5_0 boost.fx"}}
got = context(hooks.recall(compiled))
assert "memory this call is about" in got and "both fxc builds" in got, got
assert hooks.recall(compiled) is None, "a note a call is about came twice"
assert hooks.recall({**compiled, "tool_input": {"command": "make all"}}) is None, "a project note came by its trigger outside its project"
assert "both fxc builds" in gate({**compiled, "session_id": "t2"}), "the gate kept back a note the call is about"
assert gate({**compiled, "session_id": "t2"}) == "", "the gate handed over a note the session already got"
assert cue({**compiled, "session_id": "t3"}) == "", "a note's trigger came as a rule cue"
for note in (fx, local):
    cli.forget_note(note.slug)

call = {"hook_event_name": "PostToolUse", "session_id": "c1", "agent_id": "", "cwd": project, "tool_name": "Bash", "tool_input": {"command": "godot --headless -s capture.gd"}}
started = time.perf_counter()
found = cue(call)
took = time.perf_counter() - started
assert found.startswith(f"a rule fits this call, {sharpened}\ncheck {grown}"), found
assert {"tool": "Bash", "text": "Bash godot --headless -s capture.gd", "places": [project]} in [json.loads(l) for l in calls_log.read_text(encoding="utf-8").splitlines()]
assert cue(call) == "", "a rule came twice in one turn"
assert cue({**call, "session_id": "c0", "tool_name": "Read"}) == "", "a rule fired on a tool its trigger doesn't name"
assert cue({**call, "session_id": "c0", "tool_input": {"command": "ls"}}) == "", "a rule fired on a call its pattern doesn't fit"
failed = {**call, "hook_event_name": "PostToolUseFailure", "tool_input": {"command": "make all"}}
assert cue(failed).startswith("this call failed"), "a failed call got no cue"
assert cue(failed).startswith("this exact call already failed"), "a repeated failure got no cue"
assert cue({**failed, "is_interrupt": True}) == "", "an interrupt counted as a failure"
edit = {**call, "tool_name": "Edit", "tool_input": {"file_path": f"{project}/x.py"}}
assert [cue(edit) for _ in range(4)] == [""] * 4 and "edit number 5" in cue(edit), "the fifth edit of a file got no cue"
turn_file = vault_dir / ".mem" / "turns" / "c1+.jsonl"
turn_file.write_text(json.dumps({"start": int(time.time()) - 16 * 60}) + "\n", encoding="utf-8")
assert "going for 15 minutes" in cue({**call, "tool_input": {"command": "ls"}}) and cue({**call, "tool_input": {"command": "ls"}}) == ""
turn_file.write_text(json.dumps({"start": int(time.time()) - 61 * 60}) + "\n" + json.dumps({"elapsed": 30}) + "\n", encoding="utf-8")
assert "going for 60 minutes" in cue({**call, "tool_input": {"command": "ls"}}), "the hourly cue never came"
now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
heard = {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "stop, wrong file", "origin": {"kind": "human"}, "timestamp": now}}
working = write_transcript(tmp / "working.jsonl", typed("fix it"), said("on it"), heard)
assert "sent a message while you worked" in cue({**call, "tool_input": {"command": "ls"}, "transcript_path": working})
assert cue({**call, "tool_input": {"command": "ls"}, "transcript_path": working}) == "", "one message got the cue twice"
cued = context(hooks.recall({**prompt, "session_id": "c1", "prompt": "is it done"}))
assert f"rules for this turn" in cued and sharpened in cued
assert cue(call).startswith("a rule fits this call"), "a new turn kept the last turn's cues"
project_rule = vault.Note(slug="ninja-goes-on-the-path", type="rules", title="ninja goes on the path", body="why it builds with ninja\n\ncheck where ninja\n\nincidents\n- 2026-10-25 user in x, built without it", project=elsewhere.as_posix(), when=["Bash:cmake"])
vault.write_note(project_rule)
index.index(db)
assert cue({**call, "session_id": "c2", "tool_input": {"command": "cmake --build ."}}) == "", "a project rule fired outside its project"
assert "ninja goes on the path" in cue({**call, "session_id": "c3", "tool_input": {"command": f"cmake --build {elsewhere.as_posix()}/build"}})
wrapped = {**call, "session_id": "c4", "tool_name": "mcp__ccd_turn__wrap_up", "tool_input": {"recap": "done"}}
vault.write_note(vault.Note(slug="look-before-calling-it-done", type="rules", title="look at the result before calling it done", body="why x\n\ncheck y\n\nincidents\n- 2026-10-25 user in x, y", when=["mcp__ccd_turn__wrap_up:."]))
index.index(db)
assert "look at the result" in cue(wrapped), "an MCP tool trigger never fired"
vault.write_note(vault.Note(slug="godot-edits-get-a-run", type="rules", title="godot edits get a test run", body="why x\n\ncheck y\n\nincidents\n- 2026-10-25 user in x, y", when=["Edit:godot"]))
index.index(db)
note_edit = {**call, "session_id": "c5", "tool_name": "Edit", "tool_input": {"file_path": godot.path.as_posix()}}
assert cue(note_edit) == "", "a vault note's file name fit a trigger"
vault.write_note(vault.Note(slug="facts-edits-say-it-generally", type="rules", title="facts edits say it generally", body="why x\n\ncheck y\n\nincidents\n- 2026-10-26 user in x, y", when=[r"Edit:[\\/]facts[\\/]\*\.md$"]))
index.index(db)
folder_cue = cue({**note_edit, "session_id": "c10"})
assert "facts edits say it generally" in folder_cue and "godot edits" not in folder_cue, "a vault folder trigger missed a note edit"
(vault_dir / "rules" / "facts-edits-say-it-generally.md").unlink()
index.index(db)
vault.write_note(long_note)
over = cue({**note_edit, "session_id": "c7", "tool_input": {"file_path": long_note.path.as_posix()}})
assert f"body at {vault.BODY_MAX + 1} characters" in over, "an edit that left a note over the cap got no cue"
long_note.path.unlink()
assert "godot edits get a test run" in cue({**note_edit, "session_id": "c6", "tool_input": {"file_path": f"{elsewhere.as_posix()}/godot_runner.py"}})
docs_rule = vault.Note(slug="elsewhere-docs-stay-short", type="rules", title="elsewhere docs stay short", body="why x\n\ncheck y\n\nincidents\n- 2026-10-25 user in x, y", project=elsewhere.as_posix(), when=["Edit:\\.md$"])
vault.write_note(docs_rule)
index.index(db)
from_elsewhere = {**note_edit, "session_id": "c8", "cwd": elsewhere.as_posix()}
assert cue(from_elsewhere) == "", "a vault note edit counted as work in the session's folder"
assert "elsewhere docs stay short" in cue({**from_elsewhere, "session_id": "c9", "tool_input": {"file_path": f"{elsewhere.as_posix()}/README.md"}})
calls_log.write_text("x" * (1 << 20) + "\n", encoding="utf-8")
cue({**call, "session_id": "c7", "tool_input": {"command": "ls"}})
old_calls = vault_dir / ".mem" / "calls.old.jsonl"
assert old_calls.exists() and old_calls.stat().st_size > 1 << 20 and calls_log.stat().st_size < 1000, "the calls log grew past its cap"
for path in (project_rule.path, vault_dir / "rules" / "look-before-calling-it-done.md", vault_dir / "rules" / "godot-edits-get-a-run.md", docs_rule.path):
    path.unlink()
index.index(db)

asked = {"hook_event_name": "PostToolUse", "session_id": "s2", "cwd": project, "tool_name": "Agent", "tool_input": {"description": "QD-OLED ABL timing research", "prompt": "find the abl timing"}, "tool_response": {"status": "async_launched", "agentId": "ag1"}}
assert hooks.journal(asked) is None, "a first question came back as asked before"
hooks.journal({"hook_event_name": "SubagentStop", "cwd": project, "agent_id": "ag1", "last_assistant_message": "found nothing on the abl timing"})
repeat = context(hooks.journal({**asked, "session_id": "s9", "tool_input": {"description": "Research OLED ABL timing", "prompt": "abl timing"}, "tool_response": {"status": "async_launched", "agentId": "ag2"}}))
assert repeat.startswith(hooks.ASKED) and "found nothing on the abl timing" in repeat, repeat
sibling = {**asked, "tool_input": {"description": "Extract flatland-rc part 1", "prompt": "x"}, "tool_response": {"status": "completed", "agentId": "ag3", "content": [{"type": "text", "text": "part 1 facts"}]}}
hooks.journal(sibling)
assert hooks.journal({**sibling, "tool_input": {"description": "Extract flatland-rc part 15", "prompt": "x"}}) is None, "a sibling of a batch counted as asked before"
assert [e["answer"] for e in attempts.read(project)][:4] == ["found nothing on the abl timing", "", "part 1 facts", "part 1 facts"]
hooks.journal({**asked, "tool_input": {"description": "Count the vault rules", "prompt": "count"}, "tool_response": {"status": "async_launched", "agentId": "ag4"}})
hooks.journal({"hook_event_name": "PostToolUse", "cwd": project, "agent_id": "ag4", "tool_name": "SubagentHandback", "tool_input": {"message": "35 rules"}})
hooks.journal({"hook_event_name": "SubagentStop", "cwd": project, "agent_id": "ag4", "last_assistant_message": "handing it back"})
hooks.journal({"hook_event_name": "SubagentStop", "cwd": project, "agent_id": "squash", "last_assistant_message": "the squash summary"})
assert "squash summary" not in attempts.journal_path(project).read_text(encoding="utf-8"), "an answer to no question got journaled"
assert attempts.read(project)[-1]["answer"] == "35 rules", "a handed back report never became the answer"

away.path.write_text(away.path.read_text(encoding="utf-8") + "\nand cmake 3.30\n", encoding="utf-8")
index.index(db)
start = {"hook_event_name": "SessionStart", "session_id": "s2", "source": "startup", "cwd": project}
text = context(hooks.brief(start))
assert f"edit {away.slug}" in sh("git", "-C", str(bare), "log", "--oneline", "main").stdout, "an edit some other index call saw first never got committed"
assert "journal/" in sh("git", "-C", str(bare), "ls-tree", "-r", "--name-only", "main").stdout, "the journal never got committed"
sh("git", "-C", str(vault_dir), "commit", "-q", "--allow-empty", "-m", "offline")
assert git.unpushed() == 1 and index.health(db, project)["unpushed"] == 1, "a commit no push reached went uncounted"
git.push()
assert git.unpushed() == 0
assert rules.HEADER in text and f"- {sharpened} (3 times)" in text and "open leftovers" in text and left.title in text and "health:" in text, text
assert f"- {ghidra.title} ({ghidra.slug})" in text and "ghidra 12 sits" not in text, "a global note without always comes as a title only"
assert away.title not in text, "the brief carries nothing from other folders"
judge.scores = fake_scores
fits = context(hooks.recall({**prompt, "session_id": "s2"}))
assert ghidra.slug not in fits, "a title the brief listed came again"
assert ghidra.slug not in {r["slug"] for r in index.injected_rows(db, "s2")}, "a title only note counted as remembered"
judge.scores = real_scores
resumed = context(hooks.brief({**start, "source": "resume"}))
assert sharpened in resumed and left.title not in resumed, "a resumed session lost its rules or got a body twice"
sub = context(hooks.brief({**start, "hook_event_name": "SubagentStart", "agent_id": "a1"}))
assert "health:" not in sub and left.title in sub and sharpened in sub
spoken = write_transcript(tmp / "spoken.jsonl", typed("make the brief fit"), said("on it"), heard, typed("and keep the rules"))
after = context(hooks.brief({**start, "source": "compact", "transcript_path": spoken}))
assert "before the squash" in after and godot.title in after, after
assert "asked of subagents this session" in after and "QD-OLED ABL timing research, came back found nothing" in after, after
said_at = after.index("the user's own words")
assert after.index("- and keep the rules", said_at) < after.index("- stop, wrong file", said_at) < after.index("- make the brief fit", said_at), after

cli.set_done(left.slug)
assert index.list_notes(index.connect(vec=True), project, ("leftovers",)) == []
cli.forget_note(gpu.slug)
assert not gpu.path.exists() and index.connect().execute("select count(*) from notes where slug=?", (gpu.slug,)).fetchone()[0] == 0

log = sh("git", "-C", str(bare), "log", "--oneline", "main").stdout.splitlines()
assert any("save godot" in line for line in log) and any("done " in line for line in log) and any("forget " in line for line in log), log
assert any(f"lesson {fb.slug}" in line for line in log) and any(f"rule {fb.slug}" in line for line in log), log

other = tmp / "other"
sh("git", "clone", "-q", str(bare), str(other))
sh("git", "-C", str(other), "config", "user.email", "other@mem")
sh("git", "-C", str(other), "config", "user.name", "other")
remote_note = other / "facts" / f"{godot.slug}.md"
remote_note.write_text(remote_note.read_text(encoding="utf-8").replace("exit on its own", "exit on its own, remote edit"), encoding="utf-8")
sh("git", "-C", str(other), "commit", "-q", "-am", "remote edit")
sh("git", "-C", str(other), "push", "-q")
local = vault.read_note(godot.path)
local.body = local.body.replace("exit on its own", "exit on its own, local edit")
vault.write_note(local)
git.commit([godot.path], "local edit")
git.sync()
conflict = vault_dir / "facts" / f"{godot.slug}-conflict.md"
assert conflict.exists() and "remote edit" in conflict.read_text(encoding="utf-8"), "conflict file missing"
assert "local edit" in godot.path.read_text(encoding="utf-8")
assert sh("git", "-C", str(vault_dir), "status", "--porcelain").stdout.strip() == "", sh("git", "-C", str(vault_dir), "status", "--porcelain").stdout
assert "merge remote" in sh("git", "-C", str(bare), "log", "--oneline", "main").stdout

report = cli.check_report()
assert report["notes"] == report["indexed"] == 6 and report["health"]["conflicts"] == 1, (report["health"], report["log_tail"])
pane = cli.pane("s2", project)
assert set(pane) == {"project", "vault", "health", "leftovers", "injected", "counts"} and pane["counts"]["recalled"] > 0
assert pane["health"]["lessons_by_user"] == 3, pane["health"]
json.dumps(pane)

moved = cli.save_note("projects", "panel sources", "old take", [], [], project)
cli.save_note("facts", "panel sources", "new take", [], [], project)
assert not moved.path.exists() and index.note_row(db, moved.slug)["path"].endswith(f"facts/{moved.slug}.md"), "a save under another type left two files"


def minutes_ago(n):
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).isoformat()


def commit_code(message, at):
    for args in (("add", "-A"), ("commit", "-q", "-m", message)):
        subprocess.run(["git", "-C", str(code), *args], env={**os.environ, "GIT_COMMITTER_DATE": at}, capture_output=True, check=True)


named = "tools/session.ps1 runs engine/nvidia_path_tracer.patch and logs to calls.jsonl at 0.5 s"
assert set(cli.FILE.findall(named)) == {"tools/session.ps1", "engine/nvidia_path_tracer.patch", "calls.jsonl"}, cli.FILE.findall(named)
code = tmp / "code"
(code / "src").mkdir(parents=True)
(code / "src" / "thing.py").write_text("read()\n")
for args in (("init", "-q"), ("config", "user.email", "code@mem"), ("config", "user.name", "code")):
    sh("git", "-C", str(code), *args)
commit_code("thing", minutes_ago(20))
os.environ["GIT_COMMITTER_DATE"] = minutes_ago(10)
old_take = cli.save_note("facts", "thing reads its config at start", "src/thing.py reads config.toml once at start", [], [], code.as_posix())
del os.environ["GIT_COMMITTER_DATE"]
assert cli.behind_code() == [], "a note newer than its code counted as behind"
(code / "src" / "thing.py").write_text("read()\nwatch()\n")
commit_code("watch", minutes_ago(5))
new_take = cli.save_note("facts", "thing watches its config", "src/thing.py rereads config.toml when it changes", [], [], code.as_posix())
assert cli.behind_code() == [{"slug": old_take.slug, "files": ["src/thing.py"]}], cli.behind_code()
for note in (old_take, new_take):
    cli.forget_note(note.slug)

labels = vault.vault_path() / "system" / "recall-eval.jsonl"
labels.parent.mkdir(exist_ok=True)
labels.write_text(json.dumps({"id": "p1", "kind": "prompt", "needed": [moved.slug], "related": ["gone-note"]}) + "\n", encoding="utf-8")
assert cli.dead_labels() == ["p1 gone-note"], cli.dead_labels()
labels.unlink()

# a big rulebook, a long leftover list and many long notes still fit under the cap the app cuts at
for i in range(19):
    vault.write_note(vault.Note(slug=f"global-rule-{i}", type="rules", title=f"global rule {i} " + "word " * 24, body="why x\n\ncheck y\n\nincidents\n- 2026-10-25 self in x, y"))
for i in range(15):
    vault.write_note(vault.Note(slug=f"project-rule-{i}", type="rules", title=f"project rule {i} " + "word " * 24, body="why x\n\ncheck y\n\nincidents", project=project))
for i in range(12):
    vault.write_note(vault.Note(slug=f"stress-note-{i}", type="facts", title=f"stress note {i}", body=("lorem " * 160).strip(), project=project))
for i in range(45):
    vault.write_note(vault.Note(slug=f"stress-left-{i}", type="leftovers", title=f"stress leftover {i}", body=("ipsum " * 60).strip(), project=project))
for i in range(40):
    vault.write_note(vault.Note(slug=f"stress-global-{i}", type="facts", title=f"stress global {i} " + "word " * 10, body="x"))
index.index(db)
text, shown, listed = hooks.brief_text(index.connect(vec=True), project)
assert len(text) < 10_000, f"the brief is {len(text)} characters, the app cuts it to a preview"
assert text.count("\n- global rule") + text.count("\n- project rule") == 34, "a rule line got cut while it had room"
assert "health:" in text and text.endswith(hooks.POINTER) and "more, mem search finds them" in text, text[-600:]
lines = text.splitlines()
assert shown and all(any(l.startswith("## ") and f"({s})" in l for l in lines) for s in shown), shown
for i in range(19, 119):
    vault.write_note(vault.Note(slug=f"global-rule-{i}", type="rules", title=f"global rule {i} " + "word " * 24, body="why x\n\ncheck y\n\nincidents"))
index.index(db)
text = hooks.brief_text(index.connect(vec=True), project)[0]
kept = text.count("\n- global rule") + text.count("\n- project rule")
assert len(text) < 10_000 and text.endswith(hooks.POINTER), f"a rulebook past the room took the brief to {len(text)} characters"
assert kept < 134 and hooks.RULES_LEFT.format(134 - kept) in text, "the rules with no room went unnamed"
for i in range(30):
    vault.write_note(vault.Note(slug=f"far-{i}", type="facts", title=f"far note {i}", body=("dolor " * 200).strip(), project=elsewhere.as_posix()))
index.index(db)
judge.scores = lambda query, docs: [judge.BODY_GATE] * len(docs)
reached = context(hooks.recall({**prompt, "session_id": "s7", "prompt": f"look at {elsewhere}"}))
assert len(reached) < 10_000 and "far note" in reached and "memory that fits" in reached, len(reached)
judge.scores = real_scores

if judge.MODEL.exists():
    hold = "import sys, time\nfrom mem import judge\nwith judge.gpu_turn(time.monotonic() + 5):\n    print('held', flush=True)\n    sys.stdin.read()"
    holder = subprocess.Popen([sys.executable, "-c", hold], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    try:
        with judge.gpu_turn(time.monotonic() + 0.5):
            raise AssertionError("two judges had the GPU at once")
    except judge.Busy:
        pass
    holder.communicate("", timeout=10)
    with judge.gpu_turn(time.monotonic() + 5) as alone:
        assert alone, "the GPU stayed taken after the other judge let go"

    @contextmanager
    def cut_ranker(seconds):
        def rank(query, docs):
            ranked.append(docs)
            if len(ranked) > 1:
                raise TimeoutError("timed out")
            return [0.5] * len(docs)

        yield rank

    ranked = []
    real_ranker, judge.ranker = judge.ranker, cut_ranker
    real_gpu, judge.gpu_now = judge.gpu_now, lambda: (judge.NEED, 0)
    assert judge.scores("q", ["d"] * (judge.CHUNK + 1)) == [0.5] * judge.CHUNK, "a judge cut by the deadline dropped what it had scored"
    ranked = [[]]
    assert judge.scores("q", ["d"]) == [] and re.search(r"no other judge.*MiB VRAM free and the GPU \d+% busy", (vault.mem_dir() / "mem.log").read_text(encoding="utf-8"))
    judge.gpu_now = lambda: (judge.NEED - 1, 0)
    ranked = []
    try:
        judge.scores("q", ["d"])
        raise AssertionError("the judge went ahead with too little VRAM free")
    except judge.Taken:
        pass
    assert not ranked, "the judge loaded with too little VRAM free"
    judge.gpu_now = real_gpu
    judge.ranker = real_ranker
    assert judge.gpu_now()[0] > 0
    docs = [hooks.doc_of(db, index.note_row(db, s)) for s in (godot.slug, away.slug)]
    try:
        real = judge.scores(hooks.query_of("godot keeps hanging when a test run never exits", ""), docs)
        assert real and real[0] >= judge.BODY_GATE > judge.TITLE_GATE > real[1], real
    except judge.Taken:
        print("the real judge check didn't run, another program holds the VRAM")

import anyio  # noqa: E402
from mcp import Client  # noqa: E402

from mem import mcp_server  # noqa: E402

settings = tmp / "Claude-Data" / "app" / "Claude Extensions Settings"
settings.mkdir(parents=True)
(settings / f"{mcp_server.EXTENSION}.json").write_text('{"isEnabled": true}')
os.environ.update(LOCALAPPDATA=str(tmp), CLAUDE_CODE_ENTRYPOINT="claude-desktop")
assert mcp_server.extension_covers()
os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
assert not mcp_server.extension_covers()


async def refused_then_shown():
    with anyio.fail_after(30):
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("memory_show", {"slug": "no-such-note"}), await client.call_tool("memory_show", {"slug": godot.slug})


refused, shown = anyio.run(refused_then_shown)
assert refused.is_error and "no note with slug no-such-note" in refused.content[0].text, refused
assert not shown.is_error and godot.title in shown.content[0].text, "a refused call took the server down"


def writable(remove, path, _):
    """git keeps its objects read only, which Windows refuses to delete"""
    os.chmod(path, stat.S_IWRITE)
    remove(path)


db.close()
gc.collect()
shutil.rmtree(tmp, onexc=writable)
print(f"all checks passed, a cue call took {took * 1000:.0f} ms")
