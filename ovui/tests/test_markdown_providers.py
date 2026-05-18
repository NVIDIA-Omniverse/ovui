# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for optional Markdown provider plugins."""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = _ROOT / "python"
if str(_PYTHON) not in sys.path:
    sys.path.insert(0, str(_PYTHON))


try:  # pragma: no cover - import guard for partial worktrees.
    from omni.ui.markdown_providers import (  # noqa: E402
        AsyncProviderPlugin,
        HttpImageProviderPlugin,
        MarkdownProviderChain,
        MarkdownProviderDocumentRenderer,
        MarkdownProviderRequest,
        MarkdownProviderResult,
        MermaidCliProviderPlugin,
    )

    _HAVE_PROVIDERS = True
except Exception:  # noqa: BLE001 - tolerate any import failure
    _HAVE_PROVIDERS = False


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestMarkdownProviders(unittest.TestCase):
    def test_document_renderer_rewrites_ready_provider_blocks(self):
        class _ReadyDiagramPlugin(AsyncProviderPlugin):
            def can_handle(self, request: MarkdownProviderRequest) -> bool:
                return request.kind in {"diagram", "math_block"}

            def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
                target = self.cache_dir / f"{request.kind}.png"
                target.write_bytes(b"not-a-real-png-but-good-enough-for-path-tests")
                return MarkdownProviderResult(state="ready", path=str(target), source=request.source)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "doc.md"
            source.write_text("# Doc\n", encoding="utf-8")
            plugin = _ReadyDiagramPlugin(root / "cache")
            renderer = MarkdownProviderDocumentRenderer(
                source,
                cache_dir=root / "cache",
                chain=MarkdownProviderChain([plugin]),
            )

            text = "Before\n\n```mermaid\ngraph TD; A-->B\n```\n\n```math\nx^2\n```"
            rendered = renderer.render(text)
            renderer.wait_for_idle(timeout=5)
            rendered = renderer.render(text)

            self.assertIn("![Mermaid diagram](", rendered)
            self.assertIn("![Math expression](", rendered)
            self.assertNotIn("```mermaid", rendered)
            self.assertNotIn("```math", rendered)
            renderer.shutdown()

    def test_document_renderer_preserves_unknown_fences(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "doc.md"
            source.write_text("# Doc\n", encoding="utf-8")
            renderer = MarkdownProviderDocumentRenderer(
                source,
                cache_dir=Path(tmp) / "cache",
                chain=MarkdownProviderChain([]),
            )
            text = "```python\nprint('ok')\n```"
            self.assertEqual(renderer.render(text), text)
            renderer.shutdown()


# ---------------------------------------------------------------------------
# Concurrency tests
#
# Verify that the AsyncProviderPlugin.request() machinery de-duplicates
# concurrent requests for the same cache key, returns pending immediately
# while a render is in flight, and caches ready results for future calls.
# All coordination uses ``threading.Event`` so the tests do not rely on
# wall-clock timing.
# ---------------------------------------------------------------------------


if _HAVE_PROVIDERS:

    class _GatedPlugin(AsyncProviderPlugin):
        """Plugin whose render() blocks until ``release`` is set.

        Each call increments ``render_calls`` so tests can assert how many
        times the heavy work ran.  Concurrent callers should observe exactly
        one render for a fixed cache key.
        """

        def __init__(self, cache_dir: Path, release: threading.Event):
            super().__init__(cache_dir=cache_dir)
            self.release = release
            self.render_calls = 0
            self._call_lock = threading.Lock()

        def can_handle(self, request: MarkdownProviderRequest) -> bool:
            return request.kind == "diagram"

        def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
            with self._call_lock:
                self.render_calls += 1
            # Block until the test says we may complete. The default ~5s
            # timeout is generous compared to the test runtime and ensures
            # we don't hang CI forever if a test forgets to release.
            self.release.wait(timeout=30)
            target = self.cache_dir / "diagram.png"
            target.write_bytes(b"ok")
            return MarkdownProviderResult(state="ready", path=str(target), source=request.source)


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestMarkdownProviderConcurrency(unittest.TestCase):
    def _request(self) -> "MarkdownProviderRequest":
        return MarkdownProviderRequest(kind="diagram", source="graph TD; A-->B")

    def test_concurrent_requests_dedupe(self):
        """Four threads hitting request() for the same key => one render()."""

        with tempfile.TemporaryDirectory() as tmp:
            release = threading.Event()
            plugin = _GatedPlugin(Path(tmp) / "cache", release)
            try:
                request = self._request()

                barrier = threading.Barrier(4)
                results: list = []
                results_lock = threading.Lock()

                def worker():
                    barrier.wait()
                    result = plugin.request(request)
                    with results_lock:
                        results.append(result)

                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(worker) for _ in range(4)]

                    # Wait until all four threads have returned their
                    # initial (pending) result. Because the gate blocks
                    # render, those returns happen as soon as each caller
                    # observes the in-flight future.
                    import time

                    deadline = time.monotonic() + 5.0
                    while len(results) < 4 and time.monotonic() < deadline:
                        time.sleep(0.01)

                    # Let the rendering worker finish so the executor drains.
                    release.set()
                    for f in futures:
                        f.result(timeout=5)

                self.assertEqual(len(results), 4)
                # All four concurrent callers must have shared a single
                # future; render() runs exactly once.
                self.assertEqual(plugin.render_calls, 1)

                # Follow-up after completion returns ready without re-rendering.
                # `release.set()` unblocks render() but the background future
                # may not have completed and materialized into _results yet;
                # wait_for_idle flushes it before we assert.
                plugin.wait_for_idle(timeout=5)
                follow_up = plugin.request(request)
                self.assertEqual(follow_up.state, "ready")
                self.assertEqual(plugin.render_calls, 1)
            finally:
                release.set()
                plugin.shutdown()

    def test_second_request_during_pending_returns_pending(self):
        """While a render is in flight, a second request returns pending fast."""

        with tempfile.TemporaryDirectory() as tmp:
            release = threading.Event()
            plugin = _GatedPlugin(Path(tmp) / "cache", release)
            try:
                request = self._request()

                first = plugin.request(request)
                # First call either kicks off a future (pending) or -- in an
                # unlikely race -- has already completed.  In practice the
                # render is gated, so we expect pending.
                self.assertEqual(first.state, "pending")

                # Second call must not block.  Measure wall-clock as a sanity
                # check but keep the assertion on state (the canonical
                # contract).  If it blocked on the gate it would take
                # ~release timeout which is far longer than 1s.
                import time

                t0 = time.monotonic()
                second = plugin.request(request)
                elapsed = time.monotonic() - t0
                self.assertLess(elapsed, 1.0, "second request should not block")
                self.assertEqual(second.state, "pending")
                self.assertEqual(plugin.render_calls, 1)
            finally:
                release.set()
                plugin.shutdown()

    def test_results_persist_across_calls(self):
        """Once ready, subsequent calls return the cached result untouched."""

        with tempfile.TemporaryDirectory() as tmp:
            release = threading.Event()
            release.set()  # let render complete immediately
            plugin = _GatedPlugin(Path(tmp) / "cache", release)
            try:
                request = self._request()

                # First request kicks off work; may return pending.
                plugin.request(request)
                plugin.wait_for_idle(timeout=5)

                second = plugin.request(request)
                self.assertEqual(second.state, "ready")
                self.assertEqual(plugin.render_calls, 1)

                third = plugin.request(request)
                self.assertEqual(third.state, "ready")
                self.assertEqual(plugin.render_calls, 1)
                # Same cached object by equality (frozen dataclass).
                self.assertEqual(second, third)
            finally:
                plugin.shutdown()


