import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
BOT_SCRIPT = SCRIPT_DIR / "weixin_codex_bot.py"
CONFIG_FILE = Path(os.environ.get("WEIXIN_CODEX_CONFIG_FILE", SCRIPT_DIR / "weixin_codex_config.json"))
STATE_FILE = Path(os.environ.get("WEIXIN_CODEX_UI_STATE_FILE", SCRIPT_DIR / "weixin_codex_ui_state.json"))
WEIXIN_EVENT_FILE = Path(os.environ.get("WEIXIN_CODEX_EVENT_FILE", SCRIPT_DIR / "weixin_codex_events.jsonl"))
X_CMD = os.environ.get("X_CMD_PATH") or "x-cmd"
HOST = os.environ.get("WEIXIN_CODEX_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEIXIN_CODEX_UI_PORT", "8787"))
MAX_LOG_LINES = 500
MAX_CHAT_MESSAGES = 200
MAX_TASK_EVENTS = 80
MAX_WEIXIN_MESSAGE_LENGTH = 1200
MAX_WEIXIN_PARTS = 8
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
VALID_CODEX_SANDBOXES = {"read-only", "workspace-write"}
VALID_REASONING_EFFORTS = {"", "low", "medium", "high", "xhigh"}
VALID_APPROVAL_POLICIES = {"never", "on-request", "untrusted", "on-failure"}

