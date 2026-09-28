"""Secret scanner. Every secret-shaped string is built at runtime so no literal ever
sits in the repository (and the hook does not block its own tests)."""

from atlas.publication.secret_scan import scan_paths, scan_text

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64
OTHER_KEY = "apikey_" + "1" * 36 + "_" + "e" * 64
AWS = "AKIA" + "B" * 16
PEM = "-----BEGIN " + "RSA PRIVATE" + " KEY-----"


def test_typesafe_key_shape_is_caught():
    hits = scan_text(f"TYPESAFE_API_KEY={CANARY}\n", "x.env")
    assert [h.rule for h in hits] == ["typesafe-api-key"]


def test_findings_never_contain_any_match():
    line = f"a {CANARY} b {OTHER_KEY} c {AWS}"
    hits = scan_text(line, "log.txt")
    blob = repr(hits) + "".join(str(h) for h in hits)
    for secret in (CANARY, OTHER_KEY, AWS):
        assert secret not in blob
    assert {h.rule for h in hits} == {"typesafe-api-key", "aws-access-key"}
    assert len([h for h in hits if h.rule == "typesafe-api-key"]) == 2


def test_other_common_secrets_are_caught():
    text = "\n".join(
        [
            "ghp_" + "a" * 36,
            AWS,
            PEM,
            "Authorization: Bearer " + "c" * 40,
        ]
    )
    rules = {h.rule for h in scan_text(text, "log.txt")}
    assert rules == {"github-token", "aws-access-key", "private-key", "bearer-token"}


def test_uppercase_and_url_encoded_keys_are_caught():
    upper = "APIKEY_" + "A" * 36 + "_" + "F" * 64
    encoded = "apikey%5F" + "0" * 36 + "%5F" + "f" * 64
    assert {h.rule for h in scan_text(f"{upper}\n{encoded}", "x")} == {
        "typesafe-api-key"
    }


def test_placeholders_pass():
    assert (
        scan_text("TYPESAFE_API_KEY=\nkey = os.environ['TYPESAFE_API_KEY']\n", "a.py")
        == []
    )


def test_scan_paths_reports_file_and_line(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("ok\nsecret " + CANARY + "\n")
    hits = scan_paths([p])
    assert (hits[0].path, hits[0].line) == (str(p), 2)
