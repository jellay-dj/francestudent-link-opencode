import os
import sys
import platform
from pathlib import Path
import httpx

BASE_DIR = Path(__file__).resolve().parent.parent

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"

if IS_WINDOWS:
    import asyncio
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

# Official France Student API host (documented by the published OpenAPI
# specification at https://api.francestudent.ai/v3/api-docs).
API_BASE_URL = os.environ.get("FS_API_BASE_URL", "https://api.francestudent.ai")
FRONTEND_URL = os.environ.get("FS_WEB_BASE_URL", "https://ia.francestudent.org")
AUTH_API_URL = f"{FRONTEND_URL}/api/auth"

# Client metadata that the France Student front end sends on every call.
# The api-token endpoint rejects requests without it ("Invalid client
# metadata"), so the bridge sends the same values.
FS_CLIENT_PLATFORM = os.environ.get("FS_CLIENT_PLATFORM", "web_fs_ai")
FS_CLIENT_VERSION = os.environ.get("FS_CLIENT_VERSION", "ac0e023")

# Authentication mode.
#   "session" : reuse the browser session of the account owner. The bridge
#                exchanges the session cookie for a short-lived access token
#                through the documented /api/auth/api-token endpoint.
#   "api_key" : use an official France Student API key (CGU "Clés API").
# The official key is only available when the account has the API-key
# feature enabled, so the session mode is the default.
FS_AUTH_MODE = os.environ.get("FS_AUTH_MODE", "session").strip().lower()
FS_API_KEY = os.environ.get("FS_API_KEY", "").strip()

# Cookie jar of the France Student web session, exported from the user's own
# browser by scripts/fs_session_login.js. It holds a credential: never commit
# it, never print it.
FS_SESSION_FILE = Path(
    os.environ.get("FS_SESSION_FILE", str(BASE_DIR / ".fs-session.json"))
)

AUTH_EMAIL = os.environ.get("FS_EMAIL", "")
AUTH_PASSWORD = os.environ.get("FS_PASSWORD", "")

STORAGE_DIR = BASE_DIR / "storage"
IMAGES_DIR = STORAGE_DIR / "images"
STORE_FILE = BASE_DIR / "store.json"

REQUEST_TIMEOUT = float(os.environ.get("FS_REQUEST_TIMEOUT", "120"))
SSE_CONNECT_TIMEOUT = float(os.environ.get("FS_SSE_CONNECT_TIMEOUT", "30"))
SSE_READ_TIMEOUT = float(os.environ.get("FS_SSE_READ_TIMEOUT", "1200"))
SSE_WRITE_TIMEOUT = float(os.environ.get("FS_SSE_WRITE_TIMEOUT", "60"))
SSE_POOL_TIMEOUT = float(os.environ.get("FS_SSE_POOL_TIMEOUT", "30"))
SSE_TIMEOUT = httpx.Timeout(
    timeout=SSE_READ_TIMEOUT,
    connect=SSE_CONNECT_TIMEOUT,
    read=SSE_READ_TIMEOUT,
    write=SSE_WRITE_TIMEOUT,
    pool=SSE_POOL_TIMEOUT,
)
SSE_RECONNECT_TIMEOUT = 30

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]

SERVER_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("BIND_PORT", "8765"))
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    f"http://localhost:{SERVER_PORT}",
).rstrip("/")

DEFAULT_AGENT_ID = None
MODEL_REFRESH_INTERVAL = 3600
DEFAULT_IMAGE_AGENT_ID = int(os.environ.get("FS_IMAGE_AGENT_ID", "64"))
DEFAULT_IMAGE_MODEL = os.environ.get("FS_IMAGE_MODEL", "gpt-5.6-sol")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_IMAGE_DOWNLOAD_BYTES = int(
    os.environ.get("MAX_IMAGE_DOWNLOAD_BYTES", str(50 * 1024 * 1024))
)

