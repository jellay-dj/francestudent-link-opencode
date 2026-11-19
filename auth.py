"""Authentication against the France Student API.

Two mechanisms are supported, both documented by France Student:

``api_key``
    Uses an official API key ("Clé API" in the CGU 2026, Livre V). The key is
    sent as the ``authorization`` header, exactly like the published OpenAPI
    security scheme declares. The feature is only enabled for accounts that
    have been granted it, so it is opt-in.

``session`` (default)
    Reuses the browser session of the account owner. The session cookie is
    exchanged for a short-lived access token through the documented
    ``GET {web}/api/auth/api-token`` endpoint, which requires the same client
    metadata headers the France Student front end sends. The access token
    lives a few minutes, so the bridge refreshes it automatically.

No secret is ever logged or returned in an error message.
"""

import base64
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx

from config.config import (
    API_BASE_URL,
    AUTH_API_URL,
    AUTH_EMAIL,
    AUTH_PASSWORD,
    FRONTEND_URL,
    FS_API_KEY,
    FS_AUTH_MODE,
    FS_CLIENT_PLATFORM,
    FS_CLIENT_VERSION,
    FS_SESSION_FILE,
    REQUEST_TIMEOUT,
    STORE_FILE,
)


logger = logging.getLogger("france_student_bridge.auth")

# The access token issued by /api/auth/api-token is short lived. Refresh it
# slightly before it expires so an in-flight request never races the expiry.
TOKEN_REFRESH_MARGIN_SEC = 60

# France Student sits behind a CDN that rejects requests without browser
# origin headers ("This request was blocked by our security rules"). The
# bridge identifies itself as the web client it is a client of, which is the
# same origin the account owner already uses.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)


def _origin_headers():
    return {
        "User-Agent": os.environ.get("FS_USER_AGENT", DEFAULT_USER_AGENT),
        "Referer": f"{FRONTEND_URL}/",
        "Origin": FRONTEND_URL,
        "Accept-Language": os.environ.get("FS_ACCEPT_LANGUAGE", "fr-FR,fr;q=0.9,en;q=0.7"),
    }


class AuthMethodError(RuntimeError):
    """An authentication attempt failed for a categorical reason."""

    def __init__(self, message, safe_diagnostic):
        super().__init__(message)
        self.safe_diagnostic = safe_diagnostic


