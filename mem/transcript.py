"""Reads the transcript the app writes for a session, from the end, since a long session grows it to tens of
megabytes"""

import json
import re

TAIL = 256 * 1024
REPLY_CHARS = 800
NO_REPLY = "No response requested."
INTERRUPT = "[Request interrupted by user"
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def entries(path, tail=TAIL):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - tail))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return []
    out = []
    for raw in lines:
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def text_of(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def typed(entry):
    """a prompt the user typed, not a tool result, a task notification or a message from another agent"""
    return entry.get("type") == "user" and (entry.get("origin") or {}).get("kind") == "human"


def said(entry):
    """what the user typed in this entry, as a prompt or as a message sent while a turn ran"""
    if typed(entry):
        return text_of(entry)
    queued = entry.get("attachment") or {}
    if queued.get("type") == "queued_command" and (queued.get("origin") or {}).get("kind") == "human":
        return queued.get("prompt") if isinstance(queued.get("prompt"), str) else ""
    return ""


def last_reply(path):
    """the end of the assistant's last reply, so the judge knows what a short prompt is about"""
    for entry in reversed(entries(path)):
        if entry.get("type") != "assistant":
            continue
        reply = text_of(entry).strip()
        if reply and reply != NO_REPLY:
            return reply[-REPLY_CHARS:]
    return ""


def last_turn(path):
    """the entries between the two latest prompts the user typed. The prompt being answered now may already be
    written, with nothing from the assistant after it yet"""
    turn = []
    for entry in reversed(entries(path)):
        if typed(entry):
            if any(e.get("type") == "assistant" for e in turn):
                break
            turn = []
            continue
        turn.append(entry)
    return turn


def stops(path):
    """whether the user interrupted the last turn, and how many of its tool calls they denied"""
    turn = last_turn(path)
    interrupted = any(e.get("type") == "user" and INTERRUPT in text_of(e) for e in turn)
    denied = sum(1 for e in turn if e.get("toolDenialKind") == "user-rejected")
    return interrupted, denied


def user_messages(path):
    """what the user typed in this session, oldest first, read from the whole file"""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                if '"kind":"human"' not in raw:
                    continue
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                if text := REMINDER.sub("", said(entry)).strip():
                    out.append(text)
    except (OSError, TypeError):
        return []
    return out
