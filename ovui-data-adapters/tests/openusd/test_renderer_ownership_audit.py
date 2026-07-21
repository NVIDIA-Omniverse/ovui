# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Static ownership audit for the depth-one LdrColor overlap (ENFORCING).

The overlap retains an ovrtx step-result container for one frame
(:mod:`ovui_data_adapters.common._ldr_overlap`). Native output handles in
that container become invalid when native renderer state mutates, so the
retained container must be released on every control-flow path that reaches
an ownership-invalidating native operation.

DEFAULT-DENY MODEL. The scanner taints every expression that denotes the
native renderer (``self._renderer``, aliases through any tracked binding
form, ``getattr(self, "_renderer")``) and then classifies every USE of a
tainted expression against a closed list of allowed contexts:

1. method access in IMMEDIATE call position with a name in the audited
   EXEMPT or MUTATING sets (``self._renderer.step(...)``);
2. capability introspection: ``getattr``/``hasattr`` with a literal name
   (a ``getattr`` binding is recorded so the bound name's INVOCATION is
   classified too), and bare ``callable``/``isinstance``/``id``/``repr``/
   ``type`` probes;
3. identity tests against ``None`` (``is`` / ``is not``);
4. assignment of the handle to a plain local name (tracked alias) and
   assignment TO the ``_renderer`` field itself (field management);

EVERY other use — bare attribute/property loads (including bound-method
aliases like ``op = r.reset``), attribute writes and deletes, returns,
yields, container literals, subscript stores, lambda bodies and default
arguments, comprehensions, conditional/boolean expressions, star-args,
f-strings, unapproved call arguments, and dynamic ``getattr`` — FAILS the
audit. Passing therefore has a specific reviewable reason per use, never
"the scanner did not model that syntax". Additional fail-closed classes:

* SCOPE STORAGE: assigning the handle (or a getattr-bound capability) to a
  name declared ``global`` or ``nonlocal`` escapes the function's proof and
  is rejected.
* IMPLICIT PROTOCOL: using the renderer as a context manager (``with r:``,
  ``async with r:``) dispatches ``__enter__``/``__exit__`` implicitly and is
  rejected; iteration, subscripting, truthiness, operators, formatting, and
  membership tests on the handle all fall to default-deny.
* DEFERRED EXECUTION: any tainted native call inside a lambda, generator
  expression, or nested function (including one whose NAME shadows a
  boundary method) executes after the enclosing function's release proof
  has gone stale and is rejected outright — exempt names included.

RELEASE ORDERING is control-flow aware: for every approved boundary
function, a path simulator proves that each reachable native mutation is
preceded by ``_release_retained_output()`` on EVERY path (must-analysis
across if/elif/else, loops, and try/except/finally), that no path executes
the release more than once, and that declared cheap-guard functions do not
release on their early-return no-op paths. Conditional release followed by
unconditional mutation fails. Exceptional flow is not discarded: an
``except`` handler's fall-through joins the post-``try`` state, and a
``finally`` body is analyzed with the pessimistic minimum of the try-entry
and every fall-through state (an exception may fire before any release in
the body took effect). SUSPENSION points (``yield``, ``yield from``,
``await``, ``async for``, ``async with``) invalidate the accumulated
release proof: retained output may be re-established while the frame loop
runs during the suspension, so a mutation after a suspension needs a fresh
release on every path.

Two shadowing forms are recognized to keep false positives down WITHOUT
opening holes (both are real Python scoping semantics): a nested-function
parameter shadows an outer renderer alias of the same name, and a
comprehension target shadows an alias inside the comprehension (the first
generator's iterable still evaluates in the enclosing scope and stays
tainted). Alias taint is otherwise sticky: rebinding an alias to a
non-renderer value does NOT clear it (fail-closed; flow-insensitive).

Negative self-tests at the bottom prove every rejection class fires,
including each bypass from both production reviews (property read, bound
method alias, annotated getattr binding, lambda/default capture,
list/dict/yield/subscript escape, attribute delete, conditional release,
global/nonlocal storage, context-manager protocol, handler fall-through,
mutation in ``finally``, deferred generators, post-``yield``/``await``
mutation) and adjacent forms (async defs, comprehensions, conditional
expressions, boundary-name spoofing in nested scopes).

The overlap ships only in the OpenUSD adapter. The OVStage BORROW adapter
is excluded by a test proving the overlap cannot activate there plus a
pinned snapshot of its native-mutation sites (fails when a new site
appears, so it cannot silently go stale).
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field

ADAPTERS_ROOT = pathlib.Path(__file__).resolve().parents[2] / "ovui_data_adapters"
OPENUSD_ADAPTER = ADAPTERS_ROOT / "openusd" / "renderer_adapter.py"
OVSTAGE_ADAPTER = ADAPTERS_ROOT / "ovstage" / "renderer_adapter.py"

# Hot / read-only native operations, each with independent runtime evidence
# (per-frame call profiles and retained-validity probes; see
# docs/ovrtx-viewport-fps-overlap.md).
EXEMPT_CALLS = {
    "step",                  # the produce call; retention exists to span it
    "write_attribute",       # per-frame Fabric writes (camera, selection groups)
    # Renderer-owned, stream-ordered selection-outline membership writes
    # (the ovrtx 0.4 replacement for the omni:selectionOutlineGroup
    # attribute write). The blocking string variant waits for operation
    # completion in-call (it is ovrtx's own ``_async(...).wait()`` wrapper);
    # the async variant's Operation is explicitly waited on by the adapter.
    # Neither transfers ownership nor invalidates retained step results —
    # live-verified: the write completes with the LDR presentation overlap
    # retaining the previous frame's output.
    "set_selection_outline_group_strings",
    "set_selection_outline_group_strings_async",
    "enqueue_pick_query",    # pick query registration
    "resolve_prim_path_id",  # read-only pick-path resolution
    "_get_path_dict",        # read-only path table access
    "version",               # read-only
}

# Ownership-invalidating native operations.
MUTATING_CALLS = {
    "remove_usd",
    "add_usd",
    "add_usd_layer",
    "add_usd_reference_from_string",
    "open_usd",
    "open_usd_from_string",
    "open_usd_from_file",
    "reset",
    "reset_stage",
    "attach_ovstage",
    "detach_ovstage",
    "set_selection_group_styles",
}

# Approved release-first boundary functions in the OpenUSD adapter.
BOUNDARY_FUNCTIONS = {
    "set_active_render_product_path",
    "load_stage",
    "shutdown",
    "_reinject_session_layer",
    "_sync_ovrtx_root_snapshot_overlay_from_stage",
    "_write_render_setting_to_ovrtx",
    "_reload_live_root_snapshot",
    "_remove_ovrtx_layers",
    "_remove_live_resync_layers",
    "_open_ovrtx_root",
    "_add_ovrtx_session_layer",
    "_configure_selection_outline_styles",
    # Stage-replacement transaction helpers (complete-old-or-complete-new
    # contract): both release first, then reclaim prospective layers /
    # re-install the previous scene on failure paths.
    "_reclaim_prospective_native",
    "_restore_native_scene",
    # Reconcile old native handles after the new scene commits, and drain
    # carried cleanup debt at the next teardown/shutdown. Both release the
    # retained output first, then remove old/debt handles.
    "_reconcile_old_native",
    "_drain_native_debt",
}

# Calls to these (on self) count as mutations for path ordering: they either
# ARE boundaries (their own release makes a second release upstream
# double-release-adjacent, so ordering still demands the local release first)
# or funnel into one (_sync_active_selector_state -> _reinject_session_layer).
DELEGATING_FUNNELS = BOUNDARY_FUNCTIONS | {"_sync_active_selector_state"}

# Boundary functions whose no-op/validation guard paths must NOT release
# (cheap early returns stay free; verified per control-flow path).
STRICT_GUARD_FUNCTIONS = {
    "_configure_selection_outline_styles",
    "_remove_live_resync_layers",
    "set_active_render_product_path",
    "_reload_live_root_snapshot",
    "_sync_ovrtx_root_snapshot_overlay_from_stage",
}

RELEASE_CALL = "_release_retained_output"
RENDERER_ATTR = "_renderer"

# Builtins that may receive the tainted handle as a bare read (no retention).
SAFE_PROBE_CALLEES = {"callable", "isinstance", "id", "repr", "type"}


@dataclass
class Finding:
    kind: str
    function: str
    lineno: int
    detail: str

    def __str__(self) -> str:  # pragma: no cover — failure diagnostics only
        return f"{self.kind} in {self.function}:{self.lineno} ({self.detail})"


# ── pass A: alias collection (closure-aware) ─────────────────────────────


