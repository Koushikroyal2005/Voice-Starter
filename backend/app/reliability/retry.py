"""Retries for explicitly idempotent control-plane probes, never business actions."""

import asyncio
import random


async def retry_probe(
    operation,
    *,
    attempts=3,
    timeout=3,
    base_delay=0.1,
    sleep=asyncio.sleep,
    jitter=random.uniform,
    retryable=(OSError, TimeoutError, ConnectionError),
):
    if not 1 <= attempts <= 4 or not 0 < timeout <= 10 or not 0 <= base_delay <= 1:
        raise ValueError("Invalid bounded probe retry policy")
    for attempt in range(attempts):
        try:
            async with asyncio.timeout(timeout):
                return await operation()
        except retryable:
            if attempt == attempts - 1:
                raise
            await sleep(jitter(0, min(2, base_delay * 2**attempt)))
