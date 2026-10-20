"""WP5a: the verification engine. In-process checks implemented to their plan
descriptions, external checks run without a shell, the provisional verdict
policy, atomic result records, `soloctl verify`, and a contract-free core.

External tools are faked with small `/bin/sh` scripts on a controlled PATH,
so no test depends on what happens to be installed."""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import soloctl.library.refs as refs_mod
import soloctl.verification as verification_pkg
from soloctl import cli
from soloctl.compiler.classify import SUPPORTED_LANGUAGES
from soloctl.compiler.compile import compile_transcript
from soloctl.compiler.extract import extract
from soloctl.compiler.models import ArtifactCandidate
from soloctl.config import SoloctlConfig
from soloctl.emitters import EmitContext
from soloctl.emitters.base import ARTIFACT_PATH, VerificationCheck, VerificationPlan
from soloctl.emitters.bash import BashEmitter
from soloctl.emitters.powershell import PowerShellEmitter
from soloctl.emitters.prompt import PromptEmitter
from soloctl.emitters.python import PythonEmitter
from soloctl.emitters.registry import registry_from_config
from soloctl.emitters.runbook import RunbookEmitter
from soloctl.emitters.sql import SqlEmitter
from soloctl.errors import (
    LibraryError, PathEscapesLibraryError, UnknownArtifactError, VerificationError,
)
from soloctl.library.paths import LibraryPaths
from soloctl.library.repository import init_library
from soloctl.transcript.models import Transcript, Turn
from soloctl.transcript.render import render_transcript
from soloctl.verification import engine
from soloctl.verification.engine import IN_PROCESS_CHECKS, decide, run_plan, substitute_path
from soloctl.verification.markdown import (
    check_prompt_body, check_prompt_front_matter, check_prompt_placeholders,
    check_runbook_fences_labeled, check_runbook_front_matter, check_runbook_title,
    parse_front_matter,
)
from soloctl.verification.models import CheckResult
from soloctl.verification.python import check_python_ast_parse
from soloctl.verification.service import (
    RECORD_SCHEMA, emitter_for, plan_for, record_path, verify_artifact,
)
from soloctl.verification.sql import check_sql_lexical, header_dialect

POLYGLOT = Path(__file__).parent / "fixtures" / "transcript-polyglot.md"
TS = "2026-10-19T12:00:00.000+00:00"
CTX = EmitContext(source="chat:test", compiled_at=TS, tool_version="0.1.0")


def cand(label: str, body: str, heading: str = "Ops task") -> ArtifactCandidate:
    # A 4-backtick outer fence, so runbook bodies may contain ``` fences.
    doc = f"## {heading}\n\n````{label}\n{body}\n````\n"
    r = extract(doc, source="inline.md", only=SUPPORTED_LANGUAGES)
    assert len(r.candidates) == 1, r.skipped
    return r.candidates[0]


def render(emitter, label: str, body: str) -> str:
    return emitter.render(cand(label, body), CTX)


def sql_doc(body: str, dialect: str | None = None) -> str:
    return render(SqlEmitter(default_dialect=dialect), "sql", body)


def prompt_doc(body: str) -> str:
    return render(PromptEmitter(), "prompt", body)


def runbook_doc(body: str) -> str:
    return render(RunbookEmitter(), "md", body)


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------------
# python-ast-parse
# --------------------------------------------------------------------------
def test_python_ast_parse_passes_a_rendered_draft():
    text = render(PythonEmitter(), "python",
                  "from __future__ import annotations\nprint(1)")
    assert check_python_ast_parse(text).passed


def test_python_ast_parse_fails_with_the_line():
    text = render(PythonEmitter(), "python", "def f(:\n    pass")
    out = check_python_ast_parse(text)
    assert not out.passed and "syntax error at line" in out.detail


def test_python_ast_parse_rejects_null_bytes():
    assert not check_python_ast_parse("x = 1\x00\n").passed


def test_python_ast_parse_executes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert check_python_ast_parse("open('pwned', 'w').write('x')\n").passed
    assert not (tmp_path / "pwned").exists()


# --------------------------------------------------------------------------
# sql-lexical
# --------------------------------------------------------------------------
def test_sql_lexical_passes_a_rendered_draft():
    out = check_sql_lexical(sql_doc("SELECT a, (b + 1)\nFROM t\nWHERE c = 'x';"))
    assert out.passed and "1 statement" in out.detail and "not a parse" in out.detail


def test_sql_lexical_needs_a_statement():
    out = check_sql_lexical(sql_doc("-- nothing here\n/* or here */"))
    assert not out.passed and "no SQL statement" in out.detail


