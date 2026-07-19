#!/usr/bin/env python
from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path
from typing import assert_never

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

with contextlib.redirect_stdout(io.StringIO()):
    from app.models.translation_job import TranslationJob


class MigrationInputError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def upgrade(engine: Engine) -> None:
    TranslationJob.__table__.create(bind=engine, checkfirst=True)


def rollback(engine: Engine) -> None:
    return None


def compile_dry_run(dialect_name: str) -> str:
    if dialect_name not in {"mysql", "sqlite"}:
        raise MigrationInputError(f"unsupported dialect: {dialect_name}")
    dialect = mysql.dialect() if dialect_name == "mysql" else sqlite.dialect()
    table = TranslationJob.__table__
    statements = [str(CreateTable(table).compile(dialect=dialect)).rstrip()]
    for index in sorted(table.indexes, key=lambda item: item.name or ""):
        statements.append(str(CreateIndex(index).compile(dialect=dialect)).rstrip())
    return ";\n\n".join(statements) + ";\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=["upgrade", "rollback"], default="upgrade")
    parser.add_argument("--database-url")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dialect", choices=["mysql", "sqlite"], default="mysql")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        print(compile_dry_run(args.dialect), end="")
        return 0
    if not args.database_url:
        print("--database-url is required unless --dry-run is set", file=sys.stderr)
        return 2
    engine = create_engine(args.database_url)
    match args.action:
        case "upgrade":
            upgrade(engine)
        case "rollback":
            rollback(engine)
        case unreachable:
            assert_never(unreachable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
