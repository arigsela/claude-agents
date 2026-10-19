from docs_checker.evidence import (
    decide_in_code,
    insufficient,
    is_evidence_source,
    named_thing_present,
    whole_files,
    windows_for,
)
from docs_checker.state import Claim, Window


def claim(values=("0.30.1",), keys=("version",), kind="version", **kw) -> Claim:
    return Claim(
        doc="base-apps/x/README.md", line_start=1, line_end=1, text="t",
        kind=kind, keys=list(keys), values=list(values), **kw,
    )  # fmt: skip


def lines(n, at):
    return "\n".join(at.get(i, f"filler {i}") for i in range(1, n + 1))


def test_is_evidence_source_excludes_docs_by_segment():
    for bad in ["a.md", "x/README.md", "docs/a.yaml", "base-apps/x/docs/a.yaml",
                "SPEC.md", "templates/a.yaml", "templates/sub/a.yaml"]:  # fmt: skip
        assert not is_evidence_source(bad), bad
    for good in ["base-apps/x/values.yaml", "base-apps/x.yaml", "templates-old/a.yaml",
                 "mydocs/a.yaml", "base-apps/x/docsy/a.yaml", "base-apps/x/mdfile"]:  # fmt: skip
        assert is_evidence_source(good), good


def test_window_radius_and_merge():
    text = lines(30, {10: "version: 0.30.1", 12: "again 0.30.1", 25: "pin 0.30.1"})
    ws = windows_for(claim(), {"base-apps/x/v.yaml": text})
    assert [(w.start, w.end) for w in ws] == [(7, 15), (22, 28)]
    assert ws[0].text == "\n".join(text.split("\n")[6:15])
    ws1 = windows_for(claim(), {"base-apps/x/v.yaml": text}, radius=1)
    assert [(w.start, w.end) for w in ws1] == [(9, 13), (24, 26)]


def test_window_clamped_to_file():
    ws = windows_for(claim(), {"base-apps/x/v.yaml": "0.30.1\nb"})
    assert (ws[0].start, ws[0].end) == (1, 2)


def test_a_value_found_200_times_yields_at_most_five_windows():
    text = "\n".join("v: 0.30.1" if i % 20 == 0 else "x" for i in range(1, 4001))
    ws = windows_for(claim(), {"base-apps/x/v.yaml": text})
    assert len(ws) == 5
    assert len(windows_for(claim(), {"base-apps/x/v.yaml": text}, max_windows=2)) == 2


def test_key_and_value_on_one_line_ranks_first():
    a = lines(20, {2: "tag: 0.30.1"})
    b = lines(20, {2: "version: 0.30.1"})
    ws = windows_for(claim(), {"base-apps/x/a.yaml": a, "base-apps/x/b.yaml": b})
    assert ws[0].source == "base-apps/x/b.yaml"
    assert ws[1].source == "base-apps/x/a.yaml"


def test_doc_files_never_supply_evidence():
    srcs = {
        "base-apps/x/README.md": "version: 0.30.1",
        "base-apps/x/docs/a.yaml": "version: 0.30.1",
        "docs/b.yaml": "version: 0.30.1",
        "SPEC.md": "version: 0.30.1",
        "templates/t.yaml": "version: 0.30.1",
    }
    assert windows_for(claim(), srcs) == []
    assert whole_files(srcs) == []
    assert windows_for(claim(), {**srcs, "templates-old/t.yaml": "version: 0.30.1"})
    forged = [Window(source="README.md", start=1, end=1, text="version: 0.30.1")]
    assert decide_in_code(claim(), forged, set()) is None


def test_comment_lines_are_not_hits():
    srcs = {"base-apps/x/v.yaml": "  # version: 0.30.1\nother"}
    assert windows_for(claim(), srcs) == []
    w = [Window(source="base-apps/x/v.yaml", start=1, end=1, text="# version: 0.30.1")]
    assert decide_in_code(claim(), w, set()) is None


