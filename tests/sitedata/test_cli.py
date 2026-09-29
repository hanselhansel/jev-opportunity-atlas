import subprocess
from pathlib import Path

from atlas import cli as atlas_cli


def test_site_build_invokes_npm_with_env(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr("atlas.paths.ROOT", tmp_path)
    parser = atlas_cli.build_parser()
    args = parser.parse_args(
        ["site", "build", "--production", "--data", "D", "--base", "/x/"]
    )
    args.func(args)
    (a, k) = calls[0]
    assert a[0] == ["npm", "run", "build"]
    assert k["cwd"] == tmp_path / "site"
    assert k["env"]["ATLAS_SITE_DATA"] == str(Path("D").resolve())
    assert k["env"]["ATLAS_SITE_MODE"] == "production"
    assert k["env"]["ATLAS_SITE_BASE"] == "/x/"
    assert k["check"] is True


def test_site_build_data_path_is_absolute_before_npm(monkeypatch, tmp_path):
    """npm runs in site/, so a relative --data must be resolved first."""
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr("atlas.paths.ROOT", tmp_path)
    parser = atlas_cli.build_parser()
    for cmd in (["site", "build"], ["site", "preview"]):
        calls.clear()
        args = parser.parse_args([*cmd, "--data", "site/data-real"])
        args.func(args)
        data = calls[0][1]["env"]["ATLAS_SITE_DATA"]
        assert Path(data).is_absolute()
        assert data == str(Path("site/data-real").resolve())


def test_site_preview_invokes_npm_dev(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr("atlas.paths.ROOT", tmp_path)
    monkeypatch.delenv("ATLAS_SITE_DATA", raising=False)
    parser = atlas_cli.build_parser()
    args = parser.parse_args(["site", "preview"])
    args.func(args)
    (a, k) = calls[0]
    assert a[0] == ["npm", "run", "dev"]
    assert k["cwd"] == tmp_path / "site"
