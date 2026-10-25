import json
import os
from pathlib import Path

from mcp.server import MCPServer

from . import cli, hooks, index, vault

EXTENSION = "local.mcpb.kurushimee.memory"

mcp = MCPServer(
    "memory",
    instructions=(
        "claude's own memory vault. call memory_brief at the start of any work or project talk, "
        "memory_search when entering an area, hitting an error, making a design call or when the user "
        "refers to something from before, memory_save the moment something worth keeping comes up"
    ),
)


@mcp.tool()
def memory_brief(project: str | None = None) -> str:
    """the brief for a project, the rules on how to work, open leftovers, project notes and health. with no project it lists the known projects and the global brief"""
    db = index.connect(vec=True)
    index.index(db)
    if project is None:
        projects = [r[0] for r in db.execute("select distinct project from notes where project!='global' order by project")]
        text = hooks.brief_text(db, "global")[0]
        return "known projects: " + (", ".join(projects) or "none yet") + "\n\n" + text
    text = hooks.brief_text(db, project)[0]
    return text


@mcp.tool()
def memory_search(query: str, project: str | None = None, type: str | None = None, k: int = 8) -> str:
    """hybrid search over the vault by words and by meaning. hits come with their body, a maybe list follows with titles worth opening. type is one of facts, rules, projects, leftovers"""
    db = index.connect(vec=True)
    index.index(db)
    hits, maybe = index.search(db, query, project=project, type=type, k=k)
    return cli.render_search(db, hits, maybe)


@mcp.tool()
def memory_show(slug: str) -> str:
    """the full note for a slug"""
    note = vault.find(slug)
    return note.path.read_text(encoding="utf-8")


@mcp.tool()
def memory_save(
    type: str, title: str, body: str, tags: list[str] | None = None, links: list[str] | None = None, project: str | None = None
) -> str:
    """save one memory. type is facts, projects or leftovers, mistakes go through memory_lesson. project is a git root like F:/radiance-cascades or global. an existing slug gets its body replaced"""
    note = cli.save_note(type, title, body, tags or [], links or [], project or "global")
    return f"saved {note.slug} at {note.path.as_posix()}"


@mcp.tool()
def memory_lesson(
    what: str,
    by: str,
    project: str = "global",
    rule: str | None = None,
    new: str | None = None,
    sharpen: str | None = None,
    why: str | None = None,
    check: str | None = None,
    when: list[str] | None = None,
    scope: str = "global",
) -> str:
    """log a mistake. by is self when you spotted it, user when the user had to. call it first with only what, by and project (where it happened) to see the closest rules, then again with rule set to the slug it is another incident of, adding sharpen, check or when if the rule missed this case, or with new set to the title of a new general rule plus why, check, when (Tool:regex triggers) and scope (global or the project it holds in)"""
    from . import rules

    return rules.lesson(what, by, project, rule, new, sharpen, why, check, when or [], scope)


@mcp.tool()
def memory_done(slug: str) -> str:
    """mark a leftover done"""
    cli.set_done(slug)
    return f"done {slug}"


@mcp.tool()
def memory_forget(slug: str) -> str:
    """delete a note for good"""
    cli.forget_note(slug)
    return f"forgot {slug}"


@mcp.tool()
def memory_check() -> str:
    """full health report of the vault and the setup"""
    return cli.render_check(cli.check_report())


def extension_covers():
    """the desktop app hands its own memory extension to code tab sessions, the plugin's copy would double every tool"""
    appdata = os.environ.get("LOCALAPPDATA")
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") != "claude-desktop" or not appdata:
        return False
    found = Path(appdata).glob(f"Claude-Data/*/Claude Extensions Settings/{EXTENSION}.json")
    return any(json.loads(p.read_text(encoding="utf-8")).get("isEnabled") for p in found)


def serve():
    (MCPServer("memory") if extension_covers() else mcp).run()