def test_values_match_whole_tokens():
    def hit(value, line):  # value matching alone: no key, so no key-position hit (K1)
        return bool(windows_for(claim(values=(value,), keys=()), {"base-apps/x/v.yaml": line}))

    assert not hit("1.2", "version: 1.23")
    assert not hit("1.2", "version: 0.1.2")
    assert not hit("vault", "name: vault-tls")
    assert not hit("vault", "name: my-vault")
    assert not hit("0.30.1", "version: 0.30.10")
    assert hit("1.2", "version: 1.2")
    assert hit("1.2", "version: 1.2.")
    assert hit("0.30.1", 'image: "app:0.30.1"')
    assert hit("Vault", "name: Vault")
    assert not hit("Vault", "name: vault")  # values are case-sensitive
    # A dotted name's tail is not the name; a port inside a longer number is not the port;
    # quotes and a digest around a value do not hide it.
    assert not hit("example.com", "host: mail.example.com")
    assert hit("example.com", "host: example.com")
    assert not hit("8080", "port: 18080")
    assert not hit("8080", "port: 80801")
    assert hit("8080", "containerPort: 8080")
    assert hit("1.15.6", 'tag: "1.15.6"')
    assert hit("1.15.6", f"image: vault:1.15.6@sha256:{'a' * 64}")


def test_supported_needs_key_and_value_on_one_line():
    def w(text):
        return [Window(source="base-apps/x/v.yaml", start=1, end=3, text=text)]

    d = decide_in_code(claim(), w("a: 1\nVersion: 0.30.1\nb: 2"), set())
    assert d is not None
    assert (d.verdict, d.judged_by, d.window_index) == ("supported", "code", 0)
    assert decide_in_code(claim(), w("version: 1\ntag: 0.30.1"), set()) is None
    assert decide_in_code(claim(), w("tag: 0.30.1"), set()) is None
    two = claim(values=("0.30.1", "prod"))
    assert decide_in_code(two, w("version: 0.30.1\nenv: prod"), set()) is None
    assert decide_in_code(two, w("version: 0.30.1 prod"), set()) is not None
    assert decide_in_code(claim(keys=()), w("version: 0.30.1"), set()) is None
    assert decide_in_code(claim(), w("version: 0.30.10"), set()) is None


def test_supported_reports_the_matching_window():
    ws = [
        Window(source="base-apps/x/a.yaml", start=1, end=1, text="tag: 0.30.1"),
        Window(source="base-apps/x/b.yaml", start=1, end=1, text="version: 0.30.1"),
    ]
    d = decide_in_code(claim(), ws, set())
    assert d is not None and d.window_index == 1


def test_missing_needs_confirmed_absence():
    c = claim(values=("base-apps/x/gone.yaml",), keys=(), kind="path")
    d = decide_in_code(c, [], {"base-apps/x/gone.yaml"})
    assert d is not None
    assert (d.verdict, d.judged_by, d.window_index) == ("missing", "code", None)
    assert decide_in_code(c, [], set()) is None
    assert decide_in_code(c, [], {"other"}) is None
    v = claim(values=("base-apps/x/gone.yaml",), kind="name")
    assert decide_in_code(v, [], {"base-apps/x/gone.yaml"}) is None


def test_empty_values_never_decide():
    c = claim().model_copy(update={"values": []})  # bypasses the model's min_length
    w = [Window(source="base-apps/x/v.yaml", start=1, end=1, text="version: anything")]
    assert decide_in_code(c, w, set()) is None
    assert decide_in_code(c.model_copy(update={"kind": "path"}), w, {""}) is None
    assert windows_for(c, {"base-apps/x/v.yaml": "version: anything"}) == []


def test_whole_files_and_insufficient():
    ws = whole_files({"a.yaml": "x\ny", "b.md": "z"})
    assert ws == [Window(source="a.yaml", start=1, end=2, text="x\ny")]
    assert insufficient([], claim())
    assert insufficient([Window(source="a.yaml", start=1, end=1, text="nope")], claim())
    assert not insufficient([Window(source="a.yaml", start=1, end=1, text="x 0.30.1")], claim())


def test_trailing_inline_comments_do_not_support_or_hit():
    c = claim(values=("1.2.3",))

    def w(text):
        return [Window(source="base-apps/x/v.yaml", start=1, end=1, text=text)]

    assert decide_in_code(c, w("version: 1.2.4 # was 1.2.3"), set()) is None
    assert decide_in_code(c, w("image: app:1.2.4  # bumped from 1.2.3"), set()) is None
    assert decide_in_code(c, w("version: 1.2.3 # pinned"), set()) is not None
    # the value in the comment is not a hit: the line is only a key-position window (K1)
    ws = windows_for(c, {"base-apps/x/v.yaml": "version: 1.2.4 # was 1.2.3"})
    assert insufficient(ws, c)
    assert windows_for(c.model_copy(update={"keys": []}), {"base-apps/x/v.yaml": ws[0].text}) == []


