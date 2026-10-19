"""Emitter tests (WP3): Bash and Python emitters in full, PowerShell / SQL /
prompt / runbook basics, and the "emitters are pure" boundary. Their WP4
verification plans and render refinements are in test_emitter_plans.py."""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

import soloctl.emitters as emitters_pkg
from soloctl.compiler.classify import SUPPORTED_LANGUAGES
from soloctl.compiler.extract import extract
from soloctl.compiler.models import ArtifactCandidate
from soloctl.emitters import ArtifactEmitter, EmitContext
from soloctl.emitters.base import ARTIFACT_PATH, PLACEHOLDER
from soloctl.emitters.bash import BashEmitter
from soloctl.emitters.powershell import PowerShellEmitter
from soloctl.emitters.prompt import PromptEmitter
from soloctl.emitters.python import PythonEmitter
from soloctl.emitters.runbook import RunbookEmitter
from soloctl.emitters.sql import SqlEmitter
from soloctl.errors import EmitterError, UnsupportedEmitterError

CTX = EmitContext(source='chat:claude 2026-07-11 "forge provisioning"',
                  compiled_at="2026-10-19T12:00:00Z", tool_version="0.1.0")

ALL_EMITTERS = [BashEmitter(), PythonEmitter(), PowerShellEmitter(),
                SqlEmitter(), PromptEmitter(), RunbookEmitter()]


def cand(label: str, body: str, heading: str | None = "Tailnet join",
         intro: str | None = None) -> ArtifactCandidate:
    doc = ""
    if heading:
        doc += f"## {heading}\n\n"
    if intro:
        doc += f"{intro}\n\n"
    doc += f"```{label}\n{body}\n```\n"
    r = extract(doc, source="inline.md", only=SUPPORTED_LANGUAGES)
    assert len(r.candidates) == 1, r.skipped
    return r.candidates[0]


# --------------------------------------------------------------------------
# Protocol conformance (all six)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("emitter", ALL_EMITTERS, ids=lambda e: e.name)
def test_every_builtin_emitter_satisfies_the_protocol(emitter):
    assert isinstance(emitter, ArtifactEmitter)
    assert emitter.extension.startswith(".")


@pytest.mark.parametrize("emitter", ALL_EMITTERS, ids=lambda e: e.name)
def test_emitters_refuse_candidates_they_do_not_support(emitter):
    # Find a candidate of some *other* language and call every method on it.
    other = next(c for c in (cand("bash", "echo hi"), cand("python", "print(1)"))
                 if not emitter.supports(c))
    for call in (lambda: emitter.normalize(other),
                 lambda: emitter.propose_filename(other),
                 lambda: emitter.render(other, CTX),
                 lambda: emitter.verification_plan(other),
                 lambda: emitter.executable(other)):
        with pytest.raises(UnsupportedEmitterError) as exc_info:
            call()
        assert "unsupported-emitter" in str(exc_info.value)


@pytest.mark.parametrize("emitter", ALL_EMITTERS, ids=lambda e: e.name)
def test_filename_proposal_refuses_non_slug_names(emitter):
    supported = {
        "bash": cand("bash", "echo hi"), "python": cand("python", "print(1)"),
        "powershell": cand("pwsh", "Get-Date"), "sql": cand("sql", "SELECT 1;"),
        "prompt": cand("prompt", "Be brief."), "runbook": cand("md", "1. step"),
    }[emitter.name]
    evil = dataclasses.replace(supported, name_proposal="../../etc/passwd")
    with pytest.raises(EmitterError, match="not a filename-safe slug"):
        emitter.propose_filename(evil)


# --------------------------------------------------------------------------
# Bash (full)
# --------------------------------------------------------------------------
TAILNET_BODY = ("#!/usr/bin/env bash\r\n# join node to tailnet\r\n"
                "sudo tailscale up --ssh   \r\nufw allow in on tailscale0 to any port 2488\r\n")


def test_bash_supports_only_bash_scripts():
    e = BashEmitter()
    assert e.supports(cand("sh", "echo hi"))
    assert not e.supports(cand("python", "print(1)"))
    assert not e.supports(cand("pwsh", "echo hi"))


def test_bash_render_matches_compiler_plan_header_template():
    c = cand("bash", TAILNET_BODY, intro="Here's a script that joins the node to the tailnet.")
    assert BashEmitter().render(c, CTX) == (
        "#!/usr/bin/env bash\n"
        "# name:        tailnet-join.sh\n"
        '# source:      chat:claude 2026-07-11 "forge provisioning"\n'
        "# compiled:    soloctl 0.1.0 2026-10-19T12:00:00Z\n"
        "# description: Joins the node to the tailnet.\n"
        "# review:      DRAFT — not executable until `soloctl lib approve`\n"
        "# risk-flags:  sudo, firewall\n"
        f"# verify-with: {PLACEHOLDER}\n"
        "set -euo pipefail\n"
        "IFS=$'\\n\\t'\n"
        "\n"
        "# join node to tailnet\n"
        "sudo tailscale up --ssh\n"
        "ufw allow in on tailscale0 to any port 2488\n"
    )


