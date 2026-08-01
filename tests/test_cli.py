"""Tests for the command-line interface."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reference_points.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_parse_command_prints_ref(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["parse", "N27-S1.T2.3"])
    assert code == 0
    assert "turn=27" in capsys.readouterr().out


def test_parse_command_rejects_bad_ref(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["parse", "S1.P1"])
    assert code == 1
    assert capsys.readouterr().err.strip() == "REJECTED: missing turn number"


def test_label_command_marks_the_turn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md = tmp_path / "m.md"
    md.write_text("Hello world. Bye now.\n")
    code = main(["label", str(md), "--turn", "5"])
    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == "N5-S1"


def test_label_command_glyph_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md = tmp_path / "m.md"
    md.write_text("Hello world. Bye now.\n")
    code = main(["label", str(md), "--turn", "5", "--glyphs"])
    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == "◆5 §1"


def test_resolve_command_prints_content(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md = tmp_path / "m.md"
    md.write_text("First sentence. Second sentence.\n")
    code = main(["resolve", "N1-S1.P1.2", str(md)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "Second sentence."


def test_resolve_command_reports_a_miss(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md = tmp_path / "m.md"
    md.write_text("Only one sentence.\n")
    code = main(["resolve", "N1-S1.P1.9", str(md)])
    assert code == 1
    assert capsys.readouterr().err.strip() == "MISSING: no such sentence 9 in P1 (has 1)"


def test_an_unreadable_file_is_its_own_category(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["resolve", "N1-S1.P1", "/nonexistent/message.md"])
    assert code == 1
    assert capsys.readouterr().err.startswith("UNREADABLE: ")
