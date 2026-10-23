import subprocess

from . import vault

NET_TIMEOUT = 10


def git(*args, timeout=None):
    cmd = ["git", "-C", str(vault.vault_path()), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout}s")


def is_repo():
    return (vault.vault_path() / ".git").exists()


def has_remote():
    return is_repo() and git("remote").stdout.strip() != ""


def sync():
    if not has_remote():
        return
    if git("fetch", "-q", timeout=NET_TIMEOUT).returncode != 0:
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


def edited():
    """note files changed but not committed, read from git since any index call may have already seen them"""
    lines = git("status", "--porcelain", "--", *vault.TYPES).stdout.splitlines()
    return [vault.vault_path() / l[3:] for l in lines if l.endswith(".md")]


def commit(paths, message):
    if not is_repo():
        return
    git("add", "-A", "--", *[str(p) for p in paths])
    if git("diff", "--cached", "--quiet").returncode == 0:
        return
    git("commit", "-q", "-m", message)
    push()


def push():
    """a failed push leaves its commits for the next one, and health counts what is still unpushed"""
    if has_remote():
        git("push", "-q", timeout=NET_TIMEOUT)


def unpushed():
    if not has_remote():
        return 0
    r = git("rev-list", "--count", "@{u}..HEAD")
    return int(r.stdout) if r.returncode == 0 else 0
