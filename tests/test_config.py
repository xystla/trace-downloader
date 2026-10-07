from pathlib import Path
import pytest
from trace_grabber.config import load_config, Config

_TEAM_URLS = "team_urls:\n  - https://go.traceup.com/traceid/team/demoteam1\n"

def test_load_defaults(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "output_dir: ~/Trace Videos\ncheck_interval_hours: 3\nquality: highest\n"
        + _TEAM_URLS
    )
    cfg = load_config(cfg_file)
    assert isinstance(cfg, Config)
    assert cfg.output_dir == Path.home() / "Trace Videos"
    assert cfg.check_interval_hours == 3
    assert cfg.quality == "highest"
    assert cfg.team_urls == ["https://go.traceup.com/traceid/team/demoteam1"]

def test_invalid_quality_rejected(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "output_dir: ~/x\ncheck_interval_hours: 3\nquality: ultra\n" + _TEAM_URLS
    )
    with pytest.raises(ValueError, match="quality"):
        load_config(cfg_file)

def test_missing_team_urls_defaults_empty(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("output_dir: ~/x\ncheck_interval_hours: 3\nquality: highest\n")
    assert load_config(cfg_file).team_urls == []

def test_empty_team_urls_allowed(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "output_dir: ~/x\ncheck_interval_hours: 3\nquality: highest\nteam_urls: []\n"
    )
    assert load_config(cfg_file).team_urls == []

def test_combine_halves_default_true(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("output_dir: ~/x\ncheck_interval_hours: 3\nquality: highest\n" + _TEAM_URLS)
    assert load_config(cfg_file).combine_halves is True

def test_combine_halves_explicit_false(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("output_dir: ~/x\ncheck_interval_hours: 3\nquality: highest\ncombine_halves: false\n" + _TEAM_URLS)
    assert load_config(cfg_file).combine_halves is False


def test_file_name_pattern_is_optional(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("output_dir: ~/Trace Videos\ncheck_interval_hours: 3\nquality: highest\n")
    assert load_config(cfg_file).file_name == ""
    cfg_file.write_text("output_dir: ~/Trace Videos\ncheck_interval_hours: 3\nquality: highest\n"
                        "file_name: '{team} vs {opponent}'\n")
    assert load_config(cfg_file).file_name == "{team} vs {opponent}"