@pytest.mark.parametrize("body, what", [
    ("SELECT 'abc;", "string literal"),
    ('SELECT "col;', "quoted identifier"),
    ("SELECT 1; /* unfinished", "block comment"),
])
def test_sql_lexical_needs_closed_literals_identifiers_comments(body, what):
    out = check_sql_lexical(sql_doc(body))
    assert not out.passed and f"{what} opened on line" in out.detail


def test_sql_lexical_doubled_quotes_are_escapes():
    assert check_sql_lexical(sql_doc("SELECT 'it''s', \"a\"\"b\";")).passed


@pytest.mark.parametrize("body, msg", [
    ("SELECT (1 + 2;", "'(' opened on line"),
    ("SELECT 1 + 2);", "unbalanced ')'"),
])
def test_sql_lexical_needs_balanced_parentheses(body, msg):
    out = check_sql_lexical(sql_doc(body))
    assert not out.passed and msg in out.detail


def test_sql_lexical_ignores_parentheses_and_semicolons_in_quotes_and_comments():
    body = "SELECT ')(' AS p, \"x(\" -- ) ;\n/* ( ; */ FROM t;"
    assert check_sql_lexical(sql_doc(body)).passed


def test_sql_lexical_last_statement_must_end_with_semicolon():
    out = check_sql_lexical(sql_doc("SELECT 1;\nSELECT 'a;b'"))
    assert not out.passed and "does not end with ';'" in out.detail


def test_sql_lexical_tsql_accepts_a_go_line():
    text = sql_doc("SELECT 1\nGO\nSELECT 2\ngo 3", dialect="tsql")
    assert header_dialect(text) == "tsql"
    assert check_sql_lexical(text).passed


def test_sql_lexical_go_only_counts_for_tsql():
    out = check_sql_lexical(sql_doc("SELECT 1\nGO", dialect="postgresql"))
    assert not out.passed and "GO" not in out.detail.split("end with")[1]


def test_sql_lexical_tsql_still_rejects_a_trailing_statement():
    out = check_sql_lexical(sql_doc("SELECT 1\nGO\nSELECT 2", dialect="tsql"))
    assert not out.passed and "';' or a GO line" in out.detail


def test_sql_lexical_postgres_dollar_quotes():
    body = ("CREATE FUNCTION f() RETURNS void AS $body$\n"
            "BEGIN RAISE NOTICE E'it\\'s ('; END;\n$body$ LANGUAGE plpgsql;\n"
            "SELECT E'don\\'t', $$a;b$$, $q$it's ($q$, $1;")
    assert check_sql_lexical(sql_doc(body, dialect="postgresql")).passed
    out = check_sql_lexical(sql_doc(body))      # unspecified dialect
    assert not out.passed and "label the fence" in out.detail


def test_sql_lexical_mysql_backslash_escapes_and_backticks():
    body = "SELECT 'it\\'s', `we;ird` FROM t; # comment ("
    assert check_sql_lexical(sql_doc(body, dialect="mysql")).passed
    assert not check_sql_lexical(sql_doc(body, dialect="ansi")).passed


def test_sql_lexical_tsql_brackets_and_nested_comments():
    body = "SELECT [a]]b(] /* outer /* inner */ still ( */ FROM t;"
    assert check_sql_lexical(sql_doc(body, dialect="tsql")).passed


def test_sql_header_dialect_unspecified_is_none():
    assert header_dialect(sql_doc("SELECT 1;")) is None
    assert header_dialect("SELECT 1;\n-- dialect: tsql\n") is None   # body, not header


# --------------------------------------------------------------------------
# prompt-front-matter / prompt-body / prompt-placeholders
# --------------------------------------------------------------------------
GOOD_PROMPT = "Summarize {ticket} for {{ team }}.\nExample: {\"a\": 1}, ${HOME}, {0}."


def test_prompt_checks_pass_a_rendered_draft():
    text = prompt_doc(GOOD_PROMPT)
    for check in (check_prompt_front_matter, check_prompt_body, check_prompt_placeholders):
        assert check(text).passed, check(text).detail


@pytest.mark.parametrize("mutate, msg", [
    (lambda t: t.removeprefix("---\n"), "line 1 must be '---'"),
    (lambda t: t.replace("\n---\n", "\n", 1), "never closed"),
    (lambda t: t.replace('kind: "prompt"', 'kind: "runbook"'), "expected 'prompt'"),
    (lambda t: t.replace('description: ', 'notes: ', 1), "missing key(s): description"),
    (lambda t: t.replace('review: "', 'review: unquoted "', 1), "is not a JSON"),
    (lambda t: t.replace('kind: "prompt"\n', 'kind: "prompt"\nkind: "prompt"\n'),
     "more than once"),
    (lambda t: t.replace('risk-flags: []', 'risk-flags: "none"'), "list of strings"),
])
def test_prompt_front_matter_fails(mutate, msg):
    out = check_prompt_front_matter(mutate(prompt_doc(GOOD_PROMPT)))
    assert not out.passed and msg in out.detail


