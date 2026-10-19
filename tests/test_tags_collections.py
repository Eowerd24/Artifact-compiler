"""WP4 item 5: tags and collections. Library-level registries, references
as `<kind>/<filename>` with a `compiled:` generation stamp, idempotent
atomic writes, path containment, and a contract-free core."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import soloctl.library.collections as collections_mod
import soloctl.library.refs as refs_mod
import soloctl.library.tags as tags_mod
from soloctl import cli
from soloctl.compiler.compile import compile_transcript
from soloctl.config import SoloctlConfig
from soloctl.errors import (
    AmbiguousArtifactError, CollectionConflictError, InvalidNameError,
    LibraryError, PathEscapesLibraryError, RegistryCorruptError,
    StaleReferenceError, UnknownArtifactError, UnknownCollectionError,
)
from soloctl.library.collections import (
    add_members, create_collection, list_collections, remove_members,
    show_collection,
)
from soloctl.library.paths import LibraryPaths
from soloctl.library.refs import read_compiled_stamp
from soloctl.library.repository import init_library
from soloctl.library.tags import (
    add_tags, all_tags, artifact_tags, artifacts_with_tag, remove_tags,
)

POLYGLOT = Path(__file__).parent / "fixtures" / "transcript-polyglot.md"
TS = "2026-10-19T12:00:00.000+00:00"
TS2 = "2026-10-20T08:00:00.000+00:00"
STAMP = f"soloctl 0.1.0 {TS}"
SH, SQL, PROMPT = "scripts/disk-audit.sh", "scripts/largest-tables.sql", "prompts/summarize-audit.md"


@pytest.fixture
def cfg(tmp_path) -> SoloctlConfig:
    config = SoloctlConfig(library_root=tmp_path / "library")
    init_library(config)
    compile_transcript(config, POLYGLOT, compiled_at=TS)
    return config


def lib(cfg: SoloctlConfig) -> LibraryPaths:
    return LibraryPaths(cfg.library_root)


def draft(cfg: SoloctlConfig, ref: str) -> Path:
    return lib(cfg).drafts / ref


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def forbid_writes(monkeypatch) -> None:
    """Make any registry write fail: for asserting that a no-op writes nothing."""
    monkeypatch.setattr(refs_mod, "atomic_write_text",
                        lambda *a, **k: pytest.fail("a no-op operation wrote a file"))


# --------------------------------------------------------------------------
# Generation stamp
# --------------------------------------------------------------------------
@pytest.mark.parametrize("ref", [SH, "scripts/disk_audit_python.py",
                                 "scripts/disk-audit-powershell.ps1", SQL, PROMPT,
                                 "runbooks/disk-full-runbook.md"])
def test_every_emitter_format_carries_a_readable_stamp(cfg, ref):
    assert read_compiled_stamp(draft(cfg, ref)) == STAMP


def test_stamp_is_read_from_the_header_only(tmp_path):
    body_only = tmp_path / "x.sh"
    body_only.write_text("#!/usr/bin/env bash\nset -e\n# compiled:    fake\n")
    assert read_compiled_stamp(body_only) is None
    front = tmp_path / "x.md"
    front.write_text('---\nkind: "prompt"\n---\n\ncompiled: "fake"\n')
    assert read_compiled_stamp(front) is None


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------
def test_add_tags_writes_a_deterministic_registry(cfg):
    change = add_tags(cfg, SH, ["linux", "disk"])
    assert (change.ref, change.changed, change.tags, change.written) == (
        SH, ("linux", "disk"), ("disk", "linux"), True)
    doc = json.loads(lib(cfg).tags_file.read_text())
    assert doc == {"schema": "soloctl.tags/1",
                   "artifacts": {SH: {"compiled": STAMP, "tags": ["disk", "linux"]}}}
    assert lib(cfg).tags_file.read_text().endswith("}\n")


def test_registry_bytes_do_not_depend_on_operation_order(cfg, tmp_path):
    add_tags(cfg, SQL, ["db"])
    add_tags(cfg, SH, ["linux", "disk"])
    first = lib(cfg).tags_file.read_bytes()
    lib(cfg).tags_file.unlink()
    add_tags(cfg, SH, ["disk"])
    add_tags(cfg, SH, ["linux"])
    add_tags(cfg, SQL, ["db"])
    assert lib(cfg).tags_file.read_bytes() == first


def test_add_tags_is_idempotent_and_a_noop_writes_nothing(cfg, monkeypatch):
    add_tags(cfg, SH, ["disk"])
    before = lib(cfg).tags_file.read_bytes()
    forbid_writes(monkeypatch)
    again = add_tags(cfg, SH, ["disk"])
    assert (again.changed, again.unchanged, again.written) == ((), ("disk",), False)
    assert lib(cfg).tags_file.read_bytes() == before


def test_duplicate_tags_in_one_call_collapse(cfg):
    change = add_tags(cfg, SH, ["disk", "disk", "linux", "disk"])
    assert change.changed == ("disk", "linux") and change.tags == ("disk", "linux")


def test_remove_tags_is_idempotent_and_drops_empty_entries(cfg, monkeypatch):
    add_tags(cfg, SH, ["disk", "linux"])
    assert remove_tags(cfg, SH, ["disk"]).tags == ("linux",)
    last = remove_tags(cfg, SH, ["linux"])
    assert last.written and last.tags == ()
    assert json.loads(lib(cfg).tags_file.read_text())["artifacts"] == {}
    forbid_writes(monkeypatch)
    noop = remove_tags(cfg, SH, ["linux"])
    assert (noop.changed, noop.unchanged, noop.written) == ((), ("linux",), False)


def test_tagging_never_changes_an_artifact(cfg):
    before = tree(lib(cfg).artifacts)
    add_tags(cfg, SH, ["disk"])
    remove_tags(cfg, SH, ["disk"])
    assert tree(lib(cfg).artifacts) == before


@pytest.mark.parametrize("arg", [
    SH, f"artifacts/drafts/{SH}", "ABSOLUTE",
])
def test_artifact_argument_forms_normalize_to_one_ref(cfg, arg):
    if arg == "ABSOLUTE":
        arg = str(draft(cfg, SH))
    assert add_tags(cfg, arg, ["disk"]).ref == SH


def test_unknown_artifacts_are_refused(cfg):
    with pytest.raises(UnknownArtifactError, match="no artifact scripts/nope.sh"):
        add_tags(cfg, "scripts/nope.sh", ["x"])
    with pytest.raises(UnknownArtifactError, match="not a soloctl artifact"):
        add_tags(cfg, "notes/x.txt", ["x"])
    with pytest.raises(UnknownArtifactError, match="no artifact"):
        remove_tags(cfg, "scripts/nope.sh", ["x"])
    with pytest.raises(UnknownArtifactError, match="no artifact"):
        artifact_tags(cfg, "scripts/nope.sh")
    assert not lib(cfg).tags_file.exists()


def test_a_file_without_a_stamp_cannot_be_tagged(cfg):
    hand = draft(cfg, "scripts/hand-written.sh")
    hand.write_text("#!/usr/bin/env bash\necho hi\n")
    with pytest.raises(UnknownArtifactError, match="no `compiled:` header"):
        add_tags(cfg, "scripts/hand-written.sh", ["x"])


@pytest.mark.parametrize("bad", ["", "Disk", "disk tag", "-disk", "disk/x", "../x",
                                 "a" * 49, "disk_audit", "dïsk", ".hidden"])
def test_invalid_tag_names_are_refused_before_anything_is_read(cfg, bad):
    with pytest.raises(InvalidNameError):
        add_tags(cfg, SH, ["ok", bad])
    assert not lib(cfg).tags_file.exists()


def test_invalid_name_message_suggests_the_slug(cfg):
    with pytest.raises(InvalidNameError, match="try 'disk-tag'"):
        add_tags(cfg, SH, ["Disk Tag"])


def test_no_tags_given_is_refused(cfg):
    with pytest.raises(InvalidNameError, match="no tags given"):
        add_tags(cfg, SH, [])


def test_queries(cfg):
    add_tags(cfg, SH, ["disk", "linux"])
    add_tags(cfg, SQL, ["disk"])
    assert all_tags(cfg) == {"disk": (SH, SQL), "linux": (SH,)}
    assert [(a.ref, a.status) for a in artifacts_with_tag(cfg, "disk")] == [
        (SH, "draft"), (SQL, "draft")]
    assert artifact_tags(cfg, PROMPT).tags == ()
    assert artifact_tags(cfg, SH).tags == ("disk", "linux")


# --------------------------------------------------------------------------
# References across moves, deletion and name reuse
# --------------------------------------------------------------------------
def test_approval_move_keeps_the_reference(cfg):
    add_tags(cfg, SH, ["disk"])
    approved = lib(cfg).approved / SH
    draft(cfg, SH).rename(approved)
    assert artifact_tags(cfg, SH).status == "approved"
    assert add_tags(cfg, str(approved), ["linux"]).ref == SH


def test_deleted_artifact_reads_missing_and_can_still_be_cleaned_up(cfg):
    add_tags(cfg, SH, ["disk"])
    draft(cfg, SH).unlink()
    assert artifact_tags(cfg, SH).status == "missing"
    assert remove_tags(cfg, SH, ["disk"]).written


def test_reused_name_is_stale_never_reattached(cfg):
    add_tags(cfg, SH, ["disk"])
    create_collection(cfg, "ops")
    add_members(cfg, "ops", [SH])
    draft(cfg, SH).unlink()
    compile_transcript(cfg, POLYGLOT, compiled_at=TS2)     # re-claims disk-audit.sh
    assert read_compiled_stamp(draft(cfg, SH)) == f"soloctl 0.1.0 {TS2}"
    assert artifact_tags(cfg, SH).status == "stale"
    assert show_collection(cfg, "ops").members[0].status == "stale"
    with pytest.raises(StaleReferenceError, match="soloctl tag remove scripts/disk-audit.sh disk"):
        add_tags(cfg, SH, ["linux"])
    with pytest.raises(StaleReferenceError, match="soloctl collection remove ops"):
        add_members(cfg, "ops", [SH])
    remove_tags(cfg, SH, ["disk"])
    remove_members(cfg, "ops", [SH])
    assert add_tags(cfg, SH, ["linux"]).written
    assert add_members(cfg, "ops", [SH]).collection.members[0].compiled.endswith(TS2)


def test_same_name_in_drafts_and_approved_is_refused(cfg):
    approved = lib(cfg).approved / SH
    approved.write_bytes(draft(cfg, SH).read_bytes())
    with pytest.raises(AmbiguousArtifactError, match="both drafts/ and approved/"):
        add_tags(cfg, SH, ["disk"])


# --------------------------------------------------------------------------
# Path containment
# --------------------------------------------------------------------------
@pytest.mark.parametrize("arg", ["scripts/../../../etc/passwd", "../etc/passwd",
                                 "scripts/x/../../y.sh", "/etc/passwd",
                                 "artifacts/drafts/../../tags.json", "scripts/.x.sh"])
def test_artifact_arguments_cannot_leave_the_kind_directories(cfg, arg):
    with pytest.raises(UnknownArtifactError):
        add_tags(cfg, arg, ["x"])


def test_symlink_out_of_the_library_is_refused(cfg, tmp_path):
    outside = tmp_path / "outside.sh"
    outside.write_text(draft(cfg, SH).read_text())
    draft(cfg, "scripts/evil.sh").symlink_to(outside)
    with pytest.raises(PathEscapesLibraryError):
        add_tags(cfg, "scripts/evil.sh", ["x"])


@pytest.mark.parametrize("bad", ["../tags", "a/b", "/abs", "Ops", "ops.json", ".x", ""])
def test_collection_names_cannot_escape_or_be_invalid(cfg, bad):
    with pytest.raises(InvalidNameError):
        create_collection(cfg, bad)
    assert list(lib(cfg).collections.iterdir()) == []


def test_collection_files_land_in_collections_dir(cfg):
    create_collection(cfg, "ops")
    assert [p.name for p in lib(cfg).collections.iterdir()] == ["ops.json"]


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------
def test_create_is_idempotent_and_conflicts_are_refused(cfg, monkeypatch):
    first = create_collection(cfg, "ops", title="Ops kit", description="fleet tools")
    assert first.created
    before = lib(cfg).collection_file("ops").read_bytes()
    forbid_writes(monkeypatch)
    assert create_collection(cfg, "ops").created is False
    assert create_collection(cfg, "ops", title="Ops kit").created is False
    with pytest.raises(CollectionConflictError, match="title 'Ops kit', not 'Other'"):
        create_collection(cfg, "ops", title="Other")
    assert lib(cfg).collection_file("ops").read_bytes() == before


def test_create_never_clobbers_a_concurrent_create(cfg, monkeypatch):
    real = refs_mod.atomic_write_text

    def racing(path, text, *, exist_ok=True):
        real(path, text.replace('"title": ""', '"title": "theirs"'), exist_ok=True)
        real(path, text, exist_ok=exist_ok)              # ours: must refuse
    monkeypatch.setattr(refs_mod, "atomic_write_text", racing)
    change = create_collection(cfg, "ops")
    assert change.created is False and change.collection.title == "theirs"
    with pytest.raises(CollectionConflictError):
        create_collection(cfg, "ops", title="mine")


def test_members_keep_order_and_duplicates_collapse(cfg):
    create_collection(cfg, "ops")
    change = add_members(cfg, "ops", [SQL, SH, SQL, f"artifacts/drafts/{SH}"])
    assert change.changed == (SQL, SH)
    assert [m.ref for m in change.collection.members] == [SQL, SH]
    again = add_members(cfg, "ops", [SH, PROMPT])
    assert again.changed == (PROMPT,) and again.unchanged == (SH,)
    assert [m.ref for m in again.collection.members] == [SQL, SH, PROMPT]


def test_add_members_is_idempotent_and_a_noop_writes_nothing(cfg, monkeypatch):
    create_collection(cfg, "ops")
    add_members(cfg, "ops", [SH])
    forbid_writes(monkeypatch)
    assert add_members(cfg, "ops", [SH]).written is False


def test_add_members_is_all_or_nothing(cfg):
    create_collection(cfg, "ops")
    before = lib(cfg).collection_file("ops").read_bytes()
    with pytest.raises(UnknownArtifactError):
        add_members(cfg, "ops", [SH, "scripts/nope.sh"])
    assert lib(cfg).collection_file("ops").read_bytes() == before


def test_remove_members_idempotent_and_works_on_missing_files(cfg, monkeypatch):
    create_collection(cfg, "ops")
    add_members(cfg, "ops", [SH, SQL])
    draft(cfg, SQL).unlink()
    assert show_collection(cfg, "ops").members[1].status == "missing"
    change = remove_members(cfg, "ops", [SQL, SQL])
    assert change.changed == (SQL,) and [m.ref for m in change.collection.members] == [SH]
    forbid_writes(monkeypatch)
    noop = remove_members(cfg, "ops", [PROMPT])
    assert noop.written is False and noop.unchanged == (PROMPT,)
    with pytest.raises(UnknownArtifactError):
        remove_members(cfg, "ops", [SQL])      # not a member and gone from disk


def test_unknown_collection_is_refused(cfg):
    for call in (lambda: add_members(cfg, "nope", [SH]),
                 lambda: remove_members(cfg, "nope", [SH]),
                 lambda: show_collection(cfg, "nope")):
        with pytest.raises(UnknownCollectionError, match="soloctl collection create nope"):
            call()
    assert list(lib(cfg).collections.iterdir()) == []


def test_list_collections_sorted_and_ignores_non_collections(cfg):
    create_collection(cfg, "zeta")
    create_collection(cfg, "alpha", title="A")
    (lib(cfg).collections / ".alpha.json.abc.tmp").write_text("{")
    (lib(cfg).collections / "README.md").write_text("notes")
    (lib(cfg).collections / "Not A Name.json").write_text("{}")
    assert [(c.name, c.title) for c in list_collections(cfg)] == [("alpha", "A"), ("zeta", "")]


# --------------------------------------------------------------------------
# Corrupt registries fail closed and are never overwritten
# --------------------------------------------------------------------------
@pytest.mark.parametrize("content", [
    "{not json", '{"schema": "other/1", "artifacts": {}}', "[]",
    '{"schema": "soloctl.tags/1", "artifacts": {"../x.sh": {"compiled": "s", "tags": ["a"]}}}',
    '{"schema": "soloctl.tags/1", "artifacts": {"scripts/x.sh": {"compiled": "s", "tags": ["BAD"]}}}',
    '{"schema": "soloctl.tags/1", "artifacts": {"scripts/x.sh": {"tags": ["a"]}}}',
])
def test_corrupt_tags_file_is_refused_and_left_alone(cfg, content):
    lib(cfg).tags_file.write_text(content)
    with pytest.raises(RegistryCorruptError, match="fix or remove it by hand"):
        add_tags(cfg, SH, ["disk"])
    assert lib(cfg).tags_file.read_text() == content


@pytest.mark.parametrize("content", [
    "{", '{"schema": "soloctl.collection/1", "name": "other", "title": "", '
         '"description": "", "members": []}',
    '{"schema": "soloctl.collection/1", "name": "ops", "title": "", "description": "", '
    '"members": [{"ref": "/etc/passwd", "compiled": "s"}]}',
    '{"schema": "soloctl.collection/1", "name": "ops", "title": "", "description": "", '
    '"members": [{"ref": "scripts/a.sh", "compiled": "s"}, {"ref": "scripts/a.sh", "compiled": "s"}]}',
])
def test_corrupt_collection_file_is_refused_and_left_alone(cfg, content):
    path = lib(cfg).collection_file("ops")
    path.write_text(content)
    with pytest.raises(RegistryCorruptError):
        add_members(cfg, "ops", [SH])
    with pytest.raises(RegistryCorruptError):
        list_collections(cfg)
    assert path.read_text() == content


def test_uninitialized_library_is_refused(tmp_path):
    cfg = SoloctlConfig(library_root=tmp_path / "nolib")
    with pytest.raises(LibraryError, match="run 'soloctl init"):
        add_tags(cfg, SH, ["x"])
    with pytest.raises(LibraryError, match="run 'soloctl init"):
        create_collection(cfg, "ops")
    assert not (tmp_path / "nolib").exists()


def test_no_event_is_appended(cfg):
    events = lib(cfg).events_file.read_bytes()
    add_tags(cfg, SH, ["disk"])
    create_collection(cfg, "ops")
    add_members(cfg, "ops", [SH])
    assert lib(cfg).events_file.read_bytes() == events
    assert not (cfg.library_root / "events").exists()


# --------------------------------------------------------------------------
# Contract-free boundary (same rule as compile.py)
# --------------------------------------------------------------------------
_EDGE = {"ucc_contracts", "ucc_events", "artifact_store", "artifact_port",
         "idempotency_store", "idempotent_import"}
_MODULES = [refs_mod, tags_mod, collections_mod]


@pytest.mark.parametrize("mod", _MODULES, ids=lambda m: m.__name__)
def test_curation_modules_import_no_contract_edge_module(mod):
    tree_ = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree_):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [a.name for a in node.names]
        for n in names:
            assert not set(n.split(".")) & _EDGE, f"{mod.__name__} imports {n}"


def test_curation_modules_load_without_contract_modules():
    code = ("import sys, soloctl.library.tags, soloctl.library.collections\n"
            "print(','.join(sorted(m for m in sys.modules "
            f"if set(m.split('.')) & set({sorted(_EDGE)!r}))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == ""


# --------------------------------------------------------------------------
# CLI — thin wrapper
# --------------------------------------------------------------------------
runner = CliRunner()


def run(cfg: SoloctlConfig, *args: str):
    return runner.invoke(cli.app, [*args, "--library", str(cfg.library_root)])


def test_cli_tag_add_list_remove(cfg):
    res = run(cfg, "tag", "add", f"artifacts/drafts/{SH}", "disk", "linux")
    assert res.exit_code == 0, res.output
    assert "added: disk, linux" in res.output
    assert "nothing to do" in run(cfg, "tag", "add", SH, "disk").output
    assert "disk                     1" in run(cfg, "tag", "list").output
    assert f"{SH}: disk, linux" in run(cfg, "tag", "list", SH).output
    assert f"  {SH}\n" in run(cfg, "tag", "list", "--tag", "disk").output
    assert run(cfg, "tag", "list", SH, "--tag", "disk").exit_code == 1
    res = run(cfg, "tag", "remove", SH, "disk")
    assert res.exit_code == 0 and "tags: linux" in res.output


def test_cli_tag_refusals_exit_1(cfg):
    for args in (("tag", "add", "scripts/nope.sh", "x"),
                 ("tag", "add", SH, "Bad Tag"),
                 ("tag", "add", "../etc/passwd", "x")):
        res = run(cfg, *args)
        assert res.exit_code == 1 and "ERROR:" in res.output
    assert not lib(cfg).tags_file.exists()


def test_cli_collection_flow(cfg):
    res = run(cfg, "collection", "create", "ops", "--title", "Ops kit")
    assert res.exit_code == 0 and "ops: created" in res.output
    assert "already exists" in run(cfg, "collection", "create", "ops").output
    assert run(cfg, "collection", "create", "ops", "--title", "x").exit_code == 1
    res = run(cfg, "collection", "add", "ops", SH, SQL)
    assert res.exit_code == 0 and "members: 2" in res.output
    draft(cfg, SQL).unlink()
    show = run(cfg, "collection", "show", "ops").output
    assert f"1. {SH}\n" in show and f"2. {SQL}  (MISSING)" in show
    assert "ops                        2 members  Ops kit" in run(cfg, "collection", "list").output
    res = run(cfg, "collection", "remove", "ops", SQL)
    assert res.exit_code == 0 and f"removed: {SQL}" in res.output


def test_cli_collection_refusals_exit_1(cfg):
    for args in (("collection", "show", "nope"),
                 ("collection", "add", "nope", SH),
                 ("collection", "create", "../x")):
        res = run(cfg, *args)
        assert res.exit_code == 1 and "ERROR:" in res.output
