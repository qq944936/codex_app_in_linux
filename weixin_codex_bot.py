import subprocess
import json
import re
import os
import shutil
import tempfile
import threading
import time

# ===================== 配置项 =====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_X_CMD_PATH = os.path.join(SCRIPT_DIR, ".x-cmd.root", "bin", "x-cmd")
HOME_X_CMD_PATH = os.path.expanduser("~/.x-cmd.root/bin/x-cmd")
X_CMD_PATH = (
    os.environ.get("X_CMD_PATH")
    or shutil.which("x-cmd")
    or (HOME_X_CMD_PATH if os.path.exists(HOME_X_CMD_PATH) else None)
    or DEFAULT_X_CMD_PATH
)
CODEX_CMD = os.environ.get("CODEX_CMD") or "codex"
AUTO_INSTALL_DEPS = os.environ.get("WEIXIN_CODEX_AUTO_INSTALL", "1") != "0"
CODEX_NPM_PACKAGE = os.environ.get("CODEX_NPM_PACKAGE", "@openai/codex")
CODEX_SANDBOX = os.environ.get("CODEX_SANDBOX") or "read-only"
CODEX_APPROVAL_POLICY = os.environ.get("CODEX_APPROVAL_POLICY") or "never"
CODEX_MODEL = os.environ.get("CODEX_MODEL") or ""
CODEX_REASONING_EFFORT = os.environ.get("CODEX_REASONING_EFFORT") or ""
CODEX_SEARCH = os.environ.get("CODEX_SEARCH", "0") == "1"
CONFIG_FILE = os.environ.get(
    "WEIXIN_CODEX_CONFIG_FILE",
    os.path.join(SCRIPT_DIR, "weixin_codex_config.json")
)
MAX_REPLY_LENGTH = 1200
MAX_WEIXIN_PARTS = 8
MAX_STORED_REPLY_LENGTH = 30000
LISTEN_KEY = "/codex"
CODEX_TIMEOUT = int(os.environ.get("CODEX_TIMEOUT", "120"))
MAX_CONTEXT_TURNS = 8
CONTEXT_FILE = os.environ.get(
    "WEIXIN_CODEX_CONTEXT_FILE",
    os.path.join(SCRIPT_DIR, "weixin_codex_context.json")
)
EVENT_FILE = os.environ.get(
    "WEIXIN_CODEX_EVENT_FILE",
    os.path.join(SCRIPT_DIR, "weixin_codex_events.jsonl")
)
CODEX_SESSIONS_FILE = os.environ.get(
    "WEIXIN_CODEX_CODEX_SESSIONS_FILE",
    os.path.join(SCRIPT_DIR, "weixin_codex_sessions.json")
)
DEBUG_RAW_LINES = os.environ.get("WEIXIN_BOT_DEBUG") == "1"
SEEN_MESSAGE_IDS = set()
CONVERSATIONS = {}
CODEX_SESSIONS = {}
ACTIVE_CONTEXTS = set()
ACTIVE_PROCESSES = {}
ACTIVE_PROMPTS = {}
ACTIVE_CONTEXTS_LOCK = threading.Lock()
APP_CONFIG = {}
PROJECT_DIR = SCRIPT_DIR
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
VALID_CODEX_SANDBOXES = {"read-only", "workspace-write"}
VALID_REASONING_EFFORTS = {"", "low", "medium", "high", "xhigh"}
VALID_APPROVAL_POLICIES = {"never", "on-request", "untrusted", "on-failure"}
CHAT_PROMPT_PREFIX = """你是微信里的代码助手。
请直接在聊天中回答用户的问题。
除非用户明确要求修改本机文件，否则不要创建、编辑或删除任何文件。
如果用户让你“写一段代码”或“写一个程序”，请直接返回可复制的代码和必要说明。
"""
# ==================================================

def executable_exists(command):
    """判断命令或路径是否可执行。"""
    if os.path.isabs(command) or os.sep in command:
        return os.path.isfile(command) and os.access(command, os.X_OK)
    return shutil.which(command) is not None

