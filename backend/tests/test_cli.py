import sys

import pytest
from postgrest.exceptions import APIError

from grimoire_ingest import cli


def _set_cli_environment(monkeypatch, pdf_path):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["grimoire-ingest", str(pdf_path)],
    )
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "placeholder")


def test_rejects_publishable_key_before_connecting(monkeypatch, tmp_path, capsys):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.touch()
    _set_cli_environment(monkeypatch, pdf_path)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_publishable_placeholder")

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "contains a publishable key" in capsys.readouterr().err


def test_explains_row_level_security_error(monkeypatch, tmp_path, capsys):
    pdf_path = tmp_path / "guide.pdf"
    pdf_path.touch()
    _set_cli_environment(monkeypatch, pdf_path)
    monkeypatch.setattr(cli, "create_client", lambda *_args: object())

    def fail_ingestion(*_args, **_kwargs):
        raise APIError({"code": "42501", "message": "row-level security violation"})

    monkeypatch.setattr(cli, "ingest_pdf", fail_ingestion)

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "denied the write because of row-level security" in capsys.readouterr().err