def test_bash_normalize_strips_shebang_crlf_and_trailing_space_only():
    out = BashEmitter().normalize(cand("bash", TAILNET_BODY))
    assert out == ("# join node to tailnet\nsudo tailscale up --ssh\n"
                   "ufw allow in on tailscale0 to any port 2488\n")
    assert "\r" not in out and out.count("#!") == 0


def test_bash_empty_description_and_flags_render_placeholders():
    text = BashEmitter().render(cand("bash", "echo hi", heading=None), CTX)
    assert f"# description: {PLACEHOLDER}\n" in text
    assert "# risk-flags:  none\n" in text
    assert "# name:        block-01.sh\n" in text


def test_bash_header_values_cannot_inject_extra_lines():
    ctx = dataclasses.replace(CTX, source="evil\nrm -rf /")
    text = BashEmitter().render(cand("bash", "echo hi"), ctx)
    header = text.split("set -euo pipefail")[0]
    assert all(line.startswith("#") for line in header.splitlines())
    assert "# source:      evil rm -rf /\n" in header


def test_bash_render_is_deterministic():
    c = cand("bash", TAILNET_BODY)
    assert BashEmitter().render(c, CTX) == BashEmitter().render(c, CTX)


def test_bash_verification_plan_describes_but_does_not_run_checks():
    c = cand("bash", TAILNET_BODY)
    plan = BashEmitter().verification_plan(c)
    assert plan.emitter == "bash" and plan.artifact_type == "script" and plan.complete
    assert [ch.name for ch in plan.checks] == ["bash-syntax", "shellcheck"]
    for ch in plan.checks:
        assert ch.kind == "external" and ch.required
        assert isinstance(ch.argv, tuple) and all(isinstance(a, str) for a in ch.argv)
        assert ch.argv[0] == ch.tool and ch.argv[-1] == ARTIFACT_PATH
        assert not any(" " in a for a in ch.argv)    # argv, never a shell string
    assert plan.checks[0].argv == ("bash", "-n", ARTIFACT_PATH)
    assert "sudo, firewall" in plan.notes[0]
    assert BashEmitter().verification_plan(cand("bash", "echo hi")).notes == ()


def test_bash_filename_and_executable():
    c = cand("bash", "echo hi")
    assert BashEmitter().propose_filename(c) == "tailnet-join.sh"
    assert BashEmitter().executable(c) is True


# --------------------------------------------------------------------------
# Python (full)
# --------------------------------------------------------------------------
PY_BODY = ('#!/usr/bin/env python3\nfrom __future__ import annotations\n\n'
           'import shutil\n\ndef used() -> float:\n'
           '    total, used, _ = shutil.disk_usage("/")\n    return used / total\n')


def test_python_supports_python_and_py_labels_only():
    e = PythonEmitter()
    assert e.supports(cand("python", "print(1)")) and e.supports(cand("py", "print(1)"))
    assert not e.supports(cand("bash", "echo hi"))


def test_python_render_header_and_body():
    c = cand("py", PY_BODY, heading="Disk usage")
    text = PythonEmitter().render(c, CTX)
    lines = text.splitlines()
    assert lines[0] == "#!/usr/bin/env python3"
    assert lines[1] == "# name:        disk_usage.py"
    assert lines[5] == "# review:      DRAFT — not executable until `soloctl lib approve`"
    assert lines[7] == f"# verify-with: {PLACEHOLDER}"
    assert lines[8] == ""
    assert text.endswith(PythonEmitter().normalize(c))
    assert text.count("#!/usr/bin/env python3") == 1


def test_python_rendered_output_still_parses_with_future_import():
    c = cand("python", PY_BODY)
    tree = ast.parse(PythonEmitter().render(c, CTX))
    first = tree.body[0]
    assert isinstance(first, ast.ImportFrom) and first.module == "__future__"


def test_python_filename_uses_underscores_so_it_is_importable():
    c = cand("python", "print(1)", heading="Rotate panel key")
    name = PythonEmitter().propose_filename(c)
    assert name == "rotate_panel_key.py" and name[:-3].isidentifier()


def test_python_verification_plan():
    plan = PythonEmitter().verification_plan(cand("python", "import os\nos.system('sudo ls')"))
    assert plan.complete and plan.emitter == "python"
    ast_check, ruff = plan.checks
    assert (ast_check.name, ast_check.kind, ast_check.required) == (
        "python-ast-parse", "in-process", True)
    assert ast_check.tool is None and ast_check.argv == ()
    assert (ruff.name, ruff.kind, ruff.required, ruff.tool) == (
        "ruff", "external", False, "ruff")
    assert ruff.argv[-1] == ARTIFACT_PATH
    assert "sudo" in plan.notes[0]


def test_python_executable():
    assert PythonEmitter().executable(cand("python", "print(1)")) is True


