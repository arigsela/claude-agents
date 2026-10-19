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


@pytest.mark.parametrize(
    "path",
    ["../x.md", "docs/./a.md", "docs/../a.md", "docs/a.md\n", " docs/a.md", "/docs/a.md",
     "docs//a.md", "docs\\a.md", "docs/a b.md", "docs/a\x00.md", "docs/a.md/", ""],
)  # fmt: skip
def test_unnormalized_paths_are_rejected(path):
    with pytest.raises(ValueError):
        parse_request(None, {"scope": [path]})


@pytest.mark.parametrize("ref", [None, 1234567, ["main"]])
def test_non_string_ref_is_rejected(ref):
    with pytest.raises(ValueError):
        parse_request(None, {"scope": "all", "ref": ref})


def test_scope_is_deduplicated_and_capped():
    r = parse_request(None, {"scope": ["docs/b.md", "docs/a.md", "docs/b.md"] * 1000})
    assert r.scope == ["docs/b.md", "docs/a.md"]
    many = [f"docs/{i}.md" for i in range(81)]
    with pytest.raises(ValueError, match="too many"):
        parse_request(None, {"scope": many})
    assert len(parse_request(None, {"scope": many}, max_paths=81).scope) == 81
    with pytest.raises(ValueError, match="too many"):
        parse_request("check " + ", ".join(many), None)


@pytest.mark.parametrize("data", ["scope", ["scope"], 5])
def test_non_dict_data_is_rejected(data):
    with pytest.raises(ValueError, match="object"):
        parse_request("check all", data)
