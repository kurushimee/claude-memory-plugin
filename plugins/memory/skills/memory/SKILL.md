---
name: memory
description: Claude's own memory, an Obsidian vault of notes and rules with search, reminders and a learning loop. Load it whenever memory comes up, when the user says remember, forget, I told you this before, what was I doing, or asks about leftovers, lessons, rules or the vault, when a brief, a recall or a cue was injected and you want the rules behind it, before logging a lesson the first time in a session, when something worth keeping comes up mid task, and before a cleanup pass. Also load it in Chat and in cloud sessions, where no hooks run and you do the reminding yourself.
---

# Memory

The vault at `F:\claude-memory` (a private GitHub repo, `kurushimee/claude-memory`) holds one note per file in four folders, `facts`, `rules`, `projects` and `leftovers`, plus `journal`, the questions sent to subagents per project. The `mem` command indexes it and syncs it with GitHub, hooks push notes, rules and cues into Code and local Cowork sessions, and the `memory_*` MCP tools give the same memory as tools, listed as `mcp__Memory__memory_*` in the desktop app (the Memory extension) and `mcp__plugin_memory_memory__memory_*` in a terminal session, and loaded with ToolSearch when they show as deferred. Prefer the tools when they are listed, fall back to `mem` through Bash, and in a session with neither, see Working without hooks below.

## The point

Nothing here is automatic beyond indexing, reminding and cueing. What gets saved, what gets logged as a lesson, what gets cleaned up and what the policy below says are all yours to decide and to change. The system exists so your own work gets better over time and no mistake happens the same way twice, not only so facts survive a session.

## Voice

Notes and rules are written in the tumblr voice in full, the same as chat output. All lowercase, no period at the end of a paragraph, no colons, semicolons or em dashes, plain everyday words, short. This overrides the writing rule that files get normal capitalization. Titles too.

## The learning loop

A rule in `rules/` is one general behavior grown out of real mistakes. Its title is the rule itself. Its body says why, gives the check that catches the mistake, and lists the incidents behind it, one line each with the date, who spotted it and where. Its `when` triggers name the tool calls where it matters. Every rule in scope is one line in the brief, a prompt gets the rules the last turn's calls brought up plus the ones closest in meaning to the message, and `mem-gate` puts a rule with its check next to the result of any call one of its triggers fits, once per turn.

- Log a mistake the moment it shows, whoever spotted it. `mem lesson "what went wrong" --by self` when you caught it, from a failed call, a result that looks wrong, a cue, a rerun, a second try. `--by user` when the user had to point it out, which the line on every prompt and on every message sent mid turn asks for first. The first call lists the closest rules with their slugs. Then strengthen the one that covers it with `--rule <slug>`, or write a new one with `--new "<title>" --why "..." --check "..." --when "Tool:regex"`, plus `--scope <project>` when it only holds there. `memory_lesson` does the same as a tool.
- Write the general behavior, never the one case. A tone curve that passed a bounds check while it clipped highlights is a case of looking at the real result before calling it done, so it goes in as an incident of that rule, not as a rule of its own. A new rule only when no rule covers the behavior. The caps, 20 global rules and 15 per project, make the rulebook merge instead of grow.
- A rule the user had to remind you of did not catch the case in time, so a `--by user` lesson on it also sharpens its title (`--sharpen`), adds a sentence to its check (`--check`) or adds a trigger at the call where it would have caught it (`--when`), in the same call, and is refused without one. A new trigger prints the recent calls it fits. Narrow its regex by hand when one of them is a call the rule has nothing to say about, since a cue that comes for nothing teaches skipping cues.
- A lesson about a tool, a script or a harness also gets that code fixed in the same turn, a watchdog in the harness, a check in the script, so the mistake can't happen the same way again.
- The cues next to tool results say when to look. A failed call, a call that already failed this turn, the fifth edit of one file, a turn past 5, 15 and 30 minutes, a message the user sent mid turn, and on the next prompt an interrupt or a denied call. Each one points at a real result, so act on it and log what it turns up.
- A trigger is `Tool:regex`. The tool part is matched against the whole tool name, MCP tools included, like `mcp__ccd_turn__wrap_up:.` for the end of every turn. The regex is matched against the call's text, the tool name plus its path, pattern and command, ignoring case. Go's RE2 runs them, so no lookaround and no backreferences.
- At every natural end of a task, and at the latest when calling `wrap_up`, ask what you would do differently and what is left open. The first is a lesson or nothing, the second a leftover or nothing.
- The health line counts lessons this week, how many the user spotted and how many were repeats of a rule that already had an incident. Both should fall to zero.
- Lessons about how memory itself works, a save that turned out to be noise, a recall that was useless, a cue that came at the wrong time, a search that missed and why, are facts saved with project `F:/claude-memory-plugin`, so they come up when working on it. When one is clear enough, edit the policy here in place, commit and push `F:\claude-memory-plugin`.
- Gaps in the system itself get fixed when they show up. A missing command, a cut that is clearly off, a path form the scope rules miss, these are a few lines in `F:\claude-memory-plugin`, fixed in session with `uv run python tests/check.py` passing, committed and pushed. A change under `plugins/` also bumps that plugin's version in its `plugin.json`, installed copies only refresh on a new version. A change to `mem-gate`, the Go program that answers the tool call hooks with the cues and hands only real folder entries to `mem recall`, takes effect after `go install` in its folder. `mem` is an editable install of `F:\claude-memory-plugin`, so every saved edit runs in the live hooks at once and a half done edit throws in `mem log`. Make big changes in a worktree, run the check there, and merge once it passes. Anything bigger becomes a leftover tagged `memory`.