# --------------------------------------------------------------------------
# PowerShell / SQL / prompt / runbook — supports/normalize/render/plan basics
# (scaffolded in WP3; plan details in test_emitter_plans.py)
# --------------------------------------------------------------------------
def test_powershell_basics():
    e = PowerShellEmitter()
    c = cand("pwsh", "Get-PSDrive   \r\n", heading="List drives")
    assert e.supports(c) and e.supports(cand("ps1", "Get-Date"))
    assert not e.supports(cand("bash", "echo hi"))
    assert e.normalize(c) == "Get-PSDrive\n"
    assert e.propose_filename(c) == "list-drives.ps1"
    text = e.render(c, CTX)
    assert text.startswith("# name:        list-drives.ps1\n")
    assert text.endswith("\nGet-PSDrive\n")
    plan = e.verification_plan(c)
    assert plan.complete is False                    # every check is advisory
    assert plan.checks and not any(ch.required for ch in plan.checks)
    assert e.executable(c) is False


def test_sql_dialect_from_label_then_config_default():
    c_pg = cand("postgres", "SELECT 1;  ", heading="Top tables")
    c_plain = cand("sql", "-- top tables\nSELECT 1;", heading=None)
    e = SqlEmitter(default_dialect="sqlite")
    assert e.supports(c_pg) and e.supports(c_plain)
    assert not e.supports(cand("python", "print(1)"))
    assert e.normalize(c_pg) == "SELECT 1;\n"
    assert e.dialect(c_pg) == "postgresql"           # label wins
    assert e.dialect(c_plain) == "sqlite"            # config default
    assert SqlEmitter().dialect(c_plain) is None     # neither
    assert e.propose_filename(c_plain) == "top-tables.sql"
    text = e.render(c_pg, CTX)
    assert text.startswith("-- name:        top-tables.sql\n-- dialect:     postgresql\n")
    assert "-- dialect:     unspecified\n" in SqlEmitter().render(c_plain, CTX)
    assert e.verification_plan(c_pg).complete is True
    assert e.executable(c_pg) is False


def test_prompt_basics():
    e = PromptEmitter()
    c = cand("prompt", "You are an SRE.\nSummarize: {input}", heading="Summarize audit")
    assert e.supports(c) and not e.supports(cand("md", "1. step"))
    assert e.normalize(c) == "You are an SRE.\nSummarize: {input}\n"
    assert e.propose_filename(c) == "summarize-audit.md"
    text = e.render(c, CTX)
    assert text.startswith('---\nkind: "prompt"\nname: "summarize-audit.md"\n')
    assert '\nrisk-flags: []\n' in text
    assert f'\nverify-with: "{PLACEHOLDER}"\n---\n\nYou are an SRE.' in text
    assert e.verification_plan(c).complete is True
    assert e.executable(c) is False


def test_runbook_basics():
    e = RunbookEmitter()
    c = cand("md", "# Disk full\n\n1. `sudo logrotate -f x`\n", heading="Disk full runbook")
    assert e.supports(c) and e.supports(cand("runbook", "1. step"))
    assert not e.supports(cand("prompt", "Be brief."))
    assert e.normalize(c) == "# Disk full\n\n1. `sudo logrotate -f x`\n"
    assert e.propose_filename(c) == "disk-full-runbook.md"
    text = e.render(c, CTX)
    assert text.startswith('---\nkind: "runbook"\n')
    assert '\nrisk-flags: ["sudo"]\n' in text
    assert text.endswith("---\n\n# Disk full\n\n1. `sudo logrotate -f x`\n")
    plan = e.verification_plan(c)
    assert plan.complete is True and plan.notes[0].startswith("risk flags present (sudo)")
    assert e.executable(c) is False


def test_markdown_front_matter_quotes_hostile_values():
    ctx = dataclasses.replace(CTX, source='a: b\n---\nkind: "script"')
    text = PromptEmitter().render(cand("prompt", "hi"), ctx)
    front = text.split("\n---\n", 1)[0]
    assert front.count("\n") == 9      # 10 lines (incl. placeholders), no injection
    assert 'source: "a: b --- kind: \\"script\\""' in front


# --------------------------------------------------------------------------
# Boundary: emitters are pure (AST-checked, not substring-checked)
# --------------------------------------------------------------------------
_FORBIDDEN_IMPORTS = {"os", "subprocess", "shutil", "pathlib", "datetime", "time",
                      "tempfile", "socket", "urllib", "http"}
# With os/pathlib/shutil/subprocess unimportable, these are the remaining
# ways to touch the world: builtins, and methods on objects passed in.
_FORBIDDEN_CALLS = {"open", "exec", "eval", "__import__", "write_text", "write_bytes",
                    "mkdir", "chmod", "touch", "unlink", "now", "utcnow", "Popen"}


def _emitter_sources() -> list[Path]:
    return sorted(Path(emitters_pkg.__file__).parent.glob("*.py"))


@pytest.mark.parametrize("path", _emitter_sources(), ids=lambda p: p.name)
def test_emitter_modules_do_no_io_and_run_nothing(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in _FORBIDDEN_IMPORTS, (
                    f"{path.name} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert (node.module or "").split(".")[0] not in _FORBIDDEN_IMPORTS, (
                f"{path.name} imports from {node.module}")
        elif isinstance(node, ast.Call):
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None)
            assert called not in _FORBIDDEN_CALLS, f"{path.name} calls {called}()"
