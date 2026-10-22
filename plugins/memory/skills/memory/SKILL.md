---
name: memory
description: Claude's own memory, an Obsidian vault of notes with search, reminders and a learning loop. Load it whenever memory comes up, when the user says remember, forget, I told you this before, what was I doing, or asks about leftovers, lessons or the vault, when a brief or recall was injected and you want the rules behind it, when something worth keeping comes up mid task, and before a cleanup pass. Also load it in Chat and in cloud sessions, where no hooks run and you do the reminding yourself.
---

# Memory

The vault at `F:\claude-memory` (a private GitHub repo, `kurushimee/claude-memory`) holds one note per file in four folders, `facts`, `feedback`, `projects` and `leftovers`. The `mem` command indexes it and syncs it with GitHub, hooks push notes into Code and local Cowork sessions, and the `memory_*` MCP tools give the same memory as tools, listed as `mcp__Memory__memory_*` in the desktop app (the Memory extension) and `mcp__plugin_memory_memory__memory_*` in a terminal session, and loaded with ToolSearch when they show as deferred. Prefer the tools when they are listed, fall back to `mem` through Bash, and in a session with neither, see Working without hooks below.

## The point

Nothing here is automatic beyond indexing and reminding. What gets saved, what gets cleaned up and when, and what the policy below says are all yours to decide and to change. The system exists so your own work gets better over time, not only so facts survive a session. Treat every correction and every lesson as the most valuable thing to keep.

## Voice

Notes are written in the tumblr voice in full, the same as chat output. All lowercase, no period at the end of a paragraph, no colons, semicolons or em dashes, plain everyday words, short. This overrides the writing rule that files get normal capitalization. Titles too.

## The learning loop

- A correction from the user is a `feedback` note the moment it lands. Say what was wrong, what is right, and the situation it applies to, and tag it with words that name that situation so a search finds it when the situation comes back. The project's feedback and every feedback note tagged `always` are the first thing in every brief, so a correction that fits every task gets `always` and changes the next session, not only this one.
- A lesson you draw yourself goes the same way. Something you did that you would do differently, a way of working that turned out better, a thing that cost time.
- At every natural end of a task, and at the latest when calling `wrap_up`, ask three things. What did the user correct. What would I do differently. What is left open. Each answer is a note or nothing.
- Lessons about memory itself go in the Lessons section at the bottom of this file. A save that turned out to be noise, a recall that was useless, a search that missed and why, the user saying "I told you this before". When a lesson is clear enough, edit the policy above it in place, commit and push `F:\claude-memory-plugin`.
- The cleanup pass reads the feedback notes together. Ones that keep coming back get merged into one stronger note or promoted into this policy. Ones contradicted by newer feedback get retired with `memory_forget`. The health line counts corrections from the last seven days so you can see your own rate.
- Gaps in the system itself get fixed when they show up. A missing command, a search cut off that is clearly off, a path form the scope rules miss, these are a few lines in `F:\claude-memory-plugin`, fixed in session with `uv run python tests/check.py` passing, committed and pushed. A change under `plugins/` also bumps that plugin's version in its `plugin.json`, installed copies only refresh on a new version. A change to `mem-gate`, the Go program that answers the tool call hook and hands only real folder entries to `mem recall`, takes effect after `go install` in its folder. Anything bigger becomes a leftover tagged `memory`.

## Searching during a task

Search whenever the question "did I know something about this" comes up. That is at least

- on entering an area, a subsystem, a tool, a library, a file tree not touched yet this session
- on an error or surprising behaviour
- before picking an approach or making a design call
- when the user refers to something from before
- before writing a subagent brief, and paste the hits into that brief

`memory_search` (or `mem search <query>`) matches by parts of words and by meaning, so describe the thing rather than guessing exact words. Every answer has hits with bodies and a maybe list of titles. Open a maybe with `memory_show` (`mem show <slug>`) when the title looks like it matters. Each prompt also gets the notes in scope judged by meaning on the GPU. A note that clearly fits the prompt comes in whole and one that might fit comes in as a title, so open a recalled title when the task touches it. A tool call brings notes by folder only, so mid task a global note without `always` reaches the context only through a search.

## Saving

Save the moment it comes up, not at the end, since the end may never come (context squash, closed session). Save when

- the user says remember, always or never
- the user corrects you (feedback)
- a decision gets made for a reason that is not visible in the code
- a gotcha cost time
- a fact about the user, the machine or a project surfaces that a later session would need

Search first so an existing note gets updated instead of doubled. `memory_save(type, title, body, tags, links, project)` or `mem save --type T --title X --tags ... --links ... --project P` with the body on stdin. A saved note is indexed and pushed at once, so the rest of the session and every other host can recall it.

Do not save what the repo or git already records, one off trivia, or anything already in a note.

## Leftovers

A leftover is an open thread, unfinished work, something to come back to. Write one the moment you step away from a thread, and at the latest when calling `wrap_up`. Say what is done, what is not, where the files are, and what the next step is. Check the open leftovers before starting on something that might already have one (`mem search --type leftovers`). Mark it done with `memory_done` (`mem done <slug>`) when it is, and update the note when the state changes.

## Writing a note

