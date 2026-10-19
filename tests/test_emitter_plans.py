"""WP4 items 4: verification plans and render refinements for the PowerShell,
SQL, prompt and runbook emitters. Plans are data; nothing here runs a tool."""
from __future__ import annotations

import dataclasses

import pytest

from soloctl.compiler.classify import SUPPORTED_LANGUAGES
from soloctl.compiler.extract import extract
from soloctl.compiler.models import ArtifactCandidate
from soloctl.emitters import EmitContext
from soloctl.emitters.base import ARTIFACT_PATH
from soloctl.emitters.bash import BashEmitter
from soloctl.emitters.powershell import (
    PSSA_SCRIPT, PWSH_PARSE_SCRIPT, PowerShellEmitter,
)
from soloctl.emitters.prompt import PromptEmitter, find_placeholders
from soloctl.emitters.python import PythonEmitter
from soloctl.emitters.runbook import RunbookEmitter
from soloctl.emitters.sql import SqlEmitter

CTX = EmitContext(source="chat:test", compiled_at="2026-10-19T12:00:00Z",
                  tool_version="0.1.0")


def cand(label: str, body: str, heading: str | None = "Ops task") -> ArtifactCandidate:
    doc = (f"## {heading}\n\n" if heading else "") + f"```{label}\n{body}\n```\n"
    r = extract(doc, source="inline.md", only=SUPPORTED_LANGUAGES)
    assert len(r.candidates) == 1, r.skipped
    return r.candidates[0]


SAMPLES = {
    "bash": (BashEmitter(), cand("bash", "echo hi")),
    "python": (PythonEmitter(), cand("python", "print(1)")),
    "powershell": (PowerShellEmitter(), cand("pwsh", "Get-Date")),
    "sql": (SqlEmitter(), cand("sql", "SELECT 1;")),
    "prompt": (PromptEmitter(), cand("prompt", "Summarize {input}.")),
    "runbook": (RunbookEmitter(), cand("md", "# Disk full\n\n1. step")),
}
WP4 = ("powershell", "sql", "prompt", "runbook")


# --------------------------------------------------------------------------
# Rules shared by every plan
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_artifact_path_is_one_whole_argv_element(name):
    emitter, c = SAMPLES[name]
    for ch in emitter.verification_plan(c).checks:
        if ch.kind == "in-process":
            assert ch.tool is None and ch.argv == ()
            continue
        assert ch.argv[0] == ch.tool and ch.argv[-1] == ARTIFACT_PATH
        assert ch.argv.count(ARTIFACT_PATH) == 1
        assert not any(ARTIFACT_PATH in a for a in ch.argv[:-1])


@pytest.mark.parametrize("name", WP4)
def test_external_checks_are_advisory(name):
    """None of pwsh, sqlfluff (or any other external tool) is a soloctl
    dependency, so no WP4 plan may require one."""
    emitter, c = SAMPLES[name]
    external = [ch for ch in emitter.verification_plan(c).checks if ch.kind == "external"]
    assert all(ch.required is False for ch in external)


@pytest.mark.parametrize("name", WP4)
def test_complete_only_with_a_required_in_process_check(name):
    emitter, c = SAMPLES[name]
    plan = emitter.verification_plan(c)
    assert plan.checks
    has_required_in_process = any(
        ch.required and ch.kind == "in-process" for ch in plan.checks)
    assert plan.complete is has_required_in_process


@pytest.mark.parametrize("name", WP4)
def test_plans_carry_risk_notes(name):
    emitter, c = SAMPLES[name]
    flagged = dataclasses.replace(c, flags=("drop", "sudo"))
    assert any(n.startswith("risk flags present (drop, sudo)")
               for n in emitter.verification_plan(flagged).notes)
    assert not any("risk flags" in n for n in emitter.verification_plan(c).notes)


# --------------------------------------------------------------------------
# PowerShell
# --------------------------------------------------------------------------
def test_powershell_plan_checks_and_incomplete_note():
    plan = PowerShellEmitter().verification_plan(cand("pwsh", "Get-Date"))
    parse, pssa = plan.checks
    assert (parse.name, parse.kind, parse.tool) == ("pwsh-parse", "external", "pwsh")
    assert parse.argv == ("pwsh", "-NoProfile", "-NonInteractive", "-CommandWithArgs",
                          PWSH_PARSE_SCRIPT, ARTIFACT_PATH)
    assert "ParseFile($args[0]" in PWSH_PARSE_SCRIPT
    assert (pssa.name, pssa.tool) == ("psscriptanalyzer", "pwsh")
    assert pssa.argv[-2:] == (PSSA_SCRIPT, ARTIFACT_PATH)
    assert "Invoke-ScriptAnalyzer -Path $args[0]" in PSSA_SCRIPT
    assert plan.complete is False and "cannot-auto-verify" in plan.notes[0]


def test_powershell_scripts_are_constants_not_artifact_content():
    hostile = cand("pwsh", "'; Remove-Item C:\\ -Recurse -Force; '\n$args[0]")
    benign = cand("pwsh", "Get-Date")
    e = PowerShellEmitter()
    assert ([ch.argv for ch in e.verification_plan(hostile).checks]
            == [ch.argv for ch in e.verification_plan(benign).checks])


