"""Work Package 4 items 1-3: the compilation coordinator, collision
resolution against the library, and fence accounting through emission —
plus the invariants it must never regress (secret refusal before any write;
dry run writes nothing and appends no event; the core stays contract-free).
"""
from __future__ import annotations

import ast
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from soloctl import cli
from soloctl.compiler import compile as compile_mod
from soloctl.compiler.compile import KIND_DIRS, compile_transcript
from soloctl.config import SoloctlConfig
from soloctl.emitters import EmitContext, default_registry
from soloctl.emitters.bash import BashEmitter
from soloctl.emitters.registry import EmitterRegistry
from soloctl.errors import (
    EmitterError, LibraryError, SecretDetected, TranscriptParseError,
)
from soloctl.library.paths import LibraryPaths
from soloctl.library.repository import init_library
from soloctl.transcript.models import Transcript, Turn
from soloctl.transcript.render import render_transcript

FIXTURES = Path(__file__).parent / "fixtures"
POLYGLOT = FIXTURES / "transcript-polyglot.md"
TS = "2026-10-19T12:00:00.000+00:00"
SECRET = "ghp_" + "a" * 40

# Polyglot fixture: 10 fences -> 6 drafts (one per emitter) + 4 skips
# (user-turn, console, unlabeled, yaml).
POLYGLOT_DRAFTS = {
    "artifacts/drafts/scripts/disk-audit.sh": "bash",
    "artifacts/drafts/scripts/disk_audit_python.py": "python",
    "artifacts/drafts/scripts/disk-audit-powershell.ps1": "powershell",
    "artifacts/drafts/scripts/largest-tables.sql": "sql",
    "artifacts/drafts/prompts/summarize-audit.md": "prompt",
    "artifacts/drafts/runbooks/disk-full-runbook.md": "runbook",
}


@pytest.fixture
def cfg(tmp_path) -> SoloctlConfig:
    config = SoloctlConfig(library_root=tmp_path / "library")
    init_library(config)
    return config


def _transcript(tmp_path: Path, *turns: tuple[str, str], name: str = "t.md") -> Path:
    t = Transcript(source="markdown", adapter="markdown-v1", title="ops chat",
                   conversation_id=None,
                   turns=tuple(Turn(i, role, body) for i, (role, body)
                               in enumerate(turns, 1)))
    path = tmp_path / name
    path.write_text(render_transcript(t), encoding="utf-8")
    return path


def _fence(lang: str, body: str) -> str:
    return f"```{lang}\n{body}\n```"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _rel(outcome) -> dict[str, str]:
    return {str(d.relative_path): d.emitter for d in outcome.drafts}


# ---------------------------------------------------------------------------
# Item 1 — coordinator
# ---------------------------------------------------------------------------
def test_compile_writes_one_draft_per_candidate_under_kind_dirs(cfg):
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    assert not outcome.dry_run
    assert _rel(outcome) == POLYGLOT_DRAFTS
    for d in outcome.drafts:
        assert d.written and d.path.is_file()
        assert d.path.parent.name == KIND_DIRS[d.artifact_type]
        assert d.path.parent.parent == LibraryPaths(cfg.library_root).drafts


def test_draft_content_is_exactly_the_emitter_render(cfg):
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    registry = default_registry()
    for d in outcome.drafts:
        emitter = registry.get(d.emitter)
        ctx = EmitContext(source='markdown "polyglot ops"', compiled_at=TS,
                          tool_version=cli.__version__)
        assert d.path.read_text(encoding="utf-8") == emitter.render(d.candidate, ctx)


def test_drafts_are_never_executable(cfg):
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    for d in outcome.drafts:
        mode = d.path.stat().st_mode
        assert not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), d.path


def test_writes_go_through_atomic_write_without_overwrite(cfg, monkeypatch):
    calls = []
    real = compile_mod.atomic_write_text

    def spy(path, text, *, exist_ok=True):
        calls.append((path, exist_ok))
        return real(path, text, exist_ok=exist_ok)

    monkeypatch.setattr(compile_mod, "atomic_write_text", spy)
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    assert [p for p, _ in calls] == [d.path for d in outcome.drafts]
    assert all(exist_ok is False for _, exist_ok in calls)


def test_compiled_at_defaults_to_now(cfg):
    outcome = compile_transcript(cfg, POLYGLOT)
    text = outcome.drafts[0].path.read_text(encoding="utf-8")
    assert f"# compiled:    soloctl {cli.__version__} 20" in text


