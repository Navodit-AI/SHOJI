"""OpenAI-compatible proxy application."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from shoji.capture import Capture, RequestRecord, request_id_from
from shoji.config import Settings
from shoji.streaming import MID_STREAM_ERROR, relay
from shoji.upstream import send_with_retry
from shoji.vault import open_vault

REQUEST_ID_HEADER = "X-Request-ID"


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


def create_app(settings: Settings | None = None, capture: Capture | None = None) -> FastAPI:
    settings = settings or Settings()
    capture = capture or Capture()
    provider = settings.provider()

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
                _stream_body(resp, record),
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
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    async def _stream_body(resp: httpx.Response, record: RequestRecord) -> AsyncIterator[bytes]:
        try:
            async for event in relay(resp.aiter_bytes(), resp.aclose):
                if event is MID_STREAM_ERROR:
                    record.error_type = "upstream_error_mid_stream"
                yield event
        except (GeneratorExit, asyncio.CancelledError):
            record.error_type = "client_disconnected"
            raise
        finally:
            capture.finish(record, resp.status_code)

    return app
