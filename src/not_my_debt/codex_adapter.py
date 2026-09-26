"""Local-demo Codex CLI transport using saved ChatGPT authentication.

Created with OpenAI Codex. The model runs at OpenAI, not on this computer.
Document input/output passes through process pipes; temporary runtime files are removed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "hooks",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "view_image",
    "multi_agent",
    "code_mode",
    "code_mode_host",
    "skill_search",
    "shell_snapshot",
    "memories",
)


def codex_available() -> bool:
    """Cheap presence check for UI reruns; no login, network call, or model run."""
    return shutil.which("codex") is not None


def _environment() -> dict[str, str]:
    # Reuse the user's existing auth location without copying or reading tokens.
    # In particular, do not pass API keys or alternate API endpoints into this path.
    allowed = {
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "CODEX_HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SystemRoot",
        "WINDIR",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _timeout() -> int:
    try:
        value = int(os.environ.get("NMD_CODEX_TIMEOUT_SECONDS", "120"))
    except ValueError:
        raise ValueError("NMD_CODEX_TIMEOUT_SECONDS must be an integer from 10 to 300.") from None
    if not 10 <= value <= 300:
        raise ValueError("NMD_CODEX_TIMEOUT_SECONDS must be an integer from 10 to 300.")
    return value


def run_codex(prompt: str, schema: dict) -> str:
    """Return structured model output or a sanitized error; never switch engines."""
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError("Codex CLI is not installed. Install it and run codex login first.")
    timeout = _timeout()
    model = os.environ.get("NMD_CODEX_MODEL", "").strip()
    if len(model) > 120 or any(char.isspace() for char in model):
        raise ValueError("NMD_CODEX_MODEL must contain one model identifier.")
    env = _environment()
    with TemporaryDirectory(prefix="nmd-codex-") as directory:
        work = Path(directory)
        # Auth-status output can include account information. Capture and discard it.
        try:
            status = subprocess.run(
                [executable, "login", "status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                cwd=work,
                env=env,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError(
                "Could not check Codex sign-in. Run codex login in your terminal."
            ) from None
        if (
            status.returncode
            or "logged in using chatgpt" not in (status.stdout + status.stderr).casefold()
        ):
            raise ValueError(
                "Codex must be signed in with ChatGPT. Run codex login and choose ChatGPT."
            )

        schema_path = work / "extraction.schema.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        command = [
            executable,
            "-a",
            "never",
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
        ]
        if model:
            command.extend(["--model", model])
        for feature in DISABLED_FEATURES:
            command.extend(["--disable", feature])
        overrides = {
            "forced_login_method": "chatgpt",
            "history.persistence": "none",
            "web_search": "disabled",
            "model_reasoning_effort": "low",
            "project_doc_max_bytes": 0,
            "log_dir": str(work / "logs"),
            "sqlite_home": str(work / "state"),
        }
        for key, value in overrides.items():
            command.extend(["-c", f"{key}={json.dumps(value)}"])
        command.append("-")  # Prompt is stdin, never a process argument or shell command.
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=work,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(
                f"Codex extraction timed out after {timeout} seconds. Retry or select Local parser."
            ) from None
        except OSError:
            raise ValueError("Codex could not start. Check its installation and sign-in.") from None
        if completed.returncode:
            # Never echo provider errors, stderr, prompt contents, or auth details into the UI.
            raise ValueError(
                "Codex extraction failed. Check your ChatGPT usage, network, CLI version, and "
                "NMD_CODEX_MODEL setting; then retry or select Local parser."
            )
        if not completed.stdout.strip() or len(completed.stdout) > 512_000:
            raise ValueError("Codex returned no usable extraction. Retry or select Local parser.")
        return completed.stdout.strip()