def test_source_refs_are_library_relative_when_inside_library(cfg):
    inside = cfg.library_root / "transcripts" / "2026" / "10" / "poly.md"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(POLYGLOT.read_bytes())
    outcome = compile_transcript(cfg, inside, compiled_at=TS)
    assert {d.candidate.src.path for d in outcome.drafts} == {
        "transcripts/2026/10/poly.md"}


def test_include_user_compiles_user_turn_fences(cfg):
    outcome = compile_transcript(cfg, POLYGLOT, include_user=True, compiled_at=TS)
    assert "user-turn" not in {s.reason for s in outcome.skipped}
    assert len(outcome.drafts) == 7


def test_library_hashes_dedup_is_counted_as_skipped(cfg):
    first = compile_transcript(cfg, POLYGLOT, dry_run=True, compiled_at=TS)
    known = frozenset(d.candidate.sha256 for d in first.drafts)
    outcome = compile_transcript(cfg, POLYGLOT, library_hashes=known,
                                 compiled_at=TS)
    assert outcome.drafts == ()
    assert sum(s.reason == "dupe-in-library" for s in outcome.skipped) == 6


def test_uninitialized_library_refuses(tmp_path):
    cfg = SoloctlConfig(library_root=tmp_path / "nowhere")
    with pytest.raises(LibraryError, match="soloctl init"):
        compile_transcript(cfg, POLYGLOT)
    assert not (tmp_path / "nowhere").exists()


def test_non_canonical_input_refuses_before_any_write(cfg, tmp_path):
    raw = tmp_path / "raw.md"
    raw.write_text("# not canonical\n\n" + _fence("bash", "echo hi") + "\n",
                   encoding="utf-8")
    before = _snapshot(cfg.library_root)
    with pytest.raises(TranscriptParseError):
        compile_transcript(cfg, raw)
    assert _snapshot(cfg.library_root) == before


def test_render_error_leaves_drafts_untouched(cfg, monkeypatch):
    """Every draft is rendered before the first write."""
    real = compile_mod.atomic_write_text
    rendered = []

    class ExplodingOnSecond(BashEmitter):
        def render(self, candidate, context):
            rendered.append(candidate)
            if len(rendered) == 2:
                raise EmitterError("boom")
            return super().render(candidate, context)

    def forbid(*a, **k):
        raise AssertionError("wrote before every draft was rendered")

    monkeypatch.setattr(compile_mod, "atomic_write_text", forbid)
    path = _transcript(cfg.library_root.parent,
                       ("assistant", "## one\n\n" + _fence("bash", "echo one")),
                       ("assistant", "## two\n\n" + _fence("bash", "ls -la /tmp")))
    with pytest.raises(EmitterError):
        compile_transcript(cfg, path, registry=EmitterRegistry([ExplodingOnSecond()]))
    monkeypatch.setattr(compile_mod, "atomic_write_text", real)


# ---------------------------------------------------------------------------
# Item 2 — collision resolution against the library
# ---------------------------------------------------------------------------
def test_existing_draft_is_never_overwritten_and_gets_suffix(cfg):
    existing = cfg.library_root / "artifacts/drafts/scripts/disk-audit.sh"
    existing.write_text("operator's own edits\n", encoding="utf-8")
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    assert existing.read_text(encoding="utf-8") == "operator's own edits\n"
    bash = next(d for d in outcome.drafts if d.emitter == "bash")
    assert bash.path.name == "disk-audit-2.sh"
    assert bash.proposed_filename == "disk-audit.sh" and bash.renamed
    assert bash.candidate.name_proposal == "disk-audit-2"


def test_suffixed_header_names_the_file_it_is_in(cfg):
    compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    second = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    for d in second.drafts:
        assert d.renamed
        text = d.path.read_text(encoding="utf-8")
        assert (f"name:        {d.path.name}\n" in text
                or f'name: "{d.path.name}"\n' in text), d.path


def test_second_compile_suffixes_every_draft_and_keeps_the_first(cfg):
    first = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    snapshot = {d.path: d.path.read_bytes() for d in first.drafts}
    second = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    third = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    assert {p: p.read_bytes() for p in snapshot} == snapshot
    assert {d.path.name for d in second.drafts} == {
        "disk-audit-2.sh", "disk_audit_python_2.py",
        "disk-audit-powershell-2.ps1", "largest-tables-2.sql",
        "summarize-audit-2.md", "disk-full-runbook-2.md"}
    assert all(d.path.stem.endswith(("-3", "_3")) for d in third.drafts)