class _AliasCollector(ast.NodeVisitor):
    """Names bound (directly or transitively) to the renderer, per function.

    Nested functions inherit enclosing bindings (closure capture); each
    function's effective alias set is the union of its scope chain.
    """

    def __init__(self) -> None:
        self.per_function: dict[int, set[str]] = {}
        self._scope_chain: list[set[str]] = [set()]
        self._func_nodes: list[ast.AST] = []

    def _effective(self) -> set[str]:
        merged: set[str] = set()
        for scope in self._scope_chain:
            merged |= scope
        return merged

    def _is_renderer_value(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == RENDERER_ATTR:
            return True
        if isinstance(node, ast.Name) and node.id in self._effective():
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == RENDERER_ATTR):
            return True
        if isinstance(node, ast.NamedExpr):
            return self._is_renderer_value(node.value)
        return False

    def _visit_func(self, node):
        self._func_nodes.append(node)
        self._scope_chain.append(set())
        self.generic_visit(node)
        self._scope_chain.pop()
        self._func_nodes.pop()

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func
    visit_Lambda = _visit_func

    def _bind(self, name: str) -> None:
        self._scope_chain[-1].add(name)
        for func in self._func_nodes:
            self.per_function.setdefault(id(func), set())
        # effective sets are resolved at classification time per node; store
        # cumulative binding on the innermost function
        if self._func_nodes:
            self.per_function[id(self._func_nodes[-1])].add(name)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_renderer_value(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._bind(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (node.value is not None and self._is_renderer_value(node.value)
                and isinstance(node.target, ast.Name)):
            self._bind(node.target.id)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        if self._is_renderer_value(node.value) and isinstance(node.target, ast.Name):
            self._bind(node.target.id)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if (self._is_renderer_value(item.context_expr)
                    and isinstance(item.optional_vars, ast.Name)):
                self._bind(item.optional_vars.id)
        self.generic_visit(node)


# ── pass B: default-deny classification with parent context ──────────────


@dataclass
class FunctionFacts:
    name: str
    node: ast.AST
    owner: str = "<module>"
    release_linenos: list[int] = field(default_factory=list)
    mutation_linenos: list[int] = field(default_factory=list)
    mutation_nodes: list[ast.AST] = field(default_factory=list)
    bound_capabilities: dict[str, str] = field(default_factory=dict)


class OwnershipAudit:
    def __init__(self, source: str, *,
                 boundary_owner: str | None = None,
                 boundary_functions: frozenset | set | None = None,
                 delegating_funnels: frozenset | set | None = None,
                 safe_helper_callees: frozenset | set = frozenset(),
                 readonly_capability_names: frozenset | set = frozenset()) -> None:
        """``boundary_owner`` pins boundary identity to ONE owner scope: the
        named module-level class (the production adapter). When set, only
        that class's direct methods may register boundary facts or satisfy
        the boundary name-approval; a same-named def anywhere else is a
        ``boundary-identity-conflict``. When ``None`` (synthetic snippets),
        any single top-level definition qualifies, but DUPLICATE definitions
        of a boundary name are conflicts — a second definition can never
        establish, replace, mask, or satisfy the real ordering facts."""
        self.boundary_owner = boundary_owner
        self.boundary_functions = (BOUNDARY_FUNCTIONS
                                   if boundary_functions is None
                                   else set(boundary_functions))
        self.delegating_funnels = (
            (DELEGATING_FUNNELS if boundary_functions is None
             else self.boundary_functions)
            if delegating_funnels is None else set(delegating_funnels))
        # Narrow, reviewed read-only allowances for a specific adapter file:
        # helper callees that only VALIDATE the handle, and capability names
        # whose getattr-bound VALUE is inert metadata (never a retained-
        # output hazard) and may be read outside call position.
        self.safe_helper_callees = set(safe_helper_callees)
        self.readonly_capability_names = set(readonly_capability_names)
        self.tree = ast.parse(source)
        self.findings: list[Finding] = []
        self.calls: list[tuple[str, int, str]] = []
        self.function_facts: dict[str, FunctionFacts] = {}
        self._parents: dict[int, ast.AST] = {}
        self._func_of: dict[int, str] = {}
        self._func_node_of: dict[int, ast.AST] = {}
        self._scope_escapes: dict[int, set[str]] = {}
        self._collect_parents_and_functions()
        self._aliases = _AliasCollector()
        self._aliases.visit(self.tree)
        self._collect_capability_bindings()
        self._classify_all_tainted_uses()

    # -- infrastructure ---------------------------------------------------

    def _collect_parents_and_functions(self) -> None:
        func_stack: list[ast.AST] = []

        def walk(node: ast.AST, parent: ast.AST | None) -> None:
            if parent is not None:
                self._parents[id(node)] = parent
            # record the ENCLOSING function first (a function node belongs
            # to its parent scope; its body belongs to itself)
            name = (getattr(func_stack[-1], "name", "<lambda>")
                    if func_stack else "<module>")
            self._func_of[id(node)] = name
            if func_stack:
                self._func_node_of[id(node)] = func_stack[-1]
            if isinstance(node, (ast.Global, ast.Nonlocal)) and func_stack:
                self._scope_escapes.setdefault(
                    id(func_stack[-1]), set()).update(node.names)
            is_func = isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if is_func:
                func_stack.append(node)
            for child in ast.iter_child_nodes(node):
                walk(child, node)
            if is_func:
                func_stack.pop()

        walk(self.tree, None)
        # Ordering facts are keyed by name; only DIRECT methods of a
        # module-level class or module-level functions may claim a boundary
        # name. A def nested in a function OR in a nested class whose name
        # shadows a boundary must NOT merge into (or replace) the real
        # boundary's facts — its calls are rejected as deferred. Boundary
        # identity is further pinned: with ``boundary_owner`` set, only that
        # class's direct methods qualify; without it, a boundary name may
        # have exactly ONE eligible definition (duplicates conflict).
        for node in ast.walk(self.tree):
            if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and self._is_toplevel_def(node)):
                continue
            parent = self._parents.get(id(node))
            owner = (parent.name if isinstance(parent, ast.ClassDef)
                     else "<module>")
            if node.name in self.boundary_functions:
                if (self.boundary_owner is not None
                        and owner != self.boundary_owner):
                    self._flag("boundary-identity-conflict", node,
                               f"'{node.name}' defined on '{owner}', not the "
                               f"boundary owner '{self.boundary_owner}'")
                    continue
                existing = self.function_facts.get(node.name)
                if existing is not None and existing.node is not node:
                    self._flag("boundary-identity-conflict", node,
                               f"duplicate definition of boundary "
                               f"'{node.name}' on '{owner}' (already owned "
                               f"by '{existing.owner}')")
                    continue
            self.function_facts.setdefault(
                node.name, FunctionFacts(node.name, node, owner=owner))

    @staticmethod
    def _param_names(func_node: ast.AST) -> set[str]:
        args = getattr(func_node, "args", None)
        if args is None:
            return set()
        names = {a.arg for a in args.args}
        names |= {a.arg for a in args.posonlyargs}
        names |= {a.arg for a in args.kwonlyargs}
        if args.vararg is not None:
            names.add(args.vararg.arg)
        if args.kwarg is not None:
            names.add(args.kwarg.arg)
        return names

    def _comprehension_shadows(self, node: ast.Name) -> bool:
        """True when ``node`` is a comprehension target (own scope in py3).

        The FIRST generator's iterable evaluates in the enclosing scope, so
        a name inside it is NOT shadowed and stays tainted.
        """
        cursor: ast.AST | None = node
        while cursor is not None:
            parent = self._parents.get(id(cursor))
            if isinstance(parent, (ast.ListComp, ast.SetComp,
                                   ast.DictComp, ast.GeneratorExp)):
                in_first_iter = False
                probe: ast.AST | None = node
                first_iter = parent.generators[0].iter
                while probe is not None and probe is not parent:
                    if probe is first_iter:
                        in_first_iter = True
                        break
                    probe = self._parents.get(id(probe))
                if not in_first_iter:
                    targets: set[str] = set()
                    for gen in parent.generators:
                        for tgt in ast.walk(gen.target):
                            if isinstance(tgt, ast.Name):
                                targets.add(tgt.id)
                    if node.id in targets:
                        return True
            cursor = parent
        return False

    def _is_toplevel_def(self, func_node: ast.AST) -> bool:
        """True only for a module-level function or a DIRECT method of a
        module-level class (the production adapter shape). A def inside a
        nested class — class-in-method, class-in-class, or deeper — must
        never qualify: its name could spoof an approved boundary."""
        parent = self._parents.get(id(func_node))
        if isinstance(parent, ast.Module):
            return True
        if isinstance(parent, ast.ClassDef):
            return isinstance(self._parents.get(id(parent)), ast.Module)
        return False

    def _deferred_context(self, node: ast.AST) -> str | None:
        """Deferred-execution context of ``node``, or ``None`` if immediate.

        Code inside a lambda, a generator expression, a nested function, or
        a method of a nested class executes AFTER the enclosing function's
        release proof has gone stale — including a def whose name shadows a
        boundary method, which would otherwise launder its mutations.
        """
        cursor: ast.AST | None = self._parents.get(id(node))
        while cursor is not None:
            if isinstance(cursor, ast.GeneratorExp):
                return "generator expression"
            if isinstance(cursor, ast.Lambda):
                return "lambda"
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_toplevel_def(cursor):
                    return None
                return "nested function or nested-class method"
            cursor = self._parents.get(id(cursor))
        return None

    def _collect_capability_bindings(self) -> None:
        """Pre-pass: record getattr-bound capability names per function."""
        for node in ast.walk(self.tree):
            targets: list[str] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                value = node.value
                targets = [t.id for t in node.targets
                           if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                value = node.value
                if isinstance(node.target, ast.Name):
                    targets = [node.target.id]
            if (value is not None and isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "getattr" and len(value.args) >= 2
                    and self._is_tainted(value.args[0])
                    and isinstance(value.args[1], ast.Constant)):
                method = str(value.args[1].value)
                for name in targets:
                    self._facts(node).bound_capabilities[name] = method

    def _fn(self, node: ast.AST) -> str:
        return self._func_of.get(id(node), "<module>")

    def _identity_facts(self, node: ast.AST) -> "FunctionFacts | None":
        """Facts for ``node``'s enclosing def ONLY when it is the registered
        definition of its name. A boundary-named def that is not the
        registered definition is flagged; its lines are never recorded."""
        fn_name = self._fn(node)
        registered = self.function_facts.get(fn_name)
        enclosing = self._func_node_of.get(id(node))
        if registered is not None and registered.node is enclosing:
            return registered
        if fn_name in self.boundary_functions:
            self._flag("boundary-identity-conflict", node,
                       f"release/funnel call inside a '{fn_name}' that is "
                       f"not the registered boundary definition")
            return None
        return self._facts(node)

    def _facts(self, node: ast.AST) -> FunctionFacts:
        name = self._fn(node)
        if name not in self.function_facts:
            self.function_facts[name] = FunctionFacts(name, self.tree)
        return self.function_facts[name]

    def _flag(self, kind: str, node: ast.AST, detail: str) -> None:
        self.findings.append(
            Finding(kind, self._fn(node), getattr(node, "lineno", 0), detail))

    def _is_tainted(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == RENDERER_ATTR:
            return True
        if isinstance(node, ast.Name):
            if self._comprehension_shadows(node):
                return False
            cursor = self._func_node_of.get(id(node))
            seen: set[int] = set()
            while cursor is not None and id(cursor) not in seen:
                seen.add(id(cursor))
                if node.id in self._aliases.per_function.get(id(cursor), set()):
                    return True
                # a parameter of a closer scope shadows any outer alias of
                # the same name (passing the renderer IN is caught at the
                # call site as a handle-escape)
                if node.id in self._param_names(cursor):
                    return False
                cursor = self._func_node_of.get(id(cursor))
            # bound capability names are tracked separately (invocation is
            # classified, other uses of the bound callable are denied below)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == RENDERER_ATTR):
            return True
        if isinstance(node, ast.NamedExpr):
            return self._is_tainted(node.value)
        return False

    def _record_call(self, node: ast.AST, method: str,
                     *, is_binding: bool = False) -> None:
        self.calls.append((self._fn(node), getattr(node, "lineno", 0), method))
        if not is_binding:
            deferred = self._deferred_context(node)
            if deferred is not None:
                # ANY tainted native call (exempt names included) whose
                # execution is deferred escapes the release proof.
                self._flag("deferred-native-call", node,
                           f"native '{method}' inside a {deferred} executes "
                           f"after the enclosing release proof")
        if method in MUTATING_CALLS and not is_binding:
            fn_name = self._fn(node)
            if fn_name in self.boundary_functions:
                # name approval is by IDENTITY: the enclosing def must BE
                # the single registered boundary definition, not merely
                # share its name (unrelated/duplicate/spoofed definitions
                # must never satisfy the real boundary's ordering facts)
                registered = self.function_facts.get(fn_name)
                enclosing = self._func_node_of.get(id(node))
                if registered is None or registered.node is not enclosing:
                    self._flag("boundary-identity-conflict", node,
                               f"native '{method}' in a '{fn_name}' that is "
                               f"not the registered boundary definition")
                    return
            facts = self._facts(node)
            facts.mutation_linenos.append(getattr(node, "lineno", 0))
            facts.mutation_nodes.append(node)

    # -- the default-deny classification ----------------------------------

    def _classify_all_tainted_uses(self) -> None:
        for node in ast.walk(self.tree):
            # dynamic code execution defeats any static audit: deny outright
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("exec", "eval", "compile")):
                self._flag("dynamic-code", node,
                           f"{node.func.id}() executes code the static "
                           f"ownership audit cannot see")
            # release + funnel bookkeeping (independent of taint). Both are
            # identity-gated: lines from a def that is NOT the registered
            # definition of its name must never pollute (or satisfy) the
            # registered facts — a same-named spoof exercising the release
            # or a funnel is itself a conflict when the name is a boundary.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (node.func.attr == RELEASE_CALL
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "self"):
                    facts = self._identity_facts(node)
                    if facts is not None:
                        facts.release_linenos.append(node.lineno)
                if (node.func.attr in self.delegating_funnels
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "self"):
                    facts = self._identity_facts(node)
                    if facts is not None:
                        facts.mutation_linenos.append(node.lineno)
                        facts.mutation_nodes.append(node)
            # bound-capability invocation and misuse
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                facts = self.function_facts.get(self._fn(node))
                if facts is not None and node.id in facts.bound_capabilities:
                    method = facts.bound_capabilities[node.id]
                    parent = self._parents.get(id(node))
                    if isinstance(parent, ast.Call) and parent.func is node:
                        self._record_call(parent, method)
                    elif method in self.readonly_capability_names:
                        pass  # inert metadata value; reading it is safe
                    elif not self._is_guard_context(node, parent):
                        self._flag("capability-escape", node,
                                   f"bound capability '{node.id}' ({method}) "
                                   f"used outside call/guard position")
            if not self._is_tainted(node):
                continue
            self._classify_tainted_use(node)

    def _is_guard_context(self, node: ast.AST, parent: ast.AST | None) -> bool:
        """None-checks / callable() probes on a bound capability name."""
        if isinstance(parent, ast.Compare):
            comparators = [parent.left] + list(parent.comparators)
            if node in comparators and all(
                    isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops):
                others = [c for c in comparators if c is not node]
                return all(isinstance(c, ast.Constant) and c.value is None
                           for c in others)
        if (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
                and parent.func.id in SAFE_PROBE_CALLEES):
            return True
        return False

    def _classify_tainted_use(self, node: ast.AST) -> None:
        parent = self._parents.get(id(node))

        # a NAME in Store/Del context is the binding side of an alias (the
        # alias itself is tracked; its LOADS are classified), not a use
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            return

        # storing INTO the field (self._renderer = value) is field management
        if (isinstance(node, ast.Attribute) and node.attr == RENDERER_ATTR
                and isinstance(node.ctx, (ast.Store,))):
            return
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Del):
            self._flag("attribute-delete", node, f"del ...{node.attr}")
            return

        # 1. attribute access on the tainted handle
        if isinstance(parent, ast.Attribute) and parent.value is node:
            grand = self._parents.get(id(parent))
            if isinstance(parent.ctx, ast.Store):
                self._flag("attribute-write", parent,
                           f"renderer.{parent.attr} = ...")
                return
            if isinstance(parent.ctx, ast.Del):
                self._flag("attribute-delete", parent,
                           f"del renderer.{parent.attr}")
                return
            if isinstance(grand, ast.Call) and grand.func is parent:
                method = parent.attr
                if method in EXEMPT_CALLS or method in MUTATING_CALLS:
                    self._record_call(grand, method)
                else:
                    self._record_call(grand, method)
                    self._flag("unclassified-call", grand, method)
                return
            if isinstance(grand, ast.AugAssign) and grand.target is parent:
                self._flag("attribute-write", grand,
                           f"renderer.{parent.attr} op= ...")
                return
            self._flag("attribute-load", parent,
                       f"renderer.{parent.attr} read outside call position "
                       f"(bound-method alias / property escape)")
            return

        # 2. capability probes and safe builtins
        if isinstance(parent, ast.Call) and node in parent.args:
            callee = parent.func
            callee_name = callee.id if isinstance(callee, ast.Name) else None
            if callee_name in ("getattr", "hasattr"):
                if (len(parent.args) >= 2
                        and isinstance(parent.args[1], ast.Constant)):
                    method = str(parent.args[1].value)
                    if callee_name == "getattr":
                        self._record_binding_or_call(parent, method)
                    return
                self._flag("dynamic-access", parent,
                           f"{callee_name} on renderer with non-literal name")
                return
            if callee_name in self.safe_helper_callees:
                # reviewed read-only validation helper for this adapter file
                return
            if callee_name in SAFE_PROBE_CALLEES:
                # type(renderer).method(...) class-callable: classify the
                # outer attribute access explicitly
                grand = self._parents.get(id(parent))
                if (callee_name == "type" and isinstance(grand, ast.Attribute)
                        and grand.value is parent):
                    ggrand = self._parents.get(id(grand))
                    if isinstance(ggrand, ast.Call) and ggrand.func is grand:
                        self._record_call(ggrand, grand.attr)
                        if not (grand.attr in EXEMPT_CALLS
                                or grand.attr in MUTATING_CALLS):
                            self._flag("unclassified-call", ggrand, grand.attr)
                    else:
                        self._flag("attribute-load", grand,
                                   f"type(renderer).{grand.attr} read outside "
                                   f"call position")
                return
            self._flag("handle-escape", parent,
                       f"renderer passed to "
                       f"{callee_name or ast.dump(callee)[:40]}")
            return
        if isinstance(parent, ast.keyword):
            self._flag("handle-escape", parent,
                       "renderer passed as keyword argument")
            return

        # 3. identity tests against None
        if isinstance(parent, ast.Compare):
            comparators = [parent.left] + list(parent.comparators)
            if node in comparators and all(
                    isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops):
                others = [c for c in comparators if c is not node]
                if all(isinstance(c, ast.Constant) and c.value is None
                       for c in others):
                    return
            self._flag("unclassified-use", parent,
                       "renderer in comparison beyond `is (not) None`")
            return

        # 4. tracked alias bindings (a target declared global/nonlocal
        # stores the handle beyond this function's proof, and a class-body
        # assignment stores it on the class object: both escape)
        if isinstance(parent, ast.Assign) and node is parent.value:
            if not all(isinstance(t, ast.Name) for t in parent.targets):
                self._flag("handle-escape", parent,
                           "renderer assigned to non-local-name target")
                return
            if self._in_class_body(parent):
                self._flag("handle-escape", parent,
                           "renderer stored as a class attribute")
                return
            escaped = self._escaping_target_names(
                node, [t.id for t in parent.targets])
            if escaped:
                self._flag("handle-escape", parent,
                           f"renderer stored to global/nonlocal name(s) "
                           f"{sorted(escaped)}")
            return
        if isinstance(parent, ast.AnnAssign) and node is parent.value:
            if not isinstance(parent.target, ast.Name):
                self._flag("handle-escape", parent,
                           "renderer assigned to non-local-name target")
                return
            if self._in_class_body(parent):
                self._flag("handle-escape", parent,
                           "renderer stored as a class attribute")
                return
            escaped = self._escaping_target_names(node, [parent.target.id])
            if escaped:
                self._flag("handle-escape", parent,
                           f"renderer stored to global/nonlocal name(s) "
                           f"{sorted(escaped)}")
            return
        if isinstance(parent, ast.NamedExpr) and node is parent.value:
            escaped = self._escaping_target_names(node, [parent.target.id])
            if escaped:
                self._flag("handle-escape", parent,
                           f"renderer stored to global/nonlocal name(s) "
                           f"{sorted(escaped)}")
            return  # walrus alias tracked by pass A
        if isinstance(parent, ast.withitem) and node is parent.context_expr:
            self._flag("implicit-protocol", parent,
                       "renderer used as a context manager "
                       "(__enter__/__exit__ dispatch on the native handle)")
            return

        # default-deny: name the syntactic context in the finding
        context = type(parent).__name__ if parent is not None else "<root>"
        self._flag("unclassified-use", node,
                   f"renderer used in unsupported context: {context}")

    def _escaping_target_names(self, node: ast.AST,
                               names: list[str]) -> set[str]:
        func_node = self._func_node_of.get(id(node))
        if func_node is None:
            return set()
        declared = self._scope_escapes.get(id(func_node), set())
        return {name for name in names if name in declared}

    def _in_class_body(self, node: ast.AST) -> bool:
        """True when ``node`` executes directly in a class body scope."""
        cursor: ast.AST | None = self._parents.get(id(node))
        while cursor is not None:
            if isinstance(cursor, ast.ClassDef):
                return True
            if isinstance(cursor,
                          (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return False
            cursor = self._parents.get(id(cursor))
        return False

    def _record_binding_or_call(self, call: ast.Call, method: str) -> None:
        parent = self._parents.get(id(call))
        target_names: list[str] = []
        if isinstance(parent, ast.Assign):
            target_names = [t.id for t in parent.targets
                            if isinstance(t, ast.Name)]
            if len(target_names) != len(parent.targets):
                self._flag("capability-escape", call,
                           f"getattr-bound '{method}' assigned to "
                           f"non-local-name target")
        elif isinstance(parent, ast.AnnAssign):
            if isinstance(parent.target, ast.Name):
                target_names = [parent.target.id]
            else:
                self._flag("capability-escape", call,
                           f"getattr-bound '{method}' assigned to "
                           f"non-local-name target")
        elif isinstance(parent, ast.Call) and parent.func is call:
            # inline getattr(renderer, "m")(...) invocation
            self._record_call(parent, method)
            if not (method in EXEMPT_CALLS or method in MUTATING_CALLS):
                self._flag("unclassified-call", parent, method)
            return
        elif isinstance(parent, (ast.Compare,)):
            return  # e.g. getattr(...) is None — pure capability probe
        else:
            if method in self.readonly_capability_names:
                return  # inert metadata read (e.g. version/config logging)
            self._flag("capability-escape", call,
                       f"getattr-bound '{method}' used in unsupported "
                       f"context: {type(parent).__name__}")
            return
        self._record_call(call, method, is_binding=True)
        escaped = self._escaping_target_names(call, target_names)
        if escaped:
            self._flag("capability-escape", call,
                       f"getattr-bound '{method}' stored to global/nonlocal "
                       f"name(s) {sorted(escaped)}")
        facts = self._facts(call)
        for name in target_names:
            facts.bound_capabilities[name] = method
        if not (method in EXEMPT_CALLS or method in MUTATING_CALLS):
            self._flag("unclassified-call", call, method)


def classify(audit: OwnershipAudit) -> list[Finding]:
    findings = list(audit.findings)
    for function, lineno, method in audit.calls:
        if method in EXEMPT_CALLS:
            continue
        if method in MUTATING_CALLS and function not in audit.boundary_functions:
            findings.append(Finding("mutation-outside-boundary", function,
                                    lineno, method))
    return findings


# ── control-flow-aware release ordering ──────────────────────────────────


@dataclass
class _PathState:
    release_count: int = 0
    terminated: bool = False


class _PathAnalyzer:
    """Must-analysis: every path reaching a mutation released exactly once.

    Mutations are identified by line spans precomputed by the audit pass
    (direct native mutating calls, bound-capability invocations, delegating
    funnel calls). Branches are joined pessimistically: a mutation after an
    ``if`` requires the release on BOTH arms (or before the ``if``). Loops
    require release before entry or unconditionally within the body before
    the mutation. Exceptional flow is preserved end to end: ``try``
    handlers are analyzed with the state at try entry (an exception may
    fire before any release inside the body took effect), handler
    FALL-THROUGH states join the post-``try`` state, and a ``finally`` body
    runs with the pessimistic minimum of the entry and every fall-through
    state (it also runs on the propagating-exception path). Suspension
    points (``yield``/``yield from``/``await``/``async for``/``async
    with``) reset the accumulated release proof to zero: the frame loop may
    re-establish retained output while this function is suspended, so any
    mutation after a suspension needs a fresh release on every path.
    """

    def __init__(self, func: ast.AST, facts: FunctionFacts,
                 strict_guards: bool) -> None:
        self.func = func
        self.release_lines = set(facts.release_linenos)
        self.mutation_lines = set(facts.mutation_linenos)
        self.mutation_node_ids = {id(n) for n in facts.mutation_nodes}
        self.strict_guards = strict_guards
        self.violations: list[Finding] = []
        self._own_span = (func.lineno, func.end_lineno or func.lineno)
        self._reached_mutation = False

    def _contains(self, node: ast.AST, lines: set[int]) -> bool:
        lo = getattr(node, "lineno", None)
        hi = getattr(node, "end_lineno", None)
        if lo is None:
            return False
        hi = hi or lo
        # exclude nested function bodies from the enclosing span
        nested: list[tuple[int, int]] = []
        for child in ast.walk(node):
            if child is not node and isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                nested.append((child.lineno, child.end_lineno or child.lineno))
        for line in lines:
            if lo <= line <= hi and not any(a <= line <= b for a, b in nested):
                return True
        return False

    def _flag(self, kind: str, node: ast.AST, detail: str) -> None:
        self.violations.append(Finding(
            kind, getattr(self.func, "name", "<lambda>"),
            getattr(node, "lineno", 0), detail))

    def run(self) -> list[Finding]:
        body = list(getattr(self.func, "body", []))
        final = self._run_block(body, _PathState())
        if self.strict_guards and not final.terminated:
            # fall-through end of a strict-guard function: it must not have
            # released without mutating on this path — checked in _run_block
            pass
        return self.violations

    # returns joined fall-through state
    def _run_block(self, stmts: list[ast.stmt], state: _PathState) -> _PathState:
        for stmt in stmts:
            if state.terminated:
                return state
            state = self._run_stmt(stmt, state)
        return state

    def _require_released(self, node: ast.AST, state: _PathState) -> None:
        if state.release_count < 1:
            self._flag("mutation-without-release-on-path", node,
                       "a control-flow path reaches this mutation without a "
                       "prior _release_retained_output()")

    def _suspends(self, node: ast.AST) -> bool:
        """True when ``node`` contains a suspension point of THIS function
        (yield/yield from/await/async iteration), excluding nested function
        bodies (their suspensions belong to their own frames)."""
        nested: list[tuple[int, int]] = []
        for child in ast.walk(node):
            if child is not node and isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                nested.append((child.lineno, child.end_lineno or child.lineno))
        for child in ast.walk(node):
            if isinstance(child, (ast.Yield, ast.YieldFrom, ast.Await,
                                  ast.AsyncFor, ast.AsyncWith)):
                line = getattr(child, "lineno", None)
                if line is None or not any(a <= line <= b for a, b in nested):
                    return True
        return False

    _TRY_TYPES = ((ast.Try, ast.TryStar) if hasattr(ast, "TryStar")
                  else (ast.Try,))
    _COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While,
                 ast.With, ast.AsyncWith, ast.Match) + _TRY_TYPES

    # ── intra-expression evaluation order ────────────────────────────────
    #
    # Statement-level suspension resets are not enough: within ONE compound
    # expression an `await`/`yield` can execute BEFORE a native mutation
    # (`x = (await p, r.remove_usd(h))`), leaving the pre-statement release
    # proof stale by the time the mutation runs. `_expr_events` yields
    # ('suspend' | 'release' | 'mutate', node, ambiguous) events in
    # conservative CPython evaluation order — including value-BEFORE-target
    # for both plain and ANNOTATED assignments. Constructs whose execution
    # is conditional or repeated (conditional branches, short-circuit
    # tails, comprehension internals) are AMBIGUOUS: their suspensions
    # still count (fail closed) but their releases can never re-establish
    # a guarantee. An unambiguous, strictly ordered release DOES establish
    # a fresh guarantee for mutations evaluated after it.

    def _expr_events(self, node: ast.AST, ambiguous: bool = False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # only decorators and defaults evaluate now; the body is deferred
            for dec in node.decorator_list:
                yield from self._expr_events(dec, ambiguous)
            for default in (node.args.defaults + node.args.kw_defaults):
                if default is not None:
                    yield from self._expr_events(default, ambiguous)
            return
        if isinstance(node, ast.Lambda):
            for default in (node.args.defaults + node.args.kw_defaults):
                if default is not None:
                    yield from self._expr_events(default, ambiguous)
            return
        if isinstance(node, ast.GeneratorExp):
            # lazily evaluated (deferred-native-call covers its body); only
            # the first generator's iterable evaluates eagerly
            yield from self._expr_events(node.generators[0].iter, ambiguous)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            def one_iteration():
                first = True
                for gen in node.generators:
                    # the first iterable evaluates once, unconditionally;
                    # everything else is per-iteration (ambiguous)
                    yield from self._expr_events(
                        gen.iter, ambiguous if first else True)
                    first = False
                    if gen.is_async:
                        yield ("suspend", gen, True)
                    # target assignment happens per element AFTER the
                    # (possibly suspending) iteration step
                    yield from self._expr_events(gen.target, True)
                    for cond in gen.ifs:
                        yield from self._expr_events(cond, True)
                if isinstance(node, ast.DictComp):
                    yield from self._expr_events(node.key, True)
                    yield from self._expr_events(node.value, True)
                else:
                    yield from self._expr_events(node.elt, True)
            # two symbolic iterations: a suspension in iteration N precedes
            # every event of iteration N+1
            yield from one_iteration()
            yield from one_iteration()
            return
        if isinstance(node, (ast.Await, ast.YieldFrom)):
            yield from self._expr_events(node.value, ambiguous)
            yield ("suspend", node, ambiguous)
            return
        if isinstance(node, ast.Yield):
            if node.value is not None:
                yield from self._expr_events(node.value, ambiguous)
            yield ("suspend", node, ambiguous)
            return
        if isinstance(node, ast.Call):
            yield from self._expr_events(node.func, ambiguous)
            for arg in node.args:
                yield from self._expr_events(arg, ambiguous)
            for kw in node.keywords:
                yield from self._expr_events(kw.value, ambiguous)
            if id(node) in self.mutation_node_ids:
                yield ("mutate", node, ambiguous)
            elif (isinstance(node.func, ast.Attribute)
                    and node.func.attr == RELEASE_CALL
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"):
                yield ("release", node, ambiguous)
            return
        if isinstance(node, ast.IfExp):
            # test first, then EITHER branch: emit both, ambiguous
            yield from self._expr_events(node.test, ambiguous)
            yield from self._expr_events(node.body, True)
            yield from self._expr_events(node.orelse, True)
            return
        if isinstance(node, ast.BoolOp):
            # only the first operand evaluates unconditionally
            yield from self._expr_events(node.values[0], ambiguous)
            for value in node.values[1:]:
                yield from self._expr_events(value, True)
            return
        if isinstance(node, ast.Compare):
            # a CHAINED comparison short-circuits: `a < b < c` evaluates
            # `a` and `b` unconditionally but `c` only when `a < b` held —
            # every comparator after the first is conditional
            yield from self._expr_events(node.left, ambiguous)
            yield from self._expr_events(node.comparators[0], ambiguous)
            for comparator in node.comparators[1:]:
                yield from self._expr_events(comparator, True)
            return
        if isinstance(node, ast.Assert):
            # the message only evaluates on failure, and `-O` strips the
            # whole statement: nothing in an assert is definite
            yield from self._expr_events(node.test, True)
            if node.msg is not None:
                yield from self._expr_events(node.msg, True)
            return
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is not None:
                    yield from self._expr_events(key, ambiguous)
                yield from self._expr_events(value, ambiguous)
            return
        if isinstance(node, ast.Assign):
            yield from self._expr_events(node.value, ambiguous)
            for target in node.targets:   # value before targets
                yield from self._expr_events(target, ambiguous)
            return
        if isinstance(node, ast.AnnAssign):
            # CPython evaluates the VALUE first, then assigns to the
            # target; the annotation is not evaluated in function scope
            # (treated as ambiguous, last)
            if node.value is not None:
                yield from self._expr_events(node.value, ambiguous)
            yield from self._expr_events(node.target, ambiguous)
            yield from self._expr_events(node.annotation, True)
            return
        if isinstance(node, ast.AugAssign):
            # target subexpressions (load) evaluate before the value
            yield from self._expr_events(node.target, ambiguous)
            yield from self._expr_events(node.value, ambiguous)
            return
        # default: AST field order approximates evaluation order for the
        # remaining nodes (Compare left+comparators, BinOp, Subscript,
        # Tuple/List/Set, JoinedStr/FormattedValue, NamedExpr, Starred,
        # Return/Expr wrappers, ...)
        for child in ast.iter_child_nodes(node):
            yield from self._expr_events(child, ambiguous)

    def _check_mutation_in_expr(self, expr: ast.AST, node_for_flag: ast.AST,
                                state: _PathState) -> None:
        """Order-aware release requirement for mutations inside ``expr``.

        Each mutation needs a valid guarantee AT ITS EVALUATION POINT:
        either the pre-statement release proof with no suspension executed
        earlier in the expression, or an unambiguous in-expression release
        after the most recent suspension. Ambiguous releases never count;
        ambiguous suspensions always do.
        """
        fresh = state.release_count >= 1
        for kind, event_node, event_ambiguous in self._expr_events(expr):
            if kind == "suspend":
                fresh = False
            elif kind == "release":
                if not event_ambiguous:
                    fresh = True
            elif kind == "mutate" and not fresh:
                self._flag("mutation-without-release-on-path", event_node,
                           "no valid release guarantee at this mutation's "
                           "evaluation point (pre-statement proof stale or "
                           "absent; no unambiguous in-expression release "
                           "after the last suspension)")
        self._mark_mutated()

    def _simulate_statement(self, stmt: ast.stmt,
                            state: _PathState) -> _PathState:
        """Run a simple statement's event stream against the path state.

        The event walker provides suspensions, releases, and mutations in
        conservative evaluation order with an ambiguity flag, so this is
        where all intra-statement semantics live: a suspension resets the
        proof, only a DEFINITELY executed (unambiguous) release establishes
        one — a release in a conditional branch, short-circuit tail,
        chained-comparison tail, comprehension body, or assert can never be
        promoted to a definite guarantee — and every mutation needs a valid
        proof at its own evaluation point.
        """
        rc = state.release_count
        for kind, node, ambiguous in self._expr_events(stmt):
            if kind == "suspend":
                rc = 0
            elif kind == "release":
                if ambiguous:
                    self._flag("release-in-guard-expression", node,
                               "a conditionally executed release cannot "
                               "establish a definite guarantee")
                else:
                    if rc >= 1:
                        self._flag("release-not-exactly-once", node,
                                   "path executes the release more than "
                                   "once")
                    rc += 1
            elif kind == "mutate":
                if rc < 1:
                    self._flag("mutation-without-release-on-path", node,
                               "no valid release guarantee at this "
                               "mutation's evaluation point (proof stale, "
                               "absent, or only conditionally established)")
                self._mark_mutated()
        return _PathState(rc, state.terminated)

    def _run_stmt(self, stmt: ast.stmt, state: _PathState) -> _PathState:
        if not isinstance(stmt, self._COMPOUND):
            state = self._simulate_statement(stmt, state)

        if isinstance(stmt, (ast.Return,)):
            if (self.strict_guards and state.release_count > 0
                    and not self._reached_mutation):
                self._flag("release-on-noop-path", stmt,
                           "early-return guard path executed the release")
            return _PathState(state.release_count, terminated=True)
        if isinstance(stmt, ast.Raise):
            return _PathState(state.release_count, terminated=True)

        if isinstance(stmt, ast.If):
            if self._contains(stmt.test, self.mutation_lines):
                self._check_mutation_in_expr(stmt.test, stmt.test, state)
            if self._contains(stmt.test, self.release_lines):
                self._flag("release-in-guard-expression", stmt,
                           "release inside a condition is unverifiable")
            entry_count = (0 if self._suspends(stmt.test)
                           else state.release_count)
            then_state = self._run_block(stmt.body, _PathState(
                entry_count, state.terminated))
            else_state = self._run_block(stmt.orelse, _PathState(
                entry_count, state.terminated))
            return self._join(then_state, else_state)

        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            head_expr = (stmt.test if isinstance(stmt, ast.While)
                         else stmt.iter)
            if self._contains(head_expr, self.mutation_lines):
                self._check_mutation_in_expr(head_expr, head_expr, state)
            if self._contains(stmt, self.release_lines):
                # a release inside a loop body executes per iteration
                for inner in ast.walk(stmt):
                    if (isinstance(inner, ast.Call)
                            and isinstance(inner.func, ast.Attribute)
                            and inner.func.attr == RELEASE_CALL):
                        self._flag("release-not-exactly-once", inner,
                                   "release inside a loop executes once per "
                                   "iteration")
            head = (stmt.test if isinstance(stmt, ast.While) else stmt.iter)
            entry_count = state.release_count
            if isinstance(stmt, ast.AsyncFor) or self._suspends(head):
                entry_count = 0  # each iteration resumes from a suspension
            target = getattr(stmt, "target", None)
            if target is not None and self._contains(
                    target, self.mutation_lines):
                # the loop target assigns per element AFTER the (possibly
                # suspending) iteration step
                self._check_mutation_in_expr(
                    target, target, _PathState(entry_count, False))
            body_state = self._run_block(stmt.body, _PathState(
                entry_count, state.terminated))
            self._run_block(stmt.orelse, _PathState(
                entry_count, state.terminated))
            # loop may run zero times: fall-through keeps the entry count
            return _PathState(min(entry_count, body_state.release_count),
                              state.terminated)

        if isinstance(stmt, ast.Match):
            # match/case is not path-modeled: fail closed on any release or
            # mutation inside it rather than guessing case coverage.
            if self._contains(stmt, self.release_lines):
                self._flag("release-in-unmodeled-construct", stmt,
                           "release inside a match statement is "
                           "unverifiable")
            if self._contains(stmt, self.mutation_lines):
                self._check_mutation_in_expr(stmt, stmt, state)
            if self._suspends(stmt):
                return _PathState(0, state.terminated)
            return state

        if isinstance(stmt, self._TRY_TYPES):
            entry = _PathState(state.release_count, state.terminated)
            body_state = self._run_block(stmt.body, _PathState(
                entry.release_count, entry.terminated))
            handler_states: list[_PathState] = []
            for handler in stmt.handlers:
                # exception may fire before any release inside the body
                handler_states.append(self._run_block(handler.body, _PathState(
                    entry.release_count, entry.terminated)))
            else_state = (self._run_block(stmt.orelse, body_state)
                          if stmt.orelse else body_state)
            # a handler that falls through CONTINUES after the try: join it
            merged = else_state
            for handler_state in handler_states:
                merged = self._join(merged, handler_state)
            if stmt.finalbody:
                # finally runs on every path, including the propagating
                # exception (which may have fired before any release in the
                # body): analyze it with the pessimistic minimum.
                candidates = [entry.release_count]
                for fall in [body_state, else_state, *handler_states]:
                    if not fall.terminated:
                        candidates.append(fall.release_count)
                final_state = self._run_block(
                    stmt.finalbody, _PathState(min(candidates), False))
                return _PathState(final_state.release_count,
                                  merged.terminated or final_state.terminated)
            return merged

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            entry_count = state.release_count
            for item in stmt.items:
                if self._contains(item.context_expr, self.mutation_lines):
                    self._check_mutation_in_expr(
                        item.context_expr, item.context_expr,
                        _PathState(entry_count, False))
                if (isinstance(stmt, ast.AsyncWith)
                        or self._suspends(item.context_expr)):
                    entry_count = 0  # __(a)enter__ suspends before binding
                if (item.optional_vars is not None and self._contains(
                        item.optional_vars, self.mutation_lines)):
                    # the as-target assigns AFTER the context manager (and
                    # any suspension) ran
                    self._check_mutation_in_expr(
                        item.optional_vars, item.optional_vars,
                        _PathState(entry_count, False))
            return self._run_block(stmt.body, _PathState(
                entry_count, state.terminated))

        return state

    def _mark_mutated(self) -> None:
        self._reached_mutation = True

    def _join(self, a: _PathState, b: _PathState) -> _PathState:
        if a.terminated and b.terminated:
            return _PathState(0, terminated=True)
        if a.terminated:
            return b
        if b.terminated:
            return a
        return _PathState(min(a.release_count, b.release_count), False)


def check_release_ordering(audit: OwnershipAudit,
                           strict_guards: frozenset | set | None = None,
                           ) -> list[Finding]:
    strict = (STRICT_GUARD_FUNCTIONS if strict_guards is None
              else set(strict_guards))
    findings: list[Finding] = []
    for name in sorted(audit.boundary_functions):
        facts = audit.function_facts.get(name)
        if facts is None or not isinstance(
                facts.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            findings.append(Finding("boundary-missing", name, 0,
                                    "boundary function not found in adapter"))
            continue
        if not facts.release_linenos:
            findings.append(Finding("release-missing", name, 0,
                                    f"no {RELEASE_CALL}() call"))
            continue
        analyzer = _PathAnalyzer(facts.node, facts,
                                 strict_guards=name in strict)
        findings.extend(analyzer.run())
    return findings


def audit_findings(source: str, *, ordering: bool = False) -> list[Finding]:
    audit = OwnershipAudit(source)
    findings = classify(audit)
    if ordering:
        findings += check_release_ordering(audit)
    return findings


def ordering_findings(source: str) -> list[Finding]:
    """Path-ordering findings for ONLY the boundary functions present."""
    audit = OwnershipAudit(source)
    present = {n for n in BOUNDARY_FUNCTIONS if n in audit.function_facts
               and isinstance(audit.function_facts[n].node,
                              (ast.FunctionDef, ast.AsyncFunctionDef))}
    findings: list[Finding] = []
    for name in sorted(present):
        facts = audit.function_facts[name]
        if not facts.release_linenos:
            findings.append(Finding("release-missing", name, 0,
                                    f"no {RELEASE_CALL}() call"))
            continue
        analyzer = _PathAnalyzer(facts.node, facts,
                                 strict_guards=name in STRICT_GUARD_FUNCTIONS)
        findings.extend(analyzer.run())
    return findings


# ── the enforcing audit over production code ─────────────────────────────


PRODUCTION_BOUNDARY_OWNER = "OvRtxRendererAdapter"


def test_openusd_adapter_ownership_audit_passes() -> None:
    audit = OwnershipAudit(OPENUSD_ADAPTER.read_text(),
                           boundary_owner=PRODUCTION_BOUNDARY_OWNER)
    findings = classify(audit) + check_release_ordering(audit)
    assert not findings, "ownership audit violations:\n" + "\n".join(
        str(f) for f in findings)
    # boundary identity: every ordering proof belongs to the actual
    # production adapter, not merely to something sharing the name
    for name in sorted(BOUNDARY_FUNCTIONS):
        facts = audit.function_facts.get(name)
        assert facts is not None, f"boundary '{name}' not registered"
        assert facts.owner == PRODUCTION_BOUNDARY_OWNER, (
            f"boundary '{name}' owned by '{facts.owner}'")


# The OVStage BORROW adapter now ships the same depth-one overlap. Its
# native-mutation boundaries differ from the OpenUSD adapter's:
OVSTAGE_BOUNDARY_FUNCTIONS = {
    "load_stage",                            # attach_ovstage
    "shutdown",                              # detach + renderer teardown
    "_remove_scene",                         # detach_ovstage
    "_apply_resolution",                     # renderer reset
    "_configure_selection_outline_styles",   # set_selection_group_styles
    # Renderer reset that activates the selection-outline pass: fires at
    # most once per armed epoch (fresh attach / empty-membership resolution
    # reset), only from set_selection_highlight after a successful nonempty
    # membership write, and releases retained output first like every other
    # reset. It mutates renderer-owned activation state only — never the
    # borrowed stage.
    "_ensure_selection_outline_pass_active",
}

# Boundary functions whose no-op/validation guard paths must NOT release
# (per-frame resolution no-ops and the latched style configurator stay free).
OVSTAGE_STRICT_GUARD_FUNCTIONS = {
    "_apply_resolution",
    "_configure_selection_outline_styles",
    "_remove_scene",
    # Disarmed/armed-but-unavailable guard paths run per selection sync and
    # must stay release-free; only the actual reset path releases.
    "_ensure_selection_outline_pass_active",
}

# Reviewed read-only allowances specific to the OVStage adapter file:
# validate_ovrtx_borrow_renderer only PROBES required callables on the
# handle (runtime_preflight), and the constructor logs the getattr-bound
# ``version``/``config`` metadata values in an f-string.
OVSTAGE_SAFE_HELPER_CALLEES = {"validate_ovrtx_borrow_renderer"}
OVSTAGE_READONLY_CAPABILITIES = {"version", "config"}

OVSTAGE_BOUNDARY_OWNER = "OvstageRendererAdapter"


def _ovstage_audit() -> OwnershipAudit:
    return OwnershipAudit(
        OVSTAGE_ADAPTER.read_text(),
        boundary_owner=OVSTAGE_BOUNDARY_OWNER,
        boundary_functions=OVSTAGE_BOUNDARY_FUNCTIONS,
        safe_helper_callees=OVSTAGE_SAFE_HELPER_CALLEES,
        readonly_capability_names=OVSTAGE_READONLY_CAPABILITIES,
    )


def test_ovstage_adapter_ownership_audit_passes() -> None:
    audit = _ovstage_audit()
    findings = classify(audit) + check_release_ordering(
        audit, strict_guards=OVSTAGE_STRICT_GUARD_FUNCTIONS)
    assert not findings, "ovstage ownership audit violations:\n" + "\n".join(
        str(f) for f in findings)
    for name in sorted(OVSTAGE_BOUNDARY_FUNCTIONS):
        facts = audit.function_facts.get(name)
        assert facts is not None, f"ovstage boundary '{name}' not registered"
        assert facts.owner == OVSTAGE_BOUNDARY_OWNER, (
            f"ovstage boundary '{name}' owned by '{facts.owner}'")


def test_ovstage_overlap_is_opt_in_and_gated() -> None:
    source = OVSTAGE_ADAPTER.read_text()
    # render_frame stays synchronous until the frame loop opts in, and the
    # shared single-mapping consumers gate the overlap back off.
    assert "def set_ldr_overlap_enabled" in source
    assert "self._ldr_overlap: Optional[LdrOverlapState] = None" in source
    assert "_ldr_overlap_env_enabled()" in source
    assert "def _ldr_overlap_allowed" in source


def test_ovstage_mutation_sites_are_pinned() -> None:
    audit = OwnershipAudit(OVSTAGE_ADAPTER.read_text())
    mutating = sorted({
        (function, method)
        for function, _lineno, method in audit.calls
        if method in MUTATING_CALLS
    })
    assert mutating == [
        ("_apply_resolution", "reset"),
        ("_configure_selection_outline_styles", "set_selection_group_styles"),
        ("_ensure_selection_outline_pass_active", "reset"),
        ("_remove_scene", "detach_ovstage"),
        ("load_stage", "attach_ovstage"),
    ], f"unreviewed OVStage mutation sites: {mutating}"


# ── negative self-tests: every rejection class fires ─────────────────────


def _kinds(source: str) -> set[str]:
    return {f.kind for f in audit_findings(source)}


def test_rejects_property_read_escape() -> None:
    assert "attribute-load" in _kinds(
        "def f(self):\n    return self._renderer.some_property\n")


def test_rejects_bound_method_alias() -> None:
    assert "attribute-load" in _kinds(
        "def f(self):\n    op = self._renderer.reset\n    op()\n")


def test_rejects_annotated_capability_binding_untracked_invocation() -> None:
    kinds_and = audit_findings(
        "def f(self):\n"
        "    op: object = getattr(self._renderer, 'reset', None)\n"
        "    if op is not None:\n"
        "        op()\n")
    # binding is tracked; the invocation is a mutation outside a boundary
    assert any(f.kind == "mutation-outside-boundary" for f in kinds_and)


def test_rejects_lambda_capture() -> None:
    assert "unclassified-use" in _kinds(
        "def f(self):\n    fn = lambda: self._renderer\n")


def test_rejects_default_argument_capture() -> None:
    kinds = _kinds(
        "def f(self):\n"
        "    def g(r=self._renderer):\n"
        "        return 1\n")
    assert "unclassified-use" in kinds


def test_rejects_list_escape() -> None:
    assert "unclassified-use" in _kinds(
        "def f(self):\n    xs = [self._renderer]\n")


def test_rejects_dict_escape() -> None:
    assert "unclassified-use" in _kinds(
        "def f(self):\n    d = {'r': self._renderer}\n")


def test_rejects_yield_escape() -> None:
    assert "unclassified-use" in _kinds(
        "def f(self):\n    yield self._renderer\n")


def test_rejects_subscript_store_escape() -> None:
    assert "handle-escape" in _kinds(
        "def f(self, cache):\n    cache[0] = self._renderer\n")


def test_rejects_attribute_delete() -> None:
    assert "attribute-delete" in _kinds(
        "def f(self):\n    del self._renderer.mode\n")


def test_rejects_conditional_release_unconditional_mutation() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self, flag):\n"
        "    if flag:\n"
        "        self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_rejects_release_only_in_one_branch() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self, flag):\n"
        "    if flag:\n"
        "        self._release_retained_output()\n"
        "    else:\n"
        "        pass\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_accepts_release_in_both_branches() -> None:
    findings = ordering_findings(
        "def _reinject_session_layer(self, flag):\n"
        "    if flag:\n"
        "        self._release_retained_output()\n"
        "    else:\n"
        "        self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n")
    assert not any(f.kind == "mutation-without-release-on-path"
                   for f in findings)


def test_rejects_double_release_on_path() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "release-not-exactly-once" in kinds


def test_rejects_release_inside_loop() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _remove_live_resync_layers(self):\n"
        "    for h in self._handles:\n"
        "        self._release_retained_output()\n"
        "        self._renderer.remove_usd(h)\n")}
    assert "release-not-exactly-once" in kinds


def test_rejects_mutation_in_exception_handler_without_release() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    try:\n"
        "        x = 1\n"
        "        self._release_retained_output()\n"
        "    except Exception:\n"
        "        self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_rejects_release_on_noop_guard_path() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _configure_selection_outline_styles(self):\n"
        "    self._release_retained_output()\n"
        "    if self._selection_outline_styles_configured:\n"
        "        return\n"
        "    self._renderer.set_selection_group_styles({})\n")}
    assert "release-on-noop-path" in kinds


