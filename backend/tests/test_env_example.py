"""`.env.example` documents every setting, and the backend starts from it as written."""

import re

import pytest

from app.config import REPO_ROOT, Settings

ENV_EXAMPLE = REPO_ROOT / ".env.example"


def test_env_example_documents_every_setting() -> None:
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(), re.M))

    assert {name.upper() for name in Settings.model_fields} <= documented


def test_env_example_values_are_valid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)

    settings = Settings(_env_file=ENV_EXAMPLE, api_token="x" * 32)  # type: ignore[call-arg]

    assert settings.umessage_mode == "real"
    assert settings.allowed_origins == ["http://127.0.0.1:3000", "http://localhost:3000"]