def test_python_suffix_follows_the_emitters_snake_case(cfg):
    (cfg.library_root / "artifacts/drafts/scripts/disk_audit_python.py").write_text("x")
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    py = next(d for d in outcome.drafts if d.emitter == "python")
    assert py.path.name == "disk_audit_python_2.py"


def test_collision_with_approved_artifact_counts(cfg):
    approved = cfg.library_root / "artifacts/approved/prompts/summarize-audit.md"
    approved.write_text("approved\n", encoding="utf-8")
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    prompt = next(d for d in outcome.drafts if d.emitter == "prompt")
    assert prompt.path == (cfg.library_root
                           / "artifacts/drafts/prompts/summarize-audit-2.md")
    assert approved.read_text(encoding="utf-8") == "approved\n"


def test_collisions_only_within_the_same_kind_directory(cfg):
    """A prompt and a runbook may share a filename: different directories."""
    (cfg.library_root / "artifacts/drafts/runbooks/summarize-audit.md").write_text("x")
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    prompt = next(d for d in outcome.drafts if d.emitter == "prompt")
    assert not prompt.renamed


def test_two_candidates_in_one_run_claiming_one_filename(cfg, tmp_path):
    class ShForAll(BashEmitter):
        """Claims bash *and* powershell, so both land as `<name>.sh`."""
        def supports(self, candidate):
            return candidate.lang in {"bash", "powershell"}

    path = _transcript(tmp_path,
                       ("assistant", "## deploy\n\n" + _fence("bash", "make deploy")),
                       ("assistant", "## deploy\n\n" + _fence("pwsh", "Invoke-Deploy -Now")))
    registry = EmitterRegistry([ShForAll()])
    planned = compile_transcript(cfg, path, registry=registry, dry_run=True,
                                 compiled_at=TS)
    assert [d.path.name for d in planned.drafts] == ["deploy.sh", "deploy-2.sh"]
    outcome = compile_transcript(cfg, path, registry=registry, compiled_at=TS)
    assert [d.path.name for d in outcome.drafts] == ["deploy.sh", "deploy-2.sh"]
    assert all(d.path.is_file() for d in outcome.drafts)


def test_dry_run_and_real_run_propose_the_same_names(cfg):
    (cfg.library_root / "artifacts/drafts/scripts/disk-audit.sh").write_text("x")
    planned = compile_transcript(cfg, POLYGLOT, dry_run=True, compiled_at=TS)
    real = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    assert [d.path for d in planned.drafts] == [d.path for d in real.drafts]


def test_file_appearing_after_planning_is_not_clobbered(cfg, monkeypatch):
    """TOCTOU: another writer takes the name between check and write. The
    coordinator moves to the next suffix and re-renders the header."""
    real = compile_mod.atomic_write_text
    raced: list[Path] = []

    def racing_write(path, text, *, exist_ok=True):
        if not raced and path.name == "disk-audit.sh":
            path.write_text("racer\n", encoding="utf-8")
            raced.append(path)
        return real(path, text, exist_ok=exist_ok)

    monkeypatch.setattr(compile_mod, "atomic_write_text", racing_write)
    outcome = compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    assert raced[0].read_text(encoding="utf-8") == "racer\n"
    bash = next(d for d in outcome.drafts if d.emitter == "bash")
    assert bash.path.name == "disk-audit-2.sh" and bash.written
    assert "# name:        disk-audit-2.sh\n" in bash.path.read_text(encoding="utf-8")


def test_collision_resolution_gives_up_instead_of_spinning(cfg, monkeypatch):
    monkeypatch.setattr(compile_mod, "MAX_COLLISION_SUFFIX", 3)
    drafts = cfg.library_root / "artifacts/drafts/scripts"
    for name in ("disk-audit.sh", "disk-audit-2.sh", "disk-audit-3.sh"):
        (drafts / name).write_text("x")
    before = _snapshot(cfg.library_root)
    with pytest.raises(LibraryError, match="no free filename"):
        compile_transcript(cfg, POLYGLOT)
    assert _snapshot(cfg.library_root) == before