# ---------------------------------------------------------------------------
# Hardening tests: LRU, cancel, SSRF, subprocess size guard.
# These match the Task F contract in the hardening brief.
# ---------------------------------------------------------------------------


if _HAVE_PROVIDERS:

    class _InstantPlugin(AsyncProviderPlugin):
        """Deterministic plugin: every ``render`` succeeds immediately."""

        def can_handle(self, request: MarkdownProviderRequest) -> bool:
            return True

        def cache_key(self, request: MarkdownProviderRequest) -> str:
            return f"instant:{request.source}"

        def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
            return MarkdownProviderResult(
                state="ready", path=f"/tmp/{request.source}", source=request.source,
            )

    class _BlockingCancelPlugin(AsyncProviderPlugin):
        """``render`` blocks until released.  Used for cancel-path tests."""

        def __init__(self, cache_dir: Path, release: threading.Event, *, concurrency: int = 2):
            super().__init__(cache_dir=cache_dir, concurrency=concurrency)
            self._release = release
            self.render_entered = threading.Event()

        def can_handle(self, request: MarkdownProviderRequest) -> bool:
            return True

        def cache_key(self, request: MarkdownProviderRequest) -> str:
            return f"block:{request.source}"

        def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
            self.render_entered.set()
            self._release.wait(timeout=10.0)
            return MarkdownProviderResult(
                state="ready", path="/tmp/released", source=request.source,
            )


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestLruCache(unittest.TestCase):
    def test_lru_evicts_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _InstantPlugin(Path(tmp), max_cached_results=3)
            try:
                requests = [
                    MarkdownProviderRequest(kind="x", source=f"item-{i}")
                    for i in range(4)
                ]

                # Prime the cache. Each call may return pending once while the
                # executor runs; drive to completion before asserting.
                for req in requests[:3]:
                    result = plugin.request(req)
                    if not result.ready:
                        plugin.wait_for_idle(timeout=5)
                        result = plugin.request(req)
                    self.assertTrue(result.ready, req.source)

                # Refresh item-0's LRU position so eviction should hit item-1.
                plugin.request(requests[0])

                # Add item-3: cap is 3, so item-1 should fall out.
                res3 = plugin.request(requests[3])
                if not res3.ready:
                    plugin.wait_for_idle(timeout=5)
                    plugin.request(requests[3])

                keys = list(plugin._results.keys())
                self.assertEqual(len(keys), 3)
                self.assertIn("instant:item-0", keys)  # refreshed
                self.assertIn("instant:item-2", keys)
                self.assertIn("instant:item-3", keys)
                self.assertNotIn("instant:item-1", keys)  # evicted

                # Newest entry must be at the end of the OrderedDict.
                self.assertEqual(keys[-1], "instant:item-3")
            finally:
                plugin.shutdown()


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestCancellation(unittest.TestCase):
    def test_cancel_removes_pending_request(self):
        """After cancel() both _futures and _results are clear for the key."""

        release = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _BlockingCancelPlugin(Path(tmp), release)
            try:
                req = MarkdownProviderRequest(kind="x", source="slow")

                # First call submits the future; returns pending.
                first = plugin.request(req)
                self.assertEqual(first.state, "pending")
                plugin.render_entered.wait(timeout=2.0)

                # cancel() returns True (an entry was tracked) and purges
                # tracking dictionaries regardless of whether the worker
                # has already started (which, here, it has).
                self.assertTrue(plugin.cancel(req))
                key = plugin.cache_key(req)
                self.assertNotIn(key, plugin._futures)
                self.assertNotIn(key, plugin._results)

                # Second cancel has nothing to do.
                self.assertFalse(plugin.cancel(req))
            finally:
                release.set()
                plugin.shutdown()

    def test_cancel_chain_propagates(self):
        release = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _BlockingCancelPlugin(Path(tmp), release)
            try:
                chain = MarkdownProviderChain([plugin])
                req = MarkdownProviderRequest(kind="x", source="ch-0")
                # First call schedules a blocked future; result is "pending".
                first = chain.first(req)
                self.assertEqual(first.state, "pending")
                plugin.render_entered.wait(timeout=2.0)
                # Chain.cancel must find the plugin and proxy through.
                self.assertTrue(chain.cancel(req))
                self.assertNotIn(plugin.cache_key(req), plugin._futures)
            finally:
                release.set()
                plugin.shutdown()


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestHttpSSRF(unittest.TestCase):
    def test_http_rejects_loopback(self):
        from unittest import mock as _mock

        with tempfile.TemporaryDirectory() as tmp:
            plugin = HttpImageProviderPlugin(Path(tmp))
            try:
                req = MarkdownProviderRequest(
                    kind="image", source="http://127.0.0.1:65000/x.png",
                )
                # Belt-and-braces: fail loudly if the SSRF gate ever calls
                # out to the network.
                with _mock.patch.object(
                    plugin._opener,
                    "open",
                    side_effect=AssertionError("no network call expected"),
                ):
                    result = plugin.render(req)
                self.assertEqual(result.state, "failed")
                self.assertIn("SSRF", result.error)
            finally:
                plugin.shutdown()

    def test_http_rejects_rfc1918(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = HttpImageProviderPlugin(Path(tmp))
            try:
                req = MarkdownProviderRequest(
                    kind="image", source="http://10.0.0.1/x.png",
                )
                result = plugin.render(req)
                self.assertEqual(result.state, "failed")
                self.assertIn("SSRF", result.error)
            finally:
                plugin.shutdown()

    def test_http_rejects_cross_scheme_redirect(self):
        """A server redirecting to ``file:///etc/passwd`` must be refused."""

        import http.server

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", "file:///etc/passwd")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args, **kwargs):
                pass  # silence noise during tests

        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        host, port = server.server_address
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                plugin = HttpImageProviderPlugin(
                    Path(tmp), allow_private_networks=True,
                )
                try:
                    req = MarkdownProviderRequest(
                        kind="image", source=f"http://{host}:{port}/x.png",
                    )
                    result = plugin.render(req)
                    self.assertEqual(result.state, "failed")
                    msg = result.error.lower()
                    self.assertTrue(
                        any(k in msg for k in ("file", "scheme", "disallowed")),
                        msg,
                    )
                finally:
                    plugin.shutdown()
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=2)


