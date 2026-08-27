# Adapter Support Matrix

| Agent | Installed | Session Capture | Context Injection | Session Source | Limitations |
|-------|-----------|-----------------|-------------------|----------------|-------------|
| **Codex** | ✅ | ✅ VERIFIED_LOG | ✅ Initial prompt | `~/.codex/sessions/` (JSONL) | JSONL format depends on Codex version |
| **Kilo** | ✅ | ✅ VERIFIED_NATIVE | ✅ Initial prompt | `kilo export` CLI | Requires Kilo CLI installed |
| **OpenCode** | ✅ | ✅ VERIFIED_NATIVE | ✅ Initial prompt | `opencode export` CLI | Requires OpenCode CLI installed |
| **Cline** | ✅ | ✅ VERIFIED_LOG | ✅ Initial prompt | `~/.cline/data/sessions/` (JSON) | Cline CLI sessions only (not VS Code extension) |
| **Aider** | ✅ | ✅ VERIFIED_LOG | ✅ `--message` flag | `.aider.chat.history.md` (per project) | Markdown format; no individual message timestamps |
| Claude Code | ❌ | — | — | — | Not installed on current workstation |
| Cursor | ❌ | — | — | — | Not installed on current workstation |
| Roo Code | ❌ | — | — | — | Not installed on current workstation |
| Continue | ❌ | — | — | — | Not installed on current workstation |
| Windsurf | ❌ | — | — | — | Not installed on current workstation |

## Adapter Types

### Session Capture Adapters (`AgentSessionAdapter`)
Read agent session data from local storage formats and feed it through the Munin capture pipeline (admission → dedup → temporal → memory).

### Launch Adapters (`AgentLaunchAdapter`)
Launch coding agents with Munin project context injected. Each agent has a specific injection mechanism:
- **Initial prompt argument**: Context passed as CLI argument (`codex [PROMPT]`, `cline [PROMPT]`)
- **Message flag**: Context passed via flag (`aider --message "prompt"`)

## Architecture

```
                 MUNIN

          capture        inject
             ↑             ↓
         AgentSession   AgentLaunch
           Adapter        Adapter
             ↑             ↓
     ┌───────┼─────────────┼─────────┐
     │       │             │         │
   Codex    Kilo        OpenCode   Cline/Aider
```