class AuthManager:
    def __init__(self, mode=None):
        self._mode = (mode or FS_AUTH_MODE or "session").strip().lower()
        self._token = None
        self._expires_at_sec = 0
        self._pending = None
        self._lock = threading.RLock()
        self._client = httpx.Client(timeout=REQUEST_TIMEOUT)
        self._cookies = {}
        self._device_id = None
        self._load_store()

    # ── state ────────────────────────────────────────────────────────
    @property
    def mode(self):
        return self._mode

    @property
    def token(self):
        return self._token

    @property
    def is_authenticated(self):
        if self._mode == "api_key":
            return bool(FS_API_KEY)
        return self._token is not None and not self._is_expired()

    @property
    def has_credentials(self):
        """True when the bridge holds the material needed to authenticate.

        This is true before the first request, even though no access token
        has been fetched yet.
        """
        if self._mode == "api_key":
            return bool(FS_API_KEY)
        if self._token and not self._is_expired():
            return True
        return FS_SESSION_FILE.exists()

    def _is_expired(self):
        return time.time() + TOKEN_REFRESH_MARGIN_SEC >= self._expires_at_sec

    def _load_store(self):
        """Restore a cached access token, if any."""
        if STORE_FILE.exists():
            try:
                data = json.loads(STORE_FILE.read_text())
            except (OSError, ValueError):
                data = {}
            if self._mode != "api_key" and data.get("token"):
                self._token = data["token"]
                self._expires_at_sec = data.get("expires_at_sec", 0)

    def _save_store(self):
        if self._mode == "api_key":
            return
        temporary_file = STORE_FILE.with_suffix(STORE_FILE.suffix + ".tmp")
        temporary_file.write_text(json.dumps({
            "token": self._token,
            "expires_at_sec": self._expires_at_sec,
        }))
        os.replace(temporary_file, STORE_FILE)

    def _parse_jwt_expiry(self, token):
        """Extract the expiry timestamp from a JWT payload."""
        try:
            parts = token.split(".")
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload_b64))
            return data.get("exp", time.time() + 300)
        except Exception:
            return time.time() + 300

    # ── session material ─────────────────────────────────────────────
    def _load_session_cookies(self):
        """Read the browser session cookie jar exported from Chrome."""
        if not FS_SESSION_FILE.exists():
            raise AuthMethodError(
                "No France Student session file. Run scripts/fs_session_login.js "
                "to create one.",
                "session_file_missing",
            )
        try:
            payload = json.loads(FS_SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AuthMethodError(
                "The France Student session file is not readable JSON.",
                "session_file_invalid",
            ) from exc

        cookies = payload.get("cookies")
        if not isinstance(cookies, list) or not cookies:
            raise AuthMethodError(
                "The France Student session file contains no cookie.",
                "session_file_empty",
            )

        jar = {}
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue
            domain = (cookie.get("domain") or "").lstrip(".")
            if domain and not (
                FRONTEND_URL.replace("https://", "").split("/")[0] == domain
                or domain.endswith("francestudent.org")
            ):
                continue
            jar[name] = value
            if name == "francestudent-device-id":
                self._device_id = value

        if "next-auth.session-token" not in jar:
            raise AuthMethodError(
                "The France Student session file has no session token. Log in "
                "again and re-export it.",
                "session_token_missing",
            )
        return jar

    def _get_device_id(self):
        """Stable per-installation device identifier."""
        if self._device_id:
            return self._device_id
        candidate = uuid.uuid4().hex
        try:
            payload = json.loads(FS_SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        if payload.get("device_id"):
            self._device_id = payload["device_id"]
        else:
            payload["device_id"] = candidate
            try:
                FS_SESSION_FILE.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass
            self._device_id = candidate
        return self._device_id

    # ── authentication methods ───────────────────────────────────────
    def _login_via_api_key(self):
        if not FS_API_KEY:
            raise AuthMethodError(
                "FS_AUTH_MODE=api_key requires FS_API_KEY to be set.",
                "api_key_missing",
            )
        self._token = FS_API_KEY
        self._expires_at_sec = time.time() + 86400
        return self._token

    def _login_via_session_token(self):
        """Exchange the browser session cookie for an access token."""
        cookies = self._load_session_cookies()
        headers = {
            **_origin_headers(),
            "francestudent-client-platform": FS_CLIENT_PLATFORM,
            "francestudent-client-version": FS_CLIENT_VERSION,
            "francestudent-device-id": self._get_device_id(),
            "Accept": "application/json",
        }
        try:
            response = self._client.get(
                f"{AUTH_API_URL}/api-token",
                headers=headers,
                cookies=cookies,
            )
        except httpx.HTTPError as exc:
            raise AuthMethodError(
                "The France Student token endpoint is unreachable.",
                "token_endpoint_unreachable",
            ) from exc

        if response.status_code == 401:
            raise AuthMethodError(
                "The France Student session expired. Log in again and "
                "re-export the session.",
                "session_expired",
            )
        if response.status_code != 200:
            raise AuthMethodError(
                "The France Student token endpoint refused the request.",
                f"token_endpoint_http_{response.status_code}",
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise AuthMethodError(
                "The France Student token endpoint returned an unreadable body.",
                "token_endpoint_unreadable",
            ) from exc

        token = data.get("accessToken")
        if not token:
            raise AuthMethodError(
                "The France Student token endpoint returned no access token.",
                "token_missing",
            )

        self._token = token
        expires_at = data.get("expiresAt")
        if isinstance(expires_at, (int, float)):
            self._expires_at_sec = (
                expires_at / 1000 if expires_at > 10_000_000_000 else expires_at
            )
        else:
            self._expires_at_sec = self._parse_jwt_expiry(token)
        self._save_store()
        return self._token

    def _login_via_puppeteer(self):
        """Legacy fallback: run the SSO helper script."""
        script_path = Path(__file__).parent / "get_jwt.js"
        if not script_path.exists():
            raise AuthMethodError("Puppeteer SSO script unavailable.", "script_missing")

        node_binary = os.environ.get("NODE_BINARY") or shutil.which("node") or shutil.which("node.exe")
        if not node_binary and os.name == "nt":
            for program_dir in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
                if program_dir:
                    candidate = Path(program_dir) / "nodejs" / "node.exe"
                    if candidate.is_file():
                        node_binary = str(candidate)
                        break
        if not node_binary:
            raise AuthMethodError("Node.js unavailable for SSO fallback.", "node_unavailable")

        env = os.environ.copy()
        env["FS_EMAIL"] = os.environ.get("FS_EMAIL", AUTH_EMAIL)
        env["FS_PASSWORD"] = os.environ.get("FS_PASSWORD", AUTH_PASSWORD)

        chrome_binary = os.environ.get("CHROME_PATH") or shutil.which("chrome.exe") or shutil.which("chrome")
        if not chrome_binary and os.name == "nt":
            chrome_candidates = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
                / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Google" / "Chrome" / "Application" / "chrome.exe",
            )
            chrome_binary = next((str(path) for path in chrome_candidates if path.is_file()), None)
        if chrome_binary:
            env["CHROME_PATH"] = chrome_binary

        try:
            result = subprocess.run(
                [node_binary, str(script_path)],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AuthMethodError("Puppeteer SSO timed out.", "sso_process_timeout") from exc
        except OSError as exc:
            raise AuthMethodError("Puppeteer SSO process could not start.", "sso_process_unavailable") from exc
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if "cannot find module" in stderr and "puppeteer-core" in stderr:
                safe_diagnostic = "dependency_missing"
            elif "failed to launch the browser process" in stderr or "executable doesn't exist" in stderr:
                safe_diagnostic = "browser_launch_failed"
            elif "navigation timeout" in stderr or "navigation timeout exceeded" in stderr:
                safe_diagnostic = "sso_navigation_timeout"
            elif "jwt non obtenu" in stderr:
                safe_diagnostic = "sso_token_unavailable"
            else:
                safe_diagnostic = "sso_script_failed"
            raise AuthMethodError(
                "Puppeteer SSO a échoué; détails techniques sensibles masqués.",
                safe_diagnostic,
            )

        token = result.stdout.strip()
        # A successful child-process exit is not sufficient proof that SSO
        # returned a usable token. Keep this diagnostic categorical: never
        # include stdout or token fragments in logs or API errors.
        token_parts = token.split(".")
        if len(token) < 50 or len(token_parts) != 3 or not all(token_parts):
            raise AuthMethodError(
                "Puppeteer SSO did not return a valid JWT; token contents masked.",
                "sso_token_invalid",
            )
        self._token = token
        self._expires_at_sec = self._parse_jwt_expiry(token)
        self._save_store()
        return self._token

    def _do_auth_flow(self):
        if self._mode == "api_key":
            failures = []
            for method, login in (("api_key", self._login_via_api_key),):
                try:
                    return login()
                except Exception as exc:
                    detail = getattr(exc, "safe_diagnostic", type(exc).__name__)
                    failures.append(f"{method}={detail}")
                    logger.warning("authentication_method_failed method=%s detail=%s", method, detail)
            raise RuntimeError(
                "Impossible de s'authentifier avec la clé API FS. "
                "Diagnostic sans secrets : " + ", ".join(failures)
            )

        failures = []
        for method, login in (
            ("session", self._login_via_session_token),
            ("puppeteer", self._login_via_puppeteer),
        ):
            try:
                return login()
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                detail = (
                    f"HTTP {status}"
                    if status is not None
                    else getattr(exc, "safe_diagnostic", type(exc).__name__)
                )
                failures.append(f"{method}={detail}")
                logger.warning("authentication_method_failed method=%s detail=%s", method, detail)

        raise RuntimeError(
            "Impossible de s'authentifier auprès de France Student. Lancez "
            "scripts/fs_session_login.js pour exporter la session du compte, ou "
            "définissez FS_API_KEY si votre compte dispose d'une clé API "
            "officielle. Diagnostic sans secrets : " + ", ".join(failures)
        )

    # ── public API ───────────────────────────────────────────────────
    def get_token(self, force=False):
        with self._lock:
            if force:
                self._token = None
                self._expires_at_sec = 0

            if self._mode == "api_key":
                return self._login_via_api_key()

            if self._token and not self._is_expired():
                return self._token

            if self._pending is not None:
                return self._pending

            try:
                self._pending = self._do_auth_flow()
                return self._pending
            finally:
                self._pending = None

    def get_headers(self, force=False):
        token = self.get_token(force=force)
        headers = {
            **_origin_headers(),
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "francestudent-client-platform": FS_CLIENT_PLATFORM,
            "francestudent-client-version": FS_CLIENT_VERSION,
            "francestudent-device-id": self._get_device_id(),
        }
        return headers

    def clear(self):
        with self._lock:
            self._token = None
            self._expires_at_sec = 0
            if STORE_FILE.exists():
                STORE_FILE.unlink()
