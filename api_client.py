import asyncio
import logging

import httpx

from config.config import API_BASE_URL, REQUEST_TIMEOUT, SSE_TIMEOUT
from sse_parser import parse_sse_stream, parse_sse_stream_sync

logger = logging.getLogger("france_student_bridge.api")


class IncompleteSSEStream(RuntimeError):
    def __init__(self, events, cause):
        super().__init__(f"SSE stream interrupted ({type(cause).__name__})")
        self.events = events
        self.cause = cause


class FranceStudentLimitError(RuntimeError):
    """France Student refused the request because a published limit was hit.

    The message comes from France Student and describes a quota (for example
    the daily new-chat limit). It never contains personal data.
    """

    def __init__(self, message, status=429):
        super().__init__(message)
        self.status = status


def _raise_for_limit(response):
    """Turn a quota refusal into an explicit, readable error."""
    if response.status_code != 429:
        response.raise_for_status()
        return
    detail = ""
    try:
        payload = response.json()
        detail = str(payload.get("message") or "")
    except Exception:
        detail = ""
    if not detail:
        detail = "France Student a refusé la requête : limite atteinte."
    raise FranceStudentLimitError(detail, status=429)


class FranceStudentAPI:
    def __init__(self, auth):
        self._auth = auth

    def _headers(self, extra=None, force_auth=False):
        headers = self._auth.get_headers(force=force_auth)
        if extra:
            headers.update(extra)
        return headers

    def _chat_create_body(self, message, agent_id, images, files,
                          enable_web_search, client_tools=None, project_id=None):
        # ChatCreateDto, as published in the France Student OpenAPI spec.
        body = {
            "agentId": agent_id,
            "initialContent": message,
            "images": images or [],
            "files": files or [],
            "enableWebSearch": enable_web_search,
        }
        if client_tools:
            body["clientTools"] = list(client_tools)
        if project_id:
            body["projectId"] = project_id
        return body

    async def _get(self, session, path, **kwargs):
        headers = kwargs.pop("headers", None)
        # A read-only request is safe to repeat, so a transient connection
        # error is retried once. Mutating calls are never repeated.
        for attempt in range(3):
            try:
                response = await session.get(
                    f"{API_BASE_URL}{path}",
                    headers=self._headers(headers, force_auth=attempt > 0),
                    **kwargs,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 2:
                    raise
                logger.warning("retrying_read request=%s error=%s", path, type(exc).__name__)
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if response.status_code != 401 or attempt:
                return response
            self._auth.clear()

    async def _post(self, session, path, json=None, **kwargs):
        headers = kwargs.pop("headers", None)
        for attempt in range(2):
            response = await session.post(
                f"{API_BASE_URL}{path}",
                headers=self._headers(headers, force_auth=attempt == 1),
                json=json,
                **kwargs,
            )
            if response.status_code != 401 or attempt:
                return response
            self._auth.clear()

    async def _delete(self, session, path, **kwargs):
        headers = kwargs.pop("headers", None)
        for attempt in range(2):
            response = await session.delete(
                f"{API_BASE_URL}{path}",
                headers=self._headers(headers, force_auth=attempt == 1),
                **kwargs,
            )
            if response.status_code != 401 or attempt:
                return response
            self._auth.clear()

    async def get_user_usage(self):
        """Return the France Student quotas of the account."""
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._get(c, "/user/usage")
            r.raise_for_status()
            return r.json()

    async def get_token_usage(self):
        """Return the token counters of the account."""
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._get(c, "/user/tokenusage")
            r.raise_for_status()
            return r.json()

    async def get_models(self, include_disabled=False):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._get(
                c,
                "/chats/agents",
                params={"include-disabled": str(include_disabled).lower()},
            )
            r.raise_for_status()
            agents = r.json()
            return [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "namespace": a.get("namespace"),
                    "description": a.get("description", ""),
                    "model": a.get("model", ""),
                    "modelProvider": a.get("modelProvider", ""),
                    "isActive": a.get("isActive", False),
                    "isDefault": a.get("isDefault", False),
                }
                for a in agents
                if include_disabled or a.get("isActive")
            ]

    async def create_chat(self, message, agent_id=None, images=None, files=None,
                          enable_web_search=False, client_tools=None,
                          project_id=None):
        body = self._chat_create_body(
            message,
            agent_id,
            images,
            files,
            enable_web_search,
            client_tools,
            project_id,
        )
        async with httpx.AsyncClient(timeout=SSE_TIMEOUT) as c:
            for path in ("/chats/stream", "/chats"):
                fallback = False
                for auth_attempt in range(2):
                    async with c.stream(
                        "POST",
                        f"{API_BASE_URL}{path}",
                        headers=self._headers(force_auth=auth_attempt == 1),
                        json=body,
                    ) as r:
                        if r.status_code == 401 and not auth_attempt:
                            self._auth.clear()
                            continue
                        if path == "/chats/stream" and r.status_code in (404, 405):
                            fallback = True
                            break
                        _raise_for_limit(r)
                        r.raise_for_status()
                        events = []
                        try:
                            async for ev in parse_sse_stream(r):
                                events.append(ev)
                        except (httpx.TimeoutException, httpx.TransportError) as exc:
                            if events:
                                raise IncompleteSSEStream(events, exc) from exc
                            raise
                        return events
                if fallback:
                    continue
        raise RuntimeError("No supported France Student create-chat endpoint")

    def stream_chat(self, message, agent_id=None, images=None, files=None,
                    enable_web_search=False):
        body = self._chat_create_body(
            message,
            agent_id,
            images,
            files,
            enable_web_search,
        )
        with httpx.Client(timeout=SSE_TIMEOUT) as client:
            for path in ("/chats/stream", "/chats"):
                fallback = False
                for auth_attempt in range(2):
                    with client.stream(
                        "POST",
                        f"{API_BASE_URL}{path}",
                        headers=self._headers(force_auth=auth_attempt == 1),
                        json=body,
                    ) as response:
                        if response.status_code == 401 and not auth_attempt:
                            self._auth.clear()
                            continue
                        if path == "/chats/stream" and response.status_code in (404, 405):
                            fallback = True
                            break
                        response.raise_for_status()
                        yield from parse_sse_stream_sync(response)
                        return
                if fallback:
                    continue
        raise RuntimeError("No supported France Student create-chat endpoint")

    async def send_message(self, chat_id, message, agent_id=None, images=None,
                           files=None, enable_web_search=False,
                           tool_results=None, client_tools=None):
        body = {
            "content": message,
            "images": images or [],
            "files": files or [],
            "enableWebSearch": enable_web_search,
        }
        if agent_id is not None:
            body["agentId"] = agent_id
        if tool_results:
            # ChatToolResultInputDto entries: callId, output, isError.
            body["toolResults"] = list(tool_results)
        if client_tools:
            body["clientTools"] = list(client_tools)
        async with httpx.AsyncClient(timeout=SSE_TIMEOUT) as c:
            for auth_attempt in range(2):
                async with c.stream(
                    "POST",
                    f"{API_BASE_URL}/chats/{chat_id}",
                    headers=self._headers(force_auth=auth_attempt == 1),
                    json=body,
                ) as r:
                    if r.status_code == 401 and not auth_attempt:
                        self._auth.clear()
                        continue
                    _raise_for_limit(r)
                    r.raise_for_status()
                    events = []
                    try:
                        async for ev in parse_sse_stream(r):
                            events.append(ev)
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        if events:
                            raise IncompleteSSEStream(events, exc) from exc
                        raise
                    return events

    async def reconnect_stream(self, chat_id, last_event_id):
        headers = {
            **self._headers(),
            "Last-Event-ID": str(last_event_id),
        }
        async with httpx.AsyncClient(timeout=SSE_TIMEOUT) as c:
            for auth_attempt in range(2):
                request_headers = (
                    self._headers({"Last-Event-ID": str(last_event_id)}, force_auth=auth_attempt == 1)
                )
                async with c.stream(
                    "GET",
                    f"{API_BASE_URL}/chats/{chat_id}/stream",
                    headers=request_headers,
                    params={"last_event_id": last_event_id},
                ) as r:
                    if r.status_code == 401 and not auth_attempt:
                        self._auth.clear()
                        continue
                    r.raise_for_status()
                    events = []
                    async for ev in parse_sse_stream(r):
                        events.append(ev)
                    return events

    async def get_chat(self, chat_id):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._get(c, f"/chats/{chat_id}")
            r.raise_for_status()
            return r.json()

    async def get_chats(self, limit=20, cursor_chat_id=None):
        params = {"limit": limit}
        if cursor_chat_id:
            params["cursor_chat_id"] = cursor_chat_id
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._get(c, "/chats", params=params)
            r.raise_for_status()
            return r.json()

    async def delete_chat(self, chat_id):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._delete(c, f"/chats/{chat_id}")
            r.raise_for_status()

    async def get_chat_usage(self, chat_id):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._get(c, f"/chats/{chat_id}/usage")
            r.raise_for_status()
            return r.json()

    async def upload_file(self, file_path):
        from pathlib import Path
        file_path = Path(file_path)
        content_type = _guess_content_type(file_path.name)
        return await self.upload_bytes(
            file_path.name,
            file_path.read_bytes(),
            content_type,
        )

    async def upload_bytes(self, filename, content,
                           content_type="application/octet-stream"):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            for auth_attempt in range(2):
                auth_header = self._auth.get_headers(force=auth_attempt == 1).get("Authorization")
                r = await c.post(
                    f"{API_BASE_URL}/files/upload",
                    headers={"Authorization": auth_header},
                    files={"file": (filename, content, content_type)},
                )
                if r.status_code != 401 or auth_attempt:
                    break
                self._auth.clear()
            r.raise_for_status()
            return r.json()

    async def get_image(self, chat_id, message_id, image_id):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            r = await self._get(c, f"/chats/{chat_id}/messages/{message_id}/images/{image_id}")
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "image/png")


def _guess_content_type(filename):
    from pathlib import Path
    suffix = Path(filename).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")
