import gc
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
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

from mem import cli, git, hooks, index, judge, vault  # noqa: E402

for t in vault.TYPES:
    (vault_dir / t).mkdir()
project = vault_dir.as_posix()

bare_env = subprocess.run(
    [sys.executable, "-c", "import sys, mem.cli; print(' '.join(m for m in ('fastembed', 'mcp', 'sqlite_vec', 'numpy') if m in sys.modules))"],
    cwd=ROOT, capture_output=True, text=True,
)
assert bare_env.stdout.strip() == "", f"heavy imports at start: {bare_env.stdout}"

godot = cli.save_note("facts", "godot runs must end themselves", "every godot run started for a test has to exit on its own, see [[one-gpu-job-at-a-time]]", ["godot", "testing"], [], project)
gpu = cli.save_note("facts", "one gpu job at a time", "never start two gpu jobs at once on the 2070", ["gpu"], [], project)
left = cli.save_note("leftovers", "finish the cascade probe debug view", "the probe view in radiance-cascades is half done, next step is wiring the toggle", [], [], project)
fb = cli.save_note("feedback", "prompt length says nothing about effort", "a two word prompt can carry the biggest job of the day", ["always", "effort"], [], "global")
ghidra = cli.save_note("facts", "ghidra lives in the tools folder", "ghidra 12 sits at F:/tools/ghidra and rea is wired to it", ["reference"], [], "global")
elsewhere = tmp / "elsewhere"
elsewhere.mkdir()
away = cli.save_note("facts", "the elsewhere build needs ninja", "the elsewhere folder only builds with ninja on the path", ["build"], [], elsewhere.as_posix())
assert godot.path.exists() and godot.path.read_text(encoding="utf-8").startswith("---\ntitle: godot runs")
assert vault.read_note(godot.path).links == ["one-gpu-job-at-a-time"]

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
hits, maybe = index.search(db, "godot", project=project, type="leftovers", vector=False)
assert not hits or all(r["type"] == "leftovers" for r in hits)
listed = index.list_notes(db, project, ("leftovers",))
assert [r["slug"] for r in listed] == [left.slug]

def fake_scores(query, docs):
    """godot past the body gate, ghidra between the gates, the rest nowhere"""
    between = (judge.TITLE_GATE + judge.BODY_GATE) / 2
    return [judge.BODY_GATE if d.startswith(godot.title) else between if d.startswith(ghidra.title) else 0 for d in docs]


real_scores, judge.scores = judge.scores, fake_scores
prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "s0", "cwd": project, "prompt": f"why does {elsewhere} fail to build"}
first = hooks.recall(prompt)["hookSpecificOutput"]["additionalContext"]
assert away.title in first and f"## {godot.title}" in first, first
assert f"- {ghidra.title} ({ghidra.slug})" in first and "ghidra 12 sits" not in first, "a title past the loose gate comes without its body"
assert hooks.recall(prompt) is None, "a folder, a body or a title came twice"
index.stamp_compacted(db, "s0", "")
again = hooks.recall(prompt)["hookSpecificOutput"]["additionalContext"]
assert away.title in again and f"## {godot.title}" in again, "not brought again after compaction"
for event in ("<task-notification>\n<summary>godot run finished</summary>\n</task-notification>", '<agent-message from="a1">\ngodot run finished\n</agent-message>', '<cross-session-message from="s9">\ngodot run finished\n</cross-session-message>'):
    assert hooks.recall({**prompt, "session_id": "s0c", "prompt": event}) is None, "a background event went to the judge"
queries = []
judge.scores = lambda query, docs: queries.append(query)
assert hooks.recall({**prompt, "session_id": "s0b", "prompt": "godot keeps hanging"}) is None, "something came by meaning without the judge"
reminded = f"<system-reminder>\nrecent folders {elsewhere}\n</system-reminder>\nwhat now"
assert hooks.recall({**prompt, "session_id": "s0d", "prompt": reminded}) is None, "a path in an app reminder counted as the user's"
assert "recent folders" not in queries[-1] and "what now" in queries[-1], queries[-1]
judge.scores = real_scores

tool = {"hook_event_name": "PostToolUse", "session_id": "s1", "cwd": project, "tool_name": "Read", "tool_input": {"file_path": f"{elsewhere}/src/main.cpp"}}
got = hooks.recall(tool)["hookSpecificOutput"]["additionalContext"]
assert "this session just reached it" in got and away.title in got and godot.title not in got, got
assert hooks.recall({**tool, "tool_input": {"command": f"cat {elsewhere.as_posix()}/README.md"}}) is None, "entered twice"
assert hooks.recall({**tool, "tool_input": {"command": "grep -rn godot hanging tests"}}) is None, "tool calls match by scope only"
assert hooks.recall({**tool, "tool_input": {"command": "mem save --type facts --title x"}}) is None
assert hooks.recall({**tool, "tool_input": {"file_path": f"{project}/facts/x.md"}}) is None

gate_exe = tmp / "mem-gate.exe"
sh("go", "build", "-o", str(gate_exe), ".", cwd=ROOT / "mem-gate")


