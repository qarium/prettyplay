"""The deterministic pre-flight gate of generated candidates: syntax, name resolution and the fixed step form."""

from __future__ import annotations

import ast
import builtins

#: Dunders exempted by name analysis — not a guarantee of runtime availability.
#: exec supplies __builtins__; __file__ is absent unless candidate code binds it.
_NAMESPACE_DUNDERS = frozenset({"__builtins__", "__name__", "__file__", "__doc__"})

#: The builtins visible to step code.
_BUILTINS = frozenset(dir(builtins))


def check_step_code(code: str) -> str | None:  # noqa: PLR0911 — one return per violation kind, the validation chain is flat by design
    """Check a generated candidate deterministically before any browser execution.

    Args:
        code: the complete candidate code fresh from the provider.

    Returns:
        The violation text — the attempt record's error field; ``None`` —
        the candidate proceeds to the settle window. An unexpected
        analysis error passes the candidate: the gate fails open, the
        execution channel stays the fallback.
    """
    try:
        tree = ast.parse(code, filename="<prettyplay-preflight>")
    except SyntaxError as error:
        return f"preflight violation: the code does not compile — {error.msg} (line {error.lineno})"
    except Exception:
        return None

    if not any(isinstance(node, ast.FunctionDef) and node.name == "step" for node in tree.body):
        return "preflight violation: no module-level step function of the fixed form — def step(page)"

    if _imports_at_runtime(tree):
        return "preflight violation: __import__ is forbidden — imports are global only, at the top of the code block"

    if _leaks_a_route(tree):
        return "preflight violation: page.route without page.unroute — remove the route before the step ends"

    if _confirms_its_own_navigation(tree):
        return (
            "preflight violation: an expect(...) assertion after page.goto is a self-confirmation — "
            "the navigation already proves the landing; the next step carries its own expectation"
        )

    try:
        return _unused_imports(tree) or _undefined_names(tree)
    except Exception:
        return None


def _confirms_its_own_navigation(tree: ast.Module) -> bool:
    """Detect any assertion trailing the step's own navigation — the canonical self-confirmation.

    Args:
        tree: the parsed module of the candidate.

    Returns:
        True — a ``page.goto`` call precedes any ``expect(...).to_*`` matcher call in
        source order (line and column), independent of AST traversal order;
        False otherwise. An assertion step carries the expect without any goto
        and never trips; an action step ends at its action.
    """
    goto_positions: list[tuple[int, int]] = []
    expectation_positions: list[tuple[int, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_page_method(node, "goto"):
            goto_positions.append((node.lineno, node.col_offset))
        elif _is_expectation(node):
            expectation_positions.append((node.lineno, node.col_offset))

    if not goto_positions:
        return False

    first_goto = min(goto_positions)

    return any(position > first_goto for position in expectation_positions)


def _is_page_method(node: ast.Call, method: str) -> bool:
    """Match ``page.<method>(...)`` structurally — an attribute of the plain name ``page``.

    Args:
        node: the call to test.
        method: the method name to match.

    Returns:
        True — the call target is ``page.<method>``; False — any other shape.
    """
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == method
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "page"
    )


def _is_expectation(node: ast.Call) -> bool:
    """Match ``expect(...).<any matcher>(...)`` structurally — a method chained on an expect call.

    Args:
        node: the call to test.

    Returns:
        True — the call target is an attribute of a call to ``expect``; False —
        any other shape. Covers every matcher: ``to_have_url``, ``to_be_visible``,
        ``to_contain_text``, the negated forms, and anything else chained on ``expect``.
    """
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "expect"
    )


def _leaks_a_route(tree: ast.Module) -> bool:
    """Detect a route installation its own step never removes — a cached step would poison later steps.

    Args:
        tree: the parsed module of the candidate.

    Returns:
        True — a ``page.route`` call has no matching ``page.unroute`` call in the
        same module; False — every route is removed or no route is installed.
    """
    routes = unrouted = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_page_method(node, "route"):
            routes += 1
        elif _is_page_method(node, "unroute"):
            unrouted += 1

    return routes > unrouted


def _unused_imports(tree: ast.Module) -> str | None:
    """Name the imported names the code never loads — dead weight the gate would bill seconds for.

    Args:
        tree: the parsed module of the candidate.

    Returns:
        The violation text naming every unused import; ``None`` — every import is used.
    """
    imported: dict[str, int] = {}
    loaded: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loaded.add(node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported[alias.asname or alias.name.split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    imported[alias.asname or alias.name] = node.lineno

    unused = sorted((line, name) for name, line in imported.items() if name not in loaded)
    if not unused:
        return None

    clauses = ", ".join(f"'{name}' (line {line})" for line, name in unused)
    noun = "import" if len(unused) == 1 else "imports"

    return f"preflight violation: unused {noun} {clauses} — import only what the step uses"


def _imports_at_runtime(tree: ast.Module) -> bool:
    """Detect a runtime __import__ call — the fixed form allows top-level imports only.

    Args:
        tree: the parsed module of the candidate.

    Returns:
        True — the code calls ``__import__`` anywhere; False otherwise.
    """
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__"
        for node in ast.walk(tree)
    )


def _undefined_names(tree: ast.Module) -> str | None:  # noqa: C901, PLR0912 — the flat binding union walks every scope kind in one pass
    """Name loads absent from supported bindings — a flat union across scopes.

    Pattern-matching captures are not collected and can produce false positives.
    Whitelisted dunders are exemptions, not supplied execution metadata.

    Args:
        tree: the parsed module of the candidate.

    Returns:
        The violation text naming every undefined name with its first
        load line; ``None`` — every loaded name is bound somewhere, a
        builtin or a namespace dunder, or the module holds a star import
        (the bound set is unknowable, the check suspends).
    """
    bound: set[str] = set()
    loaded: dict[str, int] = {}
    star_imported = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loaded.setdefault(node.id, node.lineno)
            else:  # Store or Del — a deleted name was bound somewhere
                bound.add(node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    star_imported = True
                else:
                    bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arguments):
            bound.update(_argument_names(node))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)

    if star_imported:
        return None

    missing = sorted(
        (line, name)
        for name, line in loaded.items()
        if name not in bound and name not in _BUILTINS and name not in _NAMESPACE_DUNDERS
    )
    if not missing:
        return None

    clauses = ", ".join(f"'{name}' (line {line})" for line, name in missing)
    noun = "name" if len(missing) == 1 else "names"

    return f"preflight violation: undefined {noun} {clauses}"


def _argument_names(args: ast.arguments) -> set[str]:
    """Collect every parameter name of an arguments node.

    Args:
        args: the arguments node of a function, an async function or a lambda.

    Returns:
        The parameter names — positional, positional-only, keyword-only,
        *args and **kwargs.
    """
    names = {argument.arg for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs)}

    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)

    return names