def test_prompt_front_matter_tolerates_blank_and_comment_lines():
    text = prompt_doc(GOOD_PROMPT).replace('kind: "prompt"\n', 'kind: "prompt"\n\n# note\n')
    assert check_prompt_front_matter(text).passed


def test_prompt_body_must_not_be_blank():
    text = prompt_doc(GOOD_PROMPT)
    front = text[:text.index("\n---\n") + 5]
    out = check_prompt_body(front + "\n   \n")
    assert not out.passed and "blank" in out.detail


def test_prompt_placeholders_undeclared():
    text = prompt_doc(GOOD_PROMPT) + "Also {extra}.\n"
    out = check_prompt_placeholders(text)
    assert not out.passed and "undeclared placeholder(s) in the body: extra" in out.detail


def test_prompt_placeholders_declared_but_unused():
    text = prompt_doc(GOOD_PROMPT).replace('["ticket", "team"]', '["ticket", "team", "gone"]')
    out = check_prompt_placeholders(text)
    assert not out.passed and "declared but unused placeholder(s): gone" in out.detail


@pytest.mark.parametrize("fill", ["TODO", "TBD", "FIXME", "[insert name here]",
                                  "<Insert date>", "[ INSERT ]"])
def test_prompt_placeholders_editorial_fill_ins(fill):
    out = check_prompt_placeholders(prompt_doc(f"{GOOD_PROMPT}\nOwner: {fill}"))
    assert not out.passed and "editorial fill-in" in out.detail and "line" in out.detail


def test_prompt_placeholders_lower_case_prose_is_not_a_fill_in():
    assert check_prompt_placeholders(
        prompt_doc(f"{GOOD_PROMPT}\nKeep a todo list; insert rows.")).passed


def test_prompt_placeholders_need_a_declared_list():
    text = prompt_doc(GOOD_PROMPT).replace('placeholders: ["ticket", "team"]\n', "")
    out = check_prompt_placeholders(text)
    assert not out.passed and "no `placeholders` list" in out.detail


# --------------------------------------------------------------------------
# runbook-front-matter / runbook-title / runbook-fences-labeled
# --------------------------------------------------------------------------
GOOD_RUNBOOK = "# Disk full\n\n1. Check:\n\n   ```bash\n   df -h\n   ```\n\n~~~sql\nSELECT 1;\n~~~"


def test_runbook_checks_pass_a_rendered_draft():
    text = runbook_doc(GOOD_RUNBOOK)
    for check in (check_runbook_front_matter, check_runbook_title,
                  check_runbook_fences_labeled):
        assert check(text).passed, check(text).detail


def test_runbook_front_matter_needs_its_kind():
    text = runbook_doc(GOOD_RUNBOOK).replace('kind: "runbook"', 'kind: "prompt"')
    out = check_runbook_front_matter(text)
    assert not out.passed and "expected 'runbook'" in out.detail


def test_runbook_front_matter_has_no_placeholders_key_requirement():
    assert "placeholders" not in runbook_doc(GOOD_RUNBOOK)
    assert check_runbook_front_matter(runbook_doc(GOOD_RUNBOOK)).passed


def test_runbook_title_first_block_must_be_a_heading():
    out = check_runbook_title(runbook_doc("Intro text.\n\n# Disk full"))
    assert not out.passed and "paragraph, not a heading" in out.detail


def test_runbook_title_accepts_setext_heading():
    assert check_runbook_title(runbook_doc("Disk full\n=========\n\nsteps")).passed


def test_runbook_fences_labeled_reports_unlabeled_fences_with_lines():
    text = runbook_doc("# T\n\n- step\n\n  ```\n  rm -rf /tmp/x\n  ```\n")
    out = check_runbook_fences_labeled(text)
    assert not out.passed
    line = int(out.detail.rsplit(" ", 1)[1])
    assert text.split("\n")[line - 1].strip() == "```"


def test_runbook_checks_fail_when_body_cannot_be_located():
    text = runbook_doc(GOOD_RUNBOOK).replace("\n---\n", "\n", 1)
    assert not check_runbook_title(text).passed
    assert not check_runbook_fences_labeled(text).passed


def test_front_matter_body_line_points_at_the_body():
    text = runbook_doc(GOOD_RUNBOOK)
    fm = parse_front_matter(text)
    assert fm.closed and text.split("\n")[fm.body_line - 1] == fm.body.split("\n")[0]