def append_to_path(path):
    """把新安装工具所在目录加入当前进程 PATH。"""
    if not path or not os.path.isdir(path):
        return
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if path not in paths:
        os.environ["PATH"] = os.pathsep.join([path, *paths])

def ensure_executable(command, env_name):
    """检查命令是否可执行，避免启动后才静默失败。"""
    if executable_exists(command):
        return

    raise FileNotFoundError(
        f"找不到可执行文件：{command}。请安装它，或通过环境变量 {env_name} 指定路径。"
    )

def get_config_string(*keys):
    """从配置文件读取字符串值，支持顶层 key 或 codex.xxx。"""
    for key in keys:
        value = APP_CONFIG.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

        codex_config = APP_CONFIG.get("codex")
        if isinstance(codex_config, dict):
            value = codex_config.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None

def get_config_bool(key, default):
    """从配置文件读取布尔值，支持顶层 key 或 codex.xxx。"""
    values = [APP_CONFIG.get(key)]
    codex_config = APP_CONFIG.get("codex")
    if isinstance(codex_config, dict):
        values.append(codex_config.get(key))

    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
    return default

def normalize_codex_sandbox(value):
    """把配置里的沙箱模式规范成 Codex CLI 可接受的值。"""
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

def load_app_config():
    """加载机器人配置。敏感字段只进入进程环境，不打印。"""
    global APP_CONFIG, CODEX_CMD, AUTO_INSTALL_DEPS, PROJECT_DIR, CODEX_SANDBOX, CODEX_APPROVAL_POLICY, CODEX_MODEL, CODEX_REASONING_EFFORT, CODEX_TIMEOUT, CODEX_SEARCH
    if not os.path.exists(CONFIG_FILE):
        return

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as e:
        print(f"⚠️ 配置文件加载失败：{e}")
        return

    if not isinstance(data, dict):
        print("⚠️ 配置文件格式无效，已忽略。")
        return

    APP_CONFIG = data
    configured_codex_cmd = get_config_string("codex_cmd")
    if configured_codex_cmd and not os.environ.get("CODEX_CMD"):
        CODEX_CMD = configured_codex_cmd
    if not os.environ.get("WEIXIN_CODEX_AUTO_INSTALL"):
        AUTO_INSTALL_DEPS = get_config_bool("auto_install_deps", AUTO_INSTALL_DEPS)

    configured_project_dir = get_config_string("project_dir")
    if configured_project_dir:
        PROJECT_DIR = os.path.abspath(os.path.expanduser(configured_project_dir))

    if not os.environ.get("CODEX_SANDBOX"):
        CODEX_SANDBOX = normalize_codex_sandbox(get_config_string("codex_sandbox") or CODEX_SANDBOX)
    if not os.environ.get("CODEX_APPROVAL_POLICY"):
        CODEX_APPROVAL_POLICY = normalize_approval_policy(get_config_string("codex_approval_policy") or CODEX_APPROVAL_POLICY)
    if not os.environ.get("CODEX_MODEL"):
        CODEX_MODEL = get_config_string("codex_model") or CODEX_MODEL
    if not os.environ.get("CODEX_REASONING_EFFORT"):
        CODEX_REASONING_EFFORT = normalize_reasoning_effort(get_config_string("codex_reasoning_effort") or CODEX_REASONING_EFFORT)
    if not os.environ.get("CODEX_TIMEOUT"):
        CODEX_TIMEOUT = normalize_timeout(APP_CONFIG.get("codex_timeout", CODEX_TIMEOUT))
    if not os.environ.get("CODEX_SEARCH"):
        CODEX_SEARCH = get_config_bool("codex_search", CODEX_SEARCH)

    unsupported_keys = [
        key for key in (
            "openai_account",
            "openai_email",
            "openai_password",
            "codex_account",
            "codex_password",
            "username",
            "password",
        )
        if get_config_string(key)
    ]
    if unsupported_keys:
        print(
            "⚠️ Codex CLI 不支持从配置文件用账号密码自动登录，"
            f"已忽略这些字段：{', '.join(unsupported_keys)}。请使用 openai_api_key 或先运行 codex --login。"
        )

