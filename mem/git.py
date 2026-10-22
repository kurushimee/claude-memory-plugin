import subprocess

from . import vault


def git(*args):
    return subprocess.run(
        ["git", "-C", str(vault.vault_path()), *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def is_repo():
    return (vault.vault_path() / ".git").exists()


def has_remote():
    return is_repo() and git("remote").stdout.strip() != ""


def sync():
    if not has_remote():
        return
    if git("fetch", "-q").returncode != 0:
        vault.log("fetch failed, working offline")
        return
    if git("merge", "--no-edit", "-q", "origin/main").returncode != 0:
        keep_both()
    push()


def keep_both():
    files = git("diff", "--name-only", "--diff-filter=U").stdout.split()
    if not files:
        git("merge", "--abort")
        vault.log("merge failed with no conflicted files, aborted")
        return
    for f in files:
        theirs = git("show", f"origin/main:{f}")
        if theirs.returncode == 0:
            conflict = f[:-3] + "-conflict.md"
            (vault.vault_path() / conflict).write_text(theirs.stdout, encoding="utf-8", newline="\n")
            git("add", "--", conflict)
        git("checkout", "--ours", "--", f)
        git("add", "--", f)
    git("commit", "-q", "-m", "merge remote, conflicts kept beside")
    vault.log("merge conflicts kept beside: " + " ".join(files))


def commit(paths, message):
    if not is_repo():
        return
    git("add", "-A", "--", *[str(p) for p in paths])
    if git("diff", "--cached", "--quiet").returncode == 0:
        return
    git("commit", "-q", "-m", message)
    push()


def push():
    if not has_remote():
        return
    r = git("push", "-q")
    if r.returncode != 0:
        vault.log("push failed: " + r.stderr.strip()[-200:])
