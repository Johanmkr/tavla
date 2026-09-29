from __future__ import annotations

import json

from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import info

runner = CliRunner()


def test_gather_on_content(basic_content):
    result = info.gather(basic_content)
    assert result.content_dir == basic_content.resolve()
    assert result.content_source == "--content-dir"
    assert result.content_initialized
    assert result.layout == result.layout_expected
    assert result.counts == {"projects": 4, "goals": 5, "tasks": 7}
    assert result.problem is None


def test_gather_reports_where_the_content_dir_came_from(basic_content, monkeypatch):
    monkeypatch.setenv("TAVLA_CONTENT_DIR", str(basic_content))
    assert info.gather().content_source == "TAVLA_CONTENT_DIR"
    monkeypatch.delenv("TAVLA_CONTENT_DIR")
    assert info.gather().content_source == "default"


def test_gather_survives_missing_and_old_content(tmp_path):
    missing = info.gather(tmp_path / "nope")
    assert not missing.content_initialized and missing.counts is None
    (tmp_path / "registry.yaml").write_text("[]\n")  # initialized, but layout v1
    old = info.gather(tmp_path)
    assert old.layout == 1
    assert "tavla migrate" in old.problem


def test_cli_info(basic_content):
    result = runner.invoke(app, ["--content-dir", str(basic_content), "info"])
    assert result.exit_code == 0, result.output
    assert "(from --content-dir)" in result.output
    assert "4 projects · 5 goals · 7 tasks" in result.output
    data = json.loads(
        runner.invoke(app, ["info", "--content-dir", str(basic_content), "--json"]).output
    )
    assert data["layout"] == data["layout_expected"]
