# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Branch-heavy tests for Markdown provider infrastructure.

The screenshot tests prove rendering works end-to-end.  These tests cover the
Python-side provider orchestration, resolver, and optional subprocess/network
branches without requiring network access, Node, Mermaid, MathJax, or CairoSVG.
"""

from __future__ import annotations

import builtins
import json
import os
import socket
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request
from concurrent.futures import Future
from pathlib import Path
from unittest import mock


_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = _ROOT / "python"
if str(_PYTHON) not in sys.path:
    sys.path.insert(0, str(_PYTHON))


try:  # pragma: no cover - import guard for partial worktrees.
    from omni.ui.markdown_providers import (  # noqa: E402
        AsyncProviderPlugin,
        MarkdownAssetResolver,
        MarkdownProviderChain,
        MarkdownProviderDocumentRenderer,
        MarkdownProviderRequest,
        MarkdownProviderResult,
        PythonAssetProvider,
        PythonAssetRequest,
        PythonAssetResult,
        stable_digest,
    )
    from omni.ui.markdown_providers import core as provider_core  # noqa: E402
    from omni.ui.markdown_providers import http as provider_http  # noqa: E402
    from omni.ui.markdown_providers import math as provider_math  # noqa: E402
    from omni.ui.markdown_providers import mermaid as provider_mermaid  # noqa: E402
    from omni.ui.markdown_providers import svg as provider_svg  # noqa: E402

    _HAVE_PROVIDERS = True
except Exception:  # noqa: BLE001 - tolerate missing native modules in source-only checkouts.
    _HAVE_PROVIDERS = False


class _SyncExecutor:
    def __init__(self):
        self.shutdown_calls = []

    def submit(self, fn, request):
        future: Future = Future()
        try:
            future.set_result(fn(request))
        except Exception as exc:  # noqa: BLE001 - mirrors ThreadPoolExecutor result propagation.
            future.set_exception(exc)
        return future

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


class _ManualExecutor:
    def __init__(self):
        self.future: Future = Future()
        self.submissions = []
        self.shutdown_calls = []

    def submit(self, fn, request):
        self.submissions.append((fn, request))
        return self.future

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


if _HAVE_PROVIDERS:

    class _CorePlugin(AsyncProviderPlugin):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.render_calls = 0
            self.cancel_generations = []

        def can_handle(self, request: MarkdownProviderRequest) -> bool:
            return request.kind == "demo"

        def cache_key(self, request: MarkdownProviderRequest) -> str:
            return f"demo:{request.source}"

        def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
            self.render_calls += 1
            if request.source == "boom":
                raise RuntimeError("render exploded")
            return MarkdownProviderResult(state="ready", path=f"/tmp/{request.source}.png", source=request.source)

        def cancel_generation(self, generation: int) -> None:
            self.cancel_generations.append(generation)

    class _CachedPlugin(_CorePlugin):
        def cached_result(self, request: MarkdownProviderRequest):
            if request.source == "cached":
                return MarkdownProviderResult(state="ready", path="/cached.png", source=request.source)
            return None


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestCoreProviderPrimitives(unittest.TestCase):
    def test_stable_digest_uses_boundaries_and_length(self):
        self.assertEqual(len(stable_digest("one", "two", length=12)), 12)
        self.assertEqual(stable_digest("same", 1), stable_digest("same", 1))
        self.assertNotEqual(stable_digest("ab", "c"), stable_digest("a", "bc"))

    def test_migrate_legacy_cache_dir_moves_skips_and_swallows_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            new = root / "new"
            legacy.mkdir()
            (legacy / "asset.png").write_bytes(b"asset")

            provider_core.migrate_legacy_cache_dir(legacy, new)
            self.assertFalse(legacy.exists())
            self.assertTrue((new / "asset.png").exists())

            legacy2 = root / "legacy2"
            new2 = root / "new2"
            legacy2.mkdir()
            new2.mkdir()
            provider_core.migrate_legacy_cache_dir(legacy2, new2)
            self.assertTrue(legacy2.exists())
            self.assertTrue(new2.exists())

            legacy3 = root / "legacy3"
            new3 = root / "new3"
            legacy3.mkdir()
            with mock.patch.object(provider_core.os, "replace", side_effect=OSError("cross-device")):
                provider_core.migrate_legacy_cache_dir(legacy3, new3)
            self.assertTrue(legacy3.exists())

    def test_run_default_migration_once_respects_guard(self):
        with mock.patch.object(provider_core, "migrate_legacy_cache_dir") as migrate:
            old_done = provider_core._migration_done
            try:
                provider_core._migration_done = False
                provider_core._run_default_migration_once()
                provider_core._run_default_migration_once()
            finally:
                provider_core._migration_done = old_done
        migrate.assert_called_once_with()

    def test_result_ready_and_run_safely(self):
        self.assertTrue(MarkdownProviderResult(state="ready", path="/x.png").ready)
        self.assertFalse(MarkdownProviderResult(state="ready").ready)
        self.assertFalse(MarkdownProviderResult(state="failed", path="/x.png").ready)

        ok = provider_core.run_safely(lambda: MarkdownProviderResult("ready", path="/ok.png"), source="s")
        self.assertTrue(ok.ready)

        failed = provider_core.run_safely(lambda: (_ for _ in ()).throw(RuntimeError("bad")), source="s")
        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.source, "s")
        self.assertIn("bad", failed.error)

    def test_python_asset_dataclasses_and_abstract_default_methods(self):
        request = PythonAssetRequest(source="asset", inline_asset=True, dark_theme=True)
        result = PythonAssetResult(state="ready", pixels=b"rgba", pixel_width=1, pixel_height=1, extras={"k": "v"})
        self.assertEqual(request.kind, "raster_image")
        self.assertTrue(request.inline_asset)
        self.assertEqual(result.pixel_format, "rgba8_unorm")
        self.assertEqual(result.extras["k"], "v")

        class _Provider(PythonAssetProvider):
            def request(self, request: PythonAssetRequest) -> PythonAssetResult:
                return PythonAssetResult(state="unsupported", error=request.source)

        provider = _Provider()
        provider.tick()
        provider.cancel_generation(42)
        self.assertEqual(provider.request(PythonAssetRequest(source="x")).error, "x")


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestAsyncProviderBranches(unittest.TestCase):
    def _request(self, source: str) -> MarkdownProviderRequest:
        return MarkdownProviderRequest(kind="demo", source=source)

    def test_cached_result_short_circuits_executor(self):
        plugin = _CachedPlugin(executor=_SyncExecutor())
        result = plugin.request(self._request("cached"))
        self.assertTrue(result.ready)
        self.assertEqual(result.path, "/cached.png")
        self.assertEqual(plugin.render_calls, 0)

    def test_done_future_is_promoted_and_lru_hit_refreshes(self):
        plugin = _CorePlugin(executor=_SyncExecutor(), max_cached_results=2)
        try:
            one = plugin.request(self._request("one"))
            two = plugin.request(self._request("two"))
            self.assertTrue(one.ready)
            self.assertTrue(two.ready)
            self.assertEqual(plugin.render_calls, 2)

            # LRU hit should not call render and should move the key to the end.
            self.assertEqual(plugin.request(self._request("one")), one)
            self.assertEqual(plugin.render_calls, 2)
            self.assertEqual(list(plugin._results.keys())[-1], "demo:one")

            plugin.request(self._request("three"))
            self.assertNotIn("demo:two", plugin._results)
            self.assertIn("demo:one", plugin._results)
            self.assertIn("demo:three", plugin._results)
        finally:
            plugin.shutdown()

    def test_pending_future_then_ready_and_cancel_miss(self):
        executor = _ManualExecutor()
        plugin = _CorePlugin(executor=executor)
        request = self._request("manual")

        pending = plugin.request(request)
        self.assertEqual(pending.state, "pending")
        self.assertEqual(len(executor.submissions), 1)
        self.assertFalse(plugin.cancel(self._request("absent")))

        executor.future.set_result(MarkdownProviderResult("ready", path="/manual.png", source="manual"))
        ready = plugin.request(request)
        self.assertTrue(ready.ready)
        self.assertEqual(ready.path, "/manual.png")

    def test_render_exception_is_failed_result(self):
        plugin = _CorePlugin(executor=_SyncExecutor())
        result = plugin.request(self._request("boom"))
        self.assertEqual(result.state, "failed")
        self.assertIn("render exploded", result.error)
        self.assertEqual(result.source, "boom")

    def test_wait_for_idle_promotes_success_and_failure(self):
        plugin = _CorePlugin(executor=_ManualExecutor())
        success_future: Future = Future()
        success_future.set_result(MarkdownProviderResult("ready", path="/ok.png", source="ok"))
        failed_future: Future = Future()
        failed_future.set_exception(RuntimeError("wait failed"))
        with plugin._lock:
            plugin._futures["ok"] = success_future
            plugin._futures["bad"] = failed_future

        plugin.wait_for_idle(timeout=0)
        self.assertEqual(plugin._results["ok"].path, "/ok.png")
        self.assertEqual(plugin._results["bad"].state, "failed")
        self.assertIn("wait failed", plugin._results["bad"].error)
        self.assertEqual(plugin._futures, {})

    def test_owned_executor_shutdown_and_external_executor_skip(self):
        external = _SyncExecutor()
        plugin = _CorePlugin(executor=external)
        plugin.shutdown()
        self.assertEqual(external.shutdown_calls, [])

        owned = _CorePlugin()
        with mock.patch.object(owned._executor, "shutdown") as shutdown:
            owned.shutdown()
        shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    def test_provider_chain_dispatch_and_delegates(self):
        first = _CorePlugin(executor=_SyncExecutor())
        second = _CorePlugin(executor=_SyncExecutor())
        first.can_handle = lambda request: False  # type: ignore[method-assign]
        chain = MarkdownProviderChain([first, second])

        result = chain.first(self._request("chain"))
        self.assertTrue(result.ready)
        self.assertEqual(second.render_calls, 1)
        self.assertFalse(chain.cancel(MarkdownProviderRequest(kind="other", source="x")))

        chain.cancel_generation(7)
        self.assertEqual(first.cancel_generations, [7])
        self.assertEqual(second.cancel_generations, [7])

        with mock.patch.object(first, "wait_for_idle") as wait_first, mock.patch.object(second, "wait_for_idle") as wait_second:
            chain.wait_for_idle(timeout=3)
        wait_first.assert_called_once_with(timeout=3)
        wait_second.assert_called_once_with(timeout=3)

        with mock.patch.object(first, "shutdown") as shutdown_first, mock.patch.object(second, "shutdown") as shutdown_second:
            chain.shutdown()
        shutdown_first.assert_called_once_with()
        shutdown_second.assert_called_once_with()

        self.assertEqual(MarkdownProviderChain([]).first(self._request("x")).state, "unsupported")


class _QueueChain:
    def __init__(self, *results: MarkdownProviderResult):
        self.results = list(results)
        self.requests: list[MarkdownProviderRequest] = []
        self.waits = []
        self.shutdowns = 0

    def first(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
        self.requests.append(request)
        if self.results:
            return self.results.pop(0)
        return MarkdownProviderResult("unsupported", error="empty", source=request.source)

    def wait_for_idle(self, timeout=None):
        self.waits.append(timeout)

    def shutdown(self):
        self.shutdowns += 1


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestDocumentRendererBranches(unittest.TestCase):
    def _renderer(self, tmp: str, chain: _QueueChain) -> MarkdownProviderDocumentRenderer:
        source = Path(tmp) / "doc.md"
        source.write_text("# Doc\n", encoding="utf-8")
        return MarkdownProviderDocumentRenderer(source, cache_dir=Path(tmp) / "cache", chain=chain, theme="dark")

    def test_fence_states_are_rewritten_or_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            chain = _QueueChain(
                MarkdownProviderResult("ready", path=str(Path(tmp) / "mermaid.png")),
                MarkdownProviderResult("pending", source="x"),
                MarkdownProviderResult("unsupported", error="no provider", source="x"),
                MarkdownProviderResult("failed", error="bad source", source="x"),
            )
            renderer = self._renderer(tmp, chain)

            text = "\n\n".join(
                [
                    "```mermaid\ngraph TD; A-->B\n```",
                    "```math\nx^2\n```",
                    "```latex\nx+y\n```",
                    "```tex\nx-z\n```",
                    "```python\nprint('kept')\n```",
                ]
            )
            rendered = renderer.render(text, max_display_width=321, font_size=16)

            self.assertIn("![Mermaid diagram](", rendered)
            self.assertIn("> Rendering math expression...", rendered)
            self.assertIn("Optional provider unavailable: no provider", rendered)
            self.assertIn("Provider failed: bad source", rendered)
            self.assertIn("```python\nprint('kept')\n```", rendered)
            self.assertEqual([r.kind for r in chain.requests], ["diagram", "math_block", "math_block", "math_block"])
            self.assertEqual(chain.requests[0].language, "mermaid")
            self.assertEqual(chain.requests[0].theme, "dark")
            self.assertEqual(chain.requests[0].max_display_width, 321)
            self.assertEqual(chain.requests[0].font_size, 16)

    def test_math_block_and_inline_syntax_use_math_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            block_path = Path(tmp) / "block.png"
            inline_path = Path(tmp) / "inline.png"
            chain = _QueueChain(
                MarkdownProviderResult("ready", path=str(block_path)),
                MarkdownProviderResult("ready", path=str(inline_path)),
            )
            renderer = self._renderer(tmp, chain)

            rendered = renderer.render("Price is $5 each\n\n$$\na=b\n$$\nThen $x + y$ and \\$not math\\$")
            self.assertIn(f"![Math expression]({block_path.as_posix()})", rendered)
            self.assertIn(f"![x + y]({inline_path.as_posix()})", rendered)
            self.assertIn("Price is $5 each", rendered)
            self.assertIn("\\$not math\\$", rendered)
            self.assertEqual([r.kind for r in chain.requests], ["math_block", "math_inline"])
            self.assertEqual(chain.requests[0].source, "a=b")
            self.assertEqual(chain.requests[1].source, "x + y")

    def test_math_pending_preserves_original_and_delegates_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            chain = _QueueChain(MarkdownProviderResult("pending", source="x"))
            renderer = self._renderer(tmp, chain)
            self.assertEqual(renderer.render("$x$"), "$x$")

            renderer.wait_for_idle(timeout=1.5)
            renderer.shutdown()
            self.assertEqual(chain.waits, [1.5])
            self.assertEqual(chain.shutdowns, 1)


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestMarkdownAssetResolverBranches(unittest.TestCase):
    def test_empty_data_relative_file_uri_missing_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "doc.md"
            markdown.write_text("# Doc\n", encoding="utf-8")
            image = root / "asset.png"
            image.write_bytes(b"png")
            chain = _QueueChain()
            resolver = MarkdownAssetResolver(markdown, cache_dir=root / "cache", chain=chain)

            self.assertEqual(resolver.resolve("").state, "unsupported")
            self.assertEqual(resolver.resolve("data:image/png;base64,AA==").state, "unsupported")
            self.assertEqual(resolver("asset.png"), str(image.resolve()))
            self.assertEqual(resolver.resolve(f"file://{image}").path, str(image))
            self.assertEqual(resolver.resolve(f"file:{image}").path, str(image))

            missing = resolver.resolve("missing.png")
            self.assertEqual(missing.state, "failed")
            self.assertIn("image not found", missing.error)

            resolver.wait_for_idle(timeout=2)
            resolver.shutdown()
            self.assertEqual(chain.waits, [2])
            self.assertEqual(chain.shutdowns, 1)

    def test_http_and_svg_sources_are_routed_through_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "doc.md"
            markdown.write_text("# Doc\n", encoding="utf-8")
            downloaded_svg = root / "downloaded.svg"
            downloaded_svg.write_text("<svg/>", encoding="utf-8")
            raster = root / "raster.png"
            raster.write_bytes(b"png")

            chain = _QueueChain(
                MarkdownProviderResult("pending", source="http://example.test/a.png"),
                MarkdownProviderResult("ready", path=str(downloaded_svg), source="http://example.test/a.svg"),
                MarkdownProviderResult("ready", path=str(raster), source=str(downloaded_svg)),
                MarkdownProviderResult("ready", path=str(raster), source=str(downloaded_svg)),
            )
            resolver = MarkdownAssetResolver(markdown, cache_dir=root / "cache", chain=chain)

            pending = resolver.resolve("http://example.test/a.png")
            self.assertEqual(pending.state, "pending")
            self.assertIs(resolver.last_result, pending)

            ready = resolver.resolve("http://example.test/a.svg")
            self.assertTrue(ready.ready)
            self.assertEqual(ready.path, str(raster))

            local_svg = resolver.resolve(str(downloaded_svg))
            self.assertTrue(local_svg.ready)
            self.assertEqual([request.kind for request in chain.requests], ["image", "image", "image", "image"])
            self.assertEqual(chain.requests[0].base_dir, root)
            self.assertEqual(chain.requests[0].cache_dir, root / "cache")


class _FakeResponse:
    def __init__(self, headers=None, chunks=None):
        self.headers = headers or {}
        self._chunks = list(chunks or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size):
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class _FakeOpener:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.exc:
            raise self.exc
        return self.response


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestHttpProviderBranches(unittest.TestCase):
    def test_ip_and_host_policy_helpers(self):
        self.assertTrue(provider_http._ip_is_internal("127.0.0.1"))
        self.assertTrue(provider_http._ip_is_internal("10.0.0.1"))
        self.assertTrue(provider_http._ip_is_internal("100.64.0.1"))
        self.assertTrue(provider_http._ip_is_internal("224.0.0.1"))
        self.assertTrue(provider_http._ip_is_internal("not-an-ip"))
        self.assertFalse(provider_http._ip_is_internal("8.8.8.8"))

        with mock.patch.object(provider_http.socket, "getaddrinfo", side_effect=socket.gaierror):
            self.assertEqual(provider_http._resolve_host_addresses("missing.test"), [])

    def test_check_url_or_raise_branches(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = provider_http.HttpImageProviderPlugin(Path(tmp), allow_private_networks=False)
            self.addCleanup(plugin.shutdown)

            with self.assertRaises(provider_http.SSRFError):
                plugin._check_url_or_raise("file:///tmp/a.png")
            with self.assertRaises(provider_http.SSRFError):
                plugin._check_url_or_raise("http:///missing-host")

            with mock.patch.object(provider_http, "_resolve_host_addresses", return_value=[]):
                with self.assertRaises(provider_http.SSRFError):
                    plugin._check_url_or_raise("http://unresolved.test/a.png")

            with mock.patch.object(provider_http, "_resolve_host_addresses", return_value=["127.0.0.1"]):
                with self.assertRaises(provider_http.SSRFError):
                    plugin._check_url_or_raise("http://loopback.test/a.png")

            plugin.allow_private_networks = True
            plugin._check_url_or_raise("http://127.0.0.1/a.png")

    def test_target_extension_and_cached_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = provider_http.HttpImageProviderPlugin(Path(tmp), allow_private_networks=True)
            self.addCleanup(plugin.shutdown)

            self.assertTrue(str(plugin._target_for_url("http://e.test/a", "image/png")).endswith(".png"))
            self.assertTrue(str(plugin._target_for_url("http://e.test/a", "application/octet-stream")).endswith(".img"))
            self.assertTrue(str(plugin._target_for_url("http://e.test/a.webp", "")).endswith(".webp"))

            request = MarkdownProviderRequest(kind="image", source="http://e.test/existing.png")
            target = plugin.cache_dir / f"http-{stable_digest(request.source)}.png"
            target.write_bytes(b"cached")
            result = plugin.cached_result(request)
            self.assertTrue(result.ready)
            self.assertEqual(result.path, str(target))

    def test_render_success_and_request_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = provider_http.HttpImageProviderPlugin(
                Path(tmp),
                timeout=1.25,
                max_bytes=16,
                user_agent="agent",
                accept="image/png",
                allow_private_networks=True,
            )
            self.addCleanup(plugin.shutdown)
            plugin._opener = _FakeOpener(
                response=_FakeResponse(
                    {"Content-Type": "image/png", "Content-Length": "6"},
                    [b"abc", b"def"],
                )
            )

            result = plugin.render(MarkdownProviderRequest(kind="image", source="http://example.test/pic"))
            self.assertTrue(result.ready)
            self.assertEqual(Path(result.path).read_bytes(), b"abcdef")
            self.assertEqual(plugin._opener.timeouts, [1.25])
            headers = dict(plugin._opener.requests[0].header_items())
            self.assertEqual(headers["User-agent"], "agent")
            self.assertEqual(headers["Accept"], "image/png")

    def test_render_failure_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = MarkdownProviderRequest(kind="image", source="http://example.test/pic.png")

            plugin = provider_http.HttpImageProviderPlugin(root / "declared", max_bytes=3, allow_private_networks=True)
            self.addCleanup(plugin.shutdown)
            plugin._opener = _FakeOpener(response=_FakeResponse({"Content-Length": "4"}, [b"abcd"]))
            self.assertEqual(plugin.render(request).state, "failed")

            plugin = provider_http.HttpImageProviderPlugin(root / "stream", max_bytes=3, allow_private_networks=True)
            self.addCleanup(plugin.shutdown)
            plugin._opener = _FakeOpener(response=_FakeResponse({"Content-Length": "bad"}, [b"ab", b"cd"]))
            streamed = plugin.render(request)
            self.assertEqual(streamed.state, "failed")
            self.assertFalse(any(path.suffix.endswith(".tmp") for path in plugin.cache_dir.iterdir()))

            http_error = urllib.error.HTTPError(request.source, 500, "server", {}, None)
            plugin = provider_http.HttpImageProviderPlugin(root / "http-error", allow_private_networks=True)
            self.addCleanup(plugin.shutdown)
            plugin._opener = _FakeOpener(exc=http_error)
            self.assertEqual(plugin.render(request).state, "failed")

            plugin = provider_http.HttpImageProviderPlugin(root / "url-error", allow_private_networks=True)
            self.addCleanup(plugin.shutdown)
            plugin._opener = _FakeOpener(exc=urllib.error.URLError("dns"))
            self.assertEqual(plugin.render(request).state, "failed")

    def test_redirect_handler_blocks_bad_targets(self):
        req = urllib.request.Request("https://example.test/source")
        handler = provider_http._SafeRedirectHandler(allow_private_networks=False, block_scheme_downgrade=True)

        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(req, None, 302, "found", {}, "file:///etc/passwd")
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(req, None, 302, "found", {}, "mailto:user@example.test")
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(req, None, 302, "found", {}, "http://example.test/plain")

        handler = provider_http._SafeRedirectHandler(allow_private_networks=False, block_scheme_downgrade=False)
        with mock.patch.object(provider_http, "_resolve_host_addresses", return_value=["127.0.0.1"]):
            with self.assertRaises(urllib.error.HTTPError):
                handler.redirect_request(req, None, 302, "found", {}, "https://internal.test/target")


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestSvgProviderBranches(unittest.TestCase):
    def test_can_handle_cache_key_cached_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svg_path = root / "icon.svg"
            svg_path.write_text("<svg/>", encoding="utf-8")
            plugin = provider_svg.SvgRasterProviderPlugin(root / "cache", output_width=128)
            self.addCleanup(plugin.shutdown)

            self.assertTrue(plugin.can_handle(MarkdownProviderRequest(kind="image", source=str(svg_path))))
            self.assertTrue(plugin.can_handle(MarkdownProviderRequest(kind="image", source=str(root / "icon.svgz"))))
            self.assertFalse(plugin.can_handle(MarkdownProviderRequest(kind="diagram", source=str(svg_path))))
            self.assertEqual(
                plugin.cached_result(MarkdownProviderRequest(kind="image", source=str(root / "missing.svg"))).state,
                "failed",
            )

            request = MarkdownProviderRequest(kind="image", source=str(svg_path), max_display_width=77)
            target = plugin._target_for_path(svg_path, request)
            target.write_bytes(b"png")
            self.assertTrue(plugin.cached_result(request).ready)
            self.assertEqual(plugin.cache_key(request), plugin.cache_key(request))

    def test_render_unsupported_failed_and_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svg_path = root / "icon.svg"
            svg_path.write_text("<svg/>", encoding="utf-8")
            request = MarkdownProviderRequest(kind="image", source=str(svg_path), max_display_width=64)
            plugin = provider_svg.SvgRasterProviderPlugin(root / "cache")
            self.addCleanup(plugin.shutdown)

            self.assertEqual(plugin.render(MarkdownProviderRequest(kind="image", source=str(root / "missing.svg"))).state, "failed")

            real_import = builtins.__import__

            def raising_import(name, *args, **kwargs):
                if name == "cairosvg":
                    raise ImportError("not installed")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=raising_import):
                unsupported = plugin.render(request)
            self.assertEqual(unsupported.state, "unsupported")

            fake_cairo = types.SimpleNamespace(svg2png=mock.Mock(side_effect=RuntimeError("bad svg")))
            with mock.patch.dict(sys.modules, {"cairosvg": fake_cairo}):
                failed = plugin.render(request)
            self.assertEqual(failed.state, "failed")
            self.assertIn("bad svg", failed.error)

            def write_png(*, url, write_to, output_width):
                Path(write_to).write_bytes(f"{url}:{output_width}".encode("utf-8"))

            fake_cairo = types.SimpleNamespace(svg2png=mock.Mock(side_effect=write_png))
            with mock.patch.dict(sys.modules, {"cairosvg": fake_cairo}):
                ready = plugin.render(request)
            self.assertTrue(ready.ready)
            self.assertEqual(Path(ready.path).read_bytes(), f"{svg_path}:64".encode("utf-8"))


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestMermaidProviderBranches(unittest.TestCase):
    def test_can_handle_target_cached_and_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = provider_mermaid.MermaidCliProviderPlugin(Path(tmp), output_format=".svg")
            self.addCleanup(plugin.shutdown)
            request = MarkdownProviderRequest(kind="diagram", language="mermaid", source="graph TD; A-->B")
            self.assertTrue(plugin.can_handle(request))
            self.assertTrue(plugin.can_handle(MarkdownProviderRequest(kind="code_block", language="mermaid", source="x")))
            self.assertFalse(plugin.can_handle(MarkdownProviderRequest(kind="diagram", language="dot", source="x")))
            self.assertTrue(str(plugin._target_for_request(request)).endswith(".svg"))

            plugin._target_for_request(request).write_bytes(b"svg")
            self.assertTrue(plugin.cached_result(request).ready)

            with mock.patch.object(provider_mermaid.shutil, "which", return_value=None):
                unsupported = plugin.render(request)
            self.assertEqual(unsupported.state, "unsupported")

    def test_render_success_uses_local_bin_restricted_env_and_cleans_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            working_dir = root / "provider"
            bin_dir = working_dir / "node_modules" / ".bin"
            bin_dir.mkdir(parents=True)
            executable = bin_dir / f"mmdc{'.cmd' if os.name == 'nt' else ''}"
            executable.write_text("fake", encoding="utf-8")
            plugin = provider_mermaid.MermaidCliProviderPlugin(root / "cache", working_dir=working_dir, timeout=2.5)
            self.addCleanup(plugin.shutdown)
            request = MarkdownProviderRequest(kind="diagram", language="mermaid", source="graph TD; A-->B")
            seen = {}

            def fake_run(cmd, **kwargs):
                seen["cmd"] = cmd
                seen["kwargs"] = kwargs
                source_path = Path(cmd[cmd.index("-i") + 1])
                config_path = Path(cmd[cmd.index("-c") + 1])
                target_path = Path(cmd[cmd.index("-o") + 1])
                self.assertEqual(source_path.read_text(encoding="utf-8"), request.source)
                self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), {"securityLevel": "strict"})
                target_path.write_bytes(b"png")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(provider_mermaid.subprocess, "run", side_effect=fake_run):
                result = plugin.render(request)

            self.assertTrue(result.ready)
            self.assertEqual(seen["cmd"][0], str(executable))
            self.assertEqual(seen["kwargs"]["cwd"], str(working_dir))
            self.assertEqual(seen["kwargs"]["timeout"], 2.5)
            self.assertEqual(seen["kwargs"]["env"]["NODE_OPTIONS"], "")
            self.assertIn(str(bin_dir), seen["kwargs"]["env"]["PATH"])
            self.assertFalse(list(plugin.cache_dir.glob("*.mmd")))
            self.assertFalse(list(plugin.cache_dir.glob("*.config.json")))

    def test_render_process_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = MarkdownProviderRequest(kind="diagram", language="mermaid", source="graph TD; A-->B")

            cases = [
                (subprocess.CalledProcessError(1, ["mmdc"], stderr="syntax"), "syntax"),
                (subprocess.TimeoutExpired(["mmdc"], 0.01), "exceeded"),
                (RuntimeError("spawn failed"), "spawn failed"),
            ]
            for exc, expected in cases:
                plugin = provider_mermaid.MermaidCliProviderPlugin(Path(tmp) / expected.replace(" ", "-"), timeout=0.01)
                self.addCleanup(plugin.shutdown)
                with mock.patch.object(provider_mermaid.shutil, "which", return_value="/bin/mmdc"):
                    with mock.patch.object(provider_mermaid.subprocess, "run", side_effect=exc):
                        result = plugin.render(request)
                self.assertEqual(result.state, "failed")
                self.assertIn(expected, result.error)


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestMathJaxProviderBranches(unittest.TestCase):
    def test_can_handle_cache_color_and_cached_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = provider_math.MathJaxProviderPlugin(Path(tmp), output_format=".svg")
            self.addCleanup(plugin.shutdown)
            request = MarkdownProviderRequest(kind="math_inline", source="x", theme="black")
            self.assertTrue(plugin.can_handle(request))
            self.assertTrue(plugin.can_handle(MarkdownProviderRequest(kind="code", language="latex", source="x")))
            self.assertFalse(plugin.can_handle(MarkdownProviderRequest(kind="diagram", language="mermaid", source="x")))
            self.assertEqual(plugin._color_for_theme("dark-blue"), "#dbe7f6")
            self.assertEqual(plugin._color_for_theme("white"), "#172033")

            target = plugin._target_for_request(request)
            target.write_bytes(b"svg")
            self.assertTrue(plugin.cached_result(request).ready)
            self.assertTrue(str(target).endswith(".svg"))

    def test_render_oversized_and_unsupported_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = provider_math.MathJaxProviderPlugin(Path(tmp), max_source_bytes=2)
            self.addCleanup(plugin.shutdown)
            self.assertEqual(plugin.render(MarkdownProviderRequest(kind="math", source="abcd")).state, "failed")

            plugin = provider_math.MathJaxProviderPlugin(Path(tmp) / "node")
            self.addCleanup(plugin.shutdown)
            with mock.patch.object(provider_math.shutil, "which", return_value=None):
                self.assertEqual(plugin.render(MarkdownProviderRequest(kind="math", source="x")).state, "unsupported")

    def test_render_svg_success_and_scratch_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            working_dir = root / "provider"
            working_dir.mkdir()
            plugin = provider_math.MathJaxProviderPlugin(root / "cache", output_format="svg", working_dir=working_dir, timeout=3.0)
            self.addCleanup(plugin.shutdown)
            request = MarkdownProviderRequest(kind="math_inline", source="x+y", max_display_width=444, font_size=18, theme="dark")
            seen = {}

            def fake_run(cmd, **kwargs):
                seen["cmd"] = cmd
                seen["kwargs"] = kwargs
                payload = json.loads(Path(cmd[2]).read_text(encoding="utf-8"))
                self.assertEqual(payload["source"], "x+y")
                self.assertFalse(payload["display"])
                self.assertEqual(payload["font_size"], 18)
                self.assertEqual(payload["width"], 444)
                self.assertEqual(payload["color"], "#dbe7f6")
                self.assertIn("tex2svgPromise", Path(cmd[1]).read_text(encoding="utf-8"))
                return subprocess.CompletedProcess(cmd, 0, "<svg/>", "")

            with mock.patch.object(provider_math.shutil, "which", return_value="/bin/node"):
                with mock.patch.object(provider_math.subprocess, "run", side_effect=fake_run):
                    result = plugin.render(request)

            self.assertTrue(result.ready)
            self.assertEqual(Path(result.path).read_text(encoding="utf-8"), "<svg/>")
            self.assertEqual(seen["kwargs"]["cwd"], str(working_dir))
            self.assertEqual(seen["kwargs"]["timeout"], 3.0)
            self.assertFalse(list(plugin.cache_dir.glob("*.json")))
            self.assertFalse(list(plugin.cache_dir.glob("*.js")))

    def test_render_png_success_unsupported_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = MarkdownProviderRequest(kind="math_block", source="x")

            def run_stdout(stdout):
                return subprocess.CompletedProcess(["node"], 0, stdout, "")

            real_import = builtins.__import__

            def missing_cairo(name, *args, **kwargs):
                if name == "cairosvg":
                    raise ImportError("no cairo")
                return real_import(name, *args, **kwargs)

            plugin = provider_math.MathJaxProviderPlugin(root / "missing-cairo")
            self.addCleanup(plugin.shutdown)
            with mock.patch.object(provider_math.shutil, "which", return_value="/bin/node"):
                with mock.patch.object(provider_math.subprocess, "run", return_value=run_stdout("<svg/>")):
                    with mock.patch("builtins.__import__", side_effect=missing_cairo):
                        unsupported = plugin.render(request)
            self.assertEqual(unsupported.state, "unsupported")
            self.assertTrue(unsupported.path.endswith(".svg"))

            fake_cairo = types.SimpleNamespace(svg2png=mock.Mock(side_effect=RuntimeError("raster failed")))
            plugin = provider_math.MathJaxProviderPlugin(root / "bad-cairo")
            self.addCleanup(plugin.shutdown)
            with mock.patch.object(provider_math.shutil, "which", return_value="/bin/node"):
                with mock.patch.object(provider_math.subprocess, "run", return_value=run_stdout("<svg/>")):
                    with mock.patch.dict(sys.modules, {"cairosvg": fake_cairo}):
                        failed = plugin.render(request)
            self.assertEqual(failed.state, "failed")
            self.assertIn("raster failed", failed.error)

            def write_png(*, bytestring, write_to):
                Path(write_to).write_bytes(bytestring)

            fake_cairo = types.SimpleNamespace(svg2png=mock.Mock(side_effect=write_png))
            plugin = provider_math.MathJaxProviderPlugin(root / "good-cairo")
            self.addCleanup(plugin.shutdown)
            with mock.patch.object(provider_math.shutil, "which", return_value="/bin/node"):
                with mock.patch.object(provider_math.subprocess, "run", return_value=run_stdout("<svg>ok</svg>")):
                    with mock.patch.dict(sys.modules, {"cairosvg": fake_cairo}):
                        ready = plugin.render(request)
            self.assertTrue(ready.ready)
            self.assertEqual(Path(ready.path).read_bytes(), b"<svg>ok</svg>")

            failure_cases = [
                (subprocess.CalledProcessError(1, ["node"], stderr="Cannot find module '@mathjax/src/foo'"), "Install optional npm"),
                (subprocess.CalledProcessError(1, ["node"], output="syntax"), "syntax"),
                (subprocess.TimeoutExpired(["node"], 0.01), "exceeded"),
                (RuntimeError("spawn failed"), "spawn failed"),
            ]
            for exc, expected in failure_cases:
                plugin = provider_math.MathJaxProviderPlugin(root / expected.replace(" ", "-"))
                self.addCleanup(plugin.shutdown)
                with mock.patch.object(provider_math.shutil, "which", return_value="/bin/node"):
                    with mock.patch.object(provider_math.subprocess, "run", side_effect=exc):
                        result = plugin.render(request)
                self.assertEqual(result.state, "failed")
                self.assertIn(expected, result.error)

            plugin = provider_math.MathJaxProviderPlugin(root / "empty")
            self.addCleanup(plugin.shutdown)
            with mock.patch.object(provider_math.shutil, "which", return_value="/bin/node"):
                with mock.patch.object(provider_math.subprocess, "run", return_value=run_stdout("  ")):
                    empty = plugin.render(request)
            self.assertEqual(empty.state, "failed")
            self.assertIn("empty SVG", empty.error)


if __name__ == "__main__":
    unittest.main()
