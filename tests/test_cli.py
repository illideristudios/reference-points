"""Tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from reference_points.__main__ import main

if TYPE_CHECKING:
    import pytest

TRANSCRIPT = Path(__file__).parent / "fixtures" / "transcript.jsonl"


def test_parse_command_prints_ref(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["parse", "N27-S1.T2.3"])
    assert code == 0
    assert "turn=27" in capsys.readouterr().out


def test_parse_command_rejects_bad_ref(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["parse", "N1-S1.X1"])
    assert code == 1
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "REJECTED: unknown entity 'X'"
    assert err[1].startswith("  -> known entities: P paragraph")


def test_the_turn_flag_supplies_a_missing_turn(capsys: pytest.CaptureFixture[str]) -> None:
    # The CLI is holding the message, so it already knows the turn — a fragment
    # needs no turn typed onto it.
    code = main(["parse", ".P4", "--turn", "5"])
    assert code == 0
    assert "turn=5" in capsys.readouterr().out


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
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "MISSING: no such sentence 9 in P1"
    assert err[1] == "  -> P1 has 1 sentence"


def test_turns_counts_the_replies(capsys: pytest.CaptureFixture[str]) -> None:
    # Without this, the only way to learn the last turn number is to ask for one
    # that does not exist and read the range out of the MISSING hint — a caller
    # parsing an error message for a fact the tool knows.
    code = main(["turns", str(TRANSCRIPT)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "3"


def test_turns_counts_replies_not_entries(capsys: pytest.CaptureFixture[str]) -> None:
    # The fixture holds 6 entries and 3 replies. A count that included prompts
    # would be off by exactly the amount that makes every label wrong.
    code = main(["turns", str(TRANSCRIPT)])
    assert code == 0
    assert int(capsys.readouterr().out) < 6


def test_turns_on_something_that_is_not_a_transcript(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "m.md"
    empty.write_text("Just a message, not a conversation.\n")
    code = main(["turns", str(empty)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "0"


def test_an_unreadable_file_is_its_own_category(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["resolve", "N1-S1.P1", "/nonexistent/message.md"])
    assert code == 1
    assert capsys.readouterr().err.startswith("UNREADABLE: ")