bot_process = None
login_process = None
codex_login_process = None
codex_process = None
bot_lock = threading.Lock()
login_lock = threading.Lock()
codex_login_lock = threading.Lock()
codex_lock = threading.Lock()
chat_lock = threading.Lock()
log_lines = []
login_lines = []
chat_messages = []
chat_sessions = {}
active_session_id = "default"
imported_weixin_event_ids = set()
weixin_login_succeeded = False
log_queue = queue.Queue()
task_state = {
    "state": "idle",
    "label": "空闲",
    "detail": "",
    "updated_at": time.strftime("%H:%M:%S"),
}
task_state_lock = threading.Lock()
task_events = []
task_events_lock = threading.Lock()


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>微信 Codex 机器人</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #5f6f7f;
      --line: #d9e0e7;
      --primary: #1769aa;
      --primary-dark: #0f4c81;
      --danger: #b42318;
      --ok: #147d4f;
      --shadow: 0 10px 28px rgba(22, 34, 51, 0.08);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    .bar {
      width: 100%;
      margin: 0;
      padding: 18px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      font-weight: 700;
    }
    .status-strip {
      width: 100%;
      margin: 0;
      padding: 0 20px 14px;
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
    }
    .status-item {
      min-width: 0;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }
    .status-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }
    .status-value {
      margin-top: 3px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 12px;
      font-weight: 700;
    }
    .status-value.ok { color: var(--ok); }
    .status-value.bad { color: var(--danger); }
    .status-value.warn { color: #8a5a00; }
    main {
      width: 100%;
      margin: 0;
      padding: 20px;
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: 16px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .panel-head {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    h2 {
      margin: 0;
      font-size: 15px;
      font-weight: 700;
    }
    .body { padding: 16px; }
    label {
      display: block;
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    input[type="text"],
    input[type="password"],
    select,
    textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      color: var(--text);
      background: #fff;
      outline: none;
    }
    input[type="text"],
    input[type="password"] {
      min-height: 38px;
    }
    select {
      min-height: 38px;
    }
    textarea {
      min-height: 86px;
      resize: vertical;
      font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    input:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(23, 105, 170, 0.14);
    }
    .field { margin-bottom: 14px; }
    .row {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    .switch {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      font-weight: 600;
    }
    button {
      min-height: 36px;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 7px 12px;
      background: var(--primary);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover { background: var(--primary-dark); }
    button.secondary {
      background: #fff;
      color: var(--text);
      border-color: var(--line);
    }
    button.secondary:hover { background: #eef3f7; }
    button.danger { background: var(--danger); }
    button.danger:hover { background: #8f1d14; }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 6px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--muted);
      background: #fff;
      font-weight: 700;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #8795a1;
    }
    .status.running .dot { background: var(--ok); }
    .status.stopped .dot { background: var(--danger); }
    .hint {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .toast {
      min-height: 20px;
      color: var(--muted);
      font-size: 12px;
    }
    .command-box {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .tabs {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .tab {
      min-height: 32px;
      padding: 5px 10px;
      background: #fff;
      color: var(--muted);
      border: 1px solid var(--line);
    }
    .tab.active {
      background: var(--primary);
      color: #fff;
      border-color: var(--primary);
    }
    .command-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) repeat(4, auto);
      gap: 10px;
      align-items: end;
    }
    .session-meta {
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 6px 8px;
      margin: -2px 0 12px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .session-meta strong {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--text);
    }
    .task-state {
      margin-top: 10px;
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 8px;
      align-items: center;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .task-state strong { color: var(--text); }
    .task-timeline {
      margin-top: 10px;
      max-height: 132px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 8px 10px;
    }
    .timeline-item {
      display: grid;
      grid-template-columns: 58px 1fr;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      padding: 3px 0;
      border-bottom: 1px solid #eef2f6;
    }
    .timeline-item:last-child { border-bottom: 0; }
    .timeline-item strong {
      color: var(--text);
      font-weight: 700;
    }
    .chat-view {
      height: calc(100vh - 380px);
      min-height: 400px;
      overflow: auto;
      padding: 14px;
      background: #f8fafc;
      border-radius: 0 0 8px 8px;
    }
    .message {
      max-width: 92%;
      margin: 0 0 12px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.55;
    }
    .message.user {
      margin-left: auto;
      background: #e8f2fb;
      border-color: #c7dff2;
    }
    .message.assistant {
      margin-right: auto;
    }
    .message.system {
      max-width: 100%;
      background: #fff7e6;
      border-color: #f2d89b;
      color: #72531b;
    }
    .message.error {
      max-width: 100%;
      background: #fff1f0;
      border-color: #f4b6b0;
      color: #8f1d14;
    }
    .message.pending {
      max-width: 100%;
      background: #eef6ff;
      border-color: #c8dff4;
      color: #254761;
    }
    .msg-meta {
      margin-bottom: 5px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }
    .msg-source {
      color: #476173;
      background: #eef5f8;
      border: 1px solid #d7e4ea;
      border-radius: 999px;
      padding: 1px 6px;
      font-weight: 700;
    }
    .hidden { display: none; }
    .changes-view {
      height: calc(100vh - 380px);
      min-height: 400px;
      overflow: auto;
      padding: 14px;
      background: #f8fafc;
      border-radius: 0 0 8px 8px;
    }
    .changes-summary {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .changes-layout {
      display: grid;
      grid-template-columns: minmax(180px, 280px) 1fr;
      gap: 12px;
    }
    .file-list {
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
      align-content: start;
    }
    .file-row {
      display: grid;
      grid-template-columns: 36px 1fr;
      gap: 8px;
      align-items: center;
      padding: 7px 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      cursor: pointer;
    }
    .file-row.active {
      border-color: var(--primary);
      background: #e8f2fb;
    }
    .diff {
      margin: 0;
      height: auto;
      min-height: 240px;
      border-radius: 6px;
      white-space: pre-wrap;
    }
    .git-summary {
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .summary-box {
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    pre {
      margin: 0;
      height: calc(100vh - 380px);
      min-height: 400px;
      overflow: auto;
      padding: 14px;
      background: #101820;
      color: #d6e2ea;
      border-radius: 0 0 8px 8px;
      font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    #logs {
      line-height: 1;
      white-space: pre;
      overflow-wrap: normal;
      word-break: normal;
    }
    .diff {
      line-height: 1.55;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .meta {
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 8px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
    }
    .meta b { color: var(--text); }
    @media (max-width: 860px) {
      .bar { align-items: flex-start; flex-direction: column; }
      main { grid-template-columns: 1fr; padding: 14px; }
      .status-strip { grid-template-columns: 1fr 1fr; padding: 0 14px 14px; }
      .changes-layout { grid-template-columns: 1fr; }
      .git-summary { grid-template-columns: 1fr; }
      .command-row { grid-template-columns: 1fr; }
      .chat-view { height: 520px; min-height: 360px; }
      .changes-view { height: 520px; min-height: 360px; }
      pre { height: 520px; min-height: 360px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <h1>微信 Codex 机器人</h1>
      <span id="status" class="status stopped"><span class="dot"></span><span>未运行</span></span>
    </div>
    <div class="status-strip">
      <div class="status-item">
        <div class="status-label">Codex</div>
        <div class="status-value warn" id="codexStatus">检测中</div>
      </div>
      <div class="status-item">
        <div class="status-label">微信</div>
        <div class="status-value warn" id="weixinStatus">检测中</div>
      </div>
      <div class="status-item">
        <div class="status-label">x-cmd</div>
        <div class="status-value warn" id="xcmdStatus">检测中</div>
      </div>
      <div class="status-item">
        <div class="status-label">Node / npm</div>
        <div class="status-value warn" id="nodeStatus">检测中</div>
      </div>
      <div class="status-item">
        <div class="status-label">Git</div>
        <div class="status-value warn" id="gitStatus">检测中</div>
      </div>
    </div>
  </header>

  <main>
    <section>
      <div class="panel-head">
        <h2>配置</h2>
        <button class="secondary" id="reloadBtn" type="button">刷新</button>
      </div>
      <div class="body">
        <div class="field">
          <label for="apiKey">OpenAI API Key</label>
          <input id="apiKey" type="password" autocomplete="off" placeholder="留空表示保持现有密钥">
          <p id="apiKeyHint" class="hint"></p>
        </div>
        <div class="field">
          <label for="codexCmd">Codex 命令</label>
          <input id="codexCmd" type="text" placeholder="codex">
        </div>
        <div class="field">
          <label for="projectDir">项目目录</label>
          <input id="projectDir" type="text" placeholder="/home/zhw/Workspace/aichat">
          <select id="projectSelect" style="margin-top: 8px;">
            <option value="">选择常用项目目录</option>
          </select>
          <p class="hint">Codex 会在这个目录里读取和执行项目相关命令。</p>
        </div>
        <div class="field">
          <label for="codexSandbox">Codex 权限</label>
          <select id="codexSandbox">
            <option value="read-only">只读</option>
            <option value="workspace-write">可写</option>
          </select>
          <p class="hint">只读不会改项目文件；可写允许 Codex 修改项目目录内的文件。</p>
        </div>
        <div class="field">
          <label for="codexApprovalPolicy">Codex 审批模式</label>
          <select id="codexApprovalPolicy">
            <option value="never">自动执行</option>
            <option value="on-request">模型需要时请求确认</option>
            <option value="untrusted">非可信命令请求确认</option>
            <option value="on-failure">失败后再请求确认</option>
          </select>
          <p class="hint">Web 非交互运行时建议保持自动执行；需要更谨慎时可选择请求确认。</p>
        </div>
        <div class="field">
          <label for="codexModel">Codex 模型</label>
          <select id="codexModelSelect">
            <option value="">Codex 默认模型</option>
            <option value="gpt-5.5">GPT-5.5</option>
            <option value="gpt-5.4">GPT-5.4</option>
            <option value="gpt-5.4-mini">GPT-5.4 Mini</option>
            <option value="gpt-5.3-codex">GPT-5.3 Codex</option>
            <option value="gpt-5.2">GPT-5.2</option>
            <option value="custom">自定义</option>
          </select>
          <input id="codexModel" type="text" placeholder="自定义模型 ID" style="margin-top: 8px;">
        </div>
        <div class="field">
          <label for="codexReasoningEffort">推理深度</label>
          <select id="codexReasoningEffort">
            <option value="">Codex 默认</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="xhigh">超高</option>
          </select>
        </div>
        <div class="field">
          <label for="codexTimeout">Codex 超时秒数</label>
          <input id="codexTimeout" type="text" placeholder="120">
        </div>
        <div class="field">
          <label class="switch">
            <input id="codexSearch" type="checkbox">
            启用 Codex Web 搜索
          </label>
        </div>
        <div class="field">
          <label class="switch">
            <input id="autoInstall" type="checkbox">
            自动安装缺失依赖
          </label>
        </div>
        <div class="row">
          <button id="saveBtn" type="button">保存配置</button>
          <button id="startBtn" type="button">启动</button>
          <button id="weixinLoginBtn" class="secondary" type="button">微信登录</button>
          <button id="stopBtn" class="danger" type="button">停止</button>
        </div>
        <p id="toast" class="toast"></p>
        <div class="meta">
          <span>配置文件</span><b id="configPath"></b>
          <span>进程 PID</span><b id="pid">-</b>
        </div>
      </div>
    </section>

    <section>
      <div class="panel-head">
        <div class="tabs">
          <button class="tab active" id="chatTab" type="button">聊天</button>
          <button class="tab" id="logTab" type="button">日志</button>
          <button class="tab" id="changesTab" type="button">变更</button>
        </div>
        <button class="secondary" id="clearLogBtn" type="button">清空显示</button>
      </div>
      <div class="command-box">
        <label for="sessionSelect">会话</label>
        <div class="command-row" style="margin-bottom: 10px;">
          <select id="sessionSelect"></select>
          <button id="newSessionBtn" type="button">新建会话</button>
          <button id="exportSessionBtn" type="button">导出</button>
          <button id="deleteSessionBtn" class="danger" type="button">删除会话</button>
        </div>
        <div class="session-meta">
          <span>工作目录</span><strong id="sessionProjectDir">-</strong>
          <span>Codex 线程</span><strong id="sessionThreadId">未绑定</strong>
        </div>
        <label for="codexPrompt">给 Codex 下达指令</label>
        <div class="command-row">
          <textarea id="codexPrompt" placeholder="输入要让 Codex 处理的问题或任务"></textarea>
          <button id="sendCodexBtn" type="button">发送</button>
          <button id="retryCodexBtn" class="secondary" type="button">重试</button>
          <button id="stopCodexBtn" class="danger" type="button">停止</button>
        </div>
        <label class="switch" style="margin-top: 10px;">
          <input id="useConversationContext" type="checkbox" checked>
          携带当前会话上下文
        </label>
        <label class="switch" style="margin-top: 10px;">
          <input id="syncReplyToWeixin" type="checkbox">
          Codex 回复同步到微信
        </label>
        <div class="task-state">
          <span>任务状态</span>
          <strong id="taskState">空闲</strong>
          <span>详情</span>
          <strong id="taskDetail">-</strong>
        </div>
        <div id="taskTimeline" class="task-timeline"></div>
      </div>
      <div id="chatView" class="chat-view"></div>
      <pre id="logs" class="hidden"></pre>
      <div id="changesView" class="changes-view hidden"></div>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    let autoStartAfterWeixinLogin = true;
    let activeTab = "chat";
    let lastTaskState = "idle";
    let refreshAfterTaskDone = false;
    let currentSessions = [];
    let activeSessionId = "";
    let lastUserPrompt = "";

    function setToast(text) {
      $("toast").textContent = text || "";
    }

    function setStatus(data) {
      const el = $("status");
      el.className = "status " + (data.running ? "running" : "stopped");
      el.lastElementChild.textContent = data.running ? "运行中" : "未运行";
      $("pid").textContent = data.pid || "-";
      $("startBtn").disabled = data.running;
      $("stopBtn").disabled = !data.running;
    }

    function setCodexTaskRunning(running) {
      $("sendCodexBtn").disabled = running;
      $("retryCodexBtn").disabled = running || !lastUserPrompt;
      $("stopCodexBtn").disabled = !running;
    }

    function setActiveTab(tab) {
      activeTab = tab;
      $("chatTab").classList.toggle("active", tab === "chat");
      $("logTab").classList.toggle("active", tab === "log");
      $("changesTab").classList.toggle("active", tab === "changes");
      $("chatView").classList.toggle("hidden", tab !== "chat");
      $("logs").classList.toggle("hidden", tab !== "log");
      $("changesView").classList.toggle("hidden", tab !== "changes");
    }

    function setStatusValue(id, text, state) {
      const el = $(id);
      el.textContent = text;
      el.className = "status-value " + (state || "warn");
    }

    function syncModelInputFromSelect() {
      const value = $("codexModelSelect").value;
      if (value === "custom") {
        $("codexModel").disabled = false;
        $("codexModel").focus();
        return;
      }
      $("codexModel").value = value;
      $("codexModel").disabled = value !== "custom" && value !== "";
    }

    function setModelSelection(model) {
      const known = Array.from($("codexModelSelect").options).some(option => option.value === model);
      if (!model || known) {
        $("codexModelSelect").value = model || "";
        $("codexModel").value = model || "";
      } else {
        $("codexModelSelect").value = "custom";
        $("codexModel").value = model;
      }
      $("codexModel").disabled = $("codexModelSelect").value !== "custom" && $("codexModelSelect").value !== "";
    }

    function updateSessionMeta() {
      const session = currentSessions.find(item => item.id === activeSessionId) || {};
      $("sessionProjectDir").textContent = session.project_dir || $("projectDir").value || "-";
      $("sessionThreadId").textContent = session.codex_session_id || "未绑定";
    }

    function renderChat(messages, running = false) {
      const view = $("chatView");
      const atBottom = view.scrollTop + view.clientHeight >= view.scrollHeight - 20;
      view.innerHTML = "";
      const lastUser = [...messages].reverse().find(item => item.role === "user" && item.text);
      lastUserPrompt = lastUser ? lastUser.text : "";
      if (!messages.length) {
        const empty = document.createElement("div");
        empty.className = "message system";
        empty.textContent = "还没有 Web 指令。";
        view.appendChild(empty);
      }
      for (const item of messages) {
        const message = document.createElement("div");
        message.className = "message " + (item.role || "system");
        const meta = document.createElement("div");
        meta.className = "msg-meta";
        const label = document.createElement("span");
        label.textContent = item.label || item.role || "消息";
        meta.appendChild(label);
        if (item.source) {
          const source = document.createElement("span");
          source.className = "msg-source";
          source.textContent = item.source === "weixin" ? "微信" : item.source;
          meta.appendChild(source);
        }
        if (item.time) {
          const time = document.createElement("span");
          time.textContent = item.time;
          meta.appendChild(time);
        }
        const text = document.createElement("div");
        text.textContent = item.text || "";
        message.appendChild(meta);
        message.appendChild(text);
        view.appendChild(message);
      }
      if (running) {
        const pending = document.createElement("div");
        pending.className = "message pending";
        const meta = document.createElement("div");
        meta.className = "msg-meta";
        meta.textContent = "Codex";
        const text = document.createElement("div");
        text.textContent = "正在处理当前任务...";
        pending.appendChild(meta);
        pending.appendChild(text);
        view.appendChild(pending);
      }
      setCodexTaskRunning(running);
      if (atBottom) view.scrollTop = view.scrollHeight;
    }

    function renderTimeline(events) {
      const view = $("taskTimeline");
      const atBottom = view.scrollTop + view.clientHeight >= view.scrollHeight - 20;
      view.innerHTML = "";
      if (!events.length) {
        const empty = document.createElement("div");
        empty.className = "timeline-item";
        empty.innerHTML = "<strong>-</strong><span>暂无任务事件</span>";
        view.appendChild(empty);
        return;
      }
      for (const event of events) {
        const row = document.createElement("div");
        row.className = "timeline-item";
        const time = document.createElement("strong");
        time.textContent = event.time || "-";
        const text = document.createElement("span");
        text.textContent = event.text || "";
        row.appendChild(time);
        row.appendChild(text);
        view.appendChild(row);
      }
      if (atBottom) view.scrollTop = view.scrollHeight;
    }

    function renderChanges(data) {
      const view = $("changesView");
      view.innerHTML = "";

      const summary = document.createElement("div");
      summary.className = "changes-summary";
      summary.textContent = data.is_git_repo
        ? `${data.files.length} 个变更文件`
        : "当前项目目录不是 Git 仓库";
      const refresh = document.createElement("button");
      refresh.className = "secondary";
      refresh.type = "button";
      refresh.textContent = "刷新";
      refresh.addEventListener("click", () => refreshChanges().catch(e => setToast(e.message)));
      summary.appendChild(refresh);
      if (data.is_git_repo) {
        if (data.selected_file) {
          const stageFile = document.createElement("button");
          stageFile.className = "secondary";
          stageFile.type = "button";
          stageFile.textContent = "暂存文件";
          stageFile.addEventListener("click", () => gitAction("stage-file", data.selected_file).catch(e => setToast(e.message)));
          summary.appendChild(stageFile);

          const unstageFile = document.createElement("button");
          unstageFile.className = "secondary";
          unstageFile.type = "button";
          unstageFile.textContent = "取消暂存";
          unstageFile.addEventListener("click", () => gitAction("unstage-file", data.selected_file).catch(e => setToast(e.message)));
          summary.appendChild(unstageFile);
        }

        const auth = document.createElement("button");
        auth.className = "secondary";
        auth.type = "button";
        auth.textContent = "认证检查";
        auth.addEventListener("click", () => gitAction("auth-check").catch(e => setToast(e.message)));
        summary.appendChild(auth);

        const message = document.createElement("button");
        message.className = "secondary";
        message.type = "button";
        message.textContent = "生成提交说明";
        message.addEventListener("click", () => gitAction("message").catch(e => setToast(e.message)));
        summary.appendChild(message);

        const commitStaged = document.createElement("button");
        commitStaged.type = "button";
        commitStaged.textContent = "提交已暂存";
        commitStaged.disabled = !data.staged_count;
        commitStaged.addEventListener("click", () => gitAction("commit-staged").catch(e => setToast(e.message)));
        summary.appendChild(commitStaged);

        const commitAll = document.createElement("button");
        commitAll.className = "secondary";
        commitAll.type = "button";
        commitAll.textContent = "提交全部";
        commitAll.disabled = !data.files.length;
        commitAll.addEventListener("click", () => gitAction("commit").catch(e => setToast(e.message)));
        summary.appendChild(commitAll);

        const pull = document.createElement("button");
        pull.className = "secondary";
        pull.type = "button";
        pull.textContent = "拉取";
        pull.addEventListener("click", () => gitAction("pull").catch(e => setToast(e.message)));
        summary.appendChild(pull);

        const push = document.createElement("button");
        push.className = "secondary";
        push.type = "button";
        push.textContent = "推送";
        push.addEventListener("click", () => gitAction("push").catch(e => setToast(e.message)));
        summary.appendChild(push);
      }
      view.appendChild(summary);

      const layout = document.createElement("div");
      layout.className = "changes-layout";
      const list = document.createElement("div");
      list.className = "file-list";
      for (const file of data.files) {
        const row = document.createElement("div");
        row.className = "file-row" + (file.path === data.selected_file ? " active" : "");
        row.addEventListener("click", () => refreshChanges(file.path).catch(e => setToast(e.message)));
        const status = document.createElement("strong");
        status.textContent = file.status;
        const path = document.createElement("span");
        path.textContent = file.path;
        row.appendChild(status);
        row.appendChild(path);
        list.appendChild(row);
      }
      layout.appendChild(list);

      const diff = document.createElement("pre");
      diff.className = "diff";
      diff.textContent = data.diff || "没有可显示的 diff。";
      layout.appendChild(diff);
      view.appendChild(layout);

      const gitSummary = document.createElement("div");
      gitSummary.className = "git-summary";
      for (const item of data.summary || []) {
        const box = document.createElement("div");
        box.className = "summary-box";
        box.textContent = item;
        gitSummary.appendChild(box);
      }
      view.appendChild(gitSummary);
    }

    async function request(path, options = {}) {
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok || data.ok === false) throw new Error(data.error || "请求失败");
      return data;
    }

    async function loadConfig() {
      const data = await request("/api/config");
      $("codexCmd").value = data.config.codex_cmd || "codex";
      $("projectDir").value = data.config.project_dir || "";
      $("codexSandbox").value = data.config.codex_sandbox || "read-only";
      $("codexApprovalPolicy").value = data.config.codex_approval_policy || "never";
      setModelSelection(data.config.codex_model || "");
      $("codexReasoningEffort").value = data.config.codex_reasoning_effort || "";
      $("codexTimeout").value = data.config.codex_timeout || "120";
      $("codexSearch").checked = Boolean(data.config.codex_search);
      $("autoInstall").checked = data.config.auto_install_deps !== false;
      $("apiKey").value = "";
      $("apiKeyHint").textContent = data.config.has_openai_api_key
        ? "已保存密钥；留空保存时会继续沿用。"
        : "未保存密钥；也可以先在终端执行 codex --login。";
      $("configPath").textContent = data.config_path;
    }

    async function loadProjects() {
      const data = await request("/api/projects");
      const select = $("projectSelect");
      const current = $("projectDir").value;
      select.innerHTML = '<option value="">选择常用项目目录</option>';
      for (const project of data.projects || []) {
        const option = document.createElement("option");
        option.value = project.path;
        option.textContent = project.label;
        if (project.path === current) option.selected = true;
        select.appendChild(option);
      }
    }

    async function saveConfig() {
      setToast("保存中...");
      const payload = {
        codex_cmd: $("codexCmd").value.trim() || "codex",
        project_dir: $("projectDir").value.trim(),
        codex_sandbox: $("codexSandbox").value,
        codex_approval_policy: $("codexApprovalPolicy").value,
        codex_model: $("codexModel").value.trim(),
        codex_reasoning_effort: $("codexReasoningEffort").value,
        codex_timeout: $("codexTimeout").value.trim(),
        codex_search: $("codexSearch").checked,
        auto_install_deps: $("autoInstall").checked,
        openai_api_key: $("apiKey").value.trim()
      };
      const data = await request("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      $("apiKey").value = "";
      $("apiKeyHint").textContent = data.has_openai_api_key
        ? "已保存密钥；留空保存时会继续沿用。"
        : "未保存密钥；也可以先在终端执行 codex --login。";
      setToast("配置已保存");
    }

    async function refreshStatus() {
      const data = await request("/api/status");
      setStatus(data);
    }

    async function refreshLogs() {
      const data = await request("/api/logs");
      const box = $("logs");
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      box.textContent = data.logs.join("");
      if (atBottom) box.scrollTop = box.scrollHeight;
      if (data.weixin_login_success && !data.running && autoStartAfterWeixinLogin) {
        autoStartAfterWeixinLogin = false;
        setToast("微信登录成功，正在启动机器人");
        await startBot();
      }
    }

    async function refreshChat() {
      const data = await request("/api/chat");
      renderChat(data.messages || [], Boolean(data.codex_running));
    }

    async function refreshSessions() {
      const data = await request("/api/sessions");
      const select = $("sessionSelect");
      currentSessions = data.sessions || [];
      activeSessionId = data.active_session_id || "";
      select.innerHTML = "";
      for (const session of currentSessions) {
        const option = document.createElement("option");
        option.value = session.id;
        const thread = session.codex_session_id ? " · Codex 线程" : "";
        option.textContent = `${session.title} (${session.message_count})${thread}`;
        if (session.id === data.active_session_id) option.selected = true;
        select.appendChild(option);
      }
      updateSessionMeta();
    }

    async function createSession() {
      await request("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "new" })
      });
      await refreshSessions();
      await refreshChat();
      setToast("已新建会话");
    }

    async function switchSession() {
      const sessionId = $("sessionSelect").value;
      if (!sessionId) return;
      await request("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "switch", session_id: sessionId })
      });
      await refreshSessions();
      await refreshChat();
    }

    async function deleteSession() {
      const sessionId = $("sessionSelect").value;
      if (!sessionId) return;
      await request("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "delete", session_id: sessionId })
      });
      await refreshSessions();
      await refreshChat();
      setToast("已删除会话");
    }

    async function exportSession() {
      const data = await request("/api/session-export");
      const blob = new Blob([data.markdown || ""], { type: "text/markdown;charset=utf-8" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = data.filename || "codex-session.md";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(link.href);
      setToast("会话已导出");
    }

    async function refreshHealth() {
      const data = await request("/api/health");
      setStatusValue("codexStatus", data.codex.label, data.codex.ok ? "ok" : "bad");
      setStatusValue("weixinStatus", data.weixin.label, data.weixin.ok ? "ok" : "bad");
      setStatusValue("xcmdStatus", data.x_cmd.label, data.x_cmd.ok ? "ok" : "bad");
      setStatusValue("nodeStatus", data.node.label, data.node.ok ? "ok" : "bad");
      setStatusValue("gitStatus", data.git.label, data.git.ok ? "ok" : "warn");
    }

    async function refreshTaskState() {
      const data = await request("/api/task");
      $("taskState").textContent = data.label || data.state || "空闲";
      $("taskDetail").textContent = data.detail || "-";
      renderTimeline(data.events || []);
      const runningStates = new Set(["queued", "codex-running", "stopping", "bot-starting", "bot-stopping"]);
      const terminalStates = new Set(["done", "error", "stopped", "idle"]);
      const wasRunning = runningStates.has(lastTaskState);
      const isTerminal = terminalStates.has(data.state || "");
      lastTaskState = data.state || "idle";
      if (wasRunning && isTerminal && !refreshAfterTaskDone) {
        refreshAfterTaskDone = true;
        try {
          await refreshSessions();
          await refreshChat();
          await refreshLogs();
          await refreshChanges();
        } finally {
          refreshAfterTaskDone = false;
        }
      }
    }

    async function refreshChanges() {
      const fileArg = arguments.length > 0 ? arguments[0] : "";
      const suffix = fileArg ? `?file=${encodeURIComponent(fileArg)}` : "";
      const data = await request("/api/changes" + suffix);
      renderChanges(data);
    }

    async function gitAction(action, file = "") {
      let message = "";
      if (action === "commit" || action === "commit-staged") {
        message = prompt("提交说明", "");
        if (message === null) return;
        message = message.trim();
        if (!message) {
          setToast("请输入提交说明");
          return;
        }
      }
      if ((action === "pull" || action === "push") && !confirm(action === "pull" ? "确认拉取当前项目？" : "确认推送当前项目？")) {
        return;
      }
      setToast("Git 操作执行中...");
      const data = await request("/api/git-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, message, file })
      });
      if (action === "message") {
        const suggested = data.message || "";
        try {
          await navigator.clipboard.writeText(suggested);
          setToast("提交说明已复制");
        } catch (_) {
          prompt("提交说明", suggested);
          setToast("已生成提交说明");
        }
      } else {
        setToast(data.ok ? "Git 操作完成" : "Git 操作失败");
      }
      await refreshLogs();
      await refreshChanges();
      await refreshTaskState();
    }

    async function startBot() {
      setToast("启动中...");
      const data = await request("/api/start", { method: "POST" });
      if (data.codex_login_required) {
        setToast("需要 Codex 登录，请查看运行日志");
        await refreshLogs();
        return;
      }
      if (data.weixin_login_required) {
        autoStartAfterWeixinLogin = true;
        setToast("Web Codex 可继续使用；微信机器人需要扫码登录");
        await refreshLogs();
        return;
      }
      setStatus(data);
      setToast("已启动");
      await refreshLogs();
    }

    async function stopBot() {
      setToast("停止中...");
      const data = await request("/api/stop", { method: "POST" });
      setStatus(data);
      setToast("已停止");
      await refreshLogs();
    }

    async function startWeixinLoginOnly() {
      autoStartAfterWeixinLogin = false;
      setToast("正在启动微信登录...");
      await request("/api/weixin-login", { method: "POST" });
      await refreshLogs();
      await refreshHealth();
      setActiveTab("log");
      setToast("请按日志提示完成微信登录");
    }

    async function sendCodexPrompt(promptOverride = "") {
      const prompt = (promptOverride || $("codexPrompt").value).trim();
      if (!prompt) {
        setToast("请输入指令");
        return;
      }
      setToast("已发送给 Codex");
        setCodexTaskRunning(true);
      try {
        await request("/api/codex", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompt,
            use_context: $("useConversationContext").checked,
            sync_to_weixin: $("syncReplyToWeixin").checked
          })
        });
        if (!promptOverride) $("codexPrompt").value = "";
        setActiveTab("chat");
        await refreshSessions();
        await refreshChat();
        await refreshLogs();
        await refreshChanges();
      } finally {
        await refreshChat();
      }
    }

    async function retryCodexPrompt() {
      if (!lastUserPrompt) {
        setToast("没有可重试的指令");
        return;
      }
      await sendCodexPrompt(lastUserPrompt);
    }

    async function stopCodexPrompt() {
      setToast("正在停止 Codex 任务...");
      await request("/api/codex-stop", { method: "POST" });
      await refreshChat();
      await refreshLogs();
      setToast("已请求停止");
    }

    async function clearHistory() {
      await request("/api/clear", { method: "POST" });
      $("logs").textContent = "";
      await refreshChat();
      await refreshLogs();
      setToast("聊天和日志已清空");
    }

    $("reloadBtn").addEventListener("click", () => loadConfig().catch(e => setToast(e.message)));
    $("saveBtn").addEventListener("click", () => saveConfig().catch(e => setToast(e.message)));
    $("startBtn").addEventListener("click", () => startBot().catch(e => setToast(e.message)));
    $("weixinLoginBtn").addEventListener("click", () => startWeixinLoginOnly().catch(e => setToast(e.message)));
    $("stopBtn").addEventListener("click", () => stopBot().catch(e => setToast(e.message)));
    $("sendCodexBtn").addEventListener("click", () => sendCodexPrompt().catch(e => setToast(e.message)));
    $("retryCodexBtn").addEventListener("click", () => retryCodexPrompt().catch(e => setToast(e.message)));
    $("stopCodexBtn").addEventListener("click", () => stopCodexPrompt().catch(e => setToast(e.message)));
    $("newSessionBtn").addEventListener("click", () => createSession().catch(e => setToast(e.message)));
    $("exportSessionBtn").addEventListener("click", () => exportSession().catch(e => setToast(e.message)));
    $("deleteSessionBtn").addEventListener("click", () => deleteSession().catch(e => setToast(e.message)));
    $("sessionSelect").addEventListener("change", () => switchSession().catch(e => setToast(e.message)));
    $("chatTab").addEventListener("click", () => setActiveTab("chat"));
    $("logTab").addEventListener("click", () => setActiveTab("log"));
    $("changesTab").addEventListener("click", () => {
      setActiveTab("changes");
      refreshChanges().catch(e => setToast(e.message));
    });
    $("projectSelect").addEventListener("change", () => {
      if ($("projectSelect").value) $("projectDir").value = $("projectSelect").value;
    });
    $("codexModelSelect").addEventListener("change", syncModelInputFromSelect);
    $("codexPrompt").addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        sendCodexPrompt().catch(e => setToast(e.message));
      }
    });
    $("clearLogBtn").addEventListener("click", () => clearHistory().catch(e => setToast(e.message)));

    setActiveTab("chat");
    Promise.all([loadConfig(), loadProjects(), refreshSessions(), refreshStatus(), refreshLogs(), refreshChat(), refreshHealth(), refreshTaskState(), refreshChanges()]).catch(e => setToast(e.message));
    setInterval(() => refreshStatus().catch(() => {}), 2000);
    setInterval(() => refreshLogs().catch(() => {}), 1500);
    setInterval(() => refreshChat().catch(() => {}), 1500);
    setInterval(() => refreshHealth().catch(() => {}), 5000);
    setInterval(() => refreshTaskState().catch(() => {}), 1500);
  </script>
</body>
</html>
"""


def read_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_config(data):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temp_path, CONFIG_FILE)


def new_session(title=None):
    session_id = str(int(time.time() * 1000))
    return {
        "id": session_id,
        "title": title or f"会话 {time.strftime('%H:%M:%S')}",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "codex_session_id": "",
        "project_dir": "",
        "messages": [],
    }


def sync_active_messages():
    global chat_messages
    session = chat_sessions.setdefault(active_session_id, {
        "id": active_session_id,
        "title": "默认会话",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "messages": [],
    })
    chat_messages = session.setdefault("messages", [])


def remember_imported_weixin_events():
    imported_weixin_event_ids.clear()
    for session in chat_sessions.values():
        for message in session.get("messages") or []:
            event_id = message.get("event_id")
            if isinstance(event_id, str) and event_id:
                imported_weixin_event_ids.add(event_id)
                if event_id.endswith("-status"):
                    imported_weixin_event_ids.add(event_id[:-7])


def load_state():
    global active_session_id, chat_messages, chat_sessions
    if not STATE_FILE.exists():
        chat_sessions = {
            "default": {
                "id": "default",
                "title": "默认会话",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "messages": [],
            }
        }
        active_session_id = "default"
        sync_active_messages()
        return
    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return

    if not isinstance(data, dict):
        return

    raw_sessions = data.get("sessions")
    if not isinstance(raw_sessions, dict):
        raw_sessions = {
            "default": {
                "id": "default",
                "title": "默认会话",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "messages": data.get("chat_messages") if isinstance(data.get("chat_messages"), list) else [],
            }
        }

    parsed_sessions = {}
    for session_id, session in raw_sessions.items():
        if not isinstance(session, dict):
            continue
        messages = session.get("messages")
        if not isinstance(messages, list):
            messages = []
        valid_messages = []
        for item in messages[-MAX_CHAT_MESSAGES:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            text = item.get("text")
            if not isinstance(role, str) or not isinstance(text, str):
                continue
            valid_messages.append({
                "role": role,
                "label": str(item.get("label") or role),
                "text": text,
                "time": str(item.get("time") or ""),
                "source": str(item.get("source") or ""),
                "event_id": str(item.get("event_id") or ""),
            })
        session_id = str(session.get("id") or session_id)
        parsed_sessions[session_id] = {
            "id": session_id,
            "title": str(session.get("title") or "默认会话"),
            "created_at": str(session.get("created_at") or ""),
            "codex_session_id": str(session.get("codex_session_id") or ""),
            "project_dir": str(session.get("project_dir") or ""),
            "messages": valid_messages,
        }

    with chat_lock:
        chat_sessions = parsed_sessions or {}
        if not chat_sessions:
            chat_sessions["default"] = {
                "id": "default",
                "title": "默认会话",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "messages": [],
            }
        active_session_id = str(data.get("active_session_id") or next(iter(chat_sessions)))
        if active_session_id not in chat_sessions:
            active_session_id = next(iter(chat_sessions))
        sync_active_messages()
        remember_imported_weixin_events()


def save_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    with chat_lock:
        if active_session_id in chat_sessions:
            chat_sessions[active_session_id]["messages"] = list(chat_messages[-MAX_CHAT_MESSAGES:])
        sessions_copy = {
            session_id: {
                **session,
                "messages": list(session.get("messages", [])[-MAX_CHAT_MESSAGES:]),
            }
            for session_id, session in chat_sessions.items()
        }
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump({
                "active_session_id": active_session_id,
                "sessions": sessions_copy,
            }, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temp_path, STATE_FILE)
    except Exception:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def normalize_codex_sandbox(value):
    if not isinstance(value, str):
        return "read-only"
    normalized = value.strip()
    aliases = {
        "readonly": "read-only",
        "只读": "read-only",
        "read_only": "read-only",
        "write": "workspace-write",
        "writable": "workspace-write",
        "可写": "workspace-write",
        "workspace_write": "workspace-write",
    }
    normalized = aliases.get(normalized.lower(), normalized)
    if normalized not in VALID_CODEX_SANDBOXES:
        raise ValueError(f"不支持的 Codex 沙箱模式：{value}")
    return normalized


def normalize_timeout(value):
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 120
    return max(10, min(timeout, 1800))


def normalize_reasoning_effort(value):
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    aliases = {
        "低": "low",
        "中": "medium",
        "高": "high",
        "超高": "xhigh",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_REASONING_EFFORTS:
        raise ValueError(f"不支持的推理深度：{value}")
    return normalized


def normalize_approval_policy(value):
    if not isinstance(value, str):
        return "never"
    normalized = value.strip().lower()
    aliases = {
        "auto": "never",
        "自动": "never",
        "ask": "on-request",
        "request": "on-request",
        "确认": "on-request",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_APPROVAL_POLICIES:
        raise ValueError(f"不支持的 Codex 审批模式：{value}")
    return normalized


def public_config():
    config = read_config()
    api_key = str(config.get("openai_api_key") or "").strip()
    return {
        "codex_cmd": config.get("codex_cmd") or "codex",
        "project_dir": config.get("project_dir") or str(SCRIPT_DIR),
        "codex_sandbox": normalize_codex_sandbox(config.get("codex_sandbox") or "read-only"),
        "codex_approval_policy": normalize_approval_policy(config.get("codex_approval_policy") or "never"),
        "codex_model": config.get("codex_model") or "",
        "codex_reasoning_effort": normalize_reasoning_effort(config.get("codex_reasoning_effort") or ""),
        "codex_timeout": normalize_timeout(config.get("codex_timeout") or 120),
        "codex_search": bool(config.get("codex_search")),
        "auto_install_deps": config.get("auto_install_deps", True),
        "has_openai_api_key": bool(api_key),
    }


def current_project_dir(config=None):
    config = config or read_config()
    return Path(str(config.get("project_dir") or SCRIPT_DIR)).expanduser().resolve()


def run_quick(command, cwd=None, timeout=8):
    try:
        env = None
        if command and command[0] == "git":
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return None, str(exc)
    return result, None


def command_version(command):
    result, error = run_quick(command, timeout=5)
    if error or result is None or result.returncode != 0:
        return None
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return output[0].strip() if output else "已安装"


def health_status():
    config = read_config()
    codex_cmd = str(config.get("codex_cmd") or "codex").strip() or "codex"
    project_dir = current_project_dir(config)

    codex_ok = is_codex_logged_in(config)
    weixin_ok = is_weixin_logged_in() or has_recent_weixin_login_success()
    xcmd_version = command_version([X_CMD, "--version"]) or ("已安装" if shutil.which(X_CMD) else None)
    node_version = command_version(["node", "--version"])
    npm_version = command_version(["npm", "--version"])
    git_result, _ = run_quick(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_dir, timeout=5)
    git_ok = bool(git_result and git_result.returncode == 0 and "true" in (git_result.stdout or ""))

    return {
        "ok": True,
        "codex": {"ok": codex_ok, "label": "已登录" if codex_ok else "未登录"},
        "weixin": {"ok": weixin_ok, "label": "已登录" if weixin_ok else "未登录"},
        "x_cmd": {"ok": bool(xcmd_version), "label": xcmd_version or "未安装"},
        "node": {
            "ok": bool(node_version and npm_version),
            "label": f"{node_version or 'node?'} / {npm_version or 'npm?'}",
        },
        "git": {"ok": git_ok, "label": "Git 仓库" if git_ok else "非 Git 仓库"},
    }


def safe_git_path(path):
    if not path:
        return ""
    normalized = path.replace("\\", "/").strip()
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        return ""
    return normalized


def git_changes(file_path=""):
    project_dir = current_project_dir()
    selected_file = safe_git_path(file_path)
    inside, error = run_quick(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_dir, timeout=5)
    if error or not inside or inside.returncode != 0:
        return {
            "ok": True,
            "is_git_repo": False,
            "files": [],
            "diff": "",
            "selected_file": "",
            "summary": [],
        }

    status_result, _ = run_quick(["git", "status", "--short"], cwd=project_dir, timeout=8)

    files = []
    staged_count = 0
    unstaged_count = 0
    untracked_count = 0
    for line in (status_result.stdout if status_result else "").splitlines():
        if not line:
            continue
        status_code = line[:2]
        path = line[3:].strip()
        if status_code == "??":
            untracked_count += 1
        else:
            if status_code[0] != " ":
                staged_count += 1
            if status_code[1] != " ":
                unstaged_count += 1
        files.append({"status": status_code.strip() or "?", "path": path})

    if selected_file and not any(item["path"] == selected_file for item in files):
        selected_file = ""
    if not selected_file and files:
        selected_file = files[0]["path"]

    diff_parts = []
    if selected_file:
        status = next((item["status"] for item in files if item["path"] == selected_file), "")
        if status == "??":
            target = project_dir / selected_file
            try:
                content = target.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                content = f"无法读取未跟踪文件：{exc}"
            if len(content) > 20000:
                content = content[:20000] + "\n... 文件内容已截断 ..."
            diff_parts.append(f"未跟踪文件：{selected_file}\n\n{content}")
        else:
            staged_diff_result, _ = run_quick(["git", "diff", "--cached", "--", selected_file], cwd=project_dir, timeout=10)
            unstaged_stat_result, _ = run_quick(["git", "diff", "--stat", "--", selected_file], cwd=project_dir, timeout=8)
            unstaged_diff_result, _ = run_quick(["git", "diff", "--", selected_file], cwd=project_dir, timeout=10)
            if staged_diff_result and staged_diff_result.stdout.strip():
                staged_diff = staged_diff_result.stdout
                if len(staged_diff) > 20000:
                    staged_diff = staged_diff[:20000] + "\n... staged diff 已截断 ..."
                diff_parts.append("[已暂存]\n" + staged_diff.strip())
            if unstaged_stat_result and unstaged_stat_result.stdout.strip():
                diff_parts.append(unstaged_stat_result.stdout.strip())
            if unstaged_diff_result and unstaged_diff_result.stdout.strip():
                unstaged_diff = unstaged_diff_result.stdout
                if len(unstaged_diff) > 20000:
                    unstaged_diff = unstaged_diff[:20000] + "\n... diff 已截断 ..."
                diff_parts.append("[未暂存]\n" + unstaged_diff.strip())

    return {
        "ok": True,
        "is_git_repo": True,
        "files": files,
        "diff": "\n\n".join(diff_parts),
        "selected_file": selected_file,
        "staged_count": staged_count,
        "unstaged_count": unstaged_count,
        "untracked_count": untracked_count,
        "summary": [
            f"已暂存 {staged_count}",
            f"未暂存 {unstaged_count}",
            f"未跟踪 {untracked_count}",
        ],
    }


def git_output(result):
    if not result:
        return ""
    return "\n".join(part.strip() for part in [result.stdout, result.stderr] if part and part.strip())


def ensure_git_repo(project_dir):
    inside, error = run_quick(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_dir, timeout=5)
    if error or not inside or inside.returncode != 0:
        raise ValueError("当前项目目录不是 Git 仓库")


def git_status_files(project_dir):
    status_result, error = run_quick(["git", "status", "--short"], cwd=project_dir, timeout=8)
    if error or status_result is None:
        raise ValueError(error or "无法读取 Git 状态")
    files = []
    for line in (status_result.stdout or "").splitlines():
        if line.strip():
            files.append(line[3:].strip() or line.strip())
    return files


def git_staged_files(project_dir):
    status_result, error = run_quick(["git", "diff", "--cached", "--name-only"], cwd=project_dir, timeout=8)
    if error or status_result is None:
        raise ValueError(error or "无法读取已暂存文件")
    return [line.strip() for line in (status_result.stdout or "").splitlines() if line.strip()]


def suggest_commit_message(project_dir):
    files = git_status_files(project_dir)
    if not files:
        return "chore: no changes"
    if len(files) == 1:
        name = Path(files[0]).name or files[0]
        return f"chore: update {name}"
    roots = sorted({path.split("/", 1)[0] for path in files if path})
    if len(roots) == 1:
        return f"chore: update {roots[0]} changes"
    return f"chore: update {len(files)} files"


def git_config_value(project_dir, key):
    result, _ = run_quick(["git", "config", "--get", key], cwd=project_dir, timeout=5)
    if result and result.returncode == 0:
        return (result.stdout or "").strip()
    return ""


def git_auth_check(project_dir):
    ensure_git_repo(project_dir)
    remote_result, _ = run_quick(["git", "remote", "-v"], cwd=project_dir, timeout=5)
    branch_result, _ = run_quick(["git", "branch", "--show-current"], cwd=project_dir, timeout=5)
    user_name = git_config_value(project_dir, "user.name")
    user_email = git_config_value(project_dir, "user.email")
    remote_output = (remote_result.stdout if remote_result else "").strip()
    branch = (branch_result.stdout if branch_result else "").strip()

    append_log("[Git] 认证检查\n")
    append_log(f"[Git] 当前分支：{branch or '未知'}\n")
    append_log(f"[Git] user.name：{user_name or '未配置'}\n")
    append_log(f"[Git] user.email：{user_email or '未配置'}\n")
    append_log(f"[Git] remote：\n{remote_output or '未配置远程仓库'}\n")

    checks = []
    if not user_name:
        checks.append("未配置 user.name")
    if not user_email:
        checks.append("未配置 user.email")
    if not remote_output:
        checks.append("未配置 remote")

    remote_name = "origin"
    remote_names = []
    if remote_output:
        for line in remote_output.splitlines():
            parts = line.split()
            if parts:
                remote_names.append(parts[0])
        if remote_names:
            remote_name = remote_names[0]

    ls_result = None
    if remote_output:
        add_task_event("Git 正在检查远程认证")
        ls_result, ls_error = run_quick(["git", "ls-remote", "--heads", remote_name], cwd=project_dir, timeout=20)
        output = git_output(ls_result)
        if ls_error or ls_result is None or ls_result.returncode != 0:
            detail = ls_error or output or "git ls-remote 失败"
            append_log(f"[Git] 远程认证检查失败：{detail}\n")
            checks.append("远程访问失败，可能需要 SSH key、Token 或凭据管理器")
        else:
            append_log("[Git] 远程访问正常。\n")

    if checks:
        append_log("[Git] 建议：\n")
        if "未配置 user.name" in checks:
            append_log('  git config user.name "你的名字"\n')
        if "未配置 user.email" in checks:
            append_log('  git config user.email "你的邮箱"\n')
        if any("远程访问失败" in item for item in checks):
            append_log("  建议使用 SSH key，或使用 Git credential helper 保存 Token。\n")
        add_task_event("Git 认证检查发现问题")
        return {"ok": True, "passed": False, "checks": checks}

    add_task_event("Git 认证检查通过")
    return {"ok": True, "passed": True, "checks": []}


def run_git_file_action(project_dir, action, file_path):
    safe_path = safe_git_path(file_path)
    if not safe_path:
        raise ValueError("文件路径无效")

    if action == "stage-file":
        add_task_event(f"Git 正在暂存文件：{safe_path}")
        result, error = run_quick(["git", "add", "--", safe_path], cwd=project_dir, timeout=30)
        action_label = "暂存文件"
    elif action == "unstage-file":
        add_task_event(f"Git 正在取消暂存：{safe_path}")
        result, error = run_quick(["git", "restore", "--staged", "--", safe_path], cwd=project_dir, timeout=30)
        action_label = "取消暂存"
    else:
        raise ValueError("不支持的文件操作")

    output = git_output(result)
    if output:
        append_log(output + "\n")
    if error or result is None or result.returncode != 0:
        raise ValueError(error or output or f"Git {action_label}失败")
    add_task_event(f"Git {action_label}完成：{safe_path}")
    return {"ok": True, "output": output, "file": safe_path}


def run_git_action(action, message="", file_path=""):
    project_dir = current_project_dir()
    ensure_git_repo(project_dir)
    action = str(action or "").strip()
    append_log(f"[Git] 操作：{action}\n")

    if action in {"stage-file", "unstage-file"}:
        return run_git_file_action(project_dir, action, file_path)

    if action == "auth-check":
        return git_auth_check(project_dir)

    if action == "message":
        suggested = suggest_commit_message(project_dir)
        append_log(f"[Git] 建议提交说明：{suggested}\n")
        add_task_event("已生成提交说明")
        return {"ok": True, "message": suggested}

    if action == "commit":
        message = str(message or "").strip()
        if not message:
            raise ValueError("提交说明不能为空")
        files = git_status_files(project_dir)
        if not files:
            raise ValueError("没有可提交的变更")

        add_task_event("Git 正在暂存全部变更")
        add_result, add_error = run_quick(["git", "add", "-A"], cwd=project_dir, timeout=30)
        append_log(git_output(add_result) + ("\n" if git_output(add_result) else ""))
        if add_error or add_result is None or add_result.returncode != 0:
            raise ValueError(add_error or git_output(add_result) or "git add 失败")

        add_task_event("Git 正在提交")
        commit_result, commit_error = run_quick(["git", "commit", "-m", message], cwd=project_dir, timeout=60)
        output = git_output(commit_result)
        if output:
            append_log(output + "\n")
        if commit_error or commit_result is None or commit_result.returncode != 0:
            raise ValueError(commit_error or output or "git commit 失败")
        add_task_event("Git 提交完成")
        return {"ok": True, "output": output}

    if action == "commit-staged":
        message = str(message or "").strip()
        if not message:
            raise ValueError("提交说明不能为空")
        files = git_staged_files(project_dir)
        if not files:
            raise ValueError("没有已暂存的变更")

        add_task_event("Git 正在提交已暂存变更")
        commit_result, commit_error = run_quick(["git", "commit", "-m", message], cwd=project_dir, timeout=60)
        output = git_output(commit_result)
        if output:
            append_log(output + "\n")
        if commit_error or commit_result is None or commit_result.returncode != 0:
            raise ValueError(commit_error or output or "git commit 失败")
        add_task_event("Git 已暂存变更提交完成")
        return {"ok": True, "output": output}

    if action == "pull":
        add_task_event("Git 正在拉取")
        result, error = run_quick(["git", "pull", "--ff-only"], cwd=project_dir, timeout=120)
    elif action == "push":
        add_task_event("Git 正在推送")
        result, error = run_quick(["git", "push"], cwd=project_dir, timeout=120)
    else:
        raise ValueError("不支持的 Git 操作")

    output = git_output(result)
    if output:
        append_log(output + "\n")
    if error or result is None or result.returncode != 0:
        raise ValueError(error or output or f"git {action} 失败")
    add_task_event(f"Git {action} 完成")
    return {"ok": True, "output": output}


def list_projects():
    config = read_config()
    current = current_project_dir(config)
    roots = [
        SCRIPT_DIR,
        current,
        Path.home() / "Workspace",
        Path.home() / "workspace",
    ]

    seen = set()
    projects = []
    for root in roots:
        root = root.expanduser().resolve()
        if root.is_dir() and str(root) not in seen:
            seen.add(str(root))
            projects.append(root)

        if root.name.lower() == "workspace" and root.is_dir():
            try:
                children = sorted([path for path in root.iterdir() if path.is_dir()], key=lambda item: item.name.lower())
            except OSError:
                children = []
            for child in children[:80]:
                if str(child) in seen:
                    continue
                seen.add(str(child))
                projects.append(child)

    return {
        "ok": True,
        "projects": [
            {"path": str(path), "label": path.name or str(path)}
            for path in projects
        ],
    }


def clear_history():
    with chat_lock:
        chat_messages.clear()
        if active_session_id in chat_sessions:
            chat_sessions[active_session_id]["messages"] = []
    save_state()
    log_lines.clear()
    while True:
        try:
            log_queue.get_nowait()
        except queue.Empty:
            break
    return {"ok": True}


def list_sessions():
    with chat_lock:
        sessions = [
            {
                "id": session_id,
                "title": session.get("title") or "未命名会话",
                "message_count": len(session.get("messages") or []),
                "codex_session_id": session.get("codex_session_id") or "",
                "project_dir": session.get("project_dir") or "",
            }
            for session_id, session in chat_sessions.items()
        ]
        return {
            "ok": True,
            "active_session_id": active_session_id,
            "sessions": sessions,
        }


def create_session():
    global active_session_id
    session = new_session()
    with chat_lock:
        if active_session_id in chat_sessions:
            chat_sessions[active_session_id]["messages"] = chat_messages
        chat_sessions[session["id"]] = session
        active_session_id = session["id"]
        sync_active_messages()
    save_state()
    return list_sessions()


def switch_session(session_id):
    global active_session_id
    with chat_lock:
        if session_id not in chat_sessions:
            raise ValueError("会话不存在")
        if active_session_id in chat_sessions:
            chat_sessions[active_session_id]["messages"] = chat_messages
        active_session_id = session_id
        sync_active_messages()
    save_state()
    return list_sessions()


def delete_session(session_id):
    global active_session_id
    with chat_lock:
        if session_id in chat_sessions and len(chat_sessions) > 1:
            del chat_sessions[session_id]
        if active_session_id not in chat_sessions:
            active_session_id = next(iter(chat_sessions))
        sync_active_messages()
    save_state()
    return list_sessions()


def export_active_session():
    with chat_lock:
        session = chat_sessions.get(active_session_id, {})
        title = session.get("title") or "Codex 会话"
        messages = list(session.get("messages") or [])

    lines = [
        f"# {title}",
        "",
        f"- 导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 会话 ID：{active_session_id}",
        "",
    ]
    for item in messages:
        label = item.get("label") or item.get("role") or "消息"
        text = item.get("text") or ""
        msg_time = item.get("time") or ""
        lines.extend([
            f"## {label} {msg_time}".rstrip(),
            "",
            text,
            "",
        ])

    filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", title).strip("-") or "codex-session"
    return {
        "ok": True,
        "filename": f"{filename}.md",
        "markdown": "\n".join(lines).rstrip() + "\n",
    }


def get_active_codex_session(project_dir):
    with chat_lock:
        session = chat_sessions.get(active_session_id) or {}
        saved_project_dir = str(session.get("project_dir") or "")
        codex_session_id = str(session.get("codex_session_id") or "")
    if saved_project_dir == str(project_dir) and UUID_RE.match(codex_session_id):
        return codex_session_id
    return ""


def set_active_codex_session(codex_session_id, project_dir):
    if not UUID_RE.match(str(codex_session_id or "")):
        return
    with chat_lock:
        session = chat_sessions.get(active_session_id)
        if not session:
            return
        if session.get("codex_session_id") == codex_session_id and session.get("project_dir") == str(project_dir):
            return
        session["codex_session_id"] = codex_session_id
        session["project_dir"] = str(project_dir)
    save_state()
    add_task_event(f"已绑定 Codex 线程：{codex_session_id[:8]}")


def clear_active_codex_session(reason=""):
    with chat_lock:
        session = chat_sessions.get(active_session_id)
        if not session or not session.get("codex_session_id"):
            return
        session["codex_session_id"] = ""
        session["project_dir"] = ""
    save_state()
    add_task_event(reason or "已清理失效的 Codex 线程")


def append_log(line):
    log_queue.put(line)


def set_task_state(state, label, detail=""):
    with task_state_lock:
        task_state.update({
            "state": state,
            "label": label,
            "detail": detail,
            "updated_at": time.strftime("%H:%M:%S"),
        })


def add_task_event(text):
    with task_events_lock:
        task_events.append({
            "time": time.strftime("%H:%M:%S"),
            "text": text,
        })
        if len(task_events) > MAX_TASK_EVENTS:
            del task_events[:-MAX_TASK_EVENTS]


def get_task_state():
    with task_events_lock:
        events = list(task_events[-MAX_TASK_EVENTS:])
    with task_state_lock:
        return {"ok": True, **task_state, "events": events}


def add_chat_message(role, text, label=None):
    with chat_lock:
        chat_messages.append({
            "role": role,
            "label": label or role,
            "text": text,
            "time": time.strftime("%H:%M:%S"),
        })
        if len(chat_messages) > MAX_CHAT_MESSAGES:
            del chat_messages[:-MAX_CHAT_MESSAGES]
        if active_session_id in chat_sessions:
            chat_sessions[active_session_id]["messages"] = chat_messages
            if role == "user" and chat_sessions[active_session_id].get("title", "").startswith("会话 "):
                chat_sessions[active_session_id]["title"] = text[:32] or chat_sessions[active_session_id]["title"]
    save_state()


def add_weixin_message(event_id, role, text, label, msg_time):
    session = chat_sessions.setdefault("weixin", {
        "id": "weixin",
        "title": "微信会话",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "messages": [],
    })
    messages = session.setdefault("messages", [])
    messages.append({
        "role": role,
        "label": label,
        "text": text,
        "time": msg_time,
        "source": "weixin",
        "event_id": event_id,
    })
    if len(messages) > MAX_CHAT_MESSAGES:
        del messages[:-MAX_CHAT_MESSAGES]
    if active_session_id == "weixin":
        sync_active_messages()


def import_weixin_events():
    if not WEIXIN_EVENT_FILE.exists():
        return 0
    imported = 0
    try:
        lines = WEIXIN_EVENT_FILE.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        append_log(f"[UI] 读取微信同步事件失败：{exc}\n")
        return 0

    with chat_lock:
        for line in lines[-MAX_CHAT_MESSAGES:]:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or "")
            if not event_id or event_id in imported_weixin_event_ids:
                continue
            event_type = str(event.get("type") or "")
            prompt = str(event.get("prompt") or "").strip()
            reply = str(event.get("reply") or "").strip()
            msg_time = str(event.get("time") or time.strftime("%H:%M:%S"))
            weixin_messages = chat_sessions.setdefault("weixin", {
                "id": "weixin",
                "title": "微信会话",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "messages": [],
            }).setdefault("messages", [])
            recent_same_prompt = any(
                item.get("role") == "user" and item.get("text") == prompt
                for item in weixin_messages[-6:]
            )
            if prompt and (event_type != "codex_reply" or not recent_same_prompt):
                add_weixin_message(event_id, "user", prompt, "微信用户", msg_time)
            if event_type == "codex_started":
                add_weixin_message(event_id + "-status", "system", "Codex 正在处理微信指令。", "微信状态", msg_time)
            if reply:
                status_events = {"busy", "status", "stop", "stopped", "reset"}
                role = "system" if event_type in status_events else "assistant"
                label = "微信状态" if event_type in status_events else "Codex / 微信"
                add_weixin_message(event_id, role, reply, label, msg_time)
            imported_weixin_event_ids.add(event_id)
            imported += 1
    if imported:
        save_state()
        add_task_event(f"已同步 {imported} 条微信 Codex 会话")
    return imported


def build_codex_prompt(prompt, use_context=True):
    if not use_context:
        return prompt
    with chat_lock:
        history = [
            item for item in chat_messages[-12:]
            if item.get("role") in {"user", "assistant"} and item.get("text")
        ]

    if not history:
        return prompt

    lines = [
        "你正在一个 Web UI 会话里继续协助用户。",
        "下面是当前会话最近上下文；请基于上下文回答或执行当前请求。",
        "",
        "最近上下文：",
    ]
    for item in history:
        label = "用户" if item["role"] == "user" else "Codex"
        lines.append(f"{label}：{item['text']}")
    lines.extend(["", "当前用户请求：", prompt])
    return "\n".join(lines)


def codex_task_running():
    return codex_lock.locked()


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def append_login_line(line):
    clean_line = strip_ansi(line)
    login_lines.append(clean_line)
    if len(login_lines) > 120:
        del login_lines[:-120]
    append_log(clean_line)


def drain_logs():
    while True:
        try:
            line = log_queue.get_nowait()
        except queue.Empty:
            break
        log_lines.append(line)
    if len(log_lines) > MAX_LOG_LINES:
        del log_lines[:-MAX_LOG_LINES]


def is_weixin_logged_in():
    try:
        result = subprocess.run(
            [X_CMD, "weixin", "bot", "service", "status"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return False

    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return result.returncode == 0 and "alive" in output.lower()


def is_codex_logged_in(config):
    codex_cmd = str(config.get("codex_cmd") or "codex").strip() or "codex"
    try:
        result = subprocess.run(
            [codex_cmd, "login", "status"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return False

    output = "\n".join(part for part in [result.stdout, result.stderr] if part).lower()
    return result.returncode == 0 and "logged in" in output and "not logged in" not in output


def has_recent_weixin_login_success():
    return weixin_login_succeeded or any("login successful" in line.lower() for line in login_lines)


def stream_login_output(process):
    global login_process, weixin_login_succeeded
    assert process.stdout is not None
    for line in process.stdout:
        append_login_line(line)
    process.wait()
    if process.returncode == 0:
        weixin_login_succeeded = True
        add_task_event("微信扫码登录成功")
        append_login_line("\n[UI] 微信登录流程已完成。\n")
    else:
        add_task_event(f"微信登录失败：退出码 {process.returncode}")
        append_login_line(f"\n[UI] 微信登录失败，退出码：{process.returncode}\n")
    with login_lock:
        if login_process is process:
            login_process = None


def start_weixin_login():
    global login_process, weixin_login_succeeded
    with login_lock:
        if login_process and login_process.poll() is None:
            return {"ok": True, "running": True}

        del login_lines[:]
        weixin_login_succeeded = False
        add_task_event("微信登录二维码已输出到运行日志")
        append_login_line("[UI] 正在生成微信登录二维码...\n")
        login_process = subprocess.Popen(
            [X_CMD, "weixin", "login"],
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=stream_login_output, args=(login_process,), daemon=True).start()
        return {"ok": True, "running": True}


def weixin_login_status():
    with login_lock:
        running = login_process is not None and login_process.poll() is None
    return {
        "ok": True,
        "running": running,
        "logged_in": is_weixin_logged_in() or has_recent_weixin_login_success(),
        "login_success": has_recent_weixin_login_success(),
        "lines": list(login_lines),
    }


def stream_codex_login_output(process):
    global codex_login_process
    assert process.stdout is not None
    for line in process.stdout:
        append_log(strip_ansi(line))
    process.wait()
    if process.returncode == 0:
        set_task_state("login-ok", "Codex 已登录", "Codex 登录完成")
    else:
        set_task_state("error", "Codex 登录失败", f"退出码 {process.returncode}")
    append_log(f"\n[UI] Codex 登录进程已退出，退出码：{process.returncode}\n")
    with codex_login_lock:
        if codex_login_process is process:
            codex_login_process = None


def start_codex_login(config):
    global codex_login_process
    with codex_login_lock:
        if codex_login_process and codex_login_process.poll() is None:
            return {"ok": True, "running": True}

        codex_cmd = str(config.get("codex_cmd") or "codex").strip() or "codex"
        api_key = str(config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
        set_task_state("codex-login", "等待 Codex 登录", "请按日志提示完成登录")
        append_log("[UI] Codex CLI 未登录，正在启动 Codex 登录流程...\n")
        if api_key:
            codex_login_process = subprocess.Popen(
                [codex_cmd, "login", "--with-api-key"],
                cwd=str(SCRIPT_DIR),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert codex_login_process.stdin is not None
            codex_login_process.stdin.write(api_key + "\n")
            codex_login_process.stdin.close()
        else:
            codex_login_process = subprocess.Popen(
                [codex_cmd, "login", "--device-auth"],
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        threading.Thread(target=stream_codex_login_output, args=(codex_login_process,), daemon=True).start()
        return {"ok": True, "running": True}


def stream_process_output(process):
    assert process.stdout is not None
    for line in process.stdout:
        append_log(line)
    process.wait()
    set_task_state("idle", "空闲", f"机器人进程退出：{process.returncode}")
    append_log(f"\n[UI] 机器人进程已退出，退出码：{process.returncode}\n")


def process_status():
    global bot_process
    with bot_lock:
        if bot_process and bot_process.poll() is not None:
            bot_process = None
        return {
            "ok": True,
            "running": bot_process is not None,
            "pid": bot_process.pid if bot_process else None,
        }


def start_bot():
    global bot_process
    with bot_lock:
        if bot_process and bot_process.poll() is None:
            return {"ok": True, "running": True, "pid": bot_process.pid}

        config = read_config()
        if not is_codex_logged_in(config):
            start_codex_login(config)
            return {"ok": True, "codex_login_required": True, "running": False, "pid": None}

        if not is_weixin_logged_in() and not has_recent_weixin_login_success():
            append_log("[UI] 微信未登录。Web Codex 仍可直接使用；启动微信机器人需要扫码登录。\n")
            start_weixin_login()
            return {"ok": True, "weixin_login_required": True, "running": False, "pid": None}

        env = os.environ.copy()
        env["WEIXIN_CODEX_CONFIG_FILE"] = str(CONFIG_FILE)
        env["PYTHONUNBUFFERED"] = "1"
        if "auto_install_deps" in config:
            env["WEIXIN_CODEX_AUTO_INSTALL"] = "1" if config.get("auto_install_deps") else "0"
        if config.get("codex_cmd"):
            env["CODEX_CMD"] = str(config["codex_cmd"])
        if config.get("codex_sandbox"):
            env["CODEX_SANDBOX"] = normalize_codex_sandbox(config.get("codex_sandbox"))
        env["CODEX_APPROVAL_POLICY"] = normalize_approval_policy(config.get("codex_approval_policy") or "never")
        if config.get("codex_model"):
            env["CODEX_MODEL"] = str(config["codex_model"])
        codex_reasoning_effort = normalize_reasoning_effort(config.get("codex_reasoning_effort") or "")
        if codex_reasoning_effort:
            env["CODEX_REASONING_EFFORT"] = codex_reasoning_effort
        env["CODEX_TIMEOUT"] = str(normalize_timeout(config.get("codex_timeout") or 120))
        env["CODEX_SEARCH"] = "1" if config.get("codex_search") else "0"
        env["WEIXIN_CODEX_EVENT_FILE"] = str(WEIXIN_EVENT_FILE)

        set_task_state("bot-starting", "机器人启动中", "正在启动微信 Codex 机器人")
        add_task_event("正在启动微信 Codex 机器人")
        append_log("[UI] 正在启动机器人...\n")
        bot_process = subprocess.Popen(
            [sys.executable, str(BOT_SCRIPT)],
            cwd=str(SCRIPT_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=stream_process_output, args=(bot_process,), daemon=True).start()
        return {"ok": True, "running": True, "pid": bot_process.pid}


def stop_bot():
    global bot_process
    with bot_lock:
        process = bot_process
        if not process or process.poll() is not None:
            bot_process = None
            return {"ok": True, "running": False, "pid": None}

        append_log("[UI] 正在停止机器人...\n")
        set_task_state("bot-stopping", "机器人停止中", "正在停止微信 Codex 机器人")
        add_task_event("正在停止微信 Codex 机器人")
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        bot_process = None
        set_task_state("idle", "空闲", "机器人已停止")
        return {"ok": True, "running": False, "pid": None}


def stop_weixin_login():
    global login_process
    with login_lock:
        process = login_process
        if not process or process.poll() is not None:
            login_process = None
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        login_process = None


def stop_codex_login():
    global codex_login_process
    with codex_login_lock:
        process = codex_login_process
        if not process or process.poll() is not None:
            codex_login_process = None
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        codex_login_process = None


def codex_env(config):
    env = os.environ.copy()
    api_key = str(config.get("openai_api_key") or "").strip()
    if api_key:
        env["OPENAI_API_KEY"] = api_key
    return env


def split_weixin_message(text, limit=MAX_WEIXIN_MESSAGE_LENGTH, max_parts=MAX_WEIXIN_PARTS):
    text = str(text or "").strip()
    if len(text) <= limit:
        return [text]

    parts = []
    remaining = text
    while remaining and len(parts) < max_parts:
        chunk = remaining[:limit]
        split_at = max(chunk.rfind("\n"), chunk.rfind("。"), chunk.rfind("；"), chunk.rfind("，"))
        if split_at >= int(limit * 0.6):
            chunk = remaining[:split_at + 1]
        parts.append(chunk.rstrip())
        remaining = remaining[len(chunk):].lstrip()

    if remaining and parts:
        suffix = "\n...（后续内容过长，已停止发送）"
        parts[-1] = parts[-1][: max(0, limit - len(suffix))].rstrip() + suffix

    if len(parts) <= 1:
        return parts
    total = len(parts)
    return [f"({index}/{total})\n{part}" for index, part in enumerate(parts, 1)]


def send_to_weixin_from_ui(text):
    if not is_weixin_logged_in() and not has_recent_weixin_login_success():
        append_log("[UI] 微信未登录，已跳过同步到微信；Web Codex 回复不受影响。\n")
        add_chat_message("system", "微信未登录，已跳过同步到微信。", "微信同步")
        return False

    parts = split_weixin_message(text)
    for index, part in enumerate(parts, 1):
        try:
            result = subprocess.run(
                [X_CMD, "weixin", "bot", "send", "--text", part],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception as exc:
            append_log(f"[UI] 同步到微信失败：{exc}\n")
            add_chat_message("error", f"同步到微信失败：{exc}", "微信同步")
            return False

        if result.returncode != 0:
            message = (result.stderr or result.stdout or f"退出码 {result.returncode}").strip()
            append_log(f"[UI] 同步到微信失败：{message}\n")
            add_chat_message("error", f"同步到微信失败：{message}", "微信同步")
            return False
        if len(parts) > 1:
            append_log(f"[UI] 已同步微信分段：{index}/{len(parts)}\n")
        time.sleep(0.15)

    suffix = f"（{len(parts)} 条）" if len(parts) > 1 else ""
    append_log(f"[UI] Codex 回复已同步到微信{suffix}。\n")
    add_chat_message("system", f"Codex 回复已同步到微信{suffix}。", "微信同步")
    return True


def compact_json(value, limit=600):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "...（已截断）"


def first_string(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def nested_value(data, *path):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def find_codex_session_id(value, parent_key=""):
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if isinstance(item, str) and UUID_RE.match(item):
                if any(token in key_lower for token in ("session", "conversation", "thread")):
                    return item
            found = find_codex_session_id(item, key_text)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_codex_session_id(item, parent_key)
            if found:
                return found
    elif isinstance(value, str) and UUID_RE.match(value):
        parent_lower = parent_key.lower()
        if any(token in parent_lower for token in ("session", "conversation", "thread")):
            return value
    return ""


def summarize_codex_event(event):
    event_type = first_string(event.get("type"), event.get("event"), event.get("name"))
    if not event_type:
        return "Codex 事件"

    lower_type = event_type.lower()
    command = first_string(
        event.get("command"),
        event.get("cmd"),
        nested_value(event, "item", "command"),
        nested_value(event, "call", "command"),
    )
    status = first_string(event.get("status"), event.get("state"), nested_value(event, "item", "status"))
    message = first_string(
        event.get("message"),
        event.get("text"),
        nested_value(event, "message", "content"),
        nested_value(event, "item", "text"),
        nested_value(event, "delta", "text"),
    )

    if "exec" in lower_type or "command" in lower_type or "shell" in lower_type:
        if command:
            return f"命令：{command[:120]}"
        if status:
            return f"命令状态：{status}"
    if "file" in lower_type or "patch" in lower_type or "diff" in lower_type:
        path = first_string(event.get("path"), nested_value(event, "item", "path"))
        return f"文件事件：{path or event_type}"
    if "error" in lower_type:
        return f"错误：{message or event_type}"
    if "approval" in lower_type:
        return f"审批事件：{message or event_type}"
    if "message" in lower_type or "response" in lower_type:
        if message:
            return f"回复片段：{message[:120]}"
    return event_type


def handle_codex_json_line(line, collector):
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return False
    collector.append(line)
    summary = summarize_codex_event(event)
    append_log(f"[Codex 事件] {summary}\n")
    append_log(f"[Codex JSON] {compact_json(event)}\n")
    add_task_event(summary)
    set_task_state("codex-running", "Codex 运行中", summary[:120])
    return True


def extract_reply_from_codex_jsonl(text):
    parts = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = first_string(event.get("type"), event.get("event"), event.get("name")).lower()
        message = first_string(
            event.get("message"),
            event.get("text"),
            nested_value(event, "message", "content"),
            nested_value(event, "item", "text"),
            nested_value(event, "delta", "text"),
        )
        if message and ("message" in event_type or "response" in event_type or "final" in event_type):
            parts.append(message)
    return "\n".join(parts).strip()


def extract_session_id_from_jsonl(text):
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = find_codex_session_id(event)
        if session_id:
            return session_id
    return ""


def stream_codex_pipe(pipe, label, collector, parse_json=False):
    saw_output = False
    try:
        for line in iter(pipe.readline, ""):
            if parse_json and handle_codex_json_line(line, collector):
                saw_output = True
                continue
            collector.append(line)
            append_log(f"[{label}] {line}")
            if not saw_output and line.strip():
                add_task_event(f"{label} 开始输出")
                saw_output = True
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def run_codex_prompt(prompt, use_context=True, sync_to_weixin=False):
    global codex_process
    try:
        config = read_config()
        codex_cmd = str(config.get("codex_cmd") or "codex").strip() or "codex"
        codex_sandbox = normalize_codex_sandbox(config.get("codex_sandbox") or "read-only")
        codex_approval_policy = normalize_approval_policy(config.get("codex_approval_policy") or "never")
        codex_timeout = normalize_timeout(config.get("codex_timeout") or 120)
        codex_model = str(config.get("codex_model") or "").strip()
        codex_reasoning_effort = normalize_reasoning_effort(config.get("codex_reasoning_effort") or "")
        codex_search = bool(config.get("codex_search"))
        project_dir = Path(str(config.get("project_dir") or SCRIPT_DIR)).expanduser().resolve()
        if not project_dir.is_dir():
            message = f"项目目录不存在：{project_dir}"
            append_log(f"[UI] {message}\n")
            add_chat_message("error", message, "错误")
            set_task_state("error", "Codex 失败", message)
            return

        output_path = None
        append_log(f"\n[Web 指令] {prompt}\n")
        append_log(f"[UI] 工作目录：{project_dir}\n")
        append_log(f"[UI] Codex 沙箱：{codex_sandbox}\n")
        append_log(f"[UI] Codex 审批模式：{codex_approval_policy}\n")
        append_log(f"[UI] Codex 推理深度：{codex_reasoning_effort or '默认'}\n")
        append_log(f"[UI] Codex 超时：{codex_timeout} 秒\n")
        add_task_event(f"Web 指令已开始：{prompt[:60]}")
        try:
            set_task_state("codex-running", "Codex 运行中", prompt[:80])
            with tempfile.NamedTemporaryFile("w+", delete=False) as output_file:
                output_path = output_file.name

            existing_codex_session = get_active_codex_session(project_dir)
            codex_prompt = prompt if existing_codex_session else build_codex_prompt(prompt, use_context)
            command = [
                codex_cmd,
                "--ask-for-approval", codex_approval_policy,
                "--sandbox", codex_sandbox,
                "--cd", str(project_dir),
            ]
            if codex_search:
                command.append("--search")

            if existing_codex_session:
                command.extend([
                    "exec",
                    "resume",
                    "--skip-git-repo-check",
                    "--json",
                    "--output-last-message", output_path,
                ])
            else:
                command.extend([
                    "exec",
                    "--skip-git-repo-check",
                    "--color", "never",
                    "--json",
                    "--output-last-message", output_path,
                ])
            if codex_model:
                command.extend(["--model", codex_model])
            if codex_reasoning_effort:
                command.extend(["-c", f'model_reasoning_effort="{codex_reasoning_effort}"'])
            if existing_codex_session:
                command.extend([existing_codex_session, "-"])
                add_task_event(f"继续 Codex 线程：{existing_codex_session[:8]}")
                append_log(f"[UI] 继续 Codex 线程：{existing_codex_session}\n")
            else:
                add_task_event("创建新的 Codex 线程")
                command.append("-")

            codex_process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=codex_env(config),
                cwd=str(project_dir),
                bufsize=1,
            )
            assert codex_process.stdin is not None
            assert codex_process.stdout is not None
            assert codex_process.stderr is not None
            stdout_parts = []
            stderr_parts = []
            stdout_thread = threading.Thread(
                target=stream_codex_pipe,
                args=(codex_process.stdout, "Codex 事件", stdout_parts, True),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=stream_codex_pipe,
                args=(codex_process.stderr, "Codex 日志", stderr_parts, False),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            codex_process.stdin.write(codex_prompt)
            codex_process.stdin.close()

            try:
                returncode = codex_process.wait(timeout=codex_timeout)
            except subprocess.TimeoutExpired:
                codex_process.kill()
                returncode = codex_process.wait()
                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)
                append_log(f"[Codex 错误] 请求超时：Codex 超过 {codex_timeout} 秒未返回。\n")
                add_chat_message("error", f"请求超时：Codex 超过 {codex_timeout} 秒未返回。", "Codex 错误")
                set_task_state("error", "Codex 超时", f"超过 {codex_timeout} 秒未返回")
                add_task_event(f"Codex 超时：超过 {codex_timeout} 秒")
                return

            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            stdout = "".join(stdout_parts)
            stderr = "".join(stderr_parts)

            reply = ""
            if output_path and os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as output_file:
                    reply = output_file.read().strip()
            if not reply:
                reply = extract_reply_from_codex_jsonl(stdout) or (stdout or "").strip()
            discovered_session_id = extract_session_id_from_jsonl(stdout)
            if discovered_session_id:
                set_active_codex_session(discovered_session_id, project_dir)

            if returncode != 0:
                error = (stderr or stdout or "").strip()
                message = error or f"退出码 {returncode}"
                append_log(f"[Codex 错误] {message}\n")
                add_chat_message("error", message, "Codex 错误")
                set_task_state("error", "Codex 失败", message[:120])
                add_task_event(f"Codex 失败：{message[:80]}")
                if existing_codex_session:
                    clear_active_codex_session("Codex 线程恢复失败，已清理绑定")
            else:
                message = reply or "Codex 没有返回内容。"
                append_log(f"[Codex 回复]\n{message}\n")
                add_chat_message("assistant", message, "Codex")
                if sync_to_weixin:
                    send_to_weixin_from_ui(f"【Web Codex 回复】\n{message}")
                set_task_state("done", "Codex 完成", prompt[:80])
                add_task_event("Codex 已完成并返回回复")
        except Exception as exc:
            append_log(f"[Codex 错误] {exc}\n")
            add_chat_message("error", str(exc), "Codex 错误")
            set_task_state("error", "Codex 失败", str(exc)[:120])
            add_task_event(f"Codex 异常：{str(exc)[:80]}")
        finally:
            codex_process = None
            if output_path and os.path.exists(output_path):
                try:
                    os.unlink(output_path)
                except OSError:
                    pass
    finally:
        codex_lock.release()


def start_codex_prompt(prompt, use_context=True, sync_to_weixin=False):
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("指令不能为空")
    if not codex_lock.acquire(blocking=False):
        raise ValueError("Codex 正在处理上一条指令，请稍后再试。")
    set_task_state("queued", "Codex 已排队", prompt[:80])
    add_task_event(f"Codex 任务已排队：{prompt[:60]}")
    add_chat_message("user", prompt, "你")
    threading.Thread(target=run_codex_prompt, args=(prompt, use_context, sync_to_weixin), daemon=True).start()
    return {"ok": True}


def stop_codex_prompt():
    global codex_process
    process = codex_process
    if not process or process.poll() is not None:
        return {"ok": True, "running": False}

    append_log("[UI] 正在停止 Web Codex 任务...\n")
    add_chat_message("system", "正在停止当前 Codex 任务。", "系统")
    set_task_state("stopping", "Codex 停止中", "正在终止当前任务")
    add_task_event("正在停止当前 Codex 任务")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    set_task_state("stopped", "Codex 已停止", "当前任务已停止")
    add_task_event("Codex 任务已停止")
    return {"ok": True, "running": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/config":
            self.send_json({"ok": True, "config": public_config(), "config_path": str(CONFIG_FILE)})
            return
        if path == "/api/status":
            self.send_json(process_status())
            return
        if path == "/api/task":
            self.send_json(get_task_state())
            return
        if path == "/api/logs":
            drain_logs()
            status = process_status()
            self.send_json({
                "ok": True,
                "logs": log_lines[-MAX_LOG_LINES:],
                "running": status["running"],
                "weixin_login_success": has_recent_weixin_login_success(),
            })
            return
        if path == "/api/chat":
            import_weixin_events()
            with chat_lock:
                messages = list(chat_messages)
            self.send_json({
                "ok": True,
                "messages": messages,
                "codex_running": codex_task_running(),
            })
            return
        if path == "/api/sessions":
            import_weixin_events()
            self.send_json(list_sessions())
            return
        if path == "/api/session-export":
            self.send_json(export_active_session())
            return
        if path == "/api/health":
            self.send_json(health_status())
            return
        if path == "/api/changes":
            self.send_json(git_changes((query.get("file") or [""])[0]))
            return
        if path == "/api/projects":
            self.send_json(list_projects())
            return
        if path == "/api/weixin-login/status":
            self.send_json(weixin_login_status())
            return
        self.send_json({"ok": False, "error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                payload = self.read_json_body()
                config = read_config()
                config["codex_cmd"] = str(payload.get("codex_cmd") or "codex").strip() or "codex"
                project_dir = Path(str(payload.get("project_dir") or SCRIPT_DIR)).expanduser().resolve()
                if not project_dir.is_dir():
                    raise ValueError(f"项目目录不存在：{project_dir}")
                config["project_dir"] = str(project_dir)
                config["codex_sandbox"] = normalize_codex_sandbox(payload.get("codex_sandbox") or "read-only")
                config["codex_approval_policy"] = normalize_approval_policy(payload.get("codex_approval_policy") or "never")
                config["codex_model"] = str(payload.get("codex_model") or "").strip()
                config["codex_reasoning_effort"] = normalize_reasoning_effort(payload.get("codex_reasoning_effort") or "")
                config["codex_timeout"] = normalize_timeout(payload.get("codex_timeout") or 120)
                config["codex_search"] = bool(payload.get("codex_search"))
                config["auto_install_deps"] = bool(payload.get("auto_install_deps"))
                api_key = str(payload.get("openai_api_key") or "").strip()
                if api_key:
                    config["openai_api_key"] = api_key
                write_config(config)
                self.send_json({"ok": True, "has_openai_api_key": bool(config.get("openai_api_key"))})
                return
            if path == "/api/start":
                self.send_json(start_bot())
                return
            if path == "/api/stop":
                self.send_json(stop_bot())
                return
            if path == "/api/weixin-login":
                self.send_json(start_weixin_login())
                return
            if path == "/api/codex":
                payload = self.read_json_body()
                self.send_json(start_codex_prompt(
                    str(payload.get("prompt") or ""),
                    bool(payload.get("use_context", True)),
                    bool(payload.get("sync_to_weixin")),
                ))
                return
            if path == "/api/codex-stop":
                self.send_json(stop_codex_prompt())
                return
            if path == "/api/git-action":
                payload = self.read_json_body()
                self.send_json(run_git_action(
                    str(payload.get("action") or ""),
                    str(payload.get("message") or ""),
                    str(payload.get("file") or ""),
                ))
                return
            if path == "/api/clear":
                self.send_json(clear_history())
                return
            if path == "/api/sessions":
                payload = self.read_json_body()
                action = str(payload.get("action") or "")
                if action == "new":
                    self.send_json(create_session())
                    return
                if action == "switch":
                    self.send_json(switch_session(str(payload.get("session_id") or "")))
                    return
                if action == "delete":
                    self.send_json(delete_session(str(payload.get("session_id") or "")))
                    return
                raise ValueError("不支持的会话操作")
            self.send_json({"ok": False, "error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)


def main():
    load_state()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"微信 Codex UI 已启动：http://{HOST}:{PORT}")
    print(f"配置文件：{CONFIG_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_codex_prompt()
        stop_bot()
        stop_weixin_login()
        stop_codex_login()
        server.server_close()
        print("\nUI 已停止")


if __name__ == "__main__":
    main()