## Searching during a task

Search whenever the question "did I know something about this" comes up. That is at least

- on entering an area, a subsystem, a tool, a library, a file tree not touched yet this session
- on an error or surprising behaviour
- before picking an approach or making a design call
- when the user refers to something from before
- before writing a subagent brief, and paste the hits into that brief

`memory_search` (or `mem search <query>`) matches by parts of words and by meaning, so describe the thing rather than guessing exact words. Every answer has hits with bodies and a maybe list of titles. Open a maybe with `memory_show` (`mem show <slug>`) when the title looks like it matters. Each prompt also gets the facts, projects and leftovers in scope judged by meaning on the GPU. Sessions take turns on it, and a judge short on time reads the notes closest in meaning first and leaves the rest for the next prompt. A note that clearly fits the prompt comes in whole and one that might fit comes in as a title, so open a recalled title when the task touches it. A tool call brings notes by folder only, so mid task a global note without `always` reaches the context only through a search. An Agent call gets back the questions already asked in this project that share most of its description's words, with what came back, and the brief after a squash lists the ones asked this session.

## Saving

Save the moment it comes up, not at the end, since the end may never come (context squash, closed session). Save when

- the user says remember, always or never
- a decision gets made for a reason that is not visible in the code
- a gotcha cost time
- a fact about the user, the machine or a project surfaces that a later session would need

A mistake, yours or one the user points out, goes through `mem lesson` instead. Search first so an existing note gets updated instead of doubled. `memory_save(type, title, body, tags, links, project)` or `mem save --type T --title X --tags ... --links ... --project P` with the body on stdin. A saved note is indexed and pushed at once, so the rest of the session and every other host can recall it.

Do not save what the repo or git already records, one off trivia, or anything already in a note.

## Leftovers

A leftover is an open thread, unfinished work, something to come back to. Write one the moment you step away from a thread, and at the latest when calling `wrap_up`. Say what is done, what is not, where the files are, and what the next step is. Check the open leftovers before starting on something that might already have one (`mem search --type leftovers`). Mark it done with `memory_done` (`mem done <slug>`) when it is, and update the note when the state changes.

## Writing a note

One subject per note, in the voice above, with a body under 3,000 characters so three fit in one hook's room, which `mem save` enforces and a cue flags after a direct edit. Every word of a note gets read whenever it comes up, so it holds only what a later task needs and can't get faster another way.

- The title is the claim itself, so the note can be judged without opening it.
- Write what holds now and why, never how it got there. No history, no commit or session narration, no "as of", "uncommitted" or "now", no numbers that a newer measurement replaced. When the state changes, rewrite the note to the new state.
- Keep the reason that stops a later session from undoing it. A rejected approach stays as one line with why it failed, and a choice the user made says so.
- Leave out what the repo's own docs, the code, git or a rule already say, and link to it or name the file instead. A project's CLAUDE.md loads by itself in every session there.
- Link only to notes that exist, `mem save` refuses others.

