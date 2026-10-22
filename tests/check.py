import json
import os
import shutil
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

from mem import cli, git, hooks, index, vault  # noqa: E402

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
fb = cli.save_note("feedback", "prompt length says nothing about effort", "a two word prompt can carry the biggest job of the day", ["effort"], [], "global")
assert godot.path.exists() and godot.path.read_text(encoding="utf-8").startswith("---\ntitle: godot runs")
assert vault.read_note(godot.path).links == ["one-gpu-job-at-a-time"]

db = index.connect(vec=True)
assert index.index(db) == ([], set())
assert db.execute("select count(*) from notes").fetchone()[0] == 4
assert index.embed(["check"]) is not None, "embedder unavailable, the vector checks need the model cached"
assert db.execute("select count(*) from vec").fetchone()[0] == 4

hits, maybe = index.search(db, "casca", project=project, vector=False)
assert left.slug in [r["slug"] for r in hits + maybe], "trigram miss"
hits, maybe = index.search(db, "the thing that stops godot hanging", project=project)
assert hits and hits[0]["slug"] == godot.slug, [r["slug"] for r in hits]
assert gpu.slug in [r["slug"] for r in hits + maybe], "link hop miss"
hits, maybe = index.search(db, "godot", project=project, type="leftovers", vector=False)
assert not hits or all(r["type"] == "leftovers" for r in hits)
listed = index.list_notes(db, project, ("leftovers",))
assert [r["slug"] for r in listed] == [left.slug]

prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": project, "prompt": "godot keeps hanging in the tests"}
first = hooks.recall(prompt)["hookSpecificOutput"]["additionalContext"]
assert "godot runs must end themselves" in first and "maybe relevant" in first, first
second = hooks.recall(prompt)
assert second is None or "## godot runs" not in second["hookSpecificOutput"]["additionalContext"]
hooks.compacted({"session_id": "s1"})
third = hooks.recall(prompt)["hookSpecificOutput"]["additionalContext"]
assert "godot runs must end themselves" in third

tool = {"hook_event_name": "PostToolUse", "session_id": "s1", "cwd": project, "tool_name": "Read", "tool_input": {"file_path": "F:/proj/src/cascade_probe.gd"}}
assert hooks.keywords(tool["tool_input"]) == "proj cascade probe"
got = hooks.recall(tool)["hookSpecificOutput"]["additionalContext"]
assert left.slug in got, got
assert hooks.recall({**tool, "tool_input": {"command": "mem save --type facts --title x"}}) is None
assert hooks.recall({**tool, "tool_input": {"file_path": f"{project}/facts/x.md"}}) is None

start = {"hook_event_name": "SessionStart", "session_id": "s2", "source": "startup", "cwd": project}
text = hooks.brief(start)["hookSpecificOutput"]["additionalContext"]
assert "how to work" in text and fb.title in text and "open leftovers" in text and left.title in text and "health:" in text, text
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
assert report["notes"] == report["indexed"] == 4 and report["health"]["conflicts"] == 1, (report["health"], report["log_tail"])
pane = cli.pane("s2", project)
assert set(pane) == {"project", "vault", "health", "leftovers", "injected", "counts"} and pane["counts"]["recalled"] > 0
json.dumps(pane)

db.close()
shutil.rmtree(tmp, ignore_errors=True)
print("all checks passed")