# --------------------------------------------------------------------------
# Every in-process check an emitter names is implemented
# --------------------------------------------------------------------------
EMITTER_SAMPLES = [
    (BashEmitter(), "bash", "echo hi"),
    (PythonEmitter(), "python", "print(1)"),
    (PowerShellEmitter(), "pwsh", "Get-Date"),
    (SqlEmitter(), "sql", "SELECT 1;"),
    (PromptEmitter(), "prompt", "Summarize {input}."),
    (RunbookEmitter(), "md", "# T\n\n1. step"),
]


@pytest.mark.parametrize("emitter, label, body", EMITTER_SAMPLES, ids=lambda x: getattr(x, "name", None))
def test_every_in_process_check_is_implemented(emitter, label, body):
    for check in emitter.verification_plan(cand(label, body)).checks:
        if check.kind == "in-process":
            assert check.name in IN_PROCESS_CHECKS


# --------------------------------------------------------------------------
# Engine: verdict policy (provisional)
# --------------------------------------------------------------------------
def _plan(*checks: VerificationCheck, complete: bool = True,
          notes: tuple[str, ...] = ()) -> VerificationPlan:
    return VerificationPlan(emitter="test", artifact_type="script", checks=checks,
                            complete=complete, notes=notes)


def _inproc(name: str = "python-ast-parse", required: bool = True) -> VerificationCheck:
    return VerificationCheck(name=name, kind="in-process", description="d",
                             required=required)


def _ext(tool: str, required: bool, *args: str) -> VerificationCheck:
    return VerificationCheck(name=f"{tool}-check", kind="external", description="d",
                             required=required, tool=tool,
                             argv=(tool, *args, ARTIFACT_PATH))


@pytest.fixture
def bindir(tmp_path, monkeypatch) -> Path:
    """An isolated PATH: only the fake tools a test writes (plus `sh`)."""
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", str(d))
    return d


