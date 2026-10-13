"""Tests for the deterministic pre-flight gate of the prettyplay.engine cell."""

import inspect
from unittest import mock

import pytest
from prettyplay.engine import preflight as preflight_module
from prettyplay.engine.preflight import check_step_code

VALID_CODE = (
    "import re\n"
    "\n"
    "\n"
    "def helper(value: str) -> bool:\n"
    '    return bool(re.match(r"\\d+", value))\n'
    "\n"
    "\n"
    "class Box:\n"
    '    label = "box"\n'
    "\n"
    "\n"
    "def step(page) -> None:\n"
    "    matched = [item for item in page.list_items() if helper(item)]\n"
    "    with page.dialog() as dialog:\n"
    "        try:\n"
    "            dialog.accept()\n"
    "        except RuntimeError as failure:\n"
    "            print(failure)\n"
    "    while (count := len(matched)) > 3:\n"
    "        matched.pop()\n"
    "    counted = page.apply(lambda event: event.count)\n"
    "    assert isinstance(Box(), Box) and sorted(map(str, matched)) and count >= 0 and counted\n"
)

STAR_IMPORT_CODE = "from x import *\n\n\ndef step(page) -> None:\n    mystery()\n"


class TestPreflightEmptyInputs:
    """Empty and invalid inputs exercise missing-step and fail-open behavior."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("", "preflight violation: no module-level step function of the fixed form — def step(page)"),
            (None, None),
            ([], None),
            ({}, None),
            (42, None),
        ],
    )
    def test_check_step_code_with_empty_or_invalid_input(self, code: object, expected: str | None) -> None:
        """Check empty source and invalid-input fail-open behavior."""
        assert check_step_code(code) == expected


class TestPreflightContract:
    """Contract tests: the signature of the gate routine."""

    def test_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(check_step_code).parameters.values())

        assert [parameter.name for parameter in parameters] == ["code"]


class TestPreflightPasses:
    """Logic tests: valid candidates of the generated-code subset never trip the gate."""

    def test_valid_code_passes(self) -> None:
        assert check_step_code(VALID_CODE) is None

    def test_bare_step_function_passes(self) -> None:
        assert check_step_code("def step(page) -> None:\n    page.goto('https://a.example')\n") is None

    def test_star_import_suspends_the_name_analysis(self) -> None:
        assert check_step_code(STAR_IMPORT_CODE) is None

    def test_import_alias_binds_the_alias(self) -> None:
        code = "import json as data\n\n\ndef step(page) -> None:\n    page.fill(data.dumps({}))\n"

        assert check_step_code(code) is None

    def test_namespace_dunders_pass(self) -> None:
        code = "def step(page) -> None:\n    assert __name__ and __doc__ is None\n"

        assert check_step_code(code) is None

    def test_unexpected_analysis_error_passes_the_candidate(self, monkeypatch) -> None:
        def explode(code: str, filename: str) -> object:
            raise RuntimeError("analyzer bug")

        monkeypatch.setattr(preflight_module.ast, "parse", explode)

        assert check_step_code("def step(page) -> None:\n    page.goto('x')\n") is None


class TestPreflightBlocks:
    """Logic tests: the deterministic violations of the gate."""

    def test_missing_import_is_named_with_its_line(self) -> None:
        code = "def step(page) -> None:\n    page.fill(re.compile(r'q'))\n"

        assert check_step_code(code) == "preflight violation: undefined name 're' (line 2)"

    def test_import_alias_does_not_bind_the_module_name(self) -> None:
        code = "def step(page) -> None:\n    page.fill(json.dumps({}))\n"

        assert check_step_code(code) == "preflight violation: undefined name 'json' (line 2)"

    def test_multiple_undefined_names_are_ordered_by_first_load_line(self) -> None:
        code = "def step(page) -> None:\n    alpha()\n    beta()\n"

        assert check_step_code(code) == ("preflight violation: undefined names 'alpha' (line 2), 'beta' (line 3)")

    def test_syntax_error_carries_the_message_and_line(self) -> None:
        code = "def step(page) -> None:\n    page.goto('https://a.example'\n"
        violation = check_step_code(code)

        assert violation is not None
        assert violation.startswith("preflight violation: the code does not compile —")
        assert "(line 2)" in violation

    def test_missing_step_function_is_a_violation(self) -> None:
        code = "def run(page) -> None:\n    page.goto('https://a.example')\n"

        assert check_step_code(code) == (
            "preflight violation: no module-level step function of the fixed form — def step(page)"
        )

    def test_nested_step_function_does_not_count(self) -> None:
        code = "def outer(page) -> None:\n    def step(page) -> None:\n        page.goto('https://a.example')\n"

        assert check_step_code(code) == (
            "preflight violation: no module-level step function of the fixed form — def step(page)"
        )

    def test_a_runtime_import_call_is_a_violation(self) -> None:
        code = 'def step(page) -> None:\n    expect = __import__("playwright.sync_api").expect\n    page.goto("https://a.example")\n'

        assert check_step_code(code) == (
            "preflight violation: __import__ is forbidden — imports are global only, at the top of the code block"
        )

    def test_an_unused_import_is_a_violation(self) -> None:
        code = (
            "import re\n"
            "from playwright.sync_api import expect\n"
            "\n"
            "\n"
            "def step(page) -> None:\n"
            "    page.goto('https://a.example')\n"
        )

        assert check_step_code(code) == (
            "preflight violation: unused imports 're' (line 1), 'expect' (line 2) — import only what the step uses"
        )

    def test_a_used_import_passes(self) -> None:
        code = "import re\n\n\ndef step(page) -> None:\n    page.get_by_text(re.compile(r'search', re.I)).click()\n"

        assert check_step_code(code) is None

    def test_a_route_without_its_unroute_is_a_violation(self) -> None:
        code = (
            "import re\n"
            "\n"
            "\n"
            "def step(page) -> None:\n"
            "    page.route(re.compile(r'/api/quote'), lambda route: route.fulfill(json={'price': 1}))\n"
            "    page.locator('#fetch-btn').click()\n"
        )

        assert check_step_code(code) == (
            "preflight violation: page.route without page.unroute — remove the route before the step ends"
        )

    def test_a_route_removed_inside_the_step_passes(self) -> None:
        code = (
            "import re\n"
            "\n"
            "\n"
            "def step(page) -> None:\n"
            "    page.route(re.compile(r'/api/quote'), lambda route: route.fulfill(json={'price': 1}))\n"
            "    try:\n"
            "        page.locator('#fetch-btn').click()\n"
            "    finally:\n"
            "        page.unroute(re.compile(r'/api/quote'))\n"
        )

        assert check_step_code(code) is None

    def test_a_url_assertion_trailing_the_own_goto_is_a_violation(self) -> None:
        code = (
            "import re\n"
            "from playwright.sync_api import expect\n"
            "\n"
            "\n"
            "def step(page) -> None:\n"
            "    page.goto('https://a.example')\n"
            "    expect(page).to_have_url(re.compile(r'a'))\n"
        )

        assert check_step_code(code) == (
            "preflight violation: an expect(...) assertion after page.goto is a self-confirmation — "
            "the navigation already proves the landing; the next step carries its own expectation"
        )

    def test_a_title_assertion_trailing_the_own_goto_is_a_violation(self) -> None:
        code = (
            "from playwright.sync_api import expect\n"
            "\n"
            "\n"
            "def step(page) -> None:\n"
            "    page.goto('https://a.example')\n"
            "    expect(page).to_have_title('A')\n"
        )

        assert check_step_code(code) is not None

    def test_a_visibility_assertion_trailing_the_own_goto_is_a_violation(self) -> None:
        code = (
            "from playwright.sync_api import expect\n"
            "\n"
            "\n"
            "def step(page) -> None:\n"
            "    page.goto('https://a.example')\n"
            "    expect(page.get_by_role('heading')).to_be_visible()\n"
        )

        assert check_step_code(code) is not None

    def test_a_url_assertion_without_goto_passes(self) -> None:
        code = (
            "import re\n"
            "from playwright.sync_api import expect\n"
            "\n"
            "\n"
            "def step(page) -> None:\n"
            "    expect(page).to_have_url(re.compile(r'a'))\n"
        )

        assert check_step_code(code) is None

    @pytest.mark.parametrize(
        "body",
        [
            "    try:\n        page.goto('x')\n    finally:\n        pass\n    expect(page).to_have_title('X')\n",
            "    with page.expect_response('x'):\n        page.goto('x')\n    expect(page).to_have_title('X')\n",
            "    for url in ['x']:\n        page.goto(url)\n    expect(page).to_have_title('X')\n",
            "    expect(page).to_have_title('Before')\n    page.goto('x')\n    expect(page).to_have_title('After')\n",
            "    page.goto('x'); expect(page).to_have_title('X')\n",
        ],
    )
    def test_navigation_confirmation_is_blocked_independently_of_ast_traversal_order(self, body: str) -> None:
        """Reject trailing checks regardless of nesting or shared source lines.

        Args:
            body: the source of the step function body.
        """
        code = "from playwright.sync_api import expect\ndef step(page):\n" + body

        compile(code, "<preflight-test>", "exec")

        assert check_step_code(code) == (
            "preflight violation: an expect(...) assertion after page.goto is a self-confirmation — "
            "the navigation already proves the landing; the next step carries its own expectation"
        )

    @pytest.mark.parametrize(
        "body",
        [
            "    expect(page).to_have_title('Before')\n    page.goto('x')\n",
            "    expect(page).to_have_title('Before'); page.goto('x')\n",
            "    try:\n        expect(page).to_have_title('Before')\n    finally:\n        page.goto('x')\n",
        ],
    )
    def test_expectation_before_navigation_remains_allowed(self, body: str) -> None:
        """Keep checks before navigation outside the self-confirmation rule.

        Args:
            body: the source of the step function body.
        """
        code = "from playwright.sync_api import expect\ndef step(page):\n" + body

        compile(code, "<preflight-test>", "exec")

        assert check_step_code(code) is None

    def test_an_unexpected_analysis_error_fails_open(self) -> None:
        original_walk = preflight_module.ast.walk
        calls = 0

        def walk(tree: object):
            nonlocal calls
            calls += 1

            if calls == 4:
                raise RuntimeError("the AST traversal failed")

            return original_walk(tree)

        with mock.patch.object(preflight_module.ast, "walk", side_effect=walk):
            assert check_step_code(VALID_CODE) is None
