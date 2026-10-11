"""Tests for the command-line interface."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from reference_points.__main__ import main, run_captured

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


def test_expand_resolves_every_address_in_the_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("what did N1-S1.P2 mean?"))
    code = main(["expand", str(TRANSCRIPT)])
    assert code == 0
    assert capsys.readouterr().out == "[N1-S1.P2]\nThe second half of the reply.\n"


def test_expand_prints_nothing_when_the_text_holds_no_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("no citations here, just N2 gas"))
    assert main(["expand", str(TRANSCRIPT)]) == 0
    assert not capsys.readouterr().out


def test_expand_fails_loud_on_an_address_that_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("and N1-S1.P9?"))
    assert main(["expand", str(TRANSCRIPT)]) == 1
    assert capsys.readouterr().err.startswith("MISSING:")


def _blocks_transcript(tmp_path: Path) -> Path:
    def record(role: str, uuid: str, text: str) -> str:
        message = {"role": role, "content": [{"type": "text", "text": text}]}
        return json.dumps({"type": role, "uuid": uuid, "message": message})

    path = tmp_path / "t.jsonl"
    path.write_text(
        "\n".join([
            record("user", "q", "question"),
            record("assistant", "u1", "First para."),
            record("assistant", "u2", "Second para."),
        ])
    )
    return path


def test_label_block_labels_one_block_of_its_turn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["label", str(_blocks_transcript(tmp_path)), "-T", "--block", "u2"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["text"] == f"[.P2]({out['base']}N1-S1.P2) Second para."


def test_label_block_fails_loud_on_a_uuid_the_transcript_does_not_hold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["label", str(_blocks_transcript(tmp_path)), "-T", "--block", "nope"]) == 1
    assert capsys.readouterr().err.startswith("MISSING:")


def test_label_block_needs_a_transcript(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "m.md"
    path.write_text("Hello.")
    assert main(["label", str(path), "--block", "u1"]) == 1
    assert "REJECTED:" in capsys.readouterr().err


def test_label_block_refuses_a_marker_style_it_would_ignore(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text("")
    assert main(["label", str(path), "-T", "--block", "u1", "--glyphs"]) == 1
    assert "REJECTED:" in capsys.readouterr().err


def test_run_captured_gives_a_request_the_cli_exit_code_and_both_streams() -> None:
    assert run_captured(["parse", "N1-S1.P1"], "")[0] == 0
    code, out, err = run_captured(["parse", "N1-S1.Q"], "")
    assert (code, out) == (1, "")
    assert err.startswith("REJECTED:")


def test_run_captured_feeds_the_request_text_to_expand_as_stdin() -> None:
    code, out, _ = run_captured(["expand", str(TRANSCRIPT)], "what did N1-S1.P2 mean?")
    assert code == 0
    assert out == "[N1-S1.P2]\nThe second half of the reply.\n"


def test_run_captured_turns_a_usage_error_into_a_result_not_an_exit() -> None:
    code, _, err = run_captured(["no-such-command"], "")
    assert code == 2
    assert "invalid choice" in err


def test_a_request_cannot_start_another_server() -> None:
    code, _, err = run_captured(["serve"], "")
    assert code == 1
    assert err.startswith("REJECTED:")


def test_expand_does_not_read_the_transcript_for_a_prompt_with_no_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A plain prompt must go through even when the transcript is not there yet.
    monkeypatch.setattr("sys.stdin", io.StringIO("hello there"))
    assert main(["expand", "/nonexistent/session.jsonl"]) == 0
    assert not capsys.readouterr().out


def test_expand_still_reports_an_unreadable_transcript_when_there_is_an_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("what did N1-S1.P2 mean?"))
    assert main(["expand", "/nonexistent/session.jsonl"]) == 1
    assert capsys.readouterr().err.startswith("UNREADABLE: ")
