# codex_app_in_linux
### 在浏览器里运行 Codex，在微信里调用 Codex，全部留在你的 Linux 本机。

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](#环境要求)
[![Codex CLI](https://img.shields.io/badge/Codex-CLI-111827)](#环境要求)
[![WeChat](https://img.shields.io/badge/WeChat-x--cmd-07C160?logo=wechat&logoColor=white)](#微信入口)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English README](README.md)

> 一个轻量的 Linux 本地 Codex 控制台。
>
> 浏览器负责桌面体验，微信负责移动入口，Git 辅助功能随手可用。

```text
 ██████╗ ██████╗ ██████╗ ███████╗██╗  ██╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗██╔╝
██║     ██║   ██║██║  ██║█████╗   ╚███╔╝
██║     ██║   ██║██║  ██║██╔══╝   ██╔██╗
╚██████╗╚██████╔╝██████╔╝███████╗██╔╝ ██╗
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝

        Codex 的 Web UI + 微信桥接
```

---

## 这是什么？

`codex_app_in_linux` 是一个基于 Python 的本地 Web UI 和微信机器人封装，用来调用 OpenAI Codex CLI。

你启动一个本地服务，打开浏览器，选择项目目录，就可以开始给 Codex 派任务。如果通过 `x-cmd weixin` 连接微信，还可以直接在微信里发送 `/codex ...` 调用 Codex。

一句话：本地 Codex 任务控制台，加上浏览器界面和微信入口。

---

## 快速开始

```bash
# 克隆项目
git clone https://github.com/qq944936/codex_app_in_linux.git
cd codex_app_in_linux

# 创建本地配置
cp weixin_codex_config.example.json weixin_codex_config.json

# 启动 Web UI
python3 weixin_codex_ui.py
```

然后打开：

```text
http://127.0.0.1:8787
```

在 UI 中：

1. 设置项目目录。
2. 确认 Codex 已登录，或填写 API Key。
3. 点击 `微信登录`，扫码登录微信。
4. 点击 `启动`，启动微信 Codex 机器人。

---

## 功能

> 真正有用的部分。

- Linux 上的浏览器版 Codex 控制台。
- Web 聊天窗口，直接发送 Codex 指令。
- 微信 `/codex` 指令桥接。
- 真实 Codex session 恢复，连续追问更顺滑。
- Web 会话和微信会话分别保存上下文。
- 任务状态时间线和运行日志。
- Web UI 中停止长任务。
- 微信中用 `/codex stop` 停止长任务。
- 微信中用 `/codex status` 查询任务状态。
- 微信长回复自动分段发送。
- Git diff、暂存、提交、拉取、推送辅助。
- 默认忽略运行态文件和个人配置，避免误提交隐私数据。

---

## 微信入口

发送任务：

```text
/codex 解释这个项目
/codex 修复测试失败
/codex 给 README 增加部署说明
```

控制命令：

```text
/codex status
/codex stop
/codex reset
```

中文别名：

```text
/codex 状态
/codex 停止
/codex 清空上下文
```

当 `x-cmd` 能提供语音识别文本时，语音内容也会作为 Codex 指令处理。

---

## 界面和流程

没有营销页，打开就是工具本体：

- 左侧：配置、登录、运行控制
- 右侧：聊天、日志、任务事件、Git 变更
- 微信消息会同步回 Web UI 的微信会话

---

## 架构

```text
┌──────────────────────────────┐
│ Browser Web UI               │
│ http://127.0.0.1:8787         │
└──────────────┬───────────────┘
               │ local HTTP API
┌──────────────▼───────────────┐
│ weixin_codex_ui.py            │
│ 配置、会话、日志、Git 辅助     │
└───────┬──────────────────────┘
        │ 启动 / 监控
┌───────▼──────────────────────┐
│ weixin_codex_bot.py           │
│ x-cmd 微信日志监听            │
└───────┬──────────────────────┘
        │ /codex 指令
┌───────▼──────────────────────┐
│ Codex CLI                     │
│ exec / exec resume            │
└──────────────────────────────┘
```

---

## 环境要求

- Python `3.10+`
- Node.js 和 npm
- Codex CLI
- `x-cmd` 及其微信模块
- Codex 登录状态或 OpenAI API Key

安装或登录 Codex：

```bash
npm install -g @openai/codex
codex login
```

---

## 配置

创建配置文件：

```bash
cp weixin_codex_config.example.json weixin_codex_config.json
```

示例：

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

重要字段：

- `project_dir`：Codex 读取和工作的目录。
- `codex_sandbox`：只问问题用 `read-only`，需要改代码用 `workspace-write`。
- `codex_approval_policy`：机器人非交互运行建议用 `never`。
- `codex_search`：启用 Codex Web 搜索。

---

## 本地运行态文件

这些是本地状态文件，默认被 Git 忽略：

```text
weixin_codex_config.json
weixin_codex_context.json
weixin_codex_events.jsonl
weixin_codex_sessions.json
weixin_codex_ui_state.json
__pycache__/
.codex
```

不要提交 API Key、个人聊天记录或本地运行状态。

---

## 常见问题

| 问题 | 处理方式 |
| --- | --- |
| 微信二维码显示变形 | 刷新到最新版 UI；日志区已使用紧凑行高。 |
| 微信显示未登录 | 点击 `微信登录` 扫码，然后点击 `启动`。 |
| Codex 未登录 | 运行 `codex login`，或在配置里填写 `openai_api_key`。 |
| 微信长回复被截断 | 回复会自动拆分成多条消息，但有最大分段数。 |
| 微信任务卡住 | 先发 `/codex status`，需要时再发 `/codex stop`。 |
| 需要让 Codex 改文件 | 把 `codex_sandbox` 改成 `workspace-write`。 |

---

## 喜欢并支持

如果这个项目对你有帮助，欢迎通过微信或支付宝捐赠 1 元，请我喝杯咖啡。

后续可以在这里放微信/支付宝收款码图片。

---

## License

MIT License. See [LICENSE](LICENSE).
