from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.services.parameter_changelog import ParameterChangelogService


def test_parameter_changelog_initial_and_no_change(tmp_path: Path) -> None:
    settings = get_settings()
    old_path = settings.parameter_changelog_path
    old_snapshot_dir = settings.parameter_snapshot_dir
    old_enabled = settings.parameter_changelog_enabled

    changelog_path = tmp_path / "PARAM_CHANGELOG.md"
    snapshot_dir = tmp_path / "snapshots"

    settings.parameter_changelog_enabled = True
    settings.parameter_changelog_path = str(changelog_path)
    settings.parameter_snapshot_dir = str(snapshot_dir)

    try:
        service = ParameterChangelogService()
        first = service.generate(version="v1", trigger="test")
        second = service.generate(version="v1", trigger="test")

        assert first["updated"] is True
        assert first["reason"] == "initialized"
        assert first["changes_count"] > 0
        assert first["snapshot_path"]
        assert Path(first["snapshot_path"]).exists()

        assert second["updated"] is False
        assert second["reason"] == "no_changes"
        assert second["changes_count"] == 0
        assert second["snapshot_path"] == ""

        body = changelog_path.read_text(encoding="utf-8")
        assert "initialized parameters snapshot" in body
    finally:
        settings.parameter_changelog_path = old_path
        settings.parameter_snapshot_dir = old_snapshot_dir
        settings.parameter_changelog_enabled = old_enabled


def test_parameter_changelog_detects_setting_change(tmp_path: Path) -> None:
    settings = get_settings()
    old_path = settings.parameter_changelog_path
    old_snapshot_dir = settings.parameter_snapshot_dir
    old_enabled = settings.parameter_changelog_enabled
    old_min_rr = settings.min_rr

    changelog_path = tmp_path / "PARAM_CHANGELOG.md"
    snapshot_dir = tmp_path / "snapshots"

    settings.parameter_changelog_enabled = True
    settings.parameter_changelog_path = str(changelog_path)
    settings.parameter_snapshot_dir = str(snapshot_dir)

    try:
        service = ParameterChangelogService()
        service.generate(version="v1", trigger="test")
        settings.min_rr = old_min_rr + 0.1
        changed = service.generate(version="v1", trigger="test")

        assert changed["updated"] is True
        assert changed["reason"] == "changes_detected"
        assert changed["changes_count"] >= 1
        assert "min_rr" in changed["changes"]
        assert changed["changes"]["min_rr"]["old"] == old_min_rr
        assert changed["changes"]["min_rr"]["new"] == old_min_rr + 0.1
        assert Path(changed["snapshot_path"]).exists()

        body = changelog_path.read_text(encoding="utf-8")
        assert "`min_rr`" in body
    finally:
        settings.min_rr = old_min_rr
        settings.parameter_changelog_path = old_path
        settings.parameter_snapshot_dir = old_snapshot_dir
        settings.parameter_changelog_enabled = old_enabled