def gate(payload):
    return subprocess.run([str(gate_exe)], input=json.dumps(payload), capture_output=True, text=True, check=True).stdout


bash_path = f"/{elsewhere.as_posix()[0].lower()}{elsewhere.as_posix()[2:]}/src"
gated = {**tool, "session_id": "g1", "tool_input": {"command": f"ls {bash_path}"}}
assert gate({**gated, "tool_input": {"command": "git status"}}) == ""
assert away.title in gate(gated), "the gate kept back a folder entry"
assert gate(gated) == "", "the gate let a reached folder through"
assert gate({**gated, "tool_input": {"file_path": f"{project}/facts/x.md"}}) == ""

away.path.write_text(away.path.read_text(encoding="utf-8") + "\nand cmake 3.30\n", encoding="utf-8")
index.index(db)
start = {"hook_event_name": "SessionStart", "session_id": "s2", "source": "startup", "cwd": project}
text = hooks.brief(start)["hookSpecificOutput"]["additionalContext"]
assert f"edit {away.slug}" in sh("git", "-C", str(bare), "log", "--oneline", "main").stdout, "an edit some other index call saw first never got committed"
sh("git", "-C", str(vault_dir), "commit", "-q", "--allow-empty", "-m", "offline")
assert git.unpushed() == 1 and index.health(db, project)["unpushed"] == 1, "a commit no push reached went uncounted"
git.push()
assert git.unpushed() == 0
assert "how to work" in text and fb.title in text and "open leftovers" in text and left.title in text and "health:" in text, text
assert f"- {ghidra.title} ({ghidra.slug})" in text and "ghidra 12 sits" not in text, "a global note without always comes as a title only"
assert away.title not in text, "the brief carries nothing from other folders"
judge.scores = fake_scores
fits = hooks.recall({**prompt, "session_id": "s2"})["hookSpecificOutput"]["additionalContext"]
assert ghidra.slug not in fits, "a title the brief listed came again"
assert ghidra.slug not in {r["slug"] for r in index.injected_rows(db, "s2")}, "a title only note counted as remembered"
judge.scores = real_scores
resumed = hooks.brief({**start, "source": "resume"})["hookSpecificOutput"]["additionalContext"]
assert fb.title not in resumed and left.title not in resumed, resumed
sub = hooks.brief({**start, "hook_event_name": "SubagentStart", "agent_id": "a1"})["hookSpecificOutput"]["additionalContext"]
assert "health:" not in sub and left.title in sub
after = hooks.brief({**start, "source": "compact"})["hookSpecificOutput"]["additionalContext"]
assert "before the squash" in after and godot.title in after, after

cli.set_done(left.slug)
assert index.list_notes(index.connect(vec=True), project, ("leftovers",)) == []
cli.forget_note(gpu.slug)
assert not gpu.path.exists() and index.connect().execute("select count(*) from notes where slug=?", (gpu.slug,)).fetchone()[0] == 0

log = sh("git", "-C", str(bare), "log", "--oneline", "main").stdout.splitlines()
assert any("save godot" in line for line in log) and any("done " in line for line in log) and any("forget " in line for line in log), log

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
json.dumps(pane)

moved = cli.save_note("projects", "panel sources", "old take", [], [], project)
cli.save_note("facts", "panel sources", "new take", [], [], project)
assert not moved.path.exists() and index.note_row(db, moved.slug)["path"].endswith(f"facts/{moved.slug}.md"), "a save under another type left two files"

for i in range(12):
    cli.save_note("feedback", f"stress note {i}", ("lorem " * 160).strip(), [], [], project)
text, shown, _ = hooks.brief_text(index.connect(vec=True), project)
lines = text.splitlines()
assert "health:" in text and "open leftovers" in text, text[-300:]
assert all(f"(stress-note-{i})" in text for i in range(12))
assert 0 < len(shown) < 13 and all(any(l.startswith("## ") and f"({s})" in l for l in lines) for s in shown), shown

if judge.MODEL.exists():
    docs = [hooks.doc_of(db, index.note_row(db, s)) for s in (godot.slug, away.slug)]
    real = judge.scores(hooks.query_of("godot keeps hanging when a test run never exits", ""), docs)
    assert real and real[0] >= judge.BODY_GATE > judge.TITLE_GATE > real[1], real

from mem import mcp_server  # noqa: E402

settings = tmp / "Claude-Data" / "app" / "Claude Extensions Settings"
settings.mkdir(parents=True)
(settings / f"{mcp_server.EXTENSION}.json").write_text('{"isEnabled": true}')
os.environ.update(LOCALAPPDATA=str(tmp), CLAUDE_CODE_ENTRYPOINT="claude-desktop")
assert mcp_server.extension_covers()
os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
assert not mcp_server.extension_covers()

def writable(remove, path, _):
    """git keeps its objects read only, which Windows refuses to delete"""
    os.chmod(path, stat.S_IWRITE)
    remove(path)


db.close()
gc.collect()
shutil.rmtree(tmp, onexc=writable)
print("all checks passed")
