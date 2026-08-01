"""Command-line interface for reference-points.

Commands (results → stdout, errors → stderr + non-zero exit):

    parse <ref>              validate an address; print its structure
    decompose <file>         print the Section/Entity tree of a message
    label <file>             print the message with inline labels
    map <file>               print the compact address→excerpt overlay
    resolve <ref> <file>     print the content the address points at

Every command takes ``--turn N`` (default 1) — the turn the message came from.
Supplying it makes a turn-less address legal, so the fragments ``label`` prints
(``.P1``) resolve as they are written, and an address for another turn is
rejected instead of answered. ``<file>`` may be ``-`` to read from stdin.
``label`` and ``map`` take ``--glyphs`` for the ``◆ § ·`` marker set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reference_points.decompose import Entity, Message, Quote, Section, decompose
from reference_points.grammar import RefError, parse_ref
from reference_points.render import ASCII, GLYPH, render_inline, render_map
from reference_points.resolve import ResolveError, resolve


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
            default=1,
            help="the turn this message came from; makes a turn-less address legal",
        )

    p_parse = sub.add_parser("parse", help="validate an address")
    p_parse.add_argument("ref")
    turn_flag(p_parse)

    p_decompose = sub.add_parser("decompose", help="print the entity tree")
    p_decompose.add_argument("file")
    turn_flag(p_decompose)

    for name, help_text in (("label", "inline labels"), ("map", "address→excerpt overlay")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("file")
        turn_flag(p)
        p.add_argument(
            "--glyphs",
            action="store_true",
            help="draw labels with ◆ turn / § section / · entity instead of ASCII",
        )

    p_resolve = sub.add_parser("resolve", help="resolve an address to content")
    p_resolve.add_argument("ref")
    p_resolve.add_argument("file")
    turn_flag(p_resolve)

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "parse":
        print(parse_ref(args.ref, turn=args.turn))
    elif args.cmd == "decompose":
        print(_format_tree(decompose(_read(args.file), turn=args.turn)))
    elif args.cmd == "label":
        style = GLYPH if args.glyphs else ASCII
        print(render_inline(decompose(_read(args.file), turn=args.turn), style=style))
    elif args.cmd == "map":
        style = GLYPH if args.glyphs else ASCII
        print(render_map(decompose(_read(args.file), turn=args.turn), style=style))
    elif args.cmd == "resolve":
        msg = decompose(_read(args.file), turn=args.turn)
        print(resolve(parse_ref(args.ref, turn=args.turn), msg).content)
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