def test_rejects_unclassified_native_call() -> None:
    assert "unclassified-call" in _kinds(
        "def f(self):\n    self._renderer.brand_new_method()\n")


def test_rejects_mutation_outside_boundary() -> None:
    assert "mutation-outside-boundary" in _kinds(
        "def not_a_boundary(self):\n    self._renderer.reset()\n")


def test_rejects_attribute_write_and_aliased_write() -> None:
    assert "attribute-write" in _kinds(
        "def f(self):\n    self._renderer.flag = True\n")
    assert "attribute-write" in _kinds(
        "def f(self):\n    r = self._renderer\n    r.flag = True\n")
    assert "attribute-write" in _kinds(
        "def f(self):\n    self._renderer.counter += 1\n")


def test_rejects_escape_to_helper_and_keyword() -> None:
    assert "handle-escape" in _kinds(
        "def f(self):\n    helper(self._renderer)\n")
    assert "handle-escape" in _kinds(
        "def f(self):\n    helper(renderer=self._renderer)\n")


def test_rejects_return_yield_from_and_await_style_escapes() -> None:
    assert "unclassified-use" in _kinds(
        "def f(self):\n    return self._renderer\n")
    assert "unclassified-use" in _kinds(
        "def f(self):\n    yield from [self._renderer]\n") or \
        "unclassified-use" in _kinds(
        "def f(self):\n    xs = [self._renderer]\n    yield from xs\n")
    assert "unclassified-use" in _kinds(
        "async def f(self):\n    return self._renderer\n")


