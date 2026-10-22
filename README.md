# claude-memory-plugin

Memory for Claude on an Obsidian vault. The `mem` command indexes the vault with sqlite-vec and a local bge-small embedder, the `memory` plugin's hooks remind Claude of notes as it works and its MCP server gives Claude the memory as tools, and the `memory-pane` plugin draws a pane beside the chat in the Code tab.

## Install

The command, on the machine that holds the vault

```
uv tool install --python 3.13 git+https://github.com/kurushimee/claude-memory-plugin
mem init <vault folder>
mem index
```

The plugins, from the Plugins page of the desktop app or claude.ai, add the marketplace `kurushimee/claude-memory-plugin` and turn on `memory`, plus `memory-pane` for the Code tab. From a terminal instead

```
claude plugin marketplace add kurushimee/claude-memory-plugin
claude plugin install memory@claude-memory
claude plugin install memory-pane@claude-memory
```

A plugin turned on for the account shows up in Code as `memory@synced`. A copy installed from the terminal next to it makes every hook run twice, so remove that one with `claude plugin uninstall memory@claude-memory`.

The Chat tab needs the MCP server as a desktop extension, built with

```
npx @anthropic-ai/mcpb pack mcpb memory.mcpb
```

and installed from Settings, Extensions. If the app refuses the bundle, open Settings, Developer, Edit Config and add the same server by hand

```
{ "mcpServers": { "memory": { "command": "<home>/.local/bin/mem.exe", "args": ["mcp"] } } }
```

A cloud session clones the vault and runs the command through uvx, the memory skill has the lines.

## Checks

```
uv run python tests/check.py
claude plugin validate plugins/memory
claude plugin validate plugins/memory-pane
claude plugin test plugins/memory-pane
```
