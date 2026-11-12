# Application commands in Inspector

Applications can contribute typed commands to the existing Inspector without
creating another service, queue or frontend. Existing screenshot/input/execute
endpoints are unchanged. All commands execute through the same frame loop.

## Register and document a command

```python
from ovuiinspect import Arguments, Command
from pydantic import Field

class Highlight(Arguments):
    path: str = Field(min_length=1)

class MyApplication:
    def get_inspector_commands(self):
        return [Command(
            name="highlight",
            description="Select an object in this application's viewport.",
            arguments=Highlight,
            handler=self.highlight,
            read_only=False,
            category="viewport",
        )]

    def highlight(self, path):
        # Use the application's existing selection model.
        self.select([path])
        return {"path": path}
```

Adapt the handler to the host's public selection API. `attach_application(app)`
registers the iterable returned by `get_inspector_commands()` when present.
Apps without that hook keep their existing behavior. Reattaching the same app is
idempotent; attaching a different one detaches the old app's contributions.

For optional features that become available later, call
`registration = ovuiinspect.register_command(Command(...))` on the owning thread
after attachment. `registration.remove()` unregisters it. Names must be unique
lowercase identifiers, up to 64 characters. A collision raises an error; partial
registration during attachment is unwound. Prefix application-specific names to
avoid collisions. Registration is scoped to the attached application, not a
process-global plugin inventory retained after detachment.

## Discovery and invocation

```bash
ovui-inspect commands
ovui-inspect call highlight --arguments '{"path":"/World/Cube"}' --timeout 30
```

Equivalent HTTP:

```text
GET /commands
POST /commands/highlight?timeout=30
Content-Type: application/json

{"path":"/World/Cube"}
```

The catalog response is `{"success":true,"commands":[...]}`. Each entry has
`name`, `description`, `method`, `endpoint`, `input_schema`, `category` and
`read_only`. JSON Schema comes from the argument model, including defaults,
required fields and constraints. The read-only annotation is descriptive and is
not an access-control boundary. Catalog retrieval does not touch scene state.
Applications must explicitly opt in to contributing privileged commands.
These commands are not governed by `OVUIINSPECT_ENABLE_STATE` or
`OVUIINSPECT_ENABLE_EXECUTE`; disabling Python execution does not make an
application read-only. Loopback binding is not an authentication boundary.

Call responses use `{"success":true,"result":...}`. Unknown names return 404;
invalid arguments return 422 before a handler starts. Handler exceptions use the
existing Inspector failure response (400). Command timeout defaults to 30 seconds,
with a maximum of 600. Contributed-command timeouts return 400 with a timeout message.
The client should inspect current state before retrying a mutation.

Use `Arguments` as the model base to reject unknown fields and non-finite numeric
values. Use a nested model or explicit validation for unconstrained payloads;
`Any` does not imply schema validation of an arbitrary data structure.
Handlers return JSON-safe values or raise an exception on failure. A returned
`{"ok":false}` is just application data: it does not replace raising an error.

## Owner thread, async work and shutdown

Detach before releasing media, adapters, USD stages or native renderer resources.
`detach_application(app)` cancels pending commands and returns their tasks; await
them so their cleanup completes before host teardown.

Call `drain_pending` with its default `advance_input=True` only once per native
UI frame, immediately before `await ui.next_frame()`. A host that also drains
between expensive viewport renders must pass `advance_input=False` at those
intermediate points. This keeps hover/press/release/drag steps on separate UI
frames while preserving the same FIFO command queue and async dispatch.

The HTTP thread validates and queues. The host continues its normal loop:

```python
ovuiinspect.attach_application(app)
# Inside the existing async UI loop, immediately before next_frame:
ovuiinspect.drain_pending(ui._ui, application=app)
await ui.next_frame()
```

Sync handlers run on that owning thread. Async handlers run on its asyncio loop,
yield across frames and keep their queue position until complete. Input,
screenshots and Python execution do not overtake them. The queue admits at most
128 commands. A removed registration rejects queued work, and expired queued
commands never start.

Timeout requests cancellation of a running async handler once, allowing awaited
`finally` cleanup to finish before the next command. Cancellation is cooperative;
it cannot interrupt synchronous native calls or undo already authored edits.
Avoid blocking I/O in handlers. `asyncio.to_thread` can move independent I/O off
the UI thread, but USD/UI ownership must stay on the owner thread.

Detach on the owner thread. `detach_application(app)` removes the catalog, fails
pending requests, requests cancellation, and returns pending tasks. An async host
should `await asyncio.gather(*tasks, return_exceptions=True)` before releasing
native resources. Registration/discovery is HTTP/CLI functionality; this module
does not implement a separate MCP transport.

## Bounded repeated edits

Inspector `execute` runs synchronously on the application owner thread. Do not
put sleeps, polling loops or a whole animation loop inside it: rendering, Live
application and subsequent Inspector requests cannot progress while it blocks.
For a host exposing `app.call_later(delay_seconds, callback)`, install a short
callback that performs one bounded batch of owned edits, schedules the next tick,
and returns. Keep USD/UI mutations on that thread; a worker thread is not an
alternative owner.

Give the sequence a monotonic deadline, a tick limit and an explicit stop flag.
Retain its returned callback handle so a later short `execute` can cancel pending
work; stop rescheduling on errors and before leaving the document. Return a
JSON-safe status immediately, then inspect progress in separate requests. A
requested interval (for example 0.1 seconds) is a scheduling target, not evidence
of ten applied or rendered updates per second. Expensive native work inside one
callback can still block the owner thread. Measure callback duration and peer
receipt before increasing the requested frequency.

## Optional Python namespace

The existing `/execute` remains gated by `OVUIINSPECT_ENABLE_EXECUTE`. Without a
hook, each call has fresh locals as before. `get_inspector_namespace()` may return
a persistent dictionary owned by the app. Inspector adds `app` and `application`,
clears old `result`, executes the supplied code and returns a JSON-safe `result`
when assigned. Captured stdout/stderr are capped at 64 KiB each and included on
execution failures. Use short trusted code; this is not a sandbox or a background
job runner. Hosts decide which stage/module objects belong in their namespace.

## Evidence

These contributed operations are typed API actions. For mouse/keyboard QA keep
the original screenshot-before → actual input → screenshot-after discipline.
Neither scene inspection nor direct picking makes an API test screenshot-driven
UI evidence. Use the existing HTTP `POST /checkpoint` for a correlated state and
capture registration when needed; it shares the normal state opt-in gate.

## Commands from an installed Python module

A Python module can add commands to every attached application without a change
to ovui or to the application. Declare an entry point in the group
`ovui.inspector_commands`. Its value is a callable `factory(application) ->
iterable[Command]`. `attach_application` calls each entry after it registers the
application's own commands. A command with a name that is already registered is
skipped, so an application keeps its own command. An entry that fails is reported
on stderr and in `health` (`contribution_error`); the other entries and the
Inspector keep working.

`ovui-data-adapters-common` declares `render_diagnostics`, which adds
`render_diagnostics`, `material_verify` and `gpu_memory` (category `diagnostics`,
read-only).

## Status from an installed Python module

An entry point in the group `ovui.inspector_status` is `callable() -> dict`. `health` shows each
result under `extensions` (the entry name is the key). When a result has `"degraded": true`, the
`status` of `health` is `degraded`. A provider that raises is shown as degraded with the error.
`ovui-data-adapters-common` uses it to show render failures.