def test_rejects_comprehension_and_conditional_expression_escape() -> None:
    assert "unclassified-use" in _kinds(
        "def f(self):\n    xs = [self._renderer for _ in range(2)]\n")
    assert "unclassified-use" in _kinds(
        "def f(self, other):\n    r = self._renderer if other else None\n")
    assert "unclassified-use" in _kinds(
        "def f(self, other):\n    r = self._renderer or other\n")


def test_rejects_closure_and_walrus_alias_mutation() -> None:
    assert "mutation-outside-boundary" in _kinds(
        "def outer(self):\n"
        "    r = self._renderer\n"
        "    def inner():\n"
        "        r.reset()\n"
        "    inner()\n")
    assert "mutation-outside-boundary" in _kinds(
        "def f(self):\n    (r := self._renderer).reset()\n")


def test_rejects_dynamic_getattr() -> None:
    assert "dynamic-access" in _kinds(
        "def f(self, name):\n    getattr(self._renderer, name)()\n")


def test_rejects_class_callable_mutation() -> None:
    assert "mutation-outside-boundary" in _kinds(
        "def f(self):\n    type(self._renderer).reset(self._renderer)\n")


def test_rejects_capability_bound_name_escape() -> None:
    assert "capability-escape" in _kinds(
        "def f(self):\n"
        "    op = getattr(self._renderer, 'reset', None)\n"
        "    return op\n")


