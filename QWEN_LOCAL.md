# Free local Qwen setup

This fork keeps Jared Rhodenizer's fullstack-agent architecture, but routes the agent brain to a local Qwen model through Ollama instead of paid Anthropic model usage.

## What is actually running

- Claude Code / the Claude Agent SDK: the local agent shell used by Backtalk for tools, sessions, and permissions.
- Ollama: a local API server on your computer.
- Qwen: the model that performs the reasoning and tool selection.
- Backtalk, ai-memory-vault, ai-visualizer, and barehands: unchanged upstream components.

Ollama exposes an Anthropic-compatible API at `http://localhost:11434`, so the existing Backtalk integration can use Qwen without rewriting its voice loop.

## Default model

`qwen3.5:4b`

It is small enough for many normal computers while still supporting tools. To use another local model, set `FULLSTACK_QWEN_MODEL` before starting the agent and set the same model in `backtalk/backtalk.json`.

Example:

```powershell
$env:FULLSTACK_QWEN_MODEL="qwen3.5:9b"
```

## Windows setup

1. Install Ollama from the official Ollama installer.
2. Install Claude Code. You do not need paid Anthropic model usage for this fork; the launcher points it at local Ollama.
3. Pull the local model:

```powershell
ollama pull qwen3.5:4b
```

4. Before running the setup wizard for the first time:

```powershell
$env:ANTHROPIC_AUTH_TOKEN="ollama"
$env:ANTHROPIC_BASE_URL="http://localhost:11434"
claude --model qwen3.5:4b
```

5. In Claude Code, tell the installer: `set me up`.

After setup, use this fork's `start.bat`. It automatically points Backtalk at Ollama.

## macOS / Linux setup

```bash
ollama pull qwen3.5:4b
export ANTHROPIC_AUTH_TOKEN=ollama
export ANTHROPIC_BASE_URL=http://localhost:11434
claude --model qwen3.5:4b
```

After setup, use `./fullstack-agent/start.sh`.

## Backtalk configuration

The setup wizard in this fork writes:

```json
{
  "model": "qwen3.5:4b",
  "deep_model": "qwen3.5:4b",
  "show_usage": false
}
```

The launchers also export the local Ollama endpoint and dummy auth token expected by the Anthropic-compatible API.

## Cost

Local Ollama models do not have per-token API charges. Your computer supplies the compute. Optional third-party services such as ElevenLabs may still cost money if you choose to enable them.

## Privacy boundary

This fork is configured for this machine so the agent must never access the work profile:

```text
C:\\Users\\vijay koripella
```

Do not add that path to Backtalk `extra_dirs`, do not use it as a memory/vault location, and do not run the agent elevated as Administrator to bypass Windows permissions.
