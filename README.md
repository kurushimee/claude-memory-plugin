# claude-memory-plugin

Memory for Claude on an Obsidian vault. The `mem` command indexes the vault with sqlite-vec and fastembed, the `memory` plugin's hooks remind Claude of notes as it works and its MCP server gives Claude the memory as tools, and the `memory-pane` plugin draws a pane beside the chat in the Code tab.

## Install

The command, on the machine that holds the vault

```
uv tool install --python 3.13 git+https://github.com/kurushimee/claude-memory-plugin
mem init <vault folder>
mem index
```

The plugins, from the Plugins page of the desktop app or claude.ai, add the marketplace `kurushimee/claude-memory-plugin` and turn on `memory`, plus `memory-pane` for the Code tab. From a terminal session

```
/plugin install memory --marketplace kurushimee/claude-memory-plugin
```

The Chat tab needs the MCP server as a desktop extension, built with

```
npx @anthropic-ai/mcpb pack mcpb memory.mcpb
```

and installed from Settings, Extensions.