def test_accepts_identity_check_and_field_management() -> None:
    findings = audit_findings(
        "def f(self):\n"
        "    if self._renderer is None:\n"
        "        return\n"
        "    self._renderer = None\n")
    assert not findings


# ── second-review matrix: scope storage ───────────────────────────────────


def test_rejects_global_handle_storage() -> None:
    assert "handle-escape" in _kinds(
        "def f(self):\n"
        "    global G\n"
        "    G = self._renderer\n")


def test_rejects_nonlocal_handle_storage() -> None:
    assert "handle-escape" in _kinds(
        "def outer(self):\n"
        "    g = None\n"
        "    def inner():\n"
        "        nonlocal g\n"
        "        g = self._renderer\n"
        "    inner()\n")


def test_rejects_global_capability_binding() -> None:
    assert "capability-escape" in _kinds(
        "def f(self):\n"
        "    global OP\n"
        "    OP = getattr(self._renderer, 'reset', None)\n")


def test_rejects_global_walrus_storage() -> None:
    assert "handle-escape" in _kinds(
        "def f(self):\n"
        "    global G\n"
        "    if (G := self._renderer) is not None:\n"
        "        pass\n")


# ── second-review matrix: implicit native protocol ────────────────────────


def test_rejects_context_manager_protocol() -> None:
    assert "implicit-protocol" in _kinds(
        "def f(self):\n    with self._renderer:\n        pass\n")
    assert "implicit-protocol" in _kinds(
        "def f(self):\n    with self._renderer as r:\n        pass\n")
    assert "implicit-protocol" in _kinds(
        "async def f(self):\n"
        "    async with self._renderer:\n        pass\n")


