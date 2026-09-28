import subprocess

from atlas.publication import scan_cli

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    )


def test_staged_blob_is_scanned_not_the_working_copy(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    f = tmp_path / "my notes.txt"  # space in the name on purpose
    f.write_text(f"key {CANARY}\n")
    git(tmp_path, "add", "my notes.txt")
    f.write_text("clean now\n")  # working copy is clean, staged blob is not
    monkeypatch.chdir(tmp_path)
    hits = scan_cli.staged_findings()
    assert [(h.rule, h.path) for h in hits] == [("typesafe-api-key", "my notes.txt")]


def test_clean_stage_passes(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n")
    git(tmp_path, "add", "a.py")
    monkeypatch.chdir(tmp_path)
    assert scan_cli.main(["--staged"]) == 0