# OpenCode session -> France Student chat mapping. This contains opaque IDs and
# request fingerprints, never prompts, credentials, or model output.
SESSION_DB_FILE = Path(os.environ.get("FS_SESSION_DB", str(BASE_DIR / "sessions.sqlite3")))
FS_CHAT_TOTAL_TIMEOUT = float(os.environ.get("FS_CHAT_TOTAL_TIMEOUT", "1800"))
MAX_TOOL_REPAIR_ROUNDS = int(os.environ.get("FS_MAX_TOOL_REPAIR_ROUNDS", "1"))
MAX_TOOL_RESULT_CHARS = int(os.environ.get("FS_MAX_TOOL_RESULT_CHARS", "1500"))
MAX_INITIAL_CONTEXT_CHARS = int(os.environ.get("FS_MAX_INITIAL_CONTEXT_CHARS", "2000"))
# Forwarding another agent's system prompt makes the France Student models
# refuse to act: they read it as "this chat is the engine of an external
# agent". The models carry their own instructions once the client tools are
# declared, so the prompt is dropped by default.
FORWARD_SYSTEM_PROMPT = os.environ.get("FS_FORWARD_SYSTEM_PROMPT", "false").lower() not in {
    "0", "false", "no", "off"
}

# France Student projects group the conversations of one activity. The
# bridge creates its conversations inside a dedicated project so they do not
# pollute the main tab of the account. Set FS_PROJECT_ID to use another one.
FS_PROJECT_ID = os.environ.get(
    "FS_PROJECT_ID", "cf8e2f44-ca9c-49e9-b358-8714cf6e508f"
).strip()

# France Student meters some models separately: a model can be refused with
# "limite atteinte" while the others work. The bridge then falls back to
# the next candidate, in this order, and parks the refused model for a
# while. Astra is the primary candidate, Fable the first fallback.
FS_FALLBACK_MODELS = os.environ.get(
    "FS_FALLBACK_MODELS",
    "gpt-6-astra,claude-fable-5-2,claude-sonnet-5-5,gpt-6-sol",
)
FS_MODEL_BLOCK_SECONDS = int(os.environ.get("FS_MODEL_BLOCK_SECONDS", "900"))

# When France Student refuses to create a new conversation (daily limit), the
# bridge can continue the most recent one instead of failing.
FS_REUSE_LAST_CHAT = os.environ.get("FS_REUSE_LAST_CHAT", "true").lower() not in {
    "0", "false", "no", "off"
}

# OpenCode agent that the bridge runs itself instead of sending it to the
# model. "majfs" refreshes the France Student model list.
FS_ACTION_AGENT = os.environ.get("FS_ACTION_AGENT", "majfs")

# OpenCode agent that the bridge runs itself to test the connection to
# France Student. Sends a simple "$opencodetest" message.
FS_TEST_AGENT = os.environ.get("FS_TEST_AGENT", "test")

# OpenCode agent that the bridge runs itself to report France Student usage
# and quotas. Calls the local /usage endpoint and formats the result.
FS_USAGE_AGENT = os.environ.get("FS_USAGE_AGENT", "usage")

# France Student quotas the bridge stays below on purpose.
#   - 50 new chats per day (published limit: 50)
#   - a rolling hourly message budget (published limit: 100 messages/hour)
# The defaults leave headroom so a burst of OpenCode turns cannot exhaust
# the upstream quota. Set a limit to 0 to disable the corresponding guard.
FS_MAX_MESSAGES_PER_HOUR = int(os.environ.get("FS_MAX_MESSAGES_PER_HOUR", "60"))
FS_MAX_NEW_CHATS_PER_DAY = int(os.environ.get("FS_MAX_NEW_CHATS_PER_DAY", "40"))
# How long a request may wait for a free slot before the bridge gives up.
FS_QUOTA_WAIT_TIMEOUT = float(os.environ.get("FS_QUOTA_WAIT_TIMEOUT", "600"))
REQUIRE_OPENCODE_SESSION = os.environ.get("FS_REQUIRE_OPENCODE_SESSION", "true").lower() not in {
    "0", "false", "no", "off"
}

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