def test_rejects_iteration_protocol() -> None:
    assert _kinds("def f(self):\n    for x in self._renderer:\n        pass\n")
    assert _kinds(
        "async def f(self):\n"
        "    async for x in self._renderer:\n        pass\n")


def test_rejects_subscript_truthiness_format_and_operators() -> None:
    assert _kinds("def f(self):\n    return self._renderer[0]\n")
    assert _kinds("def f(self):\n    if self._renderer:\n        pass\n")
    assert _kinds("def f(self):\n    return not self._renderer\n")
    assert _kinds("def f(self):\n    return f'{self._renderer}'\n")
    assert _kinds("def f(self):\n    return self._renderer == object()\n")
    assert _kinds("def f(self, x):\n    return x in self._renderer\n")


def test_rejects_str_coercion_escape() -> None:
    assert "handle-escape" in _kinds(
        "def f(self):\n    return str(self._renderer)\n")


# ── second-review matrix: exceptional control flow ────────────────────────


def test_rejects_handler_fallthrough_bypassing_release() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    try:\n"
        "        self._release_retained_output()\n"
        "    except Exception:\n"
        "        pass\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_rejects_mutation_in_finally_without_entry_release() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    try:\n"
        "        self._release_retained_output()\n"
        "    finally:\n"
        "        self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_accepts_release_before_try_with_mutation_in_finally() -> None:
    findings = ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    try:\n"
        "        pass\n"
        "    finally:\n"
        "        self._renderer.remove_usd(1)\n")
    assert not any(f.kind == "mutation-without-release-on-path"
                   for f in findings)


