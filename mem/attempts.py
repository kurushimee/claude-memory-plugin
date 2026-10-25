"""The questions sent to subagents in each project and what came back, in journal/ in the vault, so a question gets
seen before it goes out again, in the same session after a squash or in any other"""

import json
import re
from datetime import datetime

from . import index, vault

DAYS = 30
# over 923 launches since 2026-10-02, every pair of descriptions sharing this much of their words and launched ten or
# more minutes apart asked the same thing again, while siblings of one batch shared at most two thirds
SAME = 0.75
SHOWN = 3
PROMPT = 300
ANSWER = 500


def journal_path(project):
    return vault.vault_path() / "journal" / f"{vault.slugify(project)}.jsonl"


def read(project):
    """the questions oldest first, each with the answer that came back for it, if any"""
    path = journal_path(project)
    if not path.exists():
        return []
    asked, answers = [], {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if "question" in entry:
            asked.append(entry)
        elif entry.get("agent"):
            answers[entry["agent"]] = entry.get("answer", "")
    for entry in asked:
        entry["answer"] = answers.get(entry.get("agent")) or entry.get("answer", "")
    return asked


def append(project, entry):
    """one line per write, so parallel sessions never overwrite each other"""
    path = journal_path(project)
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ask(project, session, agent, question, prompt, answer=""):
    now = datetime.now().isoformat(timespec="minutes")
    append(project, {"at": now, "session": session, "agent": agent, "question": question, "prompt": prompt[:PROMPT], "answer": answer[:ANSWER]})


def answer(project, agent, text):
    """only the first answer to a question in the journal, so a squash, which stops like a subagent, and the closing
    line after a hand back stay out"""
    if agent and text and any(e["agent"] == agent and not e["answer"] for e in read(project)):
        append(project, {"agent": agent, "answer": text[:ANSWER]})


def overlap(a, b):
    wa, wb = (set(re.findall(r"[a-z0-9]+", t.lower())) for t in (a, b))
    return len(wa & wb) / len(wa | wb) if wa | wb else 0


def asked_before(project, question):
    """the latest questions in this project that ask the same thing, newest first"""
    recent = [e for e in read(project) if index.days_ago(e["at"]) <= DAYS]
    return [e for e in reversed(recent) if overlap(e["question"], question) >= SAME][:SHOWN]


def of_session(project, session):
    return [e for e in read(project) if e.get("session") == session]


def line(entry, chars=200):
    came = f"came back {' '.join(entry['answer'].split())[:chars]}" if entry["answer"] else "never came back or is still out"
    return f"- {entry['at'].replace('T', ' ')} {entry['question']}, {came}"
