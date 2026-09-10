<p align="center">
  <h1 align="center">🤖 TaiSang</h1>
</p>

<p align="center">
  <a href="./README.md">简体中文</a> | <b>English</b>
</p>

> **Your private agent · Learns your habits**
>
> A personal AI agent that summarizes your habits — reads and writes code, runs commands, calls tools, and learns your preferences and workflow along the way.

**Status:** v0.1 — REPL + Web UI dual entry, with Skill system + multi-agent scheduling + MCP client + user profile

---

## 🚀 Quick Start

### Install

```bash
pip install -e ".[web,dev]"
```

### Configure LLM

Supports any OpenAI-compatible endpoint (DeepSeek / Kimi / OpenAI / self-hosted ollama, etc.).

**Option 1:** `~/.taisang/settings.json`

```json
{"llm": {"base_url": "https://api.deepseek.com", "api_key": "sk-xxx", "model": "deepseek-chat"}}
```

**Option 2:** Environment variables

```bash
export TAISANG_LLM_BASE_URL=https://api.deepseek.com
export TAISANG_LLM_API_KEY=sk-xxx
export TAISANG_LLM_MODEL=deepseek-chat
```

### Run

```bash
# Web UI (auto-opens browser)
taisang web

# Specify working directory
taisang web --repo ~/repos/my-project

# CLI REPL
taisang chat
taisang chat --repo ~/repos/my-project
```

### First Run in 3 Steps

1. **Configure LLM key** — open the Web UI, click the ⚙️ button in the top-right corner, fill in model / api_key / base_url, and save. Takes effect immediately.
2. **Import project** — click the `+` button on the left of the input box → "导入项目" → pick your repo in the system directory picker. It becomes the session's working directory.
3. **Start chatting** — state your goal in natural language; the agent invokes tools on its own to read, edit, and run code.

---

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TaiSang                                     │
│                                                                     │
│   ┌──────────────┐         ┌──────────────────────────────────┐    │
│   │   CLI REPL   │         │            Web UI                │    │
│   │ taisang chat │         │   Vue 3.5 + Vite + TDesign       │    │
│   └──────┬───────┘         │  Sidebar / ChatView / ConfigModal│    │
│          │                 └──────────────┬───────────────────┘    │
│          │                                │ SSE (15 AgentEvent)    │
│          │                                │                        │
│          └────────────┬───────────────────┘                        │
│                       ▼                                            │
│   ┌───────────────────────────────────────────────────────────┐   │
│   │        Agent Core (main loop, per-iteration order)         │   │
│   │                                                            │   │
│   │   ┌─────────────────────────────────────────────────┐     │   │
│   │   │  ① Context Management (3 gates, pre-LLM)        │     │   │
│   │   │   • tool-result-budget → spill large to disk    │     │   │
│   │   │   • autocompact        → LLM summary compress   │     │   │
│   │   │   • session memory     → long-term, zero inject │     │   │
│   │   └────────────────────┬────────────────────────────┘     │   │
│   │                        ▼                                  │   │
│   │   ┌─────────────────────────────────────────────────┐     │   │
│   │   │  ② LLM call (chat_stream)                        │     │   │
│   │   │     ↓ produces text / reasoning / tool_calls     │     │   │
│   │   └────────────────────┬────────────────────────────┘     │   │
│   │                        ▼                                  │   │
│   │   ┌─────────────────────────────────────────────────┐     │   │
│   │   │  ③ Tool execution (ToolRegistry)                 │     │   │
│   │   │     6 built-in: Read/Grep/Glob/Edit/Write/Bash   │     │   │
│   │   │     ┌─────────┐ ┌─────────┐ ┌─────────┐          │     │   │
│   │   │     │ Skill   │ │ Agent   │ │  MCP    │ ← 3 ext  │     │   │
│   │   │     │ Tool    │ │ Tool    │ │  Tool   │          │     │   │
│   │   │     └────┬────┘ └────┬────┘ └────┬────┘          │     │   │
│   │   │          │          │           │                │     │   │
│   │   │     ┌────▼────┐ ┌───▼─────┐ ┌───▼──────────┐      │     │   │
│   │   │     │ Skills  │ │ Agents  │ │ MCP Manager  │      │     │   │
│   │   │     │ 3-source│ │ 4 built │ │ stdio + sse  │      │     │   │
│   │   │     └─────────┘ └─────────┘ └──────────────┘      │     │   │
│   │   └────────────────────┬────────────────────────────┘     │   │
│   │                        │ observation                       │   │
│   │                        └──────┐                            │   │
│   │                               │ next iter → back to ①      │   │
│   └───────────────────────────────┼────────────────────────────┘   │
│                                   │                                │
│                       LLM Client (any OpenAI-compatible)           │
│            DeepSeek / Kimi / OpenAI / Ollama / MockLLM             │
│                                                                     │
│   ┌───────────────────────────────────────────────────────────┐   │
│   │      Personalization (injected across the loop)            │   │
│   │  • user_profile  — learns your stack / style / comms / env│   │
│   │  • TodoWrite     — task tracking, sticky progress at top  │   │
│   │  • Prompt mgr    — 4 core prompts, visual editing in UI   │   │
│   └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### Agent Core

