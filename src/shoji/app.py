"""OpenAI-compatible proxy application."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from shoji.config import Settings
from shoji.streaming import relay


def _error(status: int, message: str, err_type: str = "invalid_request_error") -> JSONResponse:
    """Return an error in the OpenAI response shape, so existing clients parse it."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": err_type, "code": None}},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    provider = settings.provider()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url=provider.base_url,
            timeout=settings.shoji_upstream_timeout,
        ) as client:
            app.state.upstream = client
            yield

    app = FastAPI(title="SHOJI", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": provider.name}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error(400, "Request body must be valid JSON.")
        if not isinstance(body, dict):
            return _error(400, "Request body must be a JSON object.")

        if "model" not in body and settings.shoji_default_model:
            body["model"] = settings.shoji_default_model

        # The client's own Authorization header is never forwarded: the proxy holds the key.
        upstream: httpx.AsyncClient = request.app.state.upstream
        upstream_request = upstream.build_request(
            "POST",
            "/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {provider.api_key}"},
        )
        resp = await upstream.send(upstream_request, stream=bool(body.get("stream")))

        if body.get("stream"):
            if resp.is_success:
                return StreamingResponse(
                    relay(resp.aiter_bytes(), resp.aclose),
                    status_code=resp.status_code,
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache"},
                )
            # Errors arrive as a normal JSON body even for stream requests.
            await resp.aread()
            await resp.aclose()

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    return app
