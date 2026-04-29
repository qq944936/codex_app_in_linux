# Weixin Codex UI

A local Web UI and WeChat bot wrapper for using OpenAI Codex from Linux.

The project provides:

- A browser UI for configuring and running Codex tasks.
- WeChat command handling through `x-cmd weixin`.
- Per-session Codex thread resume for smoother follow-up tasks.
- Task logs, status timeline, chat history, Git diff view, and basic Git actions.
- WeChat replies with automatic message splitting for long Codex responses.

## Requirements

- Python 3.10+
- Node.js and npm
- Codex CLI
- x-cmd with the WeChat module
- A valid Codex login or OpenAI API key

The bot can auto-install some missing dependencies when `auto_install_deps` is enabled in the config.

## Setup

Copy the example config:

```bash
cp weixin_codex_config.example.json weixin_codex_config.json
```

Edit `weixin_codex_config.json`:

```json
{
  "openai_api_key": "",
  "codex_cmd": "codex",
  "project_dir": "/path/to/your/project",
  "codex_sandbox": "read-only",
  "codex_approval_policy": "never",
  "codex_model": "",
  "codex_reasoning_effort": "",
  "codex_timeout": 120,
  "codex_search": false,
  "auto_install_deps": true
}
```

If `openai_api_key` is blank, sign in with Codex first:

```bash
codex login
```

## Run

Start the Web UI:

```bash
python3 weixin_codex_ui.py
```

Open:

```text
http://127.0.0.1:8787
```

From the UI you can:

- Save Codex and project settings.
- Log in to WeChat.
- Start or stop the WeChat bot.
- Send Codex tasks directly from the browser.
- View chat, logs, task state, and Git changes.

## WeChat Commands

Text command format:

```text
/codex <task>
```

Examples:

```text
/codex explain this project
/codex fix the failing tests
/codex status
/codex stop
/codex reset
```

Supported control commands:

- `/codex status`, `/codex 状态`, `/codex 进度`: show current task status.
- `/codex stop`, `/codex 停止`, `/codex 取消`, `/codex 中止`: stop the current task for that WeChat session.
- `/codex reset`, `/codex 重置`, `/codex 清空上下文`: clear saved context and Codex thread mapping for that WeChat session.

Voice messages are handled as direct Codex prompts when x-cmd provides recognized text.

## Runtime Files

These files are local runtime state and are intentionally ignored by Git:

- `weixin_codex_config.json`
- `weixin_codex_context.json`
- `weixin_codex_events.jsonl`
- `weixin_codex_sessions.json`
- `weixin_codex_ui_state.json`
- `__pycache__/`
- `.codex`

Do not commit API keys or personal chat logs.

## Environment Variables

Common overrides:

- `WEIXIN_CODEX_UI_HOST`: Web UI bind host. Default: `127.0.0.1`
- `WEIXIN_CODEX_UI_PORT`: Web UI port. Default: `8787`
- `WEIXIN_CODEX_CONFIG_FILE`: config file path
- `WEIXIN_CODEX_CONTEXT_FILE`: WeChat context file path
- `WEIXIN_CODEX_EVENT_FILE`: Web/WeChat sync event file path
- `X_CMD_PATH`: path to `x-cmd`
- `CODEX_CMD`: Codex executable. Default: `codex`
- `CODEX_TIMEOUT`: Codex task timeout in seconds

## Notes

- Keep `codex_sandbox` as `read-only` when you only want answers.
- Use `workspace-write` only when you want Codex to modify files inside the configured project directory.
- Long replies are split into multiple WeChat messages.
- The Web UI and WeChat bot keep separate session state but both use Codex CLI under the hood.
