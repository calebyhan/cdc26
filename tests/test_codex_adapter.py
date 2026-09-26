"""Codex integration boundaries. Tests mock the CLI; no network or subscription usage."""

import json
import subprocess
from pathlib import Path

import pytest

from not_my_debt import codex_adapter
from not_my_debt.extract import extract_document

TEXT = "Provider: Maple Grove Medical\nBalance: $150.00"
PAYLOAD = json.dumps(
    {
        "fields": [{"key": "balance", "value": "150.00", "quote": "Balance: $150.00", "page": 1}],
        "warnings": [],
    }
)


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(codex_adapter.shutil, "which", lambda name: "/usr/local/bin/codex")
    monkeypatch.delenv("NMD_CODEX_MODEL", raising=False)
    monkeypatch.delenv("NMD_CODEX_TIMEOUT_SECONDS", raising=False)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:] == ["login", "status"]:
            return subprocess.CompletedProcess(command, 0, "", "Logged in using ChatGPT\n")
        return subprocess.CompletedProcess(command, 0, PAYLOAD, "")

    monkeypatch.setattr(codex_adapter.subprocess, "run", run)
    return calls


def test_codex_uses_private_stdin_and_saved_chatgpt_auth(cli, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-forward")
    monkeypatch.setenv("CODEX_API_KEY", "do-not-forward")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "do-not-forward")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    document = extract_document(TEXT, "bill", "Bill", method="codex")
    assert len(cli) == 2
    command, options = cli[1]
    assert TEXT not in " ".join(command)
    assert TEXT == json.loads(options["input"].split("\n")[-1])["document_text"]
    assert command[-1] == "-"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert 'forced_login_method="chatgpt"' in command
    assert 'history.persistence="none"' in command
    assert 'web_search="disabled"' in command
    assert all(flag in command for flag in codex_adapter.DISABLED_FEATURES)
    assert "OPENAI_API_KEY" not in options["env"]
    assert "CODEX_API_KEY" not in options["env"]
    assert "CODEX_ACCESS_TOKEN" not in options["env"]
    assert "OPENAI_BASE_URL" not in options["env"]
    assert not options.get("shell", False)
    assert options["timeout"] == 120
    assert not Path(options["cwd"]).exists()  # Cleaned on success.
    fact = document.fields["balance"]
    assert fact.value == "150.00" and fact.quote == "Balance: $150.00"
    assert not fact.confirmed
    assert document.extraction_method == "Codex structured extraction (ChatGPT sign-in)"


def test_missing_cli_does_not_silently_run_local_parser(monkeypatch):
    monkeypatch.setattr(codex_adapter.shutil, "which", lambda name: None)
    assert not codex_adapter.codex_available()
    with pytest.raises(ValueError, match="not installed"):
        extract_document(TEXT, "bill", "Bill", method="codex")


@pytest.mark.parametrize("configured_model", [None, "", " \t "])
def test_no_model_override_uses_cli_default(cli, monkeypatch, configured_model):
    if configured_model is not None:
        monkeypatch.setenv("NMD_CODEX_MODEL", configured_model)

    document = extract_document(TEXT, "bill", "Bill", method="codex")

    assert len(cli) == 2
    command, _ = cli[1]
    assert "--model" not in command
    assert "-m" not in command
    assert not any(argument.startswith("model=") for argument in command)
    assert document.fields["balance"].value == "150.00"


def test_explicit_model_override_is_passed_as_one_argument(cli, monkeypatch):
    model = "demo-supported-model"
    monkeypatch.setenv("NMD_CODEX_MODEL", model)

    document = extract_document(TEXT, "bill", "Bill", method="codex")

    assert len(cli) == 2
    command, _ = cli[1]
    assert command.count("--model") == 1
    assert command[command.index("--model") + 1] == model
    assert document.fields["balance"].value == "150.00"


@pytest.mark.parametrize("model", ["two models", "model\nother", "model\tother", "x" * 121])
def test_malformed_model_is_rejected_before_auth_or_extraction(cli, monkeypatch, model):
    monkeypatch.setenv("NMD_CODEX_MODEL", model)

    with pytest.raises(ValueError, match="one model identifier"):
        extract_document(TEXT, "bill", "Bill", method="codex")

    assert not cli


@pytest.mark.parametrize("status", ["Not logged in", "Logged in using an API key"])
def test_requires_chatgpt_login(cli, monkeypatch, status):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, status, "")

    monkeypatch.setattr(codex_adapter.subprocess, "run", run)
    with pytest.raises(ValueError, match="signed in with ChatGPT"):
        extract_document(TEXT, "bill", "Bill", method="codex")
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "exit", "empty", "malformed", "oversized"])
def test_failures_are_sanitized_and_temporary_files_removed(cli, monkeypatch, failure):
    original = codex_adapter.subprocess.run
    paths = []

    def run(command, **kwargs):
        if command[1:] == ["login", "status"]:
            return original(command, **kwargs)
        paths.append(Path(kwargs["cwd"]))
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 120, output="PRIVATE CONTENT")
        if failure == "exit":
            return subprocess.CompletedProcess(command, 1, "PRIVATE CONTENT", "PRIVATE CONTENT")
        output = {"empty": "", "malformed": "PRIVATE CONTENT", "oversized": "x" * 512001}[failure]
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(codex_adapter.subprocess, "run", run)
    with pytest.raises(ValueError) as error:
        extract_document(TEXT, "bill", "Bill", method="codex")
    assert "PRIVATE CONTENT" not in str(error.value)
    assert paths and not paths[0].exists()


def test_hallucinated_fields_are_rejected_after_codex_output(cli, monkeypatch):
    monkeypatch.setattr(
        codex_adapter,
        "run_codex",
        lambda *_: json.dumps(
            {
                "fields": [
                    {"key": "balance", "value": "999.00", "quote": "Balance: $150.00", "page": 1},
                    {
                        "key": "patient",
                        "value": "Invented",
                        "quote": "Patient: Invented",
                        "page": 1,
                    },
                ],
                "warnings": [],
            }
        ),
    )
    document = extract_document(TEXT, "bill", "Bill", method="codex")
    assert not document.fields
    assert len(document.warnings) == 2


@pytest.mark.parametrize("value", ["0", "301", "abc"])
def test_invalid_timeout_stops_before_launch(cli, monkeypatch, value):
    monkeypatch.setenv("NMD_CODEX_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError, match="10 to 300"):
        extract_document(TEXT, "bill", "Bill", method="codex")
    assert not cli
