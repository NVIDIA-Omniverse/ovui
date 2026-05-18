# Runtime Environment And Real Ovrtx Requirements

## Runtime Environment For This Machine

Run disposable apps from the ovui repo root with the source roots and runtime
libraries on the environment. Keep the app alive as a foreground managed
process while `ovui-inspect` drives screenshots and input.

The example below uses environment variables for every machine-specific path so
the recipe is portable. Point each variable at the local checkout of the
corresponding repository before sourcing:

```bash
# Required: local checkouts. Set these to whatever paths the host uses.
: "${REPO:?set REPO to the local ovui repo checkout}"
: "${USD_INSTALL:?set USD_INSTALL to the local USD install prefix}"
: "${OVRTX_ROOT:?set OVRTX_ROOT to the local ovrtx checkout}"
export OVRTX_RUNTIME="${OVRTX_RUNTIME:-$OVRTX_ROOT/python/ovrtx/bin}"

# Disposable trial workspace; pick any writable scratch root outside the repo.
: "${TRIAL_ROOT:?set TRIAL_ROOT to a writable scratch directory outside the repo}"
export EVIDENCE_ROOT="${EVIDENCE_ROOT:-$TRIAL_ROOT/evidence}"
export USD_FIXTURE="${USD_FIXTURE:-$REPO/ovwidgets/tests/data/simple_scene.usda}"
export PYTHON_BIN=${PYTHON_BIN:-$(command -v python3)}
test -n "$PYTHON_BIN" || { echo "python3 not found" >&2; exit 1; }

export OVWIDGETS_REQUIRE_OVRTX=1
export OVRTX_SKIP_USD_CHECK=1
export PYTHONPATH=$TRIAL_ROOT:$REPO/skills/omniverse-ui-inspector:$REPO/ovwidgets:$REPO/ovui-data-adapters:$REPO/ovui/python:$OVRTX_ROOT/python:$USD_INSTALL/lib/python:${PYTHONPATH:-}
export LD_LIBRARY_PATH=$USD_INSTALL/lib:$OVRTX_RUNTIME:${LD_LIBRARY_PATH:-}
```

Use `"$PYTHON_BIN"` for disposable-app commands. Do not silently fall back to
bare `python`: this machine may not provide that alias. Missing `python3` is an
environment failure, but missing `python` is not acceptable when `python3`
exists.

The fixture `ovwidgets/tests/data/simple_scene.usda` contains stable prims:
`/World/Cube`, `/World/Sphere`, `/World/Pyramid`, and `/World/Pillar`.
Use `/World/Cube` as the default selected prim in proof screenshots.

## Real Ovrtx Requirements

The disposable app must fail fast when ovrtx is unavailable. Do not silently
fall back to a mock renderer.

Required renderer sequence:

1. Construct `OvRtxRendererAdapter()` before the first `Usd.Stage.Open(path)`.
   This matches `ovwidgets.app.Application.open_file()`: constructing ovrtx
   first primes the MDL cache before pxr opens the stage.
2. Only after the renderer exists, import/open the USD stage.
3. Call `renderer.load_stage(stage)`.
4. If any step raises or `AVAILABLE` is false while
   `OVWIDGETS_REQUIRE_OVRTX=1`, abort the trial.
5. Print a proof marker such as
   `[ovwidgets-trial] renderer=OvRtxRendererAdapter stage=/.../simple_scene.usda`
   after `load_stage()` succeeds.

Minimal fail-fast helper:

```python
def build_required_ovrtx_renderer():
    if not bool(AVAILABLE):
        raise RuntimeError("ovrtx is required but AVAILABLE is false")
    renderer = OvRtxRendererAdapter()
    return renderer

def open_usd_with_required_ovrtx(path: str):
    renderer = build_required_ovrtx_renderer()
    from pxr import Usd
    stage = Usd.Stage.Open(path)
    if stage is None:
        renderer.shutdown()
        raise RuntimeError(f"Usd.Stage.Open returned None for {path}")
    renderer.load_stage(stage)
    print(
        f"[ovwidgets-trial] renderer={type(renderer).__name__} stage={path}",
        flush=True,
    )
    return stage, renderer
```

Reject these log strings and stop the trial if any appear:

- `ovrtx renderer unavailable`
- `ovrtx renderer failed`
- `no ovrtx renderer was returned`
- `MockRendererAdapter`
- `fallback renderer`
- `black frame` or an all-black screenshot with no visible USD content

The required screenshot proof must show real rendered USD geometry, not only
panel chrome. The viewport should visibly contain the cube/sphere/pyramid/pillar
scene from `simple_scene.usda`, with one selected prim highlighted or showing a
transform gizmo.
