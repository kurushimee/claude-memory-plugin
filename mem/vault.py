import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

TYPES = ("facts", "rules", "projects", "leftovers")
BODY_MAX = 3000  # three bodies fit in one hook's room next to the rest
CONFIG = Path.home() / ".config" / "mem" / "vault"
MODELS = Path.home() / ".cache" / "mem" / "models"


def vault_path():
    override = os.environ.get("MEM_VAULT")
    if override:
        return Path(override)
    if not CONFIG.exists():
        raise SystemExit("no vault set, run: mem init <vault path>")
    return Path(CONFIG.read_text(encoding="utf-8").strip())


def set_vault(path):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(str(Path(path).resolve()), encoding="utf-8")


def mem_dir():
    d = vault_path() / ".mem"
    d.mkdir(exist_ok=True)
    return d


def log(text):
    with open(mem_dir() / "mem.log", "a", encoding="utf-8") as f:
        # the time of day lets an error be matched against what else ran then
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} {text.rstrip()}\n")


def today():
    return date.today().isoformat()


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:80].strip("-")
    return slug or "note"


def project_of(cwd):
    """the git root above cwd, else cwd itself"""
    if not cwd or "scratch-workspaces" in cwd:
        return "global"
    p = Path(cwd)
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d.as_posix()
    if p == Path.home() or p.parent == p:
        return "global"
    return p.as_posix()


def in_scope(note_project, project):
    """a note covers its folder and everything under it"""
    if note_project == "global":
        return True
    return (project.lower().rstrip("/") + "/").startswith(note_project.lower().rstrip("/") + "/")


INCIDENT = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (self|user)\b", re.M)


def incidents(body):
    """(date, who spotted it) for each incident line of a rule"""
    return INCIDENT.findall(body)


def section(body, word):
    """the paragraph of a note body that starts with word, like the why or the check of a rule"""
    for para in body.split("\n\n"):
        if para.startswith(word + " "):
            return para[len(word) + 1 :].strip()
    return ""


LINK = re.compile(r"\[\[([^\]|#]+)")


def links(body):
    return LINK.findall(body)


def slugs():
    return {p.stem for p in note_files()}


PATH = re.compile(r"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|(?<![\w.~/-])/[a-zA-Z]/)[^\s\"'`|;&<>()]*")


def paths_in(text):
    """windows paths and their git bash spelling like /f/x, as F:/x"""
    for p in PATH.findall(text):
        p = p.replace("\\", "/")
        yield p[1].upper() + ":" + p[2:] if p[0] == "/" else p


@dataclass
class Note:
    slug: str
    type: str
    title: str
    body: str = ""
    project: str = "global"
    created: str = field(default_factory=today)
    updated: str = field(default_factory=today)
    status: str = "active"
    tags: list = field(default_factory=list)
    when: list = field(default_factory=list)

    @property
    def path(self):
        return vault_path() / self.type / f"{self.slug}.md"

    @property
    def links(self):
        return links(self.body)

    def text(self):
        return f"{self.title}\n{' '.join(self.tags)}\n{self.body}"


FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)


def read_note(path):
    import yaml

    path = Path(path)
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = FRONT.match(raw)
    meta = yaml.safe_load(m.group(1)) if m else {}
    meta = meta if isinstance(meta, dict) else {}
    body = (m.group(2) if m else raw).strip()
    tags = meta.get("tags") or []
    return Note(
        slug=path.stem,
        type=path.parent.name,
        title=str(meta.get("title") or path.stem.replace("-", " ")),
        body=body,
        project=str(meta.get("project") or "global"),
        created=str(meta.get("created") or today()),
        updated=str(meta.get("updated") or today()),
        status=str(meta.get("status") or "active"),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [str(tags)],
        when=[str(w) for w in meta.get("when") or []],
    )


def write_note(note):
    import yaml

    meta = {
        "title": note.title,
        "project": note.project,
        "created": note.created,
        "updated": note.updated,
        "status": note.status,
        "tags": note.tags,
    }
    if note.when:
        meta["when"] = note.when
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=None)
    note.path.parent.mkdir(parents=True, exist_ok=True)
    note.path.write_text(f"---\n{front}---\n{note.body.strip()}\n", encoding="utf-8", newline="\n")
    return note.path


def note_files():
    root = vault_path()
    for t in TYPES:
        yield from sorted((root / t).glob("*.md"))


def find(slug):
    for t in TYPES:
        p = vault_path() / t / f"{slug}.md"
        if p.exists():
            return read_note(p)
    raise SystemExit(f"no note with slug {slug}")
