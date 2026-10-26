import asyncio
import ipaddress
import json
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.integrations.discovery.base import ProviderError

Resolver = Callable[[str], Awaitable[list[str]]]


async def public_addresses(host: str) -> list[str]:
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderError("DNS_FAILED") from exc
    return list({str(record[4][0]) for record in records})


class SafeHTTP:
    def __init__(
        self,
        allowed_hosts: set[str],
        *,
        timeout: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = public_addresses,
        interval: float = 0.25,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.timeout = timeout
        self.transport = transport
        self.resolver = resolver
        self.interval = interval
        self.last_request = 0.0
        self.lock = asyncio.Lock()

    async def validate(self, url: str) -> list[str]:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (
            parts.scheme != "https"
            or host not in self.allowed_hosts
            or parts.username
            or parts.password
            or parts.port not in {None, 443}
        ):
            raise ProviderError("URL_NOT_ALLOWED")
        addresses = await self.resolver(host)
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ProviderError("PRIVATE_ADDRESS_BLOCKED")
        return sorted(addresses, key=lambda address: ":" in address)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> bytes:
        addresses = await self.validate(url)
        original_host = urlsplit(url).hostname or ""
        request_headers = {"Host": original_host, "Accept-Encoding": "identity", **(headers or {})}
        attempts = 3 if method == "GET" else 1
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=False, trust_env=False, transport=self.transport
        ) as client:
            for attempt in range(attempts):
                async with self.lock:
                    pause = self.interval - (time.monotonic() - self.last_request)
                    if pause > 0:
                        await asyncio.sleep(pause)
                    self.last_request = time.monotonic()
                retry_delay = float(2**attempt)
                try:
                    # Connect to a validated address, retaining the real hostname for TLS/Host.
                    # A second DNS resolution must not permit DNS-rebinding into private networks.
                    target = (
                        httpx.URL(url)
                        if self.transport is not None
                        else httpx.URL(url).copy_with(host=addresses[attempt % len(addresses)])
                    )
                    async with client.stream(
                        method,
                        target,
                        params=params,
                        headers=request_headers,
                        data=data,
                        json=json_body,
                        extensions={"sni_hostname": original_host},
                    ) as response:
                        if response.headers.get("Content-Encoding", "identity").lower() not in {
                            "",
                            "identity",
                        }:
                            raise ProviderError("UNEXPECTED_CONTENT_ENCODING")
                        if response.status_code in {429, 500, 502, 503, 504}:
                            try:
                                retry_delay = min(
                                    5,
                                    max(0, float(response.headers.get("Retry-After", retry_delay))),
                                )
                            except ValueError:
                                pass
                            if attempt == attempts - 1:
                                raise ProviderError(f"HTTP_{response.status_code}")
                        elif response.status_code != 200:
                            raise ProviderError(f"HTTP_{response.status_code}")
                        else:
                            chunks: list[bytes] = []
                            size = 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > 5 * 1024 * 1024:
                                    raise ProviderError("RESPONSE_TOO_LARGE")
                                chunks.append(chunk)
                            return b"".join(chunks)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == attempts - 1:
                        raise ProviderError("NETWORK_ERROR") from exc
                await asyncio.sleep(retry_delay)
        raise ProviderError("REQUEST_FAILED")

    async def json(self, method: str, url: str, **kwargs: Any) -> Any:
        content = await self.request(method, url, **kwargs)
        try:
            return json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise ProviderError("INVALID_JSON") from exc