The type is the folder. The slug comes from the title. Tags are a few words that name the situation (`godot`, `testing`, `review`, `writing`). Links are slugs of related notes, written as `[[slug]]` in the body or passed as `links`, so Obsidian draws the graph and search follows them one hop. The project is the git root of where the note applies, or the folder itself when it has no git, like `F:/radiance-cascades`, or `global` for anything about the user or the machine. A note covers its folder and everything under it. The brief at session start carries every rule in scope as a line, then the project's own notes and notes tagged `always`, and it lists the other notes in scope as titles. The whole brief stays under the 10,000 characters the app cuts hook output at, and whatever doesn't fit is named by count. The judge reads the title, the tags and the start of the body, so say up front what situation the note is for. The notes of another folder come in once, the first time a prompt or tool call reaches a path in it, and again after a squash. To change a note, edit the file or save again with the same title, `mem index` picks it up on the next hook and commits it. A rule changes through `mem lesson`, or by editing its file when two rules get merged.

## The cleanup pass

Read the health line in the brief. Do a pass when it shows hook errors, unpushed commits, dupe pairs, conflicts, dead links, bodies over the cap, leftovers past 30 days, a pile of stale candidates, repeats of a rule, or more than 14 days since the last one. Do it at a natural pause in the current task, never mid edit, and in whatever session you are in.

1. `memory_check` (`mem check`) for the full picture.
2. Verify each open leftover against the project (git log, the files) and mark it done or update it.
3. Merge each dupe pair into one note and forget the other.
4. Merge each `*-conflict.md` into its note and delete the conflict file.
5. Verify or forget each stale candidate.
6. Read in full each note `mem check` lists as behind the code, against the files it names, and each note saved or edited since the last pass (`git log --since` in the vault). Fix in place what breaks the rules under Writing a note, a state the repo has moved past, two notes giving different numbers for one thing, a note in the wrong type or scope, and the dead links and long bodies `mem check` lists. Nothing a later task needs gets cut, only how it is said or where it lives.
7. Read the rules together (`mem search --type rules`). Merge two that say the same thing into one, with both incident lists. Tighten a check that doesn't cover every incident under it, by editing the file. Narrow a trigger whose examples in `mem check` are calls its rule has nothing to say about. Sharpen a rule whose incidents keep coming, its check or its triggers missed them. Retire one that newer incidents contradict with `memory_forget`.
8. Read `mem log`, fix the cause of each error in `F:\claude-memory-plugin`, run `uv run python tests/check.py`. A failed fetch or push is not logged, the next push retries it, so unpushed commits that stay across sessions mean `git push` in the vault keeps failing. Run it by hand and fix what it says.
9. Add each injection that brought an unrelated note, and each note a search had to find that should have come in by itself, to `system/recall-eval.jsonl` in the vault. Those labeled cases set the gates in `mem/judge.py`. Point each label `mem check` lists as gone at the note that took over. Label a note moved to `global` for the cases of its new scope, since a global note reaches a prompt only through the judge. After adding cases, changing the judge, or retitling, rescoping or forgetting a note, run `uv run python tests/recall_eval.py`. Keep every needed note at the body gate and every unrelated one under it, and when the judge misses a note, reword its title or opening.
10. Once a month, `uv lock --upgrade` in `F:\claude-memory-plugin` and the check again.
11. `claude plugin validate` on `plugins/memory` and `plugins/memory-pane`, `claude plugin test` on the pane, fix what they report.
12. Re-read this skill and tighten it.
13. Add an entry headed `## YYYY-MM-DD HH:MM` to `system/log.md` in the vault saying what changed. The health line reads the date from it and counts only the hook errors logged after that time, so every error before it has to be fixed by then.
14. Commit and push both repos.

## Working without hooks

In Chat and in a Cowork session in the cloud nothing is pushed into the context, so you do what the hooks do.

- At the start of any conversation about work or a project, call `memory_brief`. With no project it lists the known projects, call it again with the right one, or with none for global.
- Call `memory_search` at the same moments as above, with you as the trigger.
- Call `memory_lesson` the moment the user points out a mistake or you catch one.
- When a conversation has run long and earlier context may be gone, call `memory_brief` again.
- In a cloud session with no memory tools at all, clone the vault and install the command, then work with the cli, which pushes its own changes

```
git clone git@github.com:kurushimee/claude-memory.git ~/claude-memory
uvx --from git+https://github.com/kurushimee/claude-memory-plugin mem init ~/claude-memory
uvx --from git+https://github.com/kurushimee/claude-memory-plugin mem brief < /dev/null
```

If the clone is not possible either, say so once and go on.
