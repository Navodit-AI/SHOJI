"""OpenAI-compatible proxy application."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from shoji.capture import Capture, RequestRecord, request_id_from
from shoji.config import Settings
from shoji.detect import Entity, default_registry, resolve
from shoji.redact import Mapping, redact_messages, restore
from shoji.streaming import MID_STREAM_ERROR, SseRestorer, relay
from shoji.upstream import send_with_retry
from shoji.vault import open_vault

REQUEST_ID_HEADER = "X-Request-ID"
# Optional: lets the vault keep a conversation's placeholders across requests.
CONVERSATION_HEADER = "X-Shoji-Conversation"


def _error(status: int, message: str, err_type: str = "invalid_request_error") -> JSONResponse:
    """Return an error in the OpenAI response shape, so existing clients parse it."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": err_type, "code": None}},
    )


def _upstream_error(resp: httpx.Response) -> Response:
    """Pass the provider's error through if it is already OpenAI-shaped; otherwise wrap it.

    Gateways in front of providers sometimes return HTML or plain-text error pages, which
    OpenAI client SDKs cannot parse.
    """
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return Response(
            content=resp.content, status_code=resp.status_code, media_type="application/json"
        )
    return _error(
        resp.status_code, f"Upstream provider returned HTTP {resp.status_code}.", "upstream_error"
    )


def _restore_completion(resp: httpx.Response, mapping: Mapping) -> bytes:
    """The response body with placeholders in ``choices[].message.content`` restored."""
    try:
        payload = resp.json()
    except ValueError:
        return resp.content
    changed = False
    choices = payload.get("choices") if isinstance(payload, dict) else None
    for choice in choices if isinstance(choices, list) else []:
        message = choice.get("message") if isinstance(choice, dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            restored = restore(message["content"], mapping)
            if restored != message["content"]:
                message["content"] = restored
                changed = True
    return json.dumps(payload, ensure_ascii=False).encode() if changed else resp.content


def create_app(settings: Settings | None = None, capture: Capture | None = None) -> FastAPI:
    settings = settings or Settings()
    capture = capture or Capture()
    provider = settings.provider()
    registry = default_registry()

    def detector(text: str) -> list[Entity]:
        # Drop weak candidates before resolving overlaps, so a low-scoring long span can't
        # hide a confident shorter one.
        return resolve(e for e in registry.analyze(text) if e.score >= settings.shoji_min_score)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url=provider.base_url,
            timeout=settings.shoji_upstream_timeout,
        ) as client:
            app.state.upstream = client
            # Used by redaction from #26; opened here so a bad key fails at startup.
            app.state.vault = open_vault(
                settings.shoji_vault_key, settings.shoji_vault_path, settings.shoji_vault_ttl_hours
            )
            try:
                yield
            finally:
                if app.state.vault is not None:
                    app.state.vault.close()

    app = FastAPI(title="SHOJI", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": provider.name}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        record = RequestRecord(
            request_id=request_id_from(request.headers.get(REQUEST_ID_HEADER)),
            provider=provider.name,
        )
        response = await _proxy(request, record)
        response.headers[REQUEST_ID_HEADER] = record.request_id
        if not isinstance(response, StreamingResponse):
            capture.finish(record, response.status_code)
        # Streaming responses finish their record when the stream ends (see _stream_body).
        return response

    async def _proxy(request: Request, record: RequestRecord) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            record.error_type = "invalid_request"
            return _error(400, "Request body must be valid JSON.")
        if not isinstance(body, dict):
            record.error_type = "invalid_request"
            return _error(400, "Request body must be a JSON object.")

        if "model" not in body and settings.shoji_default_model:
            body["model"] = settings.shoji_default_model
        stream = bool(body.get("stream"))
        record.model = body.get("model") if isinstance(body.get("model"), str) else None
        record.stream = stream

        mapping = None
        if settings.shoji_redact and isinstance(body.get("messages"), list):
            mapping = _redact(body, request, record)

        # The client's own Authorization header is never forwarded: the proxy holds the key.
        upstream: httpx.AsyncClient = request.app.state.upstream
        upstream_request = upstream.build_request(
            "POST",
            "/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {provider.api_key}"},
        )
        try:
            resp = await send_with_retry(
                upstream,
                upstream_request,
                stream=stream,
                retries=settings.shoji_upstream_retries,
                backoff=settings.shoji_retry_backoff,
            )
        except httpx.TimeoutException:
            record.mark_upstream()
            record.error_type = "upstream_timeout"
            return _error(
                504,
                f"Upstream provider did not respond within {settings.shoji_upstream_timeout:g}s.",
                "upstream_timeout",
            )
        except httpx.TransportError:
            record.mark_upstream()
            record.error_type = "upstream_unavailable"
            return _error(502, "Could not reach the upstream provider.", "upstream_unavailable")
        record.mark_upstream()

        if stream and resp.is_success:
            return StreamingResponse(
                _stream_body(resp, record, mapping),
                status_code=resp.status_code,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        if stream:
            # Errors arrive as a normal body even for stream requests.
            await resp.aread()
            await resp.aclose()

        if not resp.is_success:
            record.error_type = "upstream_error"
            return _upstream_error(resp)
        return Response(
            content=_restore_completion(resp, mapping) if mapping else resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    def _redact(body: dict, request: Request, record: RequestRecord) -> Mapping:
        """Redact ``body["messages"]`` in place; return the mapping to restore the reply with."""
        t0 = time.perf_counter()
        vault = request.app.state.vault
        conversation = request.headers.get(CONVERSATION_HEADER) or None
        stored = vault.load(conversation) if vault and conversation else None
        result = redact_messages(body["messages"], detector=detector, mapping=stored)
        body["messages"] = result.messages
        if vault and conversation:
            vault.save(conversation, result.mapping)
        record.entity_counts = {str(t): n for t, n in sorted(result.counts.items())}
        record.redaction_ms = round((time.perf_counter() - t0) * 1000, 2)
        return result.mapping

    async def _stream_body(
        resp: httpx.Response, record: RequestRecord, mapping: Mapping | None
    ) -> AsyncIterator[bytes]:
        restorer = SseRestorer(mapping) if mapping else None
        try:
            async for event in relay(resp.aiter_bytes(), resp.aclose, restorer):
                if event is MID_STREAM_ERROR:
                    record.error_type = "upstream_error_mid_stream"
                yield event
        except (GeneratorExit, asyncio.CancelledError):
            record.error_type = "client_disconnected"
            raise
        finally:
            capture.finish(record, resp.status_code)

    return app