# ---------------------------------------------------------------------------
# Item 3 — fence accounting through emission
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dry_run", [False, True])
def test_accounting_holds_with_every_emitter_enabled(cfg, dry_run):
    outcome = compile_transcript(cfg, POLYGLOT, dry_run=dry_run, compiled_at=TS)
    acc = outcome.accounting
    assert acc == {"fences_seen": 10, "drafts": 6,
                   "written": 0 if dry_run else 6, "skipped": 4,
                   "unsupported": 0}
    assert acc["fences_seen"] == acc["drafts"] + acc["skipped"] + acc["unsupported"]


@pytest.mark.parametrize("dry_run", [False, True])
def test_disabled_emitters_surface_as_unsupported_not_dropped(cfg, dry_run):
    cfg = replace(cfg, enabled_emitters=("bash", "python"))
    outcome = compile_transcript(cfg, POLYGLOT, dry_run=dry_run, compiled_at=TS)
    acc = outcome.accounting
    assert (acc["drafts"], acc["skipped"], acc["unsupported"]) == (2, 4, 4)
    assert acc["fences_seen"] == 10 == acc["drafts"] + acc["skipped"] + acc["unsupported"]
    assert {s.reason for s in outcome.unsupported} == {"unsupported-emitter"}
    assert {s.lang for s in outcome.unsupported} == {
        "powershell", "sql", "prompt", "markdown"}
    written = {p.name for p in (cfg.library_root / "artifacts/drafts").rglob("*")
               if p.is_file()}
    assert written == (set() if dry_run else {"disk-audit.sh", "disk_audit_python.py"})


def test_accounting_counts_superseded_and_empty(cfg, tmp_path):
    path = _transcript(tmp_path,
                       ("assistant", "## backup\n\n" + _fence("bash", "tar czf b.tgz /etc")),
                       ("assistant", "## backup\n\n" + _fence("bash", "tar czf b.tgz /etc /home")),
                       ("assistant", _fence("bash", "")))
    outcome = compile_transcript(cfg, path, compiled_at=TS)
    acc = outcome.accounting
    assert (acc["fences_seen"], acc["drafts"], acc["skipped"]) == (3, 1, 2)
    assert {s.reason for s in outcome.skipped} == {"superseded", "empty"}


def test_accounting_self_check_fires_before_any_write(cfg, monkeypatch):
    """If a stage ever drops a candidate, compile refuses instead of writing
    a short set of drafts."""
    real_assign = EmitterRegistry.assign

    def lossy_assign(self, candidates):
        a = real_assign(self, candidates)
        return replace(a, assigned=a.assigned[1:])

    monkeypatch.setattr(EmitterRegistry, "assign", lossy_assign)
    before = _snapshot(cfg.library_root)
    with pytest.raises(AssertionError, match="compile accounting broken"):
        compile_transcript(cfg, POLYGLOT)
    assert _snapshot(cfg.library_root) == before


# ---------------------------------------------------------------------------
# Invariants — dry run, secret refusal, no event, contract-free core
# ---------------------------------------------------------------------------
def test_dry_run_writes_nothing_and_appends_no_event(cfg):
    before = _snapshot(cfg.library_root)
    outcome = compile_transcript(cfg, POLYGLOT, dry_run=True, compiled_at=TS)
    assert _snapshot(cfg.library_root) == before
    assert outcome.dry_run and outcome.written == ()
    assert _rel(outcome) == POLYGLOT_DRAFTS
    assert not any(d.path.exists() for d in outcome.drafts)


def test_real_compile_appends_no_event_yet(cfg):
    """Open decision (HANDOFF_NOTES WP4 item 6): no compile event until the
    legacy-ledger + ucc.event dual-write shape is settled."""
    paths = LibraryPaths(cfg.library_root)
    events_before = paths.events_file.read_bytes()
    compile_transcript(cfg, POLYGLOT, compiled_at=TS)
    assert paths.events_file.read_bytes() == events_before
    assert not paths.ucc_events_file.exists()


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("where", ["assistant-fence", "user-fence", "prose",
                                   "unsupported-fence"])
def test_secret_refuses_entire_compile_before_any_write(cfg, tmp_path, dry_run, where):
    clean = ("assistant", "## ok\n\n" + _fence("bash", "echo fine"))
    leak = {
        "assistant-fence": ("assistant", _fence("bash", f"export T={SECRET}")),
        "user-fence": ("user", _fence("bash", f"export T={SECRET}")),
        "prose": ("user", f"my token is {SECRET}, keep it safe"),
        "unsupported-fence": ("assistant", _fence("yaml", f"token: {SECRET}")),
    }[where]
    path = _transcript(tmp_path, clean, leak)
    before = _snapshot(cfg.library_root)
    with pytest.raises(SecretDetected):
        compile_transcript(cfg, path, dry_run=dry_run)
    assert _snapshot(cfg.library_root) == before