def test_rejects_mutation_after_try_when_only_body_released() -> None:
    # the handler swallows the exception and continues past the try with
    # the release possibly skipped: the fall-through join must catch it
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self, usda):\n"
        "    try:\n"
        "        self._validate(usda)\n"
        "        self._release_retained_output()\n"
        "    except ValueError:\n"
        "        self._log()\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_accepts_handler_that_terminates_before_mutation() -> None:
    findings = ordering_findings(
        "def _reinject_session_layer(self, usda):\n"
        "    try:\n"
        "        self._release_retained_output()\n"
        "    except Exception:\n"
        "        return\n"
        "    self._renderer.remove_usd(1)\n")
    assert not any(f.kind == "mutation-without-release-on-path"
                   for f in findings)


# ── second-review matrix: suspension points ───────────────────────────────


def test_rejects_mutation_after_yield() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    yield 1\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_rejects_mutation_after_yield_from_and_await() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self, gen):\n"
        "    self._release_retained_output()\n"
        "    yield from gen\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds
    kinds = {f.kind for f in ordering_findings(
        "async def _reinject_session_layer(self, fut):\n"
        "    self._release_retained_output()\n"
        "    await fut\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_rejects_mutation_after_async_iteration() -> None:
    kinds = {f.kind for f in ordering_findings(
        "async def _reinject_session_layer(self, items):\n"
        "    self._release_retained_output()\n"
        "    async for _ in items:\n"
        "        pass\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_accepts_fresh_release_after_suspension() -> None:
    findings = ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    yield 1\n"
        "    self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n")
    assert not any(f.kind in ("mutation-without-release-on-path",
                              "release-not-exactly-once")
                   for f in findings)


# ── second-review matrix: deferred execution ──────────────────────────────


def test_rejects_deferred_mutation_in_generator_expression() -> None:
    assert "deferred-native-call" in _kinds(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    g = (self._renderer.reset() for _ in range(1))\n"
        "    return g\n")


def test_rejects_returned_generator_with_deferred_mutation() -> None:
    kinds = _kinds(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    def gen():\n"
        "        yield 1\n"
        "        self._renderer.remove_usd(1)\n"
        "    return gen()\n")
    assert "deferred-native-call" in kinds


def test_rejects_nested_def_spoofing_boundary_name() -> None:
    # the nested function's NAME matches a boundary; without scope
    # eligibility its mutation would launder through the name check
    kinds = _kinds(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    def shutdown():\n"
        "        self._renderer.remove_usd(1)\n"
        "    return shutdown\n")
    assert "deferred-native-call" in kinds


def test_rejects_deferred_exempt_call_in_lambda() -> None:
    # even audited-exempt names defer past the proof when wrapped
    assert "deferred-native-call" in _kinds(
        "def f(self):\n"
        "    cb = lambda: self._renderer.step(render_products=[],"
        " delta_time=0.0)\n"
        "    return cb\n")


# ── second-review matrix: shadowing false-positive reductions ─────────────


def test_accepts_parameter_shadowing_of_alias_name() -> None:
    findings = audit_findings(
        "def f(self):\n"
        "    r = self._renderer\n"
        "    if r is None:\n"
        "        return\n"
        "    def helper(r):\n"
        "        return r\n"
        "    helper(1)\n")
    assert not findings


def test_accepts_comprehension_target_shadowing_alias_name() -> None:
    findings = audit_findings(
        "def f(self, items):\n"
        "    r = self._renderer\n"
        "    if r is None:\n"
        "        return\n"
        "    xs = [r for r in items]\n"
        "    return xs\n")
    assert not findings


def test_rejects_exception_group_handler_fallthrough() -> None:
    # except* (TryStar) must get the same exceptional-flow treatment
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    try:\n"
        "        self._release_retained_output()\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    self._renderer.remove_usd(1)\n")}
    assert "mutation-without-release-on-path" in kinds


def test_rejects_release_inside_match_statement() -> None:
    kinds = {f.kind for f in ordering_findings(
        "def _reinject_session_layer(self, mode):\n"
        "    match mode:\n"
        "        case 'a':\n"
        "            self._release_retained_output()\n"
        "        case _:\n"
        "            pass\n"
        "    self._renderer.remove_usd(1)\n")}
    assert ("release-in-unmodeled-construct" in kinds
            or "mutation-without-release-on-path" in kinds)


def test_rejects_class_attribute_storage() -> None:
    assert "handle-escape" in _kinds(
        "def f(self):\n"
        "    class Holder:\n"
        "        r = self._renderer\n"
        "    return Holder\n")


def test_rejects_dynamic_code_execution() -> None:
    assert "dynamic-code" in _kinds(
        "def f(self):\n    exec('self._renderer.reset()')\n")
    assert "dynamic-code" in _kinds(
        "def f(self):\n    return eval('self._renderer')\n")


# ── final-review matrix: suspension ordering WITHIN one expression ────────


ORDER = "mutation-without-release-on-path"


def _order_kinds(source: str) -> set[str]:
    return {f.kind for f in ordering_findings(source)}


def test_rejects_await_before_mutation_in_tuple() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    x = (await p, self._renderer.remove_usd(1))\n")


def test_rejects_await_before_mutation_in_short_circuit() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    ok = await p and self._renderer.remove_usd(1)\n")


def test_rejects_yield_before_mutation_in_boolean_expression() -> None:
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    ok = (yield) or self._renderer.remove_usd(1)\n")


def test_rejects_async_comprehension_mutation() -> None:
    # the async iteration suspends before (and between) elt evaluations
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, hs):\n"
        "    self._release_retained_output()\n"
        "    xs = [self._renderer.remove_usd(h) async for h in hs]\n")


def test_rejects_async_comprehension_suspending_filter() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, hs, p):\n"
        "    self._release_retained_output()\n"
        "    xs = [self._renderer.remove_usd(h)\n"
        "          for h in hs if await p(h)]\n")


def test_rejects_suspension_before_mutation_in_call_arguments() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    helper(await p, self._renderer.remove_usd(1))\n")
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    helper(a=await p, b=self._renderer.remove_usd(1))\n")


def test_rejects_suspension_before_mutation_in_fstring_dict_subscript() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    s = f'{await p}{self._renderer.remove_usd(1)}'\n")
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    d = {await p: self._renderer.remove_usd(1)}\n")
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, data):\n"
        "    self._release_retained_output()\n"
        "    x = data[await p] + self._renderer.remove_usd(1)\n")


def test_rejects_suspension_in_comparison_and_conditional_expression() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    ok = (await p) == self._renderer.remove_usd(1)\n")
    # IfExp evaluates its test FIRST: the suspension precedes the mutation
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    x = self._renderer.remove_usd(1) if await p else None\n")


def test_rejects_suspension_before_mutation_via_named_expression() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    x = ((y := await p), self._renderer.remove_usd(1))\n")


def test_rejects_suspension_before_mutation_in_if_head() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    if await p and self._renderer.remove_usd(1):\n"
        "        pass\n")


def test_rejects_suspension_before_mutation_in_return_value() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    return (await p, self._renderer.remove_usd(1))\n")


def test_accepts_mutation_evaluated_before_suspension() -> None:
    # provable order: the mutation's arguments and the call itself evaluate
    # before the await — the pre-statement release proof is still valid
    findings = ordering_findings(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    x = (self._renderer.remove_usd(1), await p)\n")
    assert not any(f.kind == ORDER for f in findings)


def test_accepts_fresh_release_statement_after_suspension_still() -> None:
    findings = ordering_findings(
        "def _reinject_session_layer(self):\n"
        "    yield 1\n"
        "    self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n")
    assert not any(f.kind in (ORDER, "release-not-exactly-once")
                   for f in findings)


# ── final-review matrix: nested-class boundary spoofing ───────────────────


def test_rejects_nested_class_method_spoofing_boundary() -> None:
    kinds = _kinds(
        "def real_method(self):\n"
        "    class Fake:\n"
        "        def shutdown(self):\n"
        "            self._renderer.remove_usd(1)\n"
        "    return Fake\n")
    assert "deferred-native-call" in kinds


def test_rejects_class_in_class_method_spoofing_boundary() -> None:
    kinds = _kinds(
        "class Adapter:\n"
        "    class Inner:\n"
        "        def shutdown(self):\n"
        "            self._renderer.remove_usd(1)\n")
    assert "deferred-native-call" in kinds


def test_rejects_async_and_decorated_nested_class_spoofs() -> None:
    assert "deferred-native-call" in _kinds(
        "def real_method(self):\n"
        "    class Fake:\n"
        "        async def shutdown(self):\n"
        "            self._renderer.remove_usd(1)\n"
        "    return Fake\n")
    assert "deferred-native-call" in _kinds(
        "def real_method(self):\n"
        "    class Fake:\n"
        "        @staticmethod\n"
        "        def _reinject_session_layer():\n"
        "            self._renderer.remove_usd(1)\n"
        "    return Fake\n")


def test_rejects_deeply_nested_boundary_spoofs() -> None:
    assert "deferred-native-call" in _kinds(
        "class Top:\n"
        "    def real_method(self):\n"
        "        class Mid:\n"
        "            class Deep:\n"
        "                def load_stage(self):\n"
        "                    self._renderer.remove_usd(1)\n"
        "        return Mid\n")


def test_nested_class_method_cannot_claim_ordering_facts() -> None:
    # a spoofed nested-class `shutdown` must not register as the boundary:
    # classification rejects it and ordering does not treat it as present
    source = (
        "def real_method(self):\n"
        "    class Fake:\n"
        "        def shutdown(self):\n"
        "            self._renderer.remove_usd(1)\n"
        "    return Fake\n")
    assert "deferred-native-call" in _kinds(source)
    assert not any(f.kind == "release-missing"
                   for f in ordering_findings(source))


def test_direct_methods_of_toplevel_class_still_qualify() -> None:
    findings = ordering_findings(
        "class Adapter:\n"
        "    def _reinject_session_layer(self):\n"
        "        self._release_retained_output()\n"
        "        self._renderer.remove_usd(1)\n")
    assert not findings


# ── final-gap matrix: annotated-assignment evaluation order ───────────────


def test_rejects_annassign_value_suspends_before_target_mutation() -> None:
    # CPython evaluates the VALUE first: the await suspends before the
    # target subscript performs the native mutation
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, d):\n"
        "    self._release_retained_output()\n"
        "    d[self._renderer.remove_usd(1)]: int = await p\n")
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, d):\n"
        "    self._release_retained_output()\n"
        "    d[self._renderer.remove_usd(1)]: int = (yield)\n")


