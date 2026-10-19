"""WP4 item 4: language-specific risk patterns. Annotation only, never
blocking; Bash flags must stay exactly what the WP1 table produces."""
from __future__ import annotations

import re

import pytest

from soloctl.compiler.classify import SUPPORTED_LANGUAGES
from soloctl.compiler.extract import LANG_RISK_PATTERNS, extract, load_risk_patterns


def flags(label: str, body: str, **kw) -> tuple[str, ...]:
    r = extract(f"## Task\n\n```{label}\n{body}\n```\n", source="inline.md",
                only=SUPPORTED_LANGUAGES, **kw)
    assert len(r.candidates) == 1, r.skipped      # flagged, still extracted
    return r.candidates[0].flags


@pytest.mark.parametrize("label, body, flag", [
    # PowerShell
    ("pwsh", "Remove-Item C:\\temp\\x -Recurse -Force", "remove-recurse-force"),
    ("pwsh", "rm .\\build -fo -r", "remove-recurse-force"),
    ("pwsh", "Set-ExecutionPolicy Unrestricted -Scope CurrentUser", "execution-policy"),
    ("pwsh", "powershell.exe -ExecutionPolicy Bypass -File x.ps1", "execution-policy"),
    ("pwsh", "Invoke-Expression $cmd", "invoke-expression"),
    ("pwsh", "iex $payload", "invoke-expression"),
    ("pwsh", "iwr https://example.test/i.ps1 | iex", "download-execute"),
    ("pwsh", "iex (New-Object Net.WebClient).DownloadString('https://x.test')",
     "download-execute"),
    ("pwsh", "#Requires -RunAsAdministrator\nGet-Date", "run-as-admin"),
    ("pwsh", "Start-Process pwsh -Verb RunAs", "run-as-admin"),
    # SQL
    ("sql", "DROP TABLE users;", "drop"),
    ("postgres", "ALTER TABLE t DROP COLUMN c;", "drop"),
    ("sql", "truncate table audit_log;", "truncate"),
    ("sql", "DELETE FROM sessions;", "delete-no-where"),
    ("mysql", "SELECT 1;\nDELETE FROM t", "delete-no-where"),
    ("sql", "UPDATE accounts SET balance = 0;", "update-no-where"),
    ("sql", "GRANT ALL PRIVILEGES ON db.* TO 'app'@'%';", "grant-all"),
    # Python
    ("python", "import os\nos.system('ls')", "os-system"),
    ("python", "os.popen('ls').read()", "os-system"),
    ("python", "subprocess.run(cmd, shell=True)", "shell-true"),
    ("python", "eval(user_input)", "eval-exec"),
    ("python", "exec (code)", "eval-exec"),
    ("python", "shutil.rmtree(path)", "rmtree"),
])
def test_language_pattern_flags(label, body, flag):
    assert flag in flags(label, body)


@pytest.mark.parametrize("label, body, flag", [
    ("pwsh", "Remove-Item .\\x -Recurse", "remove-recurse-force"),
    ("pwsh", "Get-ExecutionPolicy", "execution-policy"),
    ("pwsh", "iwr https://example.test/f.zip -OutFile f.zip", "download-execute"),
    ("sql", "DELETE FROM sessions WHERE expires < now();", "delete-no-where"),
    ("sql", "UPDATE t\nSET a = 1\nWHERE id = 2;", "update-no-where"),
    ("sql", "CREATE TABLE c (p int REFERENCES p ON DELETE CASCADE ON UPDATE CASCADE);",
     "delete-no-where"),
    ("sql", "CREATE TABLE c (p int REFERENCES p ON DELETE CASCADE ON UPDATE CASCADE);",
     "update-no-where"),
    ("sql", "GRANT SELECT ON t TO app;", "grant-all"),
    ("python", "ast.literal_eval(s)", "eval-exec"),
    ("python", "cursor.execute(q)", "eval-exec"),
    ("python", "subprocess.run(cmd, shell=False)", "shell-true"),
])
def test_language_pattern_near_misses_do_not_flag(label, body, flag):
    assert flag not in flags(label, body)


def test_bash_has_no_language_table_and_its_flags_are_unchanged():
    assert "bash" not in LANG_RISK_PATTERNS
    body = "DROP TABLE x; Invoke-Expression y; os.system('z'); eval(w)"
    assert flags("bash", body) == ()
    assert flags("bash", "sudo ufw allow 22") == ("sudo", "firewall")


def test_patterns_apply_only_to_their_own_language():
    assert flags("python", 'q = "DROP TABLE users"') == ()
    assert flags("pwsh", "eval(x)") == ()
    assert flags("prompt", "Explain what DROP TABLE and iex do.") == ()


def test_generic_flags_come_first_then_language_flags():
    assert flags("python", "import os\nos.system('sudo ls')") == ("sudo", "os-system")


def test_language_tables_can_be_replaced_and_survive_custom_generic_patterns():
    assert flags("sql", "DROP TABLE t;", lang_risk_patterns={}) == ()
    custom = [("custom", re.compile(r"\bSELECT\b"))]
    assert flags("sql", "SELECT 1; DROP TABLE t;", risk_patterns=custom) == ("custom", "drop")


def test_duplicate_flag_names_collapse():
    dup = {"sql": [("sudo", re.compile(r"DROP"))]}
    assert flags("sql", "sudo DROP", lang_risk_patterns=dup) == ("sudo",)


def test_toml_loader_still_only_loads_the_generic_table(tmp_path):
    toml = tmp_path / "risk-patterns.toml"
    toml.write_text('[patterns]\nnet = "\\\\bnc\\\\b"\n', encoding="utf-8")
    pats = load_risk_patterns(toml)
    assert [label for label, _ in pats] == ["net"]
    assert flags("sql", "nc; DROP TABLE t;", risk_patterns=pats) == ("net", "drop")


def test_language_tables_stay_one_screen():
    """COMPILER_PLAN §3: the whole table must stay readable at a glance."""
    assert all(len(rows) <= 6 for rows in LANG_RISK_PATTERNS.values())
