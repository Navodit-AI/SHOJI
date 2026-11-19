"""Sending requests to the upstream provider, with a bounded retry."""

import asyncio

import httpx

# Failures where the request never reached the provider, so retrying cannot double-run it.
RETRYABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


async def send_with_retry(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    stream: bool,
    retries: int = 1,
    backoff: float = 0.5,
) -> httpx.Response:
    """Send `request`, retrying connection failures and 5xx responses up to `retries` times.

    Retries only happen before any response is handed back, so a stream that has started is
    never retried. Read timeouts are not retried: the provider may still be generating, and
    waiting a second full timeout is worse than failing fast.
    """
    for attempt in range(retries + 1):
        last_attempt = attempt == retries
        try:
            response = await client.send(request, stream=stream)
        except RETRYABLE_ERRORS:
            if last_attempt:
                raise
        else:
            if response.status_code < 500 or last_attempt:
                return response
            await response.aclose()
        await asyncio.sleep(backoff * (attempt + 1))
    raise AssertionError("unreachable")  # pragma: no cover