- **Main loop:** LLM ⇄ 6 tools loop until a final answer is produced
- **Persistent shell:** Bash `cd` persists across calls; dangerous commands blacklisted (`rm -rf /`, `mkfs`, force-push to main, fork bomb, etc.)
- **Streaming output:** LLM response streams chunk-by-chunk (text + thinking reasoning) on both Web and CLI
- **Instant abort:** cancel signal propagates end-to-end — UI feedback instant, HTTP connection truly closed, running Bash killed + restarted, millisecond latency
- **Tool confirmation:** Web pops a confirmation card before Edit/Write; CLI uses y/n prompt
- **Permission model:** first access to a new directory prompts for approval; approved subtrees are allowed
- **TodoWrite task tracking:** LLM proactively breaks down todos for complex tasks (3+ steps); sticky progress bar at top; rebuilt from jsonl on resume

### Skill System (Progressive Disclosure)

- `SKILL.md` directory format, frontmatter defines `name` / `description` / `when_to_use` / `allowed_tools`
- **Three sources:** `project > user > system`
  - `project`: `<repo>/.taisang/skills/`
  - `user`: `~/.taisang/skills/`
  - `system`: built-in `commit` and `review`
- Loaded fully at startup; SYSTEM_PROMPT injects only a lightweight listing (≤250 chars per entry, degrades gracefully)
- **Web management:** `/skills` page supports table, enable toggle, reload, import (MD / zip), delete

### Multi-Agent Scheduling (M3)

- `Agent({subagent_type, prompt, run_in_background})` spawns a sub-agent
- **4 built-in agents:** `general-purpose` / `explore` (read-only) / `plan` (read-only) / `verification` (adversarial, async by default)
- **Two modes:** with `subagent_type` → Mode A (fresh context); without → Mode B (fork parent messages)
- Sync + async execution; async results inject into the main loop
- `AGENT.md` directory format, three sources, `/agents` management page
- Recursion guard: AgentTool physically unregistered for children + `is_fork_child` flag blocks fork-in-fork

### MCP Client

- Integrates third-party MCP servers; injects their tool / resource / prompt into the agent tool registry
- **Two transports:** `stdio` (local subprocess) + `sse` (HTTP+SSE)
- Each MCP tool registered as `mcp__<server>__<tool>`; LLM calls go through `manager.call_tool()`
- **`/mcp` management page:** CRUD, enable/disable, reconnect, 3 quick-add modes (CLI one-liner / JSON text / file upload, claude-code `mcpServers` format compatible)

### Personalization

- **User profile:** single-column markdown, segmented by `### 技术栈 / 代码风格 / 沟通 / 环境 / 禁忌`; agent auto-updates when discovering preferences
- **Zero cache waste:** updates don't touch the current session; injected only at autocompact and new session startup
- **History:** `~/.taisang/profile_history.jsonl` stores the last 5 snapshots; rollback supported
- **`/profile` management page:** full edit + reset to default + rollback + history

### Prompt Management

- 4 core prompts, visually editable in the UI, persisted to `~/.taisang/settings.json`:
  - `system_prompt` / `autocompact_prompt` / `session_memory_template` / `session_memory_update_prompt`
- Reset to default supported; `system_prompt` changes broadcast to all active sessions instantly
- **`/prompts` management page**

### Web UI / CLI

- **Web UI** (Vue 3.5 + Vite + TDesign): multi-session sidebar, Claude-style unified input, Markdown + code highlight + collapsible tool cards, SSE real-time event stream
- **CLI** (`taisang chat`): REPL with `/exit` / `/reset` / `/debug`

### Observability

- **Token usage:** per-turn + session cumulative
- **/debug mode:** prints full messages + response + tool observations sent to the LLM
- **15 AgentEvent types:** CLI and Web UI share the same rendering logic

---

## 🗺️ Roadmap

Ordered by priority:

**High priority**
- **Slash Commands:** `/commit`, `/review` and other slash commands (previously reverted, to be redone)
- **Batch skill import:** currently one skill per zip; extend to N
- **Hooks:** PreToolUse / PostToolUse / SessionStart and other hooks
- **Plugin manifest + marketplace:** `plugin.json` parsing + plugin marketplace

**Skill enhancements**
- Runtime SKILL.md hot-reload (currently requires a new session)
- Advanced frontmatter fields (`version` / `model` / `context:fork` / `agent` / `paths` / `argument-hint`)
- Fork execution: run skills inside a sub-agent

**Web UI**
- Dark theme / theme switching
- Mobile responsiveness
- Auto-reconnect on EventSource drop

**Agent behavior**
- Image / multimodal input (text-only for now)
- Resume interrupted sessions (process death kills the session; todos already support resume)

**Engineering**
- i18n: UI text is currently hardcoded in Chinese

---

## 🙏 Acknowledgements

Thanks to Claude Code and Trae for design inspiration, and to the MCP protocol for enabling a shared tool ecosystem.

If TaiSang helps you, please ⭐ Star to support it!

[github.com/zht475706171/TaiSang](https://github.com/zht475706171/TaiSang)

---

## License

MIT