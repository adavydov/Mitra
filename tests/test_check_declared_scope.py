import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "check_declared_scope.py"
SPEC = importlib.util.spec_from_file_location("check_declared_scope", MODULE_PATH)
check_declared_scope = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(check_declared_scope)


def _run(monkeypatch, capsys, *, pr_body: str, mode: str = "auto", labels: str = ""):
    monkeypatch.setenv("PR_BODY", pr_body)
    monkeypatch.setenv("PR_LABELS", labels)
    monkeypatch.setenv("PR_BASE_SHA", "base")
    monkeypatch.setenv("PR_HEAD_SHA", "head")
    monkeypatch.setenv("SCOPE_CHECK_MODE", mode)
    monkeypatch.setattr(
        check_declared_scope,
        "_git_changed_files",
        lambda base_sha, head_sha: ["mitra_app/main.py", "tests/test_import_smoke.py"],
    )
    code = check_declared_scope.main()
    output = capsys.readouterr().out
    return code, output


def test_empty_body_uses_fallback_mode(monkeypatch, capsys):
    code, output = _run(monkeypatch, capsys, pr_body="", mode="auto")

    assert code == 0
    assert "Scope check mode: fallback" in output
    assert "falling back to changed files list" in output


def test_body_without_scope_section_uses_fallback(monkeypatch, capsys):
    body = "## Risk level\n- R2\n"
    code, output = _run(monkeypatch, capsys, pr_body=body, mode="fallback")

    assert code == 0
    assert "Scope check mode: fallback" in output
    assert "falling back to changed files list" in output


def test_valid_scope_section_passes(monkeypatch, capsys):
    body = "## Allowed file scope\n- mitra_app/*\n- tests/*\n\n## Risk level\n- R2\n"
    code, output = _run(monkeypatch, capsys, pr_body=body, mode="strict")

    assert code == 0
    assert "Scope check mode: strict" in output
    assert "Scope check passed." in output


def test_out_of_scope_changes_fail(monkeypatch, capsys):
    body = "## Allowed file scope\n- mitra_app/*\n\n## Risk level\n- R2\n"
    code, output = _run(monkeypatch, capsys, pr_body=body, mode="strict")

    assert code == 1
    assert "outside declared Allowed file scope" in output
    assert "tests/test_import_smoke.py" in output
