# codex_app_in_linux
### Run Codex from a browser. Use it from WeChat. Keep it local on Linux.

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](#requirements)
[![Codex CLI](https://img.shields.io/badge/Codex-CLI-111827)](#requirements)
[![WeChat](https://img.shields.io/badge/WeChat-x--cmd-07C160?logo=wechat&logoColor=white)](#wechat-bridge)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[中文说明](README.zh-CN.md)

> A lightweight local control panel for Codex on Linux.
>
> Browser UI for your desktop. WeChat bridge for your phone. Git workflow helpers when you need them.

```text
 ██████╗ ██████╗ ██████╗ ███████╗██╗  ██╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗██╔╝
██║     ██║   ██║██║  ██║█████╗   ╚███╔╝
██║     ██║   ██║██║  ██║██╔══╝   ██╔██╗
╚██████╗╚██████╔╝██████╔╝███████╗██╔╝ ██╗
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝

        Web UI + WeChat bridge for Codex
```

---

## What Is This?

`codex_app_in_linux` is a small Python-based Web UI and WeChat bot wrapper for OpenAI Codex CLI.

You run one local server, open a browser, choose a project directory, and start sending Codex tasks. If you connect WeChat through `x-cmd weixin`, you can also send tasks from WeChat with `/codex ...`.

TL;DR: Codex local task control, with a browser dashboard and a WeChat command bridge.

---

## Quick Start

```bash
# Clone your repo
git clone https://github.com/qq944936/codex_app_in_linux.git
cd codex_app_in_linux

# Create local config
cp weixin_codex_config.example.json weixin_codex_config.json

# Start the Web UI
python3 weixin_codex_ui.py
```

Then open:

```text
http://127.0.0.1:8787
```

In the UI:

1. Set the project directory.
2. Confirm Codex login or API key.
3. Click `微信登录` to scan the WeChat login QR code.
4. Click `启动` to start the WeChat Codex bot.

---

## Features

> The useful bits.

- Browser-first Codex control panel on Linux.
- Web chat for sending Codex prompts directly.
- WeChat command bridge with `/codex`.
- Real Codex session resume for smoother follow-up tasks.
- Per-Web-session and per-WeChat-session context.
- Task status timeline and live logs.
- Stop long-running Web tasks from the UI.
- Stop long-running WeChat tasks with `/codex stop`.
- Query WeChat task state with `/codex status`.
- Automatic long-reply splitting for WeChat messages.
- Git diff view, staging, commit, pull, and push helpers.
- Runtime files and personal config ignored by Git by default.

---

## WeChat Bridge

Send a task:

```text
/codex explain this project
/codex fix the failing tests
/codex add a README section for deployment
```

Control commands:

```text
/codex status
/codex stop
/codex reset
```

Chinese aliases are supported:

```text
/codex 状态
/codex 停止
/codex 清空上下文
```

When `x-cmd` provides recognized voice text, voice messages are handled as direct Codex prompts.

---

## Screens And Flow

No marketing page. The first screen is the tool:

- left side: config, login, runtime controls
- right side: chat, logs, task events, Git changes
- WeChat messages sync back into the Web UI

---

## Architecture

```text
┌──────────────────────────────┐
│ Browser Web UI               │
│ http://127.0.0.1:8787         │
└──────────────┬───────────────┘
               │ local HTTP API
┌──────────────▼───────────────┐
│ weixin_codex_ui.py            │
│ config, sessions, logs, Git   │
└───────┬──────────────────────┘
        │ starts / monitors
┌───────▼──────────────────────┐
│ weixin_codex_bot.py           │
│ x-cmd WeChat log listener     │
└───────┬──────────────────────┘
        │ /codex prompt
┌───────▼──────────────────────┐
│ Codex CLI                     │
│ exec / exec resume            │
└──────────────────────────────┘
```

---

## Requirements

- Python `3.10+`
- Node.js and npm
- Codex CLI
- `x-cmd` with the WeChat module
- Codex login or OpenAI API key

Install or login to Codex:

```bash
npm install -g @openai/codex
codex login
```

---

## Config

Create:

```bash
cp weixin_codex_config.example.json weixin_codex_config.json
```

Example:

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

Important fields:

- `project_dir`: where Codex reads and works.
- `codex_sandbox`: use `read-only` for answers, `workspace-write` for code edits.
- `codex_approval_policy`: `never` is best for non-interactive bot runs.
- `codex_search`: enables Codex web search when supported.

---

## Runtime Files

These are local state and are ignored by Git:

```text
weixin_codex_config.json
weixin_codex_context.json
weixin_codex_events.jsonl
weixin_codex_sessions.json
weixin_codex_ui_state.json
__pycache__/
.codex
```

Do not commit API keys, personal chat logs, or local runtime state.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| WeChat QR code looks stretched | Refresh after the latest UI; log view uses compact line height. |
| WeChat shows not logged in | Click `微信登录`, scan the QR code, then click `启动`. |
| Codex is not logged in | Run `codex login` or set `openai_api_key`. |
| Long WeChat reply is cut | Replies are split into multiple messages, with a maximum part count. |
| A WeChat task is stuck | Send `/codex status`, then `/codex stop` if needed. |
| Need code edits | Set `codex_sandbox` to `workspace-write`. |

---

## Support

If this project helps you, you can support me with a 1 CNY donation via WeChat Pay or Alipay and buy me a coffee.

WeChat Pay / Alipay QR codes can be added here later.

---

## License

MIT License. See [LICENSE](LICENSE).