def test_rejects_annassign_suspension_inside_value_before_mutation() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    self._release_retained_output()\n"
        "    x: tuple = (await p, self._renderer.remove_usd(1))\n")


def test_rejects_destructuring_target_mutation_after_value_suspension() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, d):\n"
        "    self._release_retained_output()\n"
        "    a, d[self._renderer.remove_usd(1)] = await p\n")


def test_accepts_augassign_target_index_before_value_suspension() -> None:
    # `d[k] += v` evaluates the target index BEFORE the value: the
    # mutation runs under the still-valid pre-statement proof
    findings = ordering_findings(
        "async def _reinject_session_layer(self, p, d):\n"
        "    self._release_retained_output()\n"
        "    d[self._renderer.remove_usd(1)] += await p\n")
    assert not any(f.kind == ORDER for f in findings)


# ── final-gap matrix: provable fresh release within one expression ────────


def test_accepts_unambiguous_fresh_release_after_suspension_in_expr() -> None:
    findings = ordering_findings(
        "async def _reinject_session_layer(self, p):\n"
        "    x = (await p, self._release_retained_output(),\n"
        "         self._renderer.remove_usd(1))\n")
    assert not any(f.kind == ORDER for f in findings)


def test_rejects_conditional_release_after_suspension_in_expr() -> None:
    # a release that may not execute cannot re-establish the guarantee
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, q):\n"
        "    x = (await p,\n"
        "         self._release_retained_output() if q else 0,\n"
        "         self._renderer.remove_usd(1))\n")


def test_rejects_short_circuited_release_after_suspension_in_expr() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, q):\n"
        "    x = (await p,\n"
        "         q and self._release_retained_output(),\n"
        "         self._renderer.remove_usd(1))\n")


def test_rejects_release_before_suspension_then_mutation_in_expr() -> None:
    # the in-expression release is consumed by the LATER suspension
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p):\n"
        "    x = (self._release_retained_output(), await p,\n"
        "         self._renderer.remove_usd(1))\n")


def test_rejects_mutation_in_suspending_binding_targets() -> None:
    # `async with ... as <target>` binds AFTER __aenter__ awaited
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, acm, d):\n"
        "    self._release_retained_output()\n"
        "    async with acm as d[self._renderer.remove_usd(1)]:\n"
        "        pass\n")
    # `async for <target> in ...` binds AFTER the iteration step awaited
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, it, d):\n"
        "    self._release_retained_output()\n"
        "    async for d[self._renderer.remove_usd(1)] in it:\n"
        "        pass\n")
    # an async comprehension's target binds after each awaited step
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, it, d):\n"
        "    self._release_retained_output()\n"
        "    xs = [0 async for d[self._renderer.remove_usd(1)] in it]\n")


# ── chained-comparison / conditional-release matrix ───────────────────────


def test_rejects_release_in_chained_comparison_tail_statement_level() -> None:
    # `1 < q < (release() or 2)`: the release only runs when `1 < q` held —
    # it must not satisfy the next statement's mutation (Codex bypass)
    kinds = _order_kinds(
        "def _reinject_session_layer(self, q):\n"
        "    ok = 1 < q < (self._release_retained_output() or 2)\n"
        "    self._renderer.remove_usd(1)\n")
    assert ORDER in kinds
    assert "release-in-guard-expression" in kinds


def test_rejects_release_in_chained_comparison_tail_within_expression() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, q):\n"
        "    x = (await p, 1 < q < (self._release_retained_output() or 2),\n"
        "         self._renderer.remove_usd(1))\n")


def test_rejects_release_in_longer_chain_positions() -> None:
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, a, b, c):\n"
        "    ok = a < b < c < (self._release_retained_output() or 2)\n"
        "    self._renderer.remove_usd(1)\n")
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, a, b, c):\n"
        "    ok = a < b < (self._release_retained_output() or 2) < c\n"
        "    self._renderer.remove_usd(1)\n")


def test_rejects_release_in_nested_comparison_inside_conditional_tail() -> None:
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, a, b, q):\n"
        "    ok = a < b < (1 if (self._release_retained_output() is None)"
        " else 2)\n"
        "    self._renderer.remove_usd(1)\n")


def test_rejects_boolop_conditional_release_statement_level() -> None:
    # the sibling short-circuit family at statement level
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, q):\n"
        "    ok = q and self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n")
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, q):\n"
        "    ok = q or self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n")


def test_rejects_conditional_expression_release_statement_level() -> None:
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, q):\n"
        "    x = self._release_retained_output() if q else None\n"
        "    self._renderer.remove_usd(1)\n")


def test_rejects_release_in_assert_statement() -> None:
    # assert bodies vanish under -O and the message runs only on failure
    assert ORDER in _order_kinds(
        "def _reinject_session_layer(self, q):\n"
        "    assert self._release_retained_output() is None\n"
        "    self._renderer.remove_usd(1)\n")


def test_rejects_suspension_before_chain_with_trailing_mutation() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, q):\n"
        "    self._release_retained_output()\n"
        "    ok = (await p) < q < self._renderer.remove_usd(1)\n")


def test_rejects_mutation_in_chain_after_conditional_release() -> None:
    assert ORDER in _order_kinds(
        "async def _reinject_session_layer(self, p, q):\n"
        "    x = (await p,\n"
        "         q and self._release_retained_output(),\n"
        "         1 < q < self._renderer.remove_usd(1))\n")


def test_accepts_release_in_unconditional_comparison_positions() -> None:
    # Compare LEFT and the FIRST comparator always evaluate
    findings = ordering_findings(
        "def _reinject_session_layer(self, q):\n"
        "    ok = (self._release_retained_output() is None) < q\n"
        "    self._renderer.remove_usd(1)\n")
    assert not any(f.kind in (ORDER, "release-in-guard-expression")
                   for f in findings)
    findings = ordering_findings(
        "def _reinject_session_layer(self, q):\n"
        "    ok = q < (self._release_retained_output() or 2)\n"
        "    self._renderer.remove_usd(1)\n")
    assert not any(f.kind in (ORDER, "release-in-guard-expression")
                   for f in findings)


def test_accepts_definite_release_between_suspension_and_chain_mutation() -> None:
    # left suspends, first comparator releases (always evaluated), second
    # comparator mutates — IF the mutation runs, the release preceded it
    findings = ordering_findings(
        "async def _reinject_session_layer(self, p):\n"
        "    x = (await p) < self._release_retained_output()"
        " < self._renderer.remove_usd(1)\n")
    assert not any(f.kind == ORDER for f in findings)


# ── final-gap matrix: boundary identity vs same-named definitions ─────────


SPOOF_BEFORE_ADAPTER = (
    "class Spoof:\n"
    "    def shutdown(self):\n"
    "        self._renderer.remove_usd(1)\n"
    "\n"
    "class Adapter:\n"
    "    def shutdown(self):\n"
    "        self._release_retained_output()\n"
    "        self._renderer.remove_usd(1)\n")


def test_unrelated_class_cannot_satisfy_boundary_identity() -> None:
    audit = OwnershipAudit(SPOOF_BEFORE_ADAPTER, boundary_owner="Adapter")
    kinds = {f.kind for f in classify(audit)}
    assert "boundary-identity-conflict" in kinds
    # facts bind to the owner even though the spoof is defined FIRST
    assert audit.function_facts["shutdown"].owner == "Adapter"
    assert not any(f.kind == "mutation-without-release-on-path"
                   for f in check_release_ordering(audit))


def test_unrelated_class_cannot_mask_a_broken_owner_boundary() -> None:
    # the spoof is well-shaped; the REAL owner's method lacks the release —
    # ordering must analyze the owner and fail
    source = (
        "class Spoof:\n"
        "    def shutdown(self):\n"
        "        self._release_retained_output()\n"
        "        self._renderer.remove_usd(1)\n"
        "\n"
        "class Adapter:\n"
        "    def shutdown(self):\n"
        "        self._renderer.remove_usd(1)\n")
    audit = OwnershipAudit(source, boundary_owner="Adapter")
    ordering = {f.kind for f in check_release_ordering(audit)}
    assert "release-missing" in ordering
    assert any(f.kind == "boundary-identity-conflict"
               for f in classify(audit))


def test_duplicate_boundary_definitions_conflict_without_owner() -> None:
    kinds = _kinds(
        "def _reinject_session_layer(self):\n"
        "    self._release_retained_output()\n"
        "    self._renderer.remove_usd(1)\n"
        "\n"
        "class Other:\n"
        "    def _reinject_session_layer(self):\n"
        "        self._renderer.remove_usd(1)\n")
    assert "boundary-identity-conflict" in kinds


def test_subclass_override_cannot_claim_owner_identity() -> None:
    source = (
        "class Adapter:\n"
        "    def shutdown(self):\n"
        "        self._release_retained_output()\n"
        "        self._renderer.remove_usd(1)\n"
        "\n"
        "class Derived(Adapter):\n"
        "    def shutdown(self):\n"
        "        self._renderer.remove_usd(1)\n")
    audit = OwnershipAudit(source, boundary_owner="Adapter")
    assert any(f.kind == "boundary-identity-conflict"
               for f in classify(audit))
    assert audit.function_facts["shutdown"].owner == "Adapter"


def test_owner_missing_boundary_is_not_satisfied_by_other_class() -> None:
    source = (
        "class Spoof:\n"
        "    def load_stage(self):\n"
        "        self._release_retained_output()\n"
        "        self._renderer.remove_usd(1)\n"
        "\n"
        "class Adapter:\n"
        "    def unrelated(self):\n"
        "        pass\n")
    audit = OwnershipAudit(source, boundary_owner="Adapter")
    assert any(f.kind == "boundary-identity-conflict"
               for f in classify(audit))
    assert "load_stage" not in audit.function_facts


def test_comprehension_first_iterable_stays_tainted() -> None:
    # [x for x in self._renderer] iterates the handle in the ENCLOSING
    # scope — the shadowing reduction must not clear it
    assert _kinds("def f(self):\n    return [x for x in self._renderer]\n")
    assert _kinds(
        "def f(self):\n"
        "    r = self._renderer\n"
        "    if r is None:\n"
        "        return\n"
        "    return [r2 for r2 in r]\n")
