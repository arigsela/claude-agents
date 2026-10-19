import pytest

from docs_checker.redact import REDACTED, redact, redact_obj


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAABCDEFGHIJKLMNOP",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFG0123456789_abcdefghijklmnop",
        "xoxb-1234567890-abcdefghijkl",
        "hvs.CAESIabcdefghijklmnopqrstuvwxyz",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
    ],
)
def test_token_shapes_are_redacted_anywhere(secret):
    out = redact(f"some text {secret} more text")
    assert secret not in out and REDACTED in out


def test_private_key_blocks_are_redacted_whole():
    text = (
        "key: |\n  -----BEGIN RSA PRIVATE KEY-----\n  MIIEabc\n  -----END RSA PRIVATE KEY-----\nok"
    )
    out = redact(text)
    assert "MIIEabc" not in out and out.endswith("ok")


@pytest.mark.parametrize(
    "line, hidden",
    [
        ("password: hunter2hunter2", "hunter2hunter2"),
        ("DB_PASSWORD=correct-horse-battery", "correct-horse-battery"),
        ('"client_secret": "abcdef123456"', "abcdef123456"),
        ("  token: c2VjcmV0dmFsdWU=", "c2VjcmV0dmFsdWU="),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        ("url: postgres://app:s3cretpass@db:5432/app", "s3cretpass"),
    ],
)
def test_credential_values_are_redacted(line, hidden):
    assert hidden not in redact(line)


@pytest.mark.parametrize(
    "line",
    [
        "chart: vault",
        "version: 0.30.1",
        "secretName: vault-tls",
        "max_tokens: 4096",
        "password: ${DB_PASSWORD}",
        "token: {{ .Values.token }}",
        "secretKeyRef:",
        "the task-runner was started",
    ],
)
def test_ordinary_config_and_references_are_kept(line):
    assert redact(line) == line


def test_redact_obj_walks_nested_values():
    data = {"args": {"query": "token: abcdefgh12345"}, "n": 3, "l": ["AKIAABCDEFGHIJKLMNOP"]}
    out = redact_obj(data)
    assert out["n"] == 3 and REDACTED in out["args"]["query"] and out["l"] == [REDACTED]


@pytest.mark.parametrize(
    "line, hidden",
    [
        ('password: "correct horse battery staple"', "correct horse battery staple"),
        ("password = 'a b c d e'", "a b c d e"),
        ("password: correct horse battery", "correct horse battery"),
        ('{"client_secret": "ab cd ef gh", "user": "bob"}', "ab cd ef gh"),
    ],
)
def test_values_with_spaces_are_redacted_whole(line, hidden):
    out = redact(line)
    assert hidden not in out and "horse" not in out and REDACTED in out


def test_a_trailing_comment_survives_and_the_value_does_not():
    assert (
        redact("password: hunter2 # rotated monthly") == f"password: {REDACTED} # rotated monthly"
    )


def test_a_value_under_a_credential_key_is_redacted_by_its_key():
    data = {
        "password": "hunter2hunter2",
        "env": [{"name": "X", "DB_TOKEN": "abc12345"}],
        "api_key": 123456789,
        "headers": {"X-Api-Key": "short-but-real"},
        "tokens": 5,  # not a credential key
        "secret": True,  # booleans are not credentials
        "password_ref": "${DB_PASSWORD}",  # a reference is kept
    }
    out = redact_obj(data)
    assert out["password"] == REDACTED
    assert out["env"][0] == {"name": "X", "DB_TOKEN": REDACTED}
    assert out["api_key"] == REDACTED and out["headers"]["X-Api-Key"] == REDACTED
    assert out["tokens"] == 5 and out["secret"] is True
    assert out["password_ref"] == "${DB_PASSWORD}"


def test_env_var_pairs_are_redacted_by_name_in_yaml_json_and_dicts():
    yaml_text = "env:\n  - name: DB_PASSWORD\n    value: s3cr3t-hunter2\n  - name: LOG_LEVEL\n    value: debug"
    out = redact(yaml_text)
    assert "s3cr3t-hunter2" not in out and "value: debug" in out
    json_text = (
        '[{"name": "API_TOKEN", "value": "abc123def456"}, {"name": "MODE", "value": "fast"}]'
    )
    out = redact(json_text)
    assert "abc123def456" not in out and '"fast"' in out
    data = {
        "env": [{"name": "DB_PASSWORD", "value": "hunter2hunter2"}, {"name": "M", "value": "x"}]
    }
    assert redact_obj(data)["env"] == [
        {"name": "DB_PASSWORD", "value": REDACTED},
        {"name": "M", "value": "x"},
    ]


def test_a_value_from_reference_is_not_touched():
    text = "- name: GITHUB_TOKEN\n  valueFrom:\n    secretKeyRef:\n      name: gh\n      key: token"
    assert redact(text) == text


def test_every_value_under_a_secrets_data_is_redacted_and_a_configmap_is_not():
    text = (
        "apiVersion: v1\nkind: Secret\nmetadata:\n  name: x\n"
        "data:\n  config.json: eyJhIjoiYiJ9c2VjcmV0\n  username: YWRtaW4=\n"
        "stringData:\n  note: |\n    line one secret\n    line two\n"
        "---\nkind: ConfigMap\ndata:\n  config.json: public-value"
    )
    out = redact(text)
    for hidden in ("eyJhIjoiYiJ9c2VjcmV0", "YWRtaW4=", "line one secret", "line two"):
        assert hidden not in out
    assert "config.json: public-value" in out and "name: x" in out