@unittest.skipUnless(_HAVE_PROVIDERS, "omni.ui.markdown_providers not available")
class TestSubprocessSizeLimit(unittest.TestCase):
    def test_subprocess_size_limit(self):
        """Oversized Mermaid source returns failed without spawning ``mmdc``."""

        from unittest import mock as _mock

        with tempfile.TemporaryDirectory() as tmp:
            plugin = MermaidCliProviderPlugin(
                Path(tmp), max_source_bytes=64 * 1024, timeout=1.0,
            )
            try:
                payload = "A-->B;\n" * 20_000  # ~140 KB, well over the cap
                self.assertGreater(len(payload.encode("utf-8")), 64 * 1024)
                req = MarkdownProviderRequest(
                    kind="diagram", language="mermaid", source=payload,
                )
                with _mock.patch("subprocess.run") as mock_run:
                    with _mock.patch("shutil.which", return_value="/bin/true"):
                        result = plugin.render(req)
                    mock_run.assert_not_called()
                self.assertEqual(result.state, "failed")
                self.assertIn("exceeds", result.error)
            finally:
                plugin.shutdown()

    def test_restricted_env_has_no_node_options(self):
        from omni.ui.markdown_providers.mermaid import _build_restricted_env

        with tempfile.TemporaryDirectory() as tmp:
            env = _build_restricted_env(Path(tmp))
            self.assertIn("PATH", env)
            self.assertEqual(env.get("NODE_OPTIONS"), "")
            self.assertEqual(env.get("HOME"), tmp)
            # Arbitrary secret-shaped key must NOT leak into the child env.
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)


if __name__ == "__main__":
    unittest.main()
