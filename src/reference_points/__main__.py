"""Command-line interface for reference-points.

Commands (results → stdout, errors → stderr + non-zero exit):

    parse <ref>              validate an address; print its structure
    decompose <file>         print the Section/Entity tree of a message
    label <file>             print the message with inline labels
    map <file>               print the compact address→excerpt overlay
    resolve <ref> <file>     print the content the address points at
    turns <file>             count the replies a transcript holds
    expand <transcript>      resolve every address written in the text on stdin
    label <transcript> -T --block <uuid>
                             one record's text, labeled and linked, as JSON
    serve [--daemon]         answer the commands above over a Unix socket (the mod's
                             way in without paying a Python start per call)

``--transcript`` / ``-T`` makes ``<file>`` a whole conversation instead of a
single message. Then the address carries its own turn and ``--turn`` is not
needed; ``label -T`` with no ``--turn`` is the viewer, printing every reply
labeled with the prompts it answered quoted between them.

Without ``-T``, ``--turn N`` (default 1) is the turn the message came from.
Supplying it makes a turn-less address legal, so the fragments ``label`` prints
(``.P1``) resolve as they are written, and an address for another turn is
rejected instead of answered. ``<file>`` may be ``-`` to read from stdin.
``label`` and ``map`` take ``--glyphs`` for the ``◆ § ·`` marker set.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

from reference_points import claude_code, serve
from reference_points.decompose import Entity, Message, Quote, Section, decompose
from reference_points.grammar import (
    MISSING,
    REJECTED,
    RefError,
    find_refs,
    format_failure,
    parse_ref,
)
from reference_points.render import (
    ASCII,
    GLYPH,
    LINK_BASE,
    LINKED,
    render_blocks,
    render_inline,
    render_map,
    render_transcript,
    render_transcript_map,
)
from reference_points.resolve import ResolveError, find_turn, resolve, resolve_in


def _read(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def _tree_lines(entities: tuple[Entity, ...], indent: str) -> list[str]:
    rows: list[str] = []
    for entity in entities:
        letter = type(entity).__name__[0]
        rows.append(
            f"{indent}{letter}{entity.index}  ({type(entity).__name__}, line {entity.line})"
        )
        if isinstance(entity, Section | Quote):
            rows.extend(_tree_lines(entity.entities, indent + "  "))
    return rows


def _format_tree(msg: Message) -> str:
    rows: list[str] = []
    for section in msg.sections:
        label = section.heading or "(implicit)"
        rows.append(f"N{msg.turn}-S{section.index}  {label!r} (line {section.line})")
        rows.extend(_tree_lines(section.entities, "  "))
    return "\n".join(rows)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reference-points")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def turn_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--turn",
            "-n",
            type=int,
            default=None,
            help="the turn this message came from; makes a turn-less address legal",
        )

    def source_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("file")
        p.add_argument(
            "--transcript",
            "-T",
            action="store_true",
            help="read <file> as a whole conversation, not a single message",
        )
        turn_flag(p)

    p_parse = sub.add_parser("parse", help="validate an address")
    p_parse.add_argument("ref")
    turn_flag(p_parse)

    p_decompose = sub.add_parser("decompose", help="print the entity tree")
    source_flags(p_decompose)

    for name, help_text in (("label", "inline labels"), ("map", "address→excerpt overlay")):
        p = sub.add_parser(name, help=help_text)
        source_flags(p)
        p.add_argument(
            "--glyphs",
            action="store_true",
            help="draw labels with ◆ turn / § section / · entity instead of ASCII",
        )
        if name == "label":
            p.add_argument(
                "--block",
                metavar="UUID",
                help="with -T: only the transcript record with this uuid, labeled as a "
                "part of its turn, every label a link to its full address (JSON out)",
            )

    p_resolve = sub.add_parser("resolve", help="resolve an address to content")
    p_resolve.add_argument("ref")
    source_flags(p_resolve)

    # No -T: counting replies is only a question about a conversation, and a
    # count is what a caller needs to write the *next* turn's labels.
    p_turns = sub.add_parser("turns", help="count the replies a transcript holds")
    p_turns.add_argument("file")

    # The text is stdin because it is a prompt, which may be any length and holds
    # anything; the transcript is the argument because it is what addresses resolve in.
    p_expand = sub.add_parser("expand", help="resolve every address written in stdin")
    p_expand.add_argument("file", help="the transcript the addresses point into")

    p_serve = sub.add_parser("serve", help="answer these commands over a Unix socket")
    p_serve.add_argument("--daemon", action="store_true", help="detach once listening")

    return parser


def _message(args: argparse.Namespace) -> Message:
    """The one message a command operates on. In transcript mode ``--turn`` picks
    it out of the conversation; otherwise it is the whole file."""
    text = _read(args.file)
    if args.transcript:
        return find_turn(claude_code.parse(text), args.turn)
    return decompose(text, turn=args.turn if args.turn is not None else 1)


def _expand(transcript_file: str) -> int:
    transcript = claude_code.parse(_read(transcript_file))
    # Resolve all before printing any: a prompt with one bad address gets the
    # error alone, not a half-expanded context to mistake for the whole answer.
    found = [(ref, resolve_in(ref, transcript).content) for ref in find_refs(sys.stdin.read())]
    if found:
        print("\n\n".join(f"[{ref.raw}]\n{content}" for ref, content in found))
    return 0


def _sourceless(args: argparse.Namespace) -> int | None:
    """The commands that take no message source, or None for one that does."""
    if args.cmd == "parse":
        print(parse_ref(args.ref, turn=args.turn))
        return 0
    if args.cmd == "turns":
        print(len(claude_code.parse(_read(args.file)).turns))
        return 0
    if args.cmd == "expand":
        return _expand(args.file)
    if args.cmd == "serve":
        return _serve(daemon=args.daemon)
    if args.cmd == "label" and args.block:
        if not args.transcript or args.glyphs:
            raise ResolveError(
                REJECTED,
                "--block labels one transcript record, always in the viewer's link style",
                "label <transcript> -T --block <uuid>, without --glyphs",
            )
        return _block(args.file, args.block)
    return None


def _code_version() -> int:
    """Changes when any engine source file does, which is how a running server
    notices that it is no longer the engine on disk."""
    return max(path.stat().st_mtime_ns for path in Path(__file__).parent.glob("*.py"))


def _serve(*, daemon: bool) -> int:
    path = serve.socket_path(Path(__file__).resolve().parents[2])
    if not daemon:
        print(path, flush=True)  # a foreground server never returns to print it
    serve.serve(path, run_captured, _code_version, daemon=daemon)
    if daemon:
        print(path)
    return 0


def run_captured(argv: list[str], stdin: str) -> tuple[int, str, str]:
    """``main`` for a caller that is not a process: its exit code and both streams.

    Swaps process-wide streams, so callers must not overlap (the server does not).
    """
    if argv[:1] == ["serve"]:
        failure = format_failure(
            REJECTED, "a request cannot start another server", "run serve from a shell"
        )
        return 1, "", failure + "\n"
    out, err = io.StringIO(), io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(argv)
            except SystemExit as exc:  # argparse reports a usage error by exiting
                code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.stdin = real_stdin
    return code, out.getvalue(), err.getvalue()


def _block(transcript_file: str, uuid: str) -> int:
    """One record of a reply, labeled as the part of its turn that it is."""
    for turn in claude_code.parse(_read(transcript_file)).turns:
        for index, block in enumerate(turn.blocks):
            if block.uuid == uuid:
                text = render_blocks(turn.message, [b.line for b in turn.blocks], LINKED)[index]
                print(json.dumps({"text": text, "base": LINK_BASE}))
                return 0
    raise ResolveError(
        MISSING,
        f"no reply record {uuid!r} in this transcript",
        "a record not yet written, or not a reply, has no address: draw it unlabeled",
    )


def _dispatch(args: argparse.Namespace) -> int:
    done = _sourceless(args)
    if done is not None:
        return done

    whole_transcript = args.transcript and args.turn is None
    style = GLYPH if getattr(args, "glyphs", False) else ASCII

    if args.cmd == "resolve":
        ref = parse_ref(args.ref, turn=args.turn)
        if args.transcript:
            print(resolve_in(ref, claude_code.parse(_read(args.file))).content)
        else:
            print(resolve(ref, _message(args)).content)
    elif whole_transcript:
        transcript = claude_code.parse(_read(args.file))
        if args.cmd == "label":
            print(render_transcript(transcript, style=style))
        elif args.cmd == "map":
            print(render_transcript_map(transcript, style=style))
        else:
            print("\n\n".join(_format_tree(t.message) for t in transcript.turns))
    elif args.cmd == "decompose":
        print(_format_tree(_message(args)))
    elif args.cmd == "label":
        print(render_inline(_message(args), style=style))
    elif args.cmd == "map":
        print(render_map(_message(args), style=style))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (RefError, ResolveError) as exc:
        print(exc, file=sys.stderr)  # already carries its category prefix
        return 1
    except OSError as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