def test_missing_needs_every_path_absent():
    c = claim(values=("old.yaml", "new.yaml"), keys=(), kind="path")
    assert decide_in_code(c, [], {"old.yaml"}) is None
    assert decide_in_code(c, [], {"old.yaml", "new.yaml"}) is not None


def test_a_key_in_key_position_is_a_hit_ranked_last():
    # Ruling K1: a value that changed in the manifest is still found through its key.
    planted = lines(20, {5: "version: 0.31.0"})
    ws = windows_for(claim(), {"base-apps/x/v.yaml": planted})
    assert [(w.start, w.end) for w in ws] == [(2, 8)]
    port = claim(values=("8201",), keys=("port",), kind="port")
    for line in ("port: 8200", "  - port: 8200", "PORT : 8200"):
        assert windows_for(port, {"base-apps/x/s.yaml": lines(9, {5: line})}), line
    for line in ("ports: 8200", "myport: 8200", "# port: 8200", "name: port", "x: port"):
        assert windows_for(port, {"base-apps/x/s.yaml": lines(9, {5: line})}) == [], line
    # ranked after a key+value line and after a value-only line
    srcs = {
        "base-apps/x/a.yaml": lines(20, {2: "version: 0.31.0"}),
        "base-apps/x/b.yaml": lines(20, {2: "pin 0.30.1"}),
        "base-apps/x/c.yaml": lines(20, {2: "version: 0.30.1"}),
    }
    assert [w.source for w in windows_for(claim(), srcs)] == [
        "base-apps/x/c.yaml",
        "base-apps/x/b.yaml",
        "base-apps/x/a.yaml",
    ]
    # a key-only window does not satisfy insufficient(): widening may still add evidence
    assert insufficient(ws, claim())
    assert windows_for(claim(keys=()), {"base-apps/x/v.yaml": planted}) == []


# --- the claim's own source (live false positive, 2026-10-19) ----------------------------
# "The Dex side is the static client `vault` in base-apps/dex/configmap.yaml": "vault" is on
# dozens of lines of the Vault manifests listed first, which filled every window, so the
# judge never saw Dex's `- id: vault` and called the client missing.

DEX = "base-apps/dex/configmap.yaml"


def vault_sources(n_vault_files: int = 6) -> dict[str, str]:
    sources = {
        f"base-apps/vault/f{i}.yaml": lines(40, {k: "name: vault" for k in range(3, 40, 8)})
        for i in range(n_vault_files)
    }
    sources[DEX] = lines(30, {12: "    staticClients:", 13: "      - id: vault"})
    return sources


def dex_claim(keys=(), **kw) -> Claim:
    return claim(values=("vault",), keys=keys, kind="name", source_hint=DEX, **kw)


def test_the_claims_own_source_ranks_first_within_a_tier():
    ws = windows_for(dex_claim(), vault_sources())
    assert ws[0].source == DEX and "- id: vault" in ws[0].text


def test_the_claims_own_source_is_never_crowded_out_by_a_better_tier():
    sources = vault_sources()
    sources = {
        **{f"base-apps/vault/k{i}.yaml": lines(20, {5: "client: vault"}) for i in range(6)},
        **sources,
    }
    ws = windows_for(dex_claim(keys=("client",)), sources)  # six key+value hits elsewhere
    assert len(ws) == 5 and DEX in [w.source for w in ws]


def test_without_a_hint_the_doc_order_still_decides():
    ws = windows_for(claim(values=("vault",), keys=(), kind="name"), vault_sources())
    assert DEX not in [w.source for w in ws]  # unchanged behaviour: five Vault windows


def test_a_named_thing_is_present_where_the_claim_says():
    sources = vault_sources()
    assert named_thing_present(dex_claim(), sources) == DEX
    gone = {**sources, DEX: lines(30, {13: "      - id: argocd"})}
    assert named_thing_present(dex_claim(), gone) is None  # the hint was read: only it counts
    no_hint = claim(values=("vault",), keys=(), kind="name")
    assert named_thing_present(no_hint, gone) == "base-apps/vault/f0.yaml"
    commented = {DEX: lines(30, {13: "# - id: vault"})}
    assert named_thing_present(dex_claim(), commented) is None  # a comment is not evidence


def test_a_path_claim_is_present_when_its_file_was_read():
    path_claim = claim(values=("./base-apps/dex/configmap.yaml",), keys=(), kind="path")
    assert named_thing_present(path_claim, {DEX: "kind: ConfigMap"}) == DEX
    assert named_thing_present(path_claim, {"base-apps/x.yaml": "x"}) is None
