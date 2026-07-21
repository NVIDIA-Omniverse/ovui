# OVUI Inspector state-guided end-to-end QA

This directory contains durable native OVStage viewer scenarios driven only
through the `ovui-inspect` HTTP mouse and keyboard API. The scenarios may choose target
coordinates from read-only application state, so this is state-guided UI
evidence, not strict screenshot-first proof. Every action produces:

1. a full-frame PNG immediately before the action;
2. a read-only native-OVStage/widget state snapshot before the action;
3. one Inspector mouse or keyboard request;
4. a full-frame PNG immediately after the action; and
5. a second state snapshot with explicit native-OVStage/adapter/UI
   consistency checks. The OVStage provider has no backing USD stage or
   OpenUSD bridge; every semantic observation comes from the exact native
   OVStage snapshot and the adapter/UI views built on it.

The suite is opt-in because it needs the matching Kit OVStage/OVRTX build, a
standalone ovui Python 3.12 environment, a GPU, and Xvfb. Unit-test runs collect
the scenarios but skip them unless `OVUI_RUN_INSPECTOR_QA=1`.
The harness enables `OVUIINSPECT_ENABLE_STATE=1` only for the child OVStage viewer
process; ordinary Inspector sessions leave state and checkpoint access off.

Actions still use real Inspector mouse and keyboard requests, and screenshots
record visible state immediately before and after them. Because a state-derived
coordinate can still hit a clipped or unreadable control, those images verify
the result but do not prove that the target was discoverable in the image. For
strict screenshot-first proof, choose every target from the latest screenshot
and use application state only after the action for semantic verification.

The application interpreter must have both component distributions installed,
not merely their source directories on `PYTHONPATH`:

```bash
"$OVUI_INSPECTOR_APP_PYTHON" -m pip install -e \
  "$REPO_ROOT/ovui-data-adapters/dist/ovstage" --no-deps
```

That distribution registers `ovstage_physics_controls`. The harness fails as
soon as the first real frame is ready if the entry point is absent or a
component failed to load.

Required environment variables are portable paths, never host-specific values:

```bash
export REPO_ROOT=/path/to/ovui
export OVUI_RUN_INSPECTOR_QA=1
export KIT_ROOT=/path/to/omniverse-kit
export OVUI_INSPECTOR_APP_PYTHON=/path/to/standalone-ovui-python
export OVUI_PYTHON_ROOT=/path/to/built/ovui/python
export OVSTAGE_ROOT="$KIT_ROOT/rendering/ovstage"
export OVRTX_ROOT="$KIT_ROOT/rendering/ovrtx"
export OVSTAGE_BUILD_DIR="$KIT_ROOT/rendering/_build/linux-x86_64/release"

python -m pytest -m inspector_qa ovui-widgets/tests/inspector_qa
```

`feature-matrix.json` is the authoritative closure ledger. A feature is only
`inspector_covered` when a named state-guided scenario performs the visible
action and asserts both screenshot evidence and independent scene state.

## Machine-enforced evidence contracts

Coverage is checked at three levels:

1. `feature-matrix.json` defines each feature's `required_evidence` tokens and
   scenario node IDs.
2. Each workflow module declares its own `ScenarioEvidenceContract` beside the
   test that executes it. `test_feature_matrix.py` discovers those declarations
   and cross-checks them against the ledger, so there is no second central
   token list that can drift. The gate resolves every exact Python node and
   requires a real `EvidenceRecorder.action(...)` call; an existing test name
   alone is not evidence.
3. When constructed with a scenario contract, `EvidenceRecorder` writes
   schema-version-2 `manifest.json` files containing the declaration,
   `interaction_mode: "state_guided"`, Inspector actions, individual pass/fail
   evidence checks, and a completion summary. `finalize()` fails closed when an
   action is missing or any required token is missing or failed.

The runtime API is deliberately small. Action-shaped tokens can be attached to
the real Inspector action; state assertions are recorded explicitly afterward:

```python
scenario = ScenarioEvidenceContract.declare(
    "test_stage.py::test_delete",
    {
        "stage.delete": (
            "delete_key",
            "native_absent",
        ),
    },
)
evidence = EvidenceRecorder(client, evidence_root, scenario=scenario)
deleted = evidence.action(
    "delete-selection",
    lambda: client.press("delete"),
    evidence_tokens={"stage.delete": ("delete_key",)},
)
state = deleted["after"]["state"]
evidence.check(
    "stage.delete",
    "native_absent",
    "/World/Cube" not in state["ovstage"]["paths"],
)
evidence.finalize()
```

Failed checks remain in the manifest even when `check()` or `finalize()`
raises, so CI artifacts explain whether the failure was a missing action,
missing token, or an observed false result.