def test_secret_is_refused_before_parse_errors_can_quote_it(cfg, tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text(f"---\nkind: transcript\ntoken {SECRET}\n---\n", encoding="utf-8")
    with pytest.raises(SecretDetected) as exc:
        compile_transcript(cfg, bad)
    assert SECRET not in str(exc.value)


def test_secret_refusal_honours_library_scrub_patterns(cfg, tmp_path):
    (cfg.library_root / "scrub-patterns.toml").write_text(
        '[patterns]\ncorp = "CORP-[0-9]{6}"\n', encoding="utf-8")
    path = _transcript(tmp_path, ("assistant", _fence("bash", "curl -H CORP-123456 x")))
    with pytest.raises(SecretDetected) as exc:
        compile_transcript(cfg, path)
    assert exc.value.label == "corp"


_EDGE_MODULES = {"ucc_contracts", "soloctl.ucc_events", "soloctl.artifact_store",
                 "soloctl.artifact_port", "soloctl.idempotency_store",
                 "soloctl.idempotent_import"}


def _imports(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            names.add(base)
            names.update(f"{base}.{a.name}" for a in node.names)
    return names


def test_compile_module_imports_no_contract_edge_module():
    found = _imports(Path(compile_mod.__file__))
    edge_leaves = {m.rsplit(".", 1)[-1] for m in _EDGE_MODULES}
    hits = {n for n in found
            if n.split(".")[0] == "ucc_contracts"
            or any(part in edge_leaves for part in n.lstrip(".").split("."))}
    assert not hits, f"compile.py must stay contract-free, imports {hits}"


def test_compile_module_loads_without_ucc_contracts():
    """Transitive check: importing the coordinator pulls in no edge module."""
    code = ("import sys, soloctl.compiler.compile\n"
            f"bad = sorted(m for m in sys.modules if m.split('.')[0] == 'ucc_contracts' "
            f"or m in {sorted(_EDGE_MODULES)!r})\n"
            "print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == ""


# ---------------------------------------------------------------------------
# CLI — thin wrapper
# ---------------------------------------------------------------------------
runner = CliRunner()


def test_cli_compile_writes_and_reports_accounting(cfg):
    res = runner.invoke(cli.app, ["compile", str(POLYGLOT),
                                  "--library", str(cfg.library_root)])
    assert res.exit_code == 0, res.output
    assert "wrote: artifacts/drafts/scripts/disk-audit.sh  [bash]" in res.output
    assert "fences: 10 = 6 written + 4 skipped + 0 unsupported" in res.output
    assert (cfg.library_root / "artifacts/drafts/runbooks/disk-full-runbook.md").is_file()


def test_cli_compile_dry_run(cfg):
    before = _snapshot(cfg.library_root)
    res = runner.invoke(cli.app, ["compile", str(POLYGLOT), "--dry-run",
                                  "--library", str(cfg.library_root)])
    assert res.exit_code == 0, res.output
    assert "would write: artifacts/drafts/prompts/summarize-audit.md" in res.output
    assert "fences: 10 = 6 planned + 4 skipped + 0 unsupported" in res.output
    assert "nothing written (--dry-run)" in res.output
    assert _snapshot(cfg.library_root) == before


def test_cli_compile_reports_renames(cfg):
    runner.invoke(cli.app, ["compile", str(POLYGLOT), "--library", str(cfg.library_root)])
    res = runner.invoke(cli.app, ["compile", str(POLYGLOT),
                                  "--library", str(cfg.library_root)])
    assert "disk-audit-2.sh  [bash]  (renamed from disk-audit.sh)" in res.output


def test_cli_compile_secret_exits_2(cfg, tmp_path):
    path = _transcript(tmp_path, ("assistant", _fence("bash", f"T={SECRET}")))
    res = runner.invoke(cli.app, ["compile", str(path), "--library", str(cfg.library_root)])
    assert res.exit_code == 2
    assert "REFUSED" in res.output and "Nothing was written" in res.output


def test_cli_compile_error_exits_1(tmp_path):
    res = runner.invoke(cli.app, ["compile", str(POLYGLOT),
                                  "--library", str(tmp_path / "missing")])
    assert res.exit_code == 1
    assert "soloctl init" in res.output
