# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Async HTTP/S image cache provider for MarkdownWidget.

Defence-in-depth against SSRF:

* Outbound hosts are resolved (``socket.getaddrinfo``) and compared against
  an IP deny list covering loopback, link-local, RFC1918 private, CGNAT, and
  unspecified ranges.  Opt-in escape hatch via ``allow_private_networks``.
* A custom redirect handler enforces the same IP deny list after every 3xx,
  rejects dangerous schemes (``file://``, ``ftp://``, ``data:``), and can
  optionally refuse https → http downgrades.
* ``Content-Length``, when present, is validated *before* streaming the body.
* Redirects are capped at 5.
"""
from __future__ import annotations

import ipaddress
import mimetypes
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .core import AsyncProviderPlugin, MarkdownProviderRequest, MarkdownProviderResult, stable_digest


_BLOCKED_SCHEMES = {"file", "ftp", "ftps", "data", "gopher", "jar"}


def _ip_is_internal(ip_text: str) -> bool:
    """Return True when ``ip_text`` resolves to an address we refuse to hit.

    Catches loopback, link-local, RFC1918 private, CGNAT (100.64/10),
    unspecified (0/8), and IPv6 ULA (fc00::/7).
    """

    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        # Refuse anything we can't parse -- defence in depth.
        return True

    if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_unspecified or ip.is_reserved:
        return True
    if ip.is_multicast:
        return True

    # CGNAT 100.64.0.0/10 is not flagged by ``is_private`` on 3.9.
    if isinstance(ip, ipaddress.IPv4Address):
        if ipaddress.IPv4Network("100.64.0.0/10").supernet_of(ipaddress.IPv4Network(f"{ip}/32")):
            return True
    return False


def _resolve_host_addresses(host: str) -> "list[str]":
    """Resolve ``host`` to a list of IP strings.  Empty on failure."""

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]


class SSRFError(ValueError):
    """Raised when an HTTP fetch is blocked by SSRF policy."""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that re-validates the target URL against our policy."""

    max_redirections = 5

    def __init__(self, *, allow_private_networks: bool, block_scheme_downgrade: bool):
        self._allow_private_networks = allow_private_networks
        self._block_scheme_downgrade = block_scheme_downgrade

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        parsed = urllib.parse.urlparse(newurl)
        scheme = (parsed.scheme or "").lower()
        if scheme in _BLOCKED_SCHEMES:
            raise urllib.error.HTTPError(
                newurl, code, f"Redirect to disallowed scheme '{scheme}'", headers, fp,
            )
        if scheme not in {"http", "https"}:
            raise urllib.error.HTTPError(
                newurl, code, f"Redirect to non-HTTP scheme '{scheme}'", headers, fp,
            )
        if self._block_scheme_downgrade:
            old_scheme = (urllib.parse.urlparse(req.get_full_url()).scheme or "").lower()
            if old_scheme == "https" and scheme == "http":
                raise urllib.error.HTTPError(
                    newurl, code, "Refused https->http downgrade redirect", headers, fp,
                )

        if not self._allow_private_networks:
            host = parsed.hostname or ""
            for addr in _resolve_host_addresses(host):
                if _ip_is_internal(addr):
                    raise urllib.error.HTTPError(
                        newurl,
                        code,
                        f"Redirect target resolves to internal address {addr}",
                        headers,
                        fp,
                    )

        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpImageProviderPlugin(AsyncProviderPlugin):
    """Download HTTP/S image assets to a bounded local cache.

    The plugin never performs network work on the UI thread.  ``request``
    returns ``pending`` while the background fetch is in flight, then returns a
    local file path on later calls.

    Security knobs:

    * ``allow_private_networks`` – set True for local dev against
      ``127.0.0.1`` / RFC1918.  Off by default.
    * ``block_scheme_downgrade`` – refuse https → http redirects.  On by
      default.
    * ``max_bytes`` – hard cap both on the ``Content-Length`` header and on
      the streamed body.
    """

    DEFAULT_MAX_BYTES = 8 * 1024 * 1024
    DEFAULT_TIMEOUT = 8.0
    DEFAULT_CONCURRENCY = 4

    _EXT_BY_CONTENT_TYPE = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        user_agent: str = "ovui-markdown-widget/0.1.1",
        accept: str = "image/*, image/svg+xml;q=0.9, */*;q=0.1",
        allow_private_networks: bool = False,
        block_scheme_downgrade: bool = True,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        super().__init__(cache_dir, concurrency=concurrency)
        self.timeout = timeout
        self.max_bytes = int(max_bytes)
        self.user_agent = user_agent
        self.accept = accept
        self.allow_private_networks = bool(allow_private_networks)
        self.block_scheme_downgrade = bool(block_scheme_downgrade)

        # Build a dedicated opener so we don't inherit process-global state.
        redirect_handler = _SafeRedirectHandler(
            allow_private_networks=self.allow_private_networks,
            block_scheme_downgrade=self.block_scheme_downgrade,
        )
        self._opener = urllib.request.build_opener(redirect_handler)

    def can_handle(self, request: MarkdownProviderRequest) -> bool:
        return request.kind == "image" and request.source.startswith(("http://", "https://"))

    def cache_key(self, request: MarkdownProviderRequest) -> str:
        return stable_digest("http-image", request.source)

    def _target_for_url(self, url: str, content_type: str = "") -> Path:
        parsed = urllib.parse.urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".svg", ".webp"}:
            ext = self._EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower(), "")
        if not ext:
            guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
            ext = guessed if guessed in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".svg", ".webp"} else ".img"
        return self.cache_dir / f"http-{stable_digest(url)}{ext}"

    def cached_result(self, request: MarkdownProviderRequest) -> Optional[MarkdownProviderResult]:
        parsed = urllib.parse.urlparse(request.source)
        ext = Path(parsed.path).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".svg", ".webp"}:
            target = self.cache_dir / f"http-{stable_digest(request.source)}{ext}"
            if target.exists() and target.stat().st_size > 0:
                return MarkdownProviderResult(state="ready", path=str(target), source=request.source)
        return None

    # -------------------------------------------------------------- SSRF gate

    def _check_url_or_raise(self, url: str) -> None:
        """Raise SSRFError if ``url`` fails the destination policy."""

        parsed = urllib.parse.urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise SSRFError(f"Blocked scheme: {scheme or '<none>'}")
        host = parsed.hostname or ""
        if not host:
            raise SSRFError("URL is missing a hostname")
        if self.allow_private_networks:
            return
        addrs = _resolve_host_addresses(host)
        if not addrs:
            raise SSRFError(f"Host could not be resolved: {host}")
        for addr in addrs:
            if _ip_is_internal(addr):
                raise SSRFError(f"Host {host} resolves to internal address {addr}")

    def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
        url = request.source
        try:
            self._check_url_or_raise(url)
        except SSRFError as exc:
            return MarkdownProviderResult(state="failed", error=f"SSRF: {exc}", source=url)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": self.accept,
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            response_cm = self._opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            return MarkdownProviderResult(state="failed", error=str(exc), source=url)
        except urllib.error.URLError as exc:
            return MarkdownProviderResult(state="failed", error=str(exc), source=url)

        with response_cm as response:
            content_type = response.headers.get("Content-Type", "")

            # Check Content-Length before streaming.
            length_header = response.headers.get("Content-Length")
            if length_header is not None:
                try:
                    declared = int(length_header)
                except ValueError:
                    declared = -1
                if declared > self.max_bytes:
                    return MarkdownProviderResult(
                        state="failed",
                        error=f"HTTP image declares {declared} bytes, cap is {self.max_bytes}",
                        source=url,
                    )

            target = self._target_for_url(url, content_type)
            tmp = target.with_suffix(target.suffix + ".tmp")
            total = 0
            with tmp.open("wb") as out:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes:
                        out.close()
                        tmp.unlink(missing_ok=True)
                        return MarkdownProviderResult(
                            state="failed",
                            error=f"HTTP image exceeds {self.max_bytes} bytes",
                            source=url,
                        )
                    out.write(chunk)
            tmp.replace(target)
        return MarkdownProviderResult(state="ready", path=str(target), source=url)
