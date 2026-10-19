import pytest

from docs_checker.request import RunRequest, parse_request


def test_parse_request_forms():
    assert parse_request("check all", None) == RunRequest(scope="all")
    assert parse_request("Check ALL at feature/x", None) == RunRequest(scope="all", ref="feature/x")
    r = parse_request("check docs/a.md, base-apps/x/docs/b.md at abc1234", None)
    assert r.scope == ["docs/a.md", "base-apps/x/docs/b.md"] and r.ref == "abc1234"
    assert parse_request("check docs/a.md", None).ref == "main"
    # the data part wins over the text
    r = parse_request("check all", {"scope": ["docs/a.md"], "mode": "scheduled", "ref": "dev"})
    assert r.scope == ["docs/a.md"] and r.mode == "scheduled" and r.ref == "dev"
    assert parse_request("hello", None) is None
    assert parse_request(None, {}) is None
    assert parse_request("please check all", None) is None


def test_out_of_scope_path_is_rejected():
    with pytest.raises(ValueError, match="docs/superpowers/x.md"):
        parse_request("check docs/superpowers/x.md", None)
    with pytest.raises(ValueError, match="notes.txt"):
        parse_request(None, {"scope": ["docs/a.md", "notes.txt"]})


@pytest.mark.parametrize("ref", ["bad ref;", "a..b", "-x", "x" * 0 + "a b"])
def test_bad_ref_is_rejected(ref):
    with pytest.raises(ValueError):
        parse_request(None, {"scope": "all", "ref": ref})