def test_powershell_requires_statements_are_noted_not_moved():
    body = "#Requires -Version 7.2\n#requires -RunAsAdministrator\nGet-Date"
    c = cand("pwsh", body)
    e = PowerShellEmitter()
    assert e.requires(c) == ("-Version 7.2", "-RunAsAdministrator")
    assert e.verification_plan(c).notes[1] == (
        "declares #Requires -Version 7.2; -RunAsAdministrator (not checked by parsing)")
    assert e.render(c, CTX).endswith("\n" + body + "\n")
    assert len(e.verification_plan(cand("pwsh", "Get-Date")).notes) == 1


def test_powershell_requires_line_is_never_the_name():
    c = cand("pwsh", "#Requires -Version 7\n# list drives\nGet-PSDrive", heading=None)
    assert PowerShellEmitter().propose_filename(c) == "list-drives.ps1"
    # The skip is PowerShell-only: Bash naming is unchanged.
    assert cand("bash", "# requires root\nid", heading=None).name_proposal == "requires-root"


def test_powershell_shebang_is_hoisted_to_line_one():
    c = cand("pwsh", "#!/usr/bin/env pwsh   \nGet-Date")
    text = PowerShellEmitter().render(c, CTX)
    assert text.startswith("#!/usr/bin/env pwsh\n# name:        ops-task.ps1\n")
    assert text.count("#!") == 1 and text.endswith("\nGet-Date\n")
    assert PowerShellEmitter().normalize(c) == "Get-Date\n"


def test_powershell_no_shebang_is_added():
    text = PowerShellEmitter().render(cand("pwsh", "Get-Date"), CTX)
    assert text.startswith("# name:") and "#!" not in text


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------
def test_sql_plan_has_required_in_process_lexical_check():
    plan = SqlEmitter().verification_plan(cand("sql", "SELECT 1;"))
    lexical = plan.checks[0]
    assert (lexical.name, lexical.kind, lexical.required) == ("sql-lexical", "in-process", True)
    assert "Not a parse" in lexical.description
    assert plan.complete is True


@pytest.mark.parametrize("label, default, fluff, noted", [
    ("postgres", None, "postgres", False),
    ("mysql", None, "mysql", False),
    ("tsql", None, "tsql", False),
    ("sql", "sqlite", "sqlite", False),
    ("sql", "postgres", "postgres", False),     # config spelling, not the label's
    ("sql", None, "ansi", True),
    ("sql", "oracle", "ansi", True),
])
def test_sqlfluff_argv_uses_the_mapped_dialect(label, default, fluff, noted):
    plan = SqlEmitter(default_dialect=default).verification_plan(cand(label, "SELECT 1;"))
    fluff_check = plan.checks[1]
    assert fluff_check.argv == ("sqlfluff", "parse", "--dialect", fluff, ARTIFACT_PATH)
    assert fluff_check.required is False
    assert any("no sqlfluff mapping" in n for n in plan.notes) is noted


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------
def test_find_placeholders_both_syntaxes_in_order_without_duplicates():
    text = "Summarize {input} for {{ audience }}, then {input} and {{user.name}}."
    assert find_placeholders(text) == ("input", "audience", "user.name")


@pytest.mark.parametrize("text", [
    'Return JSON like {"a": 1}.', "Positional {0} and empty {}.",
    "Empty {{ }} and {{}} braces.", "Odd {input}} brace.", "Shell ${HOME} is not one",
])
def test_find_placeholders_ignores_non_placeholders(text):
    assert find_placeholders(text) == ()


def test_prompt_front_matter_lists_placeholders_before_verify_with():
    c = cand("prompt", "Summarize {input} for {{ audience }}.")
    text = PromptEmitter().render(c, CTX)
    assert '\nrisk-flags: []\nplaceholders: ["input", "audience"]\nverify-with: ' in text
    assert '\nplaceholders: []\n' in PromptEmitter().render(cand("prompt", "Be brief."), CTX)


def test_prompt_plan_is_three_required_in_process_lints():
    plan = PromptEmitter().verification_plan(cand("prompt", "Be brief."))
    assert [(ch.name, ch.kind, ch.required) for ch in plan.checks] == [
        ("prompt-front-matter", "in-process", True),
        ("prompt-body", "in-process", True),
        ("prompt-placeholders", "in-process", True),
    ]
    assert "`placeholders` list exactly" in plan.checks[2].description
    assert plan.complete is True


# --------------------------------------------------------------------------
# Runbook
# --------------------------------------------------------------------------
def test_runbook_plan_is_three_required_in_process_lints():
    plan = RunbookEmitter().verification_plan(cand("md", "# Disk full\n\n1. step"))
    assert [(ch.name, ch.kind, ch.required) for ch in plan.checks] == [
        ("runbook-front-matter", "in-process", True),
        ("runbook-title", "in-process", True),
        ("runbook-fences-labeled", "in-process", True),
    ]
    assert plan.complete is True


def test_runbook_render_format_is_unchanged_by_wp4():
    """No `placeholders` key: that refinement is prompt-only."""
    text = RunbookEmitter().render(cand("md", "# T\n\nUse {input}."), CTX)
    assert "placeholders" not in text