One fact per note, short, in the voice above. The type is the folder. The slug comes from the title. Tags are a few words that name the situation (`godot`, `testing`, `review`, `writing`). Links are slugs of related notes, written as `[[slug]]` in the body or passed as `links`, so Obsidian draws the graph and search follows them one hop. The project is the git root of where the note applies, or the folder itself when it has no git, like `F:/radiance-cascades`, or `global` for anything about the user or the machine. A note covers its folder and everything under it. The brief at session start carries only the project's own notes and notes tagged `always`, so tag `always` only what fits every task in its scope, and it lists the other notes in scope as titles. The judge reads the title, the tags and the start of the body, so say up front what situation the note is for. The notes of another folder come in once, the first time a prompt or tool call reaches a path in it, and again after a squash. To change a note, edit the file or save again with the same title, `mem index` picks it up on the next hook and commits it.

## The cleanup pass

Read the health line in the brief. Do a pass when it shows hook errors, dupe pairs, conflicts, leftovers past 30 days, a pile of stale candidates, or more than 14 days since the last one. Do it at a natural pause in the current task, never mid edit, and in whatever session you are in.

1. `memory_check` (`mem check`) for the full picture.
2. Verify each open leftover against the project (git log, the files) and mark it done or update it.
3. Merge each dupe pair into one note and forget the other.
4. Merge each `*-conflict.md` into its note and delete the conflict file.
5. Verify or forget each stale candidate.
6. Read the feedback notes together, merge, promote or retire as in the learning loop.
7. Read `mem log`, fix the cause of each error in `F:\claude-memory-plugin`, run `uv run python tests/check.py`.
8. Add each injection that brought an unrelated note, and each note a search had to find that should have come in by itself, to `system/recall-eval.jsonl` in the vault. Those labeled cases set the gates in `mem/judge.py`. After adding cases or changing the judge, run `uv run python tests/recall_eval.py` and keep the body gate above every unrelated note.
9. Once a month, `uv lock --upgrade` in `F:\claude-memory-plugin` and the check again.
10. `claude plugin validate` on `plugins/memory` and `plugins/memory-pane`, `claude plugin test` on the pane, fix what they report.
11. Re-read this skill and tighten it.
12. Add a dated `## YYYY-MM-DD` entry to `system/log.md` in the vault saying what changed, the health line reads the date from it.
13. Commit and push both repos.

## Working without hooks

In Chat and in a Cowork session in the cloud nothing is pushed into the context, so you do what the hooks do.

- At the start of any conversation about work or a project, call `memory_brief`. With no project it lists the known projects, call it again with the right one, or with none for global.
- Call `memory_search` at the same moments as above, with you as the trigger.
- When a conversation has run long and earlier context may be gone, call `memory_brief` again.
- In a cloud session with no memory tools at all, clone the vault and install the command, then work with the cli, which pushes its own changes

```
git clone git@github.com:kurushimee/claude-memory.git ~/claude-memory
uvx --from git+https://github.com/kurushimee/claude-memory-plugin mem init ~/claude-memory
uvx --from git+https://github.com/kurushimee/claude-memory-plugin mem brief < /dev/null
```

If the clone is not possible either, say so once and go on.

## Lessons

- The length of a prompt says nothing about the effort the task behind it needs. A two word prompt can carry the biggest job of the day. Never scale attention, search or care by how much the user typed.
- A flat character cap on the brief cut it mid word in a project with ten long feedback notes, so the leftovers and the health line never arrived, and the cut notes still counted as injected, so recall never brought them back. Each section now has its own budget and only a note whose body is in the text counts as shown. Whatever is cut has to fail loud, in the health line or as titles, never silently.
- Over 231 labeled real cases, recall by keywords and vectors let 67 unrelated notes in on prompts and 42 on tool calls, and small cross encoders (MiniLM, Jina turbo, Qwen3 0.6B) reached zero unrelated notes only with a gate that let almost nothing related through. Qwen3-Reranker-4B in its ranking GGUF, asked whether the note is about the subject of the message, scored the 3 needed notes across 111 prompt cases at 0.50 or more and none of the 658 unrelated pairs above 0.36. The same model run as a chat model answering yes or no said yes to empty prompts like "continue". Tool call text carries too little meaning for any judge, so tool calls stay scope only.
- A Python hook costs about 130 ms per call before it does anything, too much for every tool call, so `mem-gate` in Go reads the scope list and the reached file in about 8 ms and starts `mem recall` only for a real first entry into a folder. The Bash tool adds about 100 ms to any process it spawns, so time hooks from PowerShell.
- The first CUDA run of llama.cpp on a GPU its prebuilt kernels don't cover compiles them for about 40 seconds, then the driver cache makes each load take 2 seconds. A llama-server whose parent was killed kept 6 GB of VRAM until killed by hand, so the judge puts it in a job object that Windows kills along with the hook.
- A PostCompact hook fired right after the squash brief and marked the brief's own notes as from before the squash, so the next prompt brought them again. The squash brief marks the old rows itself before it records its own, and nothing else runs on a squash. Task notifications and subagent reports also come in through UserPromptSubmit, often, so the judge skips them.
- `mem` is an editable install of `F:\claude-memory-plugin`, so every saved edit runs in the live hooks at once and a half done edit throws in `mem log`. Make multi file changes in a few quick edits and clear the errors they leave once the check passes.