def ensure_project_dir():
    """确认 Codex 工作目录存在。"""
    if not os.path.isdir(PROJECT_DIR):
        raise FileNotFoundError(f"项目目录不存在或不是目录：{PROJECT_DIR}")

def get_codex_env():
    """构造 Codex 子进程环境，优先使用配置文件中的 API key。"""
    env = os.environ.copy()
    api_key = get_config_string("openai_api_key", "OPENAI_API_KEY")
    if api_key:
        env["OPENAI_API_KEY"] = api_key
    return env

def describe_codex_auth():
    """返回可打印的认证来源说明，不泄露密钥。"""
    if get_config_string("openai_api_key", "OPENAI_API_KEY"):
        return "配置文件 OPENAI_API_KEY"
    if os.environ.get("OPENAI_API_KEY"):
        return "环境变量 OPENAI_API_KEY"
    return "Codex 本地登录状态或 CLI 默认认证"

def run_install_step(title, command, shell=False):
    """执行安装步骤，统一打印输出并返回是否成功。"""
    print(f"🔧 {title}")
    result = subprocess.run(
        command,
        shell=shell,
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode == 0:
        print("✅ 完成")
        if DEBUG_RAW_LINES:
            print_command_output("🧾 安装输出：", result)
        return True

    print_command_output("❌ 安装失败：", result)
    return False

def refresh_x_cmd_path():
    """安装后重新定位 x-cmd。"""
    global X_CMD_PATH
    append_to_path(os.path.dirname(HOME_X_CMD_PATH))
    append_to_path(os.path.dirname(DEFAULT_X_CMD_PATH))
    X_CMD_PATH = (
        os.environ.get("X_CMD_PATH")
        or shutil.which("x-cmd")
        or (HOME_X_CMD_PATH if os.path.exists(HOME_X_CMD_PATH) else None)
        or DEFAULT_X_CMD_PATH
    )

def ensure_x_cmd_installed():
    """缺少 x-cmd 时自动安装。"""
    refresh_x_cmd_path()
    if executable_exists(X_CMD_PATH):
        return

    if not AUTO_INSTALL_DEPS:
        ensure_executable(X_CMD_PATH, "X_CMD_PATH")

    ok = run_install_step(
        "未检测到 x-cmd，正在安装 x-cmd...",
        'eval "$(curl -fsSL https://get.x-cmd.com)"',
        shell=True
    )
    refresh_x_cmd_path()
    if not ok or not executable_exists(X_CMD_PATH):
        raise RuntimeError("x-cmd 自动安装失败。请手动安装，或通过 X_CMD_PATH 指定路径。")

def ensure_node_and_npm_installed():
    """缺少 node/npm 时优先通过 x-cmd 安装 node。"""
    missing = [cmd for cmd in ("node", "npm") if not executable_exists(cmd)]
    if not missing:
        return

    if not AUTO_INSTALL_DEPS:
        ensure_executable(missing[0], missing[0].upper())

    ok = run_install_step(
        f"未检测到 {'/'.join(missing)}，正在通过 x-cmd 安装 node...",
        [X_CMD_PATH, "install", "node"]
    )
    if not ok:
        raise RuntimeError("node/npm 自动安装失败。请手动安装 Node.js 后重试。")

    if not executable_exists("node") or not executable_exists("npm"):
        raise RuntimeError("node/npm 已执行安装，但当前进程 PATH 中仍不可用。请重开终端后重试。")

def refresh_npm_global_bin():
    """把 npm 全局命令目录加入当前进程 PATH。"""
    if not executable_exists("npm"):
        return
    result = subprocess.run(
        ["npm", "config", "get", "prefix"],
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode == 0:
        append_to_path(os.path.join(result.stdout.strip(), "bin"))

def ensure_npm_global_command(command, package, env_name):
    """缺少 npm 全局命令时安装对应包。"""
    refresh_npm_global_bin()
    if executable_exists(command):
        return

    if not AUTO_INSTALL_DEPS:
        ensure_executable(command, env_name)

    ok = run_install_step(
        f"未检测到 {command}，正在安装 npm 包 {package}...",
        ["npm", "install", "-g", package]
    )
    refresh_npm_global_bin()
    if not ok or not executable_exists(command):
        raise RuntimeError(
            f"{command} 自动安装失败。请手动执行 npm install -g {package}，"
            f"或通过环境变量 {env_name} 指定路径。"
        )

def ensure_x_cmd_weixin_available():
    """确认 x-cmd 的 weixin 模块可用。"""
    result = subprocess.run(
        [X_CMD_PATH, "weixin", "--help"],
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode == 0:
        return

    print_command_output("❌ x-cmd weixin 模块不可用：", result)
    raise RuntimeError("x-cmd weixin 模块不可用。请先确认 x-cmd 安装完整，或运行 x weixin login 初始化。")

def ensure_runtime_dependencies():
    """启动前检查并补齐运行依赖。"""
    ensure_x_cmd_installed()
    ensure_x_cmd_weixin_available()
    ensure_node_and_npm_installed()
    ensure_npm_global_command(CODEX_CMD, CODEX_NPM_PACKAGE, "CODEX_CMD")

def clean_old_process():
    """清理旧的微信机器人进程"""
    try:
        subprocess.run(
            ["pkill", "-f", r"x-cmd.*weixin bot service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
        time.sleep(0.5)
        print("🔄 已清理旧进程")
    except Exception as e:
        print(f"⚠️ 清理旧进程失败：{e}")

def run_x_cmd(args, check=False):
    """运行 x-cmd 子命令，并返回执行结果。"""
    return subprocess.run(
        [X_CMD_PATH, *args],
        check=check,
        capture_output=True,
        text=True
    )

def print_command_output(title, result):
    output = "\n".join(
        part.strip() for part in [result.stdout, result.stderr] if part and part.strip()
    )
    if output:
        print(f"{title}\n{output}")

def start_weixin_service():
    """启动微信 bot 服务，并打印状态，方便确认服务是否在线。"""
    result = run_x_cmd(["weixin", "bot", "service", "start"])
    if result.returncode != 0:
        print_command_output("❌ 微信 bot 服务启动失败：", result)
        return False

    if DEBUG_RAW_LINES:
        print_command_output("🧾 service start 输出：", result)

    status = run_x_cmd(["weixin", "bot", "service", "status"])
    print_command_output("📡 微信 bot 服务状态：", status)
    return True

def load_contexts():
    """从 JSON 文件加载历史上下文。"""
    if not os.path.exists(CONTEXT_FILE):
        return

    try:
        with open(CONTEXT_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as e:
        print(f"⚠️ 上下文加载失败：{e}")
        return

    if not isinstance(data, dict):
        print("⚠️ 上下文文件格式无效，已忽略。")
        return

    for key, history in data.items():
        if not isinstance(key, str) or not isinstance(history, list):
            continue
        valid_turns = []
        for turn in history[-MAX_CONTEXT_TURNS:]:
            if not isinstance(turn, dict):
                continue
            user = turn.get("user")
            assistant = turn.get("assistant")
            if isinstance(user, str) and isinstance(assistant, str):
                valid_turns.append({"user": user, "assistant": assistant})
        if valid_turns:
            CONVERSATIONS[key] = valid_turns

    if CONVERSATIONS:
        print(f"已加载上下文：{len(CONVERSATIONS)} 个会话")

def save_contexts():
    """保存上下文到 JSON 文件。"""
    temp_path = CONTEXT_FILE + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(CONVERSATIONS, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, CONTEXT_FILE)
    except Exception as e:
        print(f"⚠️ 上下文保存失败：{e}")
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass


def load_codex_sessions():
    global CODEX_SESSIONS
    if not os.path.exists(CODEX_SESSIONS_FILE):
        return
    try:
        with open(CODEX_SESSIONS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as e:
        print(f"⚠️ Codex 线程映射加载失败：{e}")
        return
    if not isinstance(data, dict):
        return
    parsed = {}
    for context_key, item in data.items():
        if not isinstance(context_key, str) or not isinstance(item, dict):
            continue
        session_id = str(item.get("codex_session_id") or "")
        project_dir = str(item.get("project_dir") or "")
        if UUID_RE.match(session_id):
            parsed[context_key] = {
                "codex_session_id": session_id,
                "project_dir": project_dir,
            }
    CODEX_SESSIONS = parsed
    if CODEX_SESSIONS:
        print(f"已加载 Codex 线程映射：{len(CODEX_SESSIONS)} 个会话")


def save_codex_sessions():
    temp_path = CODEX_SESSIONS_FILE + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(CODEX_SESSIONS, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temp_path, CODEX_SESSIONS_FILE)
    except Exception as e:
        print(f"⚠️ Codex 线程映射保存失败：{e}")
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass


def get_codex_session_id(context_key):
    item = CODEX_SESSIONS.get(context_key)
    if not isinstance(item, dict):
        return ""
    session_id = str(item.get("codex_session_id") or "")
    project_dir = str(item.get("project_dir") or "")
    if project_dir == PROJECT_DIR and UUID_RE.match(session_id):
        return session_id
    return ""


def set_codex_session_id(context_key, session_id):
    if not UUID_RE.match(str(session_id or "")):
        return
    CODEX_SESSIONS[context_key] = {
        "codex_session_id": session_id,
        "project_dir": PROJECT_DIR,
    }
    save_codex_sessions()


def clear_codex_session_id(context_key):
    if context_key in CODEX_SESSIONS:
        CODEX_SESSIONS.pop(context_key, None)
        save_codex_sessions()


def emit_weixin_event(context_key, prompt, reply, event_type="codex_reply"):
    event = {
        "id": f"{int(time.time() * 1000)}-{abs(hash((context_key, prompt, reply))) % 1000000}",
        "type": event_type,
        "source": "weixin",
        "context_key": context_key,
        "prompt": prompt,
        "reply": reply,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(EVENT_FILE, "a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️ 写入 Web 同步事件失败：{e}")


def acknowledge_wechat_prompt(context_key, prompt):
    ack = "已收到，Codex 正在处理。"
    send_to_wechat(f"【Codex】\n{ack}")
    emit_weixin_event(context_key, prompt, "", "codex_started")


def remember_existing_messages():
    """记录启动前已有消息，避免 service log -f 重放历史命令。"""
    result = run_x_cmd(["weixin", "bot", "service", "log"])
    for line in (result.stdout or "").splitlines():
        for message in parse_log_messages(line):
            message_id = message.get("message_id")
            if message_id is not None:
                SEEN_MESSAGE_IDS.add(message_id)

    if SEEN_MESSAGE_IDS:
        print(f"已跳过历史消息：{len(SEEN_MESSAGE_IDS)} 条")

def split_weixin_message(text, limit=MAX_REPLY_LENGTH, max_parts=MAX_WEIXIN_PARTS):
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
        parts[-1] = (parts[-1][: max(0, limit - len(suffix))].rstrip() + suffix)

    if len(parts) <= 1:
        return parts
    total = len(parts)
    return [f"({index}/{total})\n{part}" for index, part in enumerate(parts, 1)]


def send_to_wechat(text):
    """调用 x-cmd 发送消息到微信"""
    for part in split_weixin_message(text):
        try:
            subprocess.run(
                [X_CMD_PATH, "weixin", "bot", "send", "--text", part],
                check=True,
                capture_output=True,
                text=True
            )
            time.sleep(0.15)
        except Exception as e:
            print(f"❌ 发送失败：{e}")
            if isinstance(e, subprocess.CalledProcessError):
                print((e.stderr or e.stdout or "").strip())
            return False
    return True

def build_chat_prompt(prompt, context_key):
    """拼接当前用户的最近对话上下文。"""
    history = CONVERSATIONS.get(context_key, [])
    if not history:
        return f"{CHAT_PROMPT_PREFIX}\n用户请求：\n{prompt}"

    lines = [CHAT_PROMPT_PREFIX.rstrip(), "", "最近对话上下文："]
    for turn in history[-MAX_CONTEXT_TURNS:]:
        lines.append(f"用户：{turn['user']}")
        lines.append(f"助手：{turn['assistant']}")
    lines.extend(["", "当前用户请求：", prompt])
    return "\n".join(lines)

def remember_turn(context_key, prompt, reply):
    """保存一轮问答，用于后续上下文。"""
    history = CONVERSATIONS.setdefault(context_key, [])
    history.append({"user": prompt, "assistant": reply})
    if len(history) > MAX_CONTEXT_TURNS:
        del history[:-MAX_CONTEXT_TURNS]
    save_contexts()

def reset_context(context_key):
    CONVERSATIONS.pop(context_key, None)
    clear_codex_session_id(context_key)
    save_contexts()


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


def codex_query(prompt, context_key):
    """调用 codex CLI 获取回答"""
    output_path = None
    try:
        with tempfile.NamedTemporaryFile("w+", delete=False) as output_file:
            output_path = output_file.name

        existing_session_id = get_codex_session_id(context_key)
        chat_prompt = prompt if existing_session_id else build_chat_prompt(prompt, context_key)
        command = [
            CODEX_CMD,
            "--ask-for-approval", CODEX_APPROVAL_POLICY,
            "--sandbox", CODEX_SANDBOX,
        ]
        if CODEX_SEARCH:
            command.append("--search")

        if existing_session_id:
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
        if CODEX_MODEL:
            command.extend(["--model", CODEX_MODEL])
        if CODEX_REASONING_EFFORT:
            command.extend(["-c", f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"'])
        if existing_session_id:
            command.extend([existing_session_id, "-"])
            print(f"继续 Codex 线程：{existing_session_id}")
        else:
            print("创建新的 Codex 线程")
            command.append("-")

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_codex_env(),
            cwd=PROJECT_DIR,
        )
        with ACTIVE_CONTEXTS_LOCK:
            ACTIVE_PROCESSES[context_key] = process
        try:
            stdout, stderr = process.communicate(chat_prompt, timeout=CODEX_TIMEOUT)
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return f"请求超时：Codex 超过 {CODEX_TIMEOUT} 秒未返回。"
        finally:
            with ACTIVE_CONTEXTS_LOCK:
                if ACTIVE_PROCESSES.get(context_key) is process:
                    ACTIVE_PROCESSES.pop(context_key, None)

        reply = ""
        if output_path and os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as output_file:
                reply = output_file.read().strip()

        if not reply:
            reply = extract_reply_from_codex_jsonl(stdout or "") or (stdout or "").strip()

        discovered_session_id = extract_session_id_from_jsonl(stdout or "")
        if discovered_session_id:
            set_codex_session_id(context_key, discovered_session_id)

        if returncode != 0:
            if existing_session_id:
                clear_codex_session_id(context_key)
            error = (stderr or stdout or "").strip()
            if returncode < 0:
                return "任务已停止。"
            return trim_reply(f"请求失败：{error or f'codex 退出码 {returncode}'}")

        return trim_reply(reply or "Codex 没有返回内容。")
    except Exception as e:
        return f"请求出错：{str(e)}"
    finally:
        if output_path and os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except OSError:
                pass

def trim_reply(reply):
    """限制本地保存的回复长度；微信发送会在 send_to_wechat 中单独分段。"""
    reply = reply.strip()
    if len(reply) <= MAX_STORED_REPLY_LENGTH:
        return reply
    return reply[:MAX_STORED_REPLY_LENGTH - 18].rstrip() + "\n...（回复过长，已截断）"


def run_weixin_codex_task(context_key, prompt):
    try:
        print(f"\n📩 收到指令：{prompt}")
        acknowledge_wechat_prompt(context_key, prompt)
        reply = codex_query(prompt, context_key)
        remember_turn(context_key, prompt, reply)
        print(f"📤 回复：{reply[:80]}...")
        if reply == "任务已停止。":
            emit_weixin_event(context_key, prompt, reply, "stopped")
        else:
            send_to_wechat(f"【Codex 回复】\n{reply}")
            emit_weixin_event(context_key, prompt, reply)
    finally:
        with ACTIVE_CONTEXTS_LOCK:
            ACTIVE_CONTEXTS.discard(context_key)
            ACTIVE_PROMPTS.pop(context_key, None)


def start_weixin_codex_task(context_key, prompt):
    with ACTIVE_CONTEXTS_LOCK:
        if context_key in ACTIVE_CONTEXTS:
            send_to_wechat("【Codex】\n当前会话已有任务在运行，请等它完成后再发送下一条。")
            emit_weixin_event(context_key, prompt, "当前会话已有任务在运行。", "busy")
            return
        ACTIVE_CONTEXTS.add(context_key)
        ACTIVE_PROMPTS[context_key] = prompt
    threading.Thread(target=run_weixin_codex_task, args=(context_key, prompt), daemon=True).start()


def stop_weixin_codex_task(context_key):
    with ACTIVE_CONTEXTS_LOCK:
        process = ACTIVE_PROCESSES.get(context_key)
        running = context_key in ACTIVE_CONTEXTS
    if not running:
        message = "当前会话没有正在运行的 Codex 任务。"
        send_to_wechat(f"【Codex】\n{message}")
        emit_weixin_event(context_key, "stop", message, "stop")
        return
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    message = "已请求停止当前 Codex 任务。"
    send_to_wechat(f"【Codex】\n{message}")
    emit_weixin_event(context_key, "stop", message, "stop")


def send_weixin_codex_status(context_key):
    with ACTIVE_CONTEXTS_LOCK:
        running = context_key in ACTIVE_CONTEXTS
        prompt = ACTIVE_PROMPTS.get(context_key, "")
        process = ACTIVE_PROCESSES.get(context_key)
        pid = process.pid if process and process.poll() is None else None
    session_id = get_codex_session_id(context_key)
    lines = [
        "状态：运行中" if running else "状态：空闲",
        f"项目：{PROJECT_DIR}",
        f"Codex 线程：{session_id[:8] if session_id else '未绑定'}",
    ]
    if running:
        lines.append(f"当前任务：{prompt[:120] or '-'}")
        if pid:
            lines.append(f"进程 PID：{pid}")
        lines.append("可发送 /codex stop 停止当前任务。")
    message = "\n".join(lines)
    send_to_wechat(f"【Codex 状态】\n{message}")
    emit_weixin_event(context_key, "status", message, "status")


def parse_log_messages(line):
    """解析 x-cmd data.tsv 中每行 JSON 消息。"""
    line = line.strip()
    if not line.startswith("["):
        return []

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []

def extract_text_messages(message):
    """从微信消息结构中提取文本内容，返回 (文本, 是否需要指令前缀)。"""
    texts = []
    for item in message.get("item_list", []):
        text = item.get("text_item", {}).get("text")
        if text:
            texts.append((text, True))
            continue

        voice_text = item.get("voice_item", {}).get("text")
        if voice_text:
            texts.append((voice_text, False))
    return texts

def process_prompt_text(text, context_key, require_listen_key=True):
    """处理文本消息，匹配 /codex 指令。"""
    if not require_listen_key:
        prompt = text.strip()
        if not prompt:
            return
        if prompt.lower() in {"reset", "重置", "清空上下文"}:
            reset_context(context_key)
            with ACTIVE_CONTEXTS_LOCK:
                running = context_key in ACTIVE_CONTEXTS
            message = "上下文已清空。"
            if running:
                message += "\n当前已有任务仍在运行；清空会影响后续任务，不会中断正在运行的任务。"
            send_to_wechat(f"【Codex 回复】\n{message}")
            emit_weixin_event(context_key, prompt, message, "reset")
            return
        if prompt.lower() in {"stop", "停止", "取消", "中止"}:
            stop_weixin_codex_task(context_key)
            return
        if prompt.lower() in {"status", "状态", "进度"}:
            send_weixin_codex_status(context_key)
            return
        start_weixin_codex_task(context_key, prompt)
        return

    if LISTEN_KEY not in text:
        return
    match = re.search(rf"{re.escape(LISTEN_KEY)}(?:\s+|$)(.*)", text)
    if not match:
        return

    prompt = match.group(1).strip()
    if not prompt:
        return
    if prompt.lower() in {"reset", "重置", "清空上下文"}:
        reset_context(context_key)
        print(f"\n🧹 已清空上下文：{context_key}")
        with ACTIVE_CONTEXTS_LOCK:
            running = context_key in ACTIVE_CONTEXTS
        message = "上下文已清空。"
        if running:
            message += "\n当前已有任务仍在运行；清空会影响后续任务，不会中断正在运行的任务。"
        send_to_wechat(f"【Codex 回复】\n{message}")
        emit_weixin_event(context_key, prompt, message, "reset")
        return
    if prompt.lower() in {"stop", "停止", "取消", "中止"}:
        stop_weixin_codex_task(context_key)
        return
    if prompt.lower() in {"status", "状态", "进度"}:
        send_weixin_codex_status(context_key)
        return

    start_weixin_codex_task(context_key, prompt)

def process_line(line):
    """处理一行日志，匹配 /codex 指令。"""
    if DEBUG_RAW_LINES:
        print(f"🧾 原始日志：{line}")

    messages = parse_log_messages(line)
    if not messages:
        process_prompt_text(line, "plain-log")
        return

    for message in messages:
        message_id = message.get("message_id")
        if message_id in SEEN_MESSAGE_IDS:
            continue
        if message_id is not None:
            SEEN_MESSAGE_IDS.add(message_id)

        context_key = get_context_key(message)
        for text, require_listen_key in extract_text_messages(message):
            if DEBUG_RAW_LINES:
                print(f"🧾 文本消息：{text}")
            process_prompt_text(text, context_key, require_listen_key)

def get_context_key(message):
    """按群聊、会话或用户区分上下文。"""
    return (
        message.get("group_id")
        or message.get("session_id")
        or message.get("from_user_id")
        or "default"
    )

def main():
    load_app_config()
    ensure_project_dir()
    ensure_runtime_dependencies()
    load_contexts()
    load_codex_sessions()
    clean_old_process()
    print(f"使用 x-cmd：{X_CMD_PATH}")
    print("使用微信模块：x-cmd weixin")
    print(f"使用 Codex：{CODEX_CMD}")
    print(f"Codex 认证：{describe_codex_auth()}")
    print(f"Codex 沙箱：{CODEX_SANDBOX}")
    print(f"Codex 审批模式：{CODEX_APPROVAL_POLICY}")
    print(f"Codex 模型：{CODEX_MODEL or '默认'}")
    print(f"Codex 推理深度：{CODEX_REASONING_EFFORT or '默认'}")
    print(f"Codex 超时：{CODEX_TIMEOUT} 秒")
    print(f"Codex 搜索：{'开启' if CODEX_SEARCH else '关闭'}")
    print(f"项目目录：{PROJECT_DIR}")
    print(f"配置文件：{CONFIG_FILE}")
    print(f"上下文文件：{CONTEXT_FILE}")
    print(f"Codex 线程映射：{CODEX_SESSIONS_FILE}")
    if DEBUG_RAW_LINES:
        print("调试模式已开启：会打印微信服务原始日志")

    if not start_weixin_service():
        return
    remember_existing_messages()

    print("✅ 微信 Codex 机器人已启动，等待消息...")
    print("提示：如果没有任何反应，用 WEIXIN_BOT_DEBUG=1 运行可查看原始日志。")

    # service log 底层是 tail，-f 会持续输出新日志。
    with subprocess.Popen(
        [X_CMD_PATH, "weixin", "bot", "service", "log", "-f"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    ) as proc:
        for line in proc.stdout:
            line = line.strip()
            if line:
                process_line(line)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 机器人已停止")
        clean_old_process()
