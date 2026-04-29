# 微信 Codex UI

这是一个在 Linux 上使用 Codex 的本地 Web UI 和微信机器人封装。

它的目标是让 Codex 像一个可在浏览器和微信里使用的本地助手：

- 在浏览器里配置和运行 Codex 任务。
- 通过微信发送 `/codex ...` 指令调用 Codex。
- 按 Web 会话和微信会话保存 Codex 线程，支持连续追问。
- 显示任务状态、运行日志、聊天记录、Git diff 和基础 Git 操作。
- 长回复会自动拆成多条微信消息发送。

## 功能

- Web 控制台：配置 Codex、选择项目目录、启动/停止微信机器人。
- 微信入口：通过 `/codex` 指令发送任务。
- 真实 Codex 线程：同一会话会优先恢复之前的 Codex session。
- 任务控制：支持状态查询、停止任务、清空上下文。
- Git 辅助：查看变更、暂存文件、提交、拉取、推送。
- 安全默认值：运行态文件、配置文件、上下文和日志默认不提交到 Git。

## 环境要求

- Python 3.10+
- Node.js 和 npm
- Codex CLI
- x-cmd 及其微信模块
- Codex 登录状态或 OpenAI API Key

如果配置里开启了 `auto_install_deps`，程序会尝试自动安装部分缺失依赖。

## 安装与配置

复制示例配置：

```bash
cp weixin_codex_config.example.json weixin_codex_config.json
```

编辑 `weixin_codex_config.json`：

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

如果不填写 `openai_api_key`，请先登录 Codex：

```bash
codex login
```

## 启动

启动 Web UI：

```bash
python3 weixin_codex_ui.py
```

浏览器打开：

```text
http://127.0.0.1:8787
```

在 Web UI 里可以：

- 保存 Codex 和项目配置。
- 登录微信。
- 启动或停止微信机器人。
- 直接从浏览器发送 Codex 任务。
- 查看聊天、日志、任务状态和 Git 变更。

## 微信指令

基本格式：

```text
/codex <任务>
```

示例：

```text
/codex 解释这个项目
/codex 修复测试失败
/codex status
/codex stop
/codex reset
```

控制命令：

- `/codex status`、`/codex 状态`、`/codex 进度`：查看当前任务状态。
- `/codex stop`、`/codex 停止`、`/codex 取消`、`/codex 中止`：停止当前微信会话正在运行的任务。
- `/codex reset`、`/codex 重置`、`/codex 清空上下文`：清空当前微信会话的上下文和 Codex 线程映射。

当 x-cmd 能识别语音消息文本时，语音内容会作为 Codex 指令处理。

## 配置说明

常用字段：

- `openai_api_key`：OpenAI API Key。留空时使用 Codex 本地登录状态。
- `codex_cmd`：Codex 命令，默认 `codex`。
- `project_dir`：Codex 工作目录。
- `codex_sandbox`：Codex 沙箱模式，支持 `read-only` 和 `workspace-write`。
- `codex_approval_policy`：审批模式，非交互运行通常用 `never`。
- `codex_model`：指定模型，留空使用 Codex 默认模型。
- `codex_reasoning_effort`：推理深度，可选 `low`、`medium`、`high`、`xhigh`。
- `codex_timeout`：任务超时时间，单位秒。
- `codex_search`：是否启用 Codex Web 搜索。
- `auto_install_deps`：是否自动安装缺失依赖。

## 环境变量

常用覆盖项：

- `WEIXIN_CODEX_UI_HOST`：Web UI 监听地址，默认 `127.0.0.1`
- `WEIXIN_CODEX_UI_PORT`：Web UI 端口，默认 `8787`
- `WEIXIN_CODEX_CONFIG_FILE`：配置文件路径
- `WEIXIN_CODEX_CONTEXT_FILE`：微信上下文文件路径
- `WEIXIN_CODEX_EVENT_FILE`：Web/微信同步事件文件路径
- `X_CMD_PATH`：`x-cmd` 路径
- `CODEX_CMD`：Codex 可执行文件，默认 `codex`
- `CODEX_TIMEOUT`：Codex 任务超时时间

## 本地运行态文件

以下文件是本地状态或敏感配置，默认不会提交到 Git：

- `weixin_codex_config.json`
- `weixin_codex_context.json`
- `weixin_codex_events.jsonl`
- `weixin_codex_sessions.json`
- `weixin_codex_ui_state.json`
- `__pycache__/`
- `.codex`

不要提交 API Key、个人聊天记录或本地运行日志。

## 使用建议

- 只问问题时，建议使用 `read-only` 沙箱。
- 需要 Codex 修改项目文件时，再切换到 `workspace-write`。
- 微信长回复会自动拆分成多条消息。
- 如果微信里任务运行时间较长，可以发送 `/codex status` 查看进度，或发送 `/codex stop` 停止任务。
