# claude-memory-plugin

Memory for Claude on an Obsidian vault. The `mem` command indexes the vault with sqlite-vec and a local bge-small embedder, the `memory` plugin's hooks give Claude an index of its memory at every start and the notes a prompt is about, its MCP server gives Claude the memory as tools, and the `memory-pane` plugin draws a pane beside the chat in the Code tab.

## Install

The command, on the machine that holds the vault

```
uv tool install --python 3.13 git+https://github.com/kurushimee/claude-memory-plugin
go install github.com/kurushimee/claude-memory-plugin/mem-gate@latest
mem init <vault folder>
mem index
```

Prompts are also matched to notes by meaning on an NVIDIA GPU. That needs both `win-cuda-12.4-x64` zips of llama.cpp release b11806 unpacked into `~/.cache/mem/llama/bin` and the reranker model next to it. Without them a prompt brings only the notes of the folders it names.

```
curl -L -o ~/.cache/mem/llama/qwen3-reranker-4b-q4_k_m.gguf https://huggingface.co/gorse-io/Qwen3-Reranker-4B-GGUF/resolve/main/Qwen3-Reranker-4B-Q4_K_M.gguf
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