def fake_tool(bindir: Path, name: str, script: str) -> Path:
    path = bindir / name
    path.write_text(f"#!/bin/sh\nPATH=/usr/bin:/bin\n{script}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def artifact(tmp_path) -> Path:
    p = tmp_path / "art" / "x.py"
    p.parent.mkdir()
    p.write_text("print(1)\n", encoding="utf-8")
    return p


def test_verdict_passed_when_every_required_check_passes(bindir, artifact):
    report = run_plan(_plan(_inproc(), _ext("absent-tool", False)), artifact)
    assert report.verdict == "passed"
    assert [c.status for c in report.checks] == ["passed", "not-run"]


def test_required_check_with_missing_tool_is_not_run_and_inconclusive(bindir, artifact):
    report = run_plan(_plan(_inproc(), _ext("absent-tool", True)), artifact)
    assert report.checks[1].status == "not-run"
    assert "not installed" in report.checks[1].detail
    assert report.verdict == "inconclusive"
    assert any("absent-tool-check did not run" in r for r in report.reasons)


def test_advisory_failure_never_decides(bindir, artifact):
    fake_tool(bindir, "lint", "exit 1")
    report = run_plan(_plan(_inproc(), _ext("lint", False)), artifact)
    assert report.checks[1].status == "failed"
    assert report.verdict == "passed"


def test_required_failure_fails(bindir, artifact):
    fake_tool(bindir, "lint", "exit 1")
    report = run_plan(_plan(_inproc(), _ext("lint", True)), artifact)
    assert report.verdict == "failed"
    assert report.reasons == ("required check lint-check failed",)


def test_incomplete_plan_cannot_pass(bindir, artifact):
    fake_tool(bindir, "lint", "exit 0")
    report = run_plan(_plan(_ext("lint", False), complete=False,
                            notes=("needs pwsh",)), artifact)
    assert report.checks[0].status == "passed"
    assert report.verdict == "inconclusive"
    assert "cannot auto-verify (needs pwsh)" in report.reasons[0]


def test_complete_plan_without_required_check_cannot_pass(bindir, artifact):
    report = run_plan(_plan(_inproc(required=False)), artifact)
    assert report.verdict == "inconclusive"
    assert "plan has no required check" in report.reasons


def test_unknown_in_process_check_is_not_run(bindir, artifact):
    report = run_plan(_plan(_inproc("no-such-check")), artifact)
    assert report.checks[0].status == "not-run"
    assert report.verdict == "inconclusive"


def test_decide_failed_beats_inconclusive():
    failed = CheckResult("a", "in-process", True, "d", "failed", "x")
    missing = CheckResult("b", "external", True, "d", "not-run", "y")
    verdict, _ = decide(_plan(complete=False), (failed, missing))
    assert verdict == "failed"


def test_bash_draft_is_inconclusive_without_shellcheck_and_passes_with_it(bindir, tmp_path):
    os.symlink(shutil.which("bash", path="/usr/bin:/bin"), bindir / "bash")
    p = tmp_path / "a.sh"
    c = cand("bash", "echo hi")
    p.write_text(BashEmitter().render(c, CTX), encoding="utf-8")
    plan = BashEmitter().verification_plan(c)
    assert run_plan(plan, p).verdict == "inconclusive"
    fake_tool(bindir, "shellcheck", "exit 0")
    assert run_plan(plan, p).verdict == "passed"


def test_bash_syntax_error_fails(bindir, tmp_path):
    os.symlink(shutil.which("bash", path="/usr/bin:/bin"), bindir / "bash")
    fake_tool(bindir, "shellcheck", "exit 0")
    c = cand("bash", "if then fi (")
    p = tmp_path / "a.sh"
    p.write_text(BashEmitter().render(c, CTX), encoding="utf-8")
    report = run_plan(BashEmitter().verification_plan(c), p)
    assert report.verdict == "failed" and report.checks[0].returncode != 0
    assert report.checks[0].output


# --------------------------------------------------------------------------
# Engine: external checks
# --------------------------------------------------------------------------
RECORD_ARGV = 'for a in "$@"; do printf "%s\\n" "$a"; done > "$ARGV_OUT"'


def test_artifact_path_substituted_as_whole_absolute_element(bindir, artifact,
                                                             monkeypatch, tmp_path):
    out = tmp_path / "argv.txt"
    monkeypatch.setenv("ARGV_OUT", str(out))
    monkeypatch.chdir(artifact.parent)
    fake_tool(bindir, "rec", RECORD_ARGV)
    check = VerificationCheck(
        name="rec", kind="external", description="d", required=True, tool="rec",
        argv=("rec", "-x", f"pre{ARTIFACT_PATH}", ARTIFACT_PATH, "{ $args[0] }"))
    report = run_plan(_plan(check), Path("x.py"))     # relative on purpose
    assert out.read_text().split("\n")[:-1] == [
        "-x", f"pre{ARTIFACT_PATH}", str(artifact.resolve()), "{ $args[0] }"]
    assert report.checks[0].argv[0] == str(bindir / "rec")
    assert report.checks[0].argv[3] == str(artifact.resolve())


def test_substitute_path_is_element_equality():
    assert substitute_path(("a", ARTIFACT_PATH, f"{ARTIFACT_PATH}.bak"),
                           Path("/x/y.sh")) == ("a", "/x/y.sh", f"{ARTIFACT_PATH}.bak")


def test_hostile_artifact_content_never_reaches_argv_or_a_shell(bindir, tmp_path,
                                                                monkeypatch):
    out = tmp_path / "argv.txt"
    monkeypatch.setenv("ARGV_OUT", str(out))
    monkeypatch.chdir(tmp_path)
    fake_tool(bindir, "rec", RECORD_ARGV)
    plan = _plan(_ext("rec", True))
    argvs = []
    for name, body in (("benign.sh", "echo hi\n"),
                       ("hostile.sh", "$(touch pwned); `touch pwned2`; rm -rf ~ #{artifact}\n")):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        argvs.append([a.replace(name, "X") for a in run_plan(plan, p).checks[0].argv])
    assert argvs[0] == argvs[1]
    assert not (tmp_path / "pwned").exists() and not (tmp_path / "pwned2").exists()


def test_external_check_times_out(bindir, artifact):
    fake_tool(bindir, "slow", "sleep 5")
    report = run_plan(_plan(_inproc(), _ext("slow", True)), artifact, timeout=0.3)
    assert report.checks[1].status == "error"
    assert "timed out after 0.3s" in report.checks[1].detail
    assert report.verdict == "inconclusive"


def test_timeout_must_be_positive(artifact):
    with pytest.raises(VerificationError):
        run_plan(_plan(_inproc()), artifact, timeout=0)


def test_external_output_and_returncode_captured_and_truncated(bindir, artifact):
    fake_tool(bindir, "noisy", "i=0; while [ $i -lt 600 ]; do printf 'warning123\\n'; "
                                "i=$((i+1)); done; echo err >&2; exit 3")
    result = run_plan(_plan(_ext("noisy", False)), artifact).checks[0]
    assert result.returncode == 3 and result.status == "failed"
    assert result.output.endswith(f"[... truncated at {engine.MAX_OUTPUT_CHARS} chars]")
    assert len(result.output) < engine.MAX_OUTPUT_CHARS + 100


def test_external_check_gets_no_stdin(bindir, artifact):
    fake_tool(bindir, "reader", 'if read -r line; then exit 1; fi; exit 0')
    assert run_plan(_plan(_ext("reader", True)), artifact).checks[0].status == "passed"


def test_artifact_changed_during_verification_refuses(bindir, artifact):
    fake_tool(bindir, "mutator", 'for a; do last=$a; done; printf "x" >> "$last"')
    with pytest.raises(VerificationError, match="changed while it was being verified"):
        run_plan(_plan(_ext("mutator", False)), artifact)


def test_non_utf8_artifact_refuses(tmp_path):
    p = tmp_path / "x.py"
    p.write_bytes(b"\xff\xfe")
    with pytest.raises(VerificationError, match="not UTF-8"):
        run_plan(_plan(_inproc()), p)


# --------------------------------------------------------------------------
# Engine purity: no shell, subprocess only in engine.py
# --------------------------------------------------------------------------
_VERIFICATION_DIR = Path(verification_pkg.__file__).parent
_MODULES = sorted(_VERIFICATION_DIR.glob("*.py"))


def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = (f.attr if isinstance(f, ast.Attribute)
                    else f.id if isinstance(f, ast.Name) else "")
            base = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
            yield node, base, name


def test_engine_runs_tools_only_via_subprocess_run_without_shell():
    tree = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))
    runs = 0
    for node, base, name in _calls(tree):
        assert not (base == "os" and name in {"system", "popen", "spawnl", "spawnlp",
                                              "spawnv", "spawnvp", "execv", "execvp"})
        if base == "subprocess":
            assert name == "run", f"subprocess.{name} used"
            runs += 1
        for kw in node.keywords:
            if kw.arg == "shell":
                assert isinstance(kw.value, ast.Constant) and kw.value.value is False
    assert runs == 1
    # The one subprocess.run call passes an argv tuple and an explicit timeout.
    call = next(n for n, b, nm in _calls(tree) if b == "subprocess" and nm == "run")
    kws = {k.arg for k in call.keywords}
    assert {"timeout", "stdin", "shell"} <= kws
    assert isinstance(call.args[0], ast.Name)