def test_a_password_in_a_yaml_block_is_redacted():
    out = redact("password: |\n  multi-line-secret-here\n  second\nnext: ok")
    assert "multi-line-secret" not in out and "second" not in out and out.endswith("next: ok")


@pytest.mark.parametrize(
    "text",
    [
        "key: |\n  -----BEGIN RSA PRIVATE KEY-----\n  MIIEabc\n  MIIEdef\n  -----END RSA PRIVATE KEY-----\nok: 1",
        "kind: Secret\ndata:\n  a: b2s=\n  c: |\n    x\n    y\n",
        "password: |\n  a\n  b\n",
        "env:\n  - name: X_TOKEN\n    value: abcdefgh1234\n",
    ],
)
def test_redaction_keeps_the_line_count_so_line_references_stay_true(text):
    assert redact(text).count("\n") == text.count("\n")


def test_a_json_secret_is_redacted_structurally():
    out = redact('{"kind":"Secret","data":{"username":"YWRtaW4=","password":"c2VjcmV0"}}')
    assert "YWRtaW4=" not in out and "c2VjcmV0" not in out and '"username"' in out


def test_yaml_wrapped_in_a_json_string_is_redacted_with_its_real_lines():
    text = '{"content": "apiVersion: v1\\nkind: Secret\\ndata:\\n  token: c2VjcmV0dG9rZW4=\\n"}'
    out = redact(text)
    assert "c2VjcmV0dG9rZW4=" not in out and "apiVersion: v1" in out


def test_json_without_secrets_keeps_its_exact_formatting():
    text = '[{"kind": "ConfigMap",   "data": {"a": "public"}}]'
    assert redact(text) == text


def test_an_env_credential_written_as_a_block_is_redacted_line_by_line():
    text = (
        "env:\n  - name: DB_PASSWORD\n    value: |-\n      line-one-secret\n      line-two\n"
        "  - name: MODE\n    value: fast"
    )
    out = redact(text)
    assert "line-one-secret" not in out and "line-two" not in out
    assert "value: fast" in out and out.count("\n") == text.count("\n")


@pytest.mark.parametrize(
    "text, hidden",
    [
        ("kind: Secret\nstringData:\n  password: abc\n", "abc"),
        ("password: abc", "abc"),
        ('{"api_key": "x9"}', "x9"),
    ],
)
def test_short_credentials_are_still_credentials(text, hidden):
    out = redact(text)
    assert f": {hidden}" not in out and f'"{hidden}"' not in out


# Secrets at any depth and in any YAML style. The keys are neutral on purpose:
# only the Secret structure may hide these values.
NESTED_SECRETS = [
    "apiVersion: v1\nkind: Secret\ndata: {config: c2VjcmV0, user: YWRtaW4=}\n",
    "kind: Secret\nstringData: {username: hunter2, note: 'quoted value'}\n",
    "kind: Secret\nstringData: {\n  username: hunter2,\n  note: ok-value\n}\n",
    (
        "apiVersion: v1\nkind: List\nitems:\n- apiVersion: v1\n  kind: Secret\n"
        "  data:\n    config: c2VjcmV0\n- apiVersion: v1\n  kind: Secret\n"
        "  stringData: {user: hunter2}\n"
    ),
    (
        "extraObjects:\n  - apiVersion: v1\n    metadata:\n      name: x\n"
        "    stringData:\n      note: |\n        line one hunter2\n        line two\n"
        "      user: admin-user\n    kind: Secret\n  - kind: ConfigMap\n    data:\n"
        "      mode: fast\n"
    ),
]


@pytest.mark.parametrize("text", NESTED_SECRETS)
def test_secret_data_is_redacted_in_flow_style_nested_and_indented(text):
    out = redact(text)
    for hidden in ("c2VjcmV0", "YWRtaW4=", "hunter2", "quoted value", "ok-value", "line two"):
        assert hidden not in out
    assert "admin-user" not in out
    assert out.count("\n") == text.count("\n")  # line references stay true


def test_a_nested_secrets_keys_and_its_sibling_configmap_are_kept():
    out = redact(NESTED_SECRETS[4])
    assert "note:" in out and "user:" in out and "name: x" in out
    assert "mode: fast" in out  # the ConfigMap item in the same list is not a Secret


@pytest.mark.parametrize(
    "text",
    [
        "kind: ConfigMap\ndata: {config: public-value, mode: fast}\n",
        "kind: List\nitems:\n- kind: ConfigMap\n  data:\n    config: public-value\n",
        "objects:\n  - kind: ConfigMap\n    data: {config: public-value}\n",
    ],
)
def test_a_configmap_in_the_same_shapes_is_untouched(text):
    assert redact(text) == text


def test_a_nested_secret_in_text_that_is_not_yaml_is_still_redacted():
    # A Helm template does not parse as YAML; the line-based pass still finds the
    # Secret at any indentation and masks its data, block or flow.
    text = (
        "{{- if .Values.enabled }}\nitems:\n  - kind: Secret\n    data:\n      config: c2VjcmV0\n"
        "    stringData: {user: hunter2}\n{{- end }}\n"
    )
    out = redact(text)
    assert "c2VjcmV0" not in out and "hunter2" not in out
    assert out.count("\n") == text.count("\n")
