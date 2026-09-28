import subprocess

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
    assert k["env"]["ATLAS_SITE_DATA"] == "D"
    assert k["env"]["ATLAS_SITE_MODE"] == "production"
    assert k["env"]["ATLAS_SITE_BASE"] == "/x/"
    assert k["check"] is True


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