def test_engine_never_formats_the_artifact_token_into_argv():
    """Substitution is by element equality; `.format`/`.replace` on argv
    elements would also rewrite tokens inside PowerShell scripts."""
    src = Path(engine.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "substitute_path")
    for node, _base, name in _calls(fn):
        assert name not in {"format", "format_map", "replace", "sub"}
    assert any(isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.Eq)
               for n in ast.walk(fn))


@pytest.mark.parametrize("path", [p for p in _MODULES if p.name != "engine.py"],
                         ids=lambda p: p.name)
def test_only_the_engine_may_import_subprocess(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        assert not any(n.split(".")[0] in {"subprocess", "shutil"} for n in names), path.name


# --------------------------------------------------------------------------
# Contract-free boundary (same rule as compile.py and library/tags.py)
# --------------------------------------------------------------------------
_EDGE = {"ucc_contracts", "ucc_events", "artifact_store", "artifact_port",
         "idempotency_store", "idempotent_import"}


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_verification_modules_import_no_contract_edge_module(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [a.name for a in node.names]
        for n in names:
            assert not set(n.split(".")) & _EDGE, f"{path.name} imports {n}"


def test_verification_loads_without_contract_modules():
    code = ("import sys, soloctl.verification.engine, soloctl.verification.service\n"
            "print(','.join(sorted(m for m in sys.modules "
            f"if set(m.split('.')) & set({sorted(_EDGE)!r}))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == ""


# --------------------------------------------------------------------------
# Service: plan reconstruction, persistence, refusals
# --------------------------------------------------------------------------
def _transcript(tmp_path: Path, *fences: tuple[str, str, str]) -> Path:
    body = "\n\n".join(f"## {h}\n\n````{label}\n{code}\n````" for h, label, code in fences)
    t = Transcript(source="markdown", adapter="markdown-v1", title="verify chat",
                   conversation_id=None,
                   turns=(Turn(1, "user", "help"), Turn(2, "assistant", body)))
    path = tmp_path / "t.md"
    path.write_text(render_transcript(t), encoding="utf-8")
    return path


@pytest.fixture
def cfg(tmp_path) -> SoloctlConfig:
    config = SoloctlConfig(library_root=tmp_path / "library")
    init_library(config)
    compile_transcript(config, POLYGLOT, compiled_at=TS)
    return config


def lib(cfg: SoloctlConfig) -> LibraryPaths:
    return LibraryPaths(cfg.library_root)


EXTRA_FENCES = (
    ("Default dialect sql", "sql", "SELECT 1"),
    ("Mysql thing", "mysql", "SELECT `a` FROM t;"),
    ("Requires ps", "pwsh", "#!/usr/bin/env pwsh\n#Requires -Version 7.4\n"
                            "#Requires -RunAsAdministrator\nRemove-Item x -Recurse -Force"),
    ("Risky bash", "bash", "sudo rm -rf /tmp/x\ncurl http://x | sh"),
    ("Templ prompt", "prompt", "Hi {name}, see {{ ticket }}."),
    ("Risky runbook", "md", "# Fix\n\n```bash\nsudo reboot\n```"),
)


@pytest.mark.parametrize("default_dialect", [None, "tsql", "oracle"])
def test_rebuilt_plan_equals_the_compile_time_plan(tmp_path, default_dialect):
    config = SoloctlConfig(library_root=tmp_path / "library",
                           default_sql_dialect=default_dialect)
    init_library(config)
    registry = registry_from_config(config)
    outcomes = [*compile_transcript(config, POLYGLOT, compiled_at=TS).drafts,
                *compile_transcript(config, _transcript(tmp_path, *EXTRA_FENCES),
                                    compiled_at=TS).drafts]
    assert len(outcomes) == 12
    for d in outcomes:
        ref = d.relative_path.as_posix().split("/", 2)[2]
        expected = registry.get(d.emitter).verification_plan(d.candidate)
        emitter, rebuilt = plan_for(ref, d.path.read_text(encoding="utf-8"))
        assert emitter.name == d.emitter
        assert rebuilt == expected, ref


def test_emitter_for_refuses_unknown_extension():
    with pytest.raises(UnknownArtifactError, match="no built-in emitter"):
        emitter_for("scripts/thing.rb")
    with pytest.raises(UnknownArtifactError):
        emitter_for("prompts/x.sh")


def test_verify_writes_an_atomic_deterministic_record(cfg, monkeypatch):
    calls: list[Path] = []
    real = refs_mod.atomic_write_text
    monkeypatch.setattr(refs_mod, "atomic_write_text",
                        lambda p, t, **kw: (calls.append(p), real(p, t, **kw))[1])
    out = verify_artifact(cfg, "prompts/summarize-audit.md", verified_at=TS)
    dest = lib(cfg).verification / "prompts" / "summarize-audit.md.json"
    assert calls == [dest] and out.record_path == dest
    assert out.relative_record_path == Path("verification/prompts/summarize-audit.md.json")
    doc = json.loads(dest.read_text(encoding="utf-8"))
    art = lib(cfg).drafts / "prompts" / "summarize-audit.md"
    import hashlib
    assert doc["schema"] == RECORD_SCHEMA
    assert doc["ref"] == "prompts/summarize-audit.md" and doc["state"] == "draft"
    assert doc["sha256"] == hashlib.sha256(art.read_bytes()).hexdigest()
    assert doc["compiled"] == f"soloctl 0.1.0 {TS}"
    assert doc["verdict"] == "passed" and doc["scope"] == "automatic"
    assert "never implies manual verification" in doc["note"]
    assert [c["name"] for c in doc["checks"]] == [
        "prompt-front-matter", "prompt-body", "prompt-placeholders"]
    first = dest.read_bytes()
    verify_artifact(cfg, "prompts/summarize-audit.md", verified_at=TS)
    assert dest.read_bytes() == first


def test_verify_keeps_only_the_latest_run(cfg):
    verify_artifact(cfg, "prompts/summarize-audit.md", verified_at=TS)
    verify_artifact(cfg, "prompts/summarize-audit.md", verified_at="2026-10-20T00:00:00Z")
    dest = record_path(lib(cfg), "prompts/summarize-audit.md")
    assert json.loads(dest.read_text())["verified_at"] == "2026-10-20T00:00:00Z"
    assert sorted(p.name for p in dest.parent.iterdir()) == ["summarize-audit.md.json"]


@pytest.mark.parametrize("form", [
    "runbooks/disk-full-runbook.md",
    "artifacts/drafts/runbooks/disk-full-runbook.md",
    "{root}/artifacts/drafts/runbooks/disk-full-runbook.md",
])
def test_verify_accepts_the_same_artifact_forms_as_tag(cfg, form):
    out = verify_artifact(cfg, form.format(root=cfg.library_root), verified_at=TS)
    assert out.ref == "runbooks/disk-full-runbook.md" and out.report.verdict == "passed"


def test_verify_never_changes_artifacts_or_appends_events(cfg, bindir):
    before = tree(lib(cfg).artifacts)
    events = lib(cfg).events_file.read_bytes()
    for ref in ("scripts/disk-audit.sh", "scripts/disk_audit_python.py",
                "scripts/disk-audit-powershell.ps1", "scripts/largest-tables.sql",
                "prompts/summarize-audit.md", "runbooks/disk-full-runbook.md"):
        verify_artifact(cfg, ref, verified_at=TS)
    assert tree(lib(cfg).artifacts) == before
    assert lib(cfg).events_file.read_bytes() == events
    assert not (cfg.library_root / "events").exists()
    assert len(list(lib(cfg).verification.rglob("*.json"))) == 6


def test_verify_refuses_if_the_file_changed_after_planning(cfg, monkeypatch):
    """The plan is built from the bytes read first; if the engine then sees
    different bytes, the plan may not match them, so nothing is recorded."""
    import soloctl.verification.service as service_mod
    real = service_mod.run_plan

    def edit_then_run(plan, path, **kw):
        path.write_text(path.read_text(encoding="utf-8") + "\nTODO\n", encoding="utf-8")
        return real(plan, path, **kw)

    monkeypatch.setattr(service_mod, "run_plan", edit_then_run)
    with pytest.raises(VerificationError, match="changed between planning and checking"):
        verify_artifact(cfg, "prompts/summarize-audit.md")
    assert list(lib(cfg).verification.rglob("*")) == []


def test_verify_works_on_approved_artifacts(cfg):
    src = lib(cfg).drafts / "scripts" / "largest-tables.sql"
    src.rename(lib(cfg).approved / "scripts" / "largest-tables.sql")
    out = verify_artifact(cfg, "scripts/largest-tables.sql", verified_at=TS)
    assert out.state == "approved" and out.report.verdict == "passed"
    assert out.record_path == lib(cfg).verification / "scripts" / "largest-tables.sql.json"


@pytest.mark.parametrize("arg, exc", [
    ("scripts/nope.sh", UnknownArtifactError),
    ("not a ref", UnknownArtifactError),
])
def test_verify_refuses_unknown_artifacts_and_writes_nothing(cfg, arg, exc):
    with pytest.raises(exc):
        verify_artifact(cfg, arg)
    assert list(lib(cfg).verification.rglob("*")) == []


def test_verify_refuses_uncompiled_files(cfg):
    (lib(cfg).drafts / "scripts" / "hand.sh").write_text("echo hi\n")
    with pytest.raises(UnknownArtifactError, match="compiled"):
        verify_artifact(cfg, "scripts/hand.sh")
    assert list(lib(cfg).verification.rglob("*")) == []


def test_verify_refuses_kinds_no_emitter_produces(cfg):
    (lib(cfg).drafts / "scripts" / "x.rb").write_text(f"# compiled:     soloctl 0.1.0 {TS}\n")
    with pytest.raises(UnknownArtifactError, match="no built-in emitter"):
        verify_artifact(cfg, "scripts/x.rb")
    assert list(lib(cfg).verification.rglob("*")) == []


def test_verify_refuses_an_uninitialized_library(tmp_path):
    with pytest.raises(LibraryError, match="soloctl init"):
        verify_artifact(SoloctlConfig(library_root=tmp_path / "nolib"), "scripts/x.sh")


def test_verify_record_path_cannot_escape_the_library(cfg, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (lib(cfg).verification / "prompts").symlink_to(outside)
    with pytest.raises(PathEscapesLibraryError):
        verify_artifact(cfg, "prompts/summarize-audit.md")
    assert list(outside.iterdir()) == []


# --------------------------------------------------------------------------
# CLI — thin wrapper
# --------------------------------------------------------------------------
runner = CliRunner()


def test_cli_verify_passed_exits_0(cfg):
    r = runner.invoke(cli.app, ["verify", "prompts/summarize-audit.md",
                                "--library", str(cfg.library_root)])
    assert r.exit_code == 0, r.output
    assert "verdict: PASSED" in r.output
    assert "recorded: verification/prompts/summarize-audit.md.json" in r.output
    assert "manual verification is separate" in r.output


def test_cli_verify_inconclusive_exits_6(cfg, bindir):
    r = runner.invoke(cli.app, ["verify", "scripts/disk-audit-powershell.ps1",
                                "--library", str(cfg.library_root)])
    assert r.exit_code == 6, r.output
    assert "verdict: INCONCLUSIVE" in r.output and "not-run" in r.output


def test_cli_verify_failed_exits_5(tmp_path):
    config = SoloctlConfig(library_root=tmp_path / "library")
    init_library(config)
    compile_transcript(config, _transcript(tmp_path, ("Broken", "sql", "SELECT (1")),
                       compiled_at=TS)
    r = runner.invoke(cli.app, ["verify", "scripts/broken.sql",
                                "--library", str(config.library_root)])
    assert r.exit_code == 5, r.output
    assert "verdict: FAILED" in r.output and "'(' opened on line" in r.output
    doc = json.loads(record_path(LibraryPaths(config.library_root),
                                 "scripts/broken.sql").read_text())
    assert doc["verdict"] == "failed"


def test_cli_verify_refusal_exits_1(cfg):
    r = runner.invoke(cli.app, ["verify", "scripts/nope.sh",
                                "--library", str(cfg.library_root)])
    assert r.exit_code == 1 and "ERROR" in r.output
