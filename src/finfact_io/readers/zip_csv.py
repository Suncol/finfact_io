from __future__ import annotations

import zipfile
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from finfact_io.errors import DataFileNotFoundError, ZipMemberNotFoundError
from finfact_io.readers.csv import read_csv_bytes


class ZipCsvReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise DataFileNotFoundError(f"Zip archive not found: {self.path}")

    def list_csv_members(self) -> tuple[str, ...]:
        with zipfile.ZipFile(self.path) as archive:
            return tuple(sorted(name for name in archive.namelist() if name.endswith(".csv")))

    def resolve_member(self, code_or_member: str) -> str:
        requested = code_or_member.strip()
        requested_member = requested if requested.endswith(".csv") else f"{requested}.csv"
        members = self.list_csv_members()
        if requested_member in members:
            return requested_member

        casefold_map = {member.casefold(): member for member in members}
        resolved = casefold_map.get(requested_member.casefold())
        if resolved is not None:
            return resolved

        raise ZipMemberNotFoundError(
            f"Zip member {requested_member!r} not found in {self.path}. "
            f"Requested code: {requested_member.removesuffix('.csv')}"
        )

    def read_member(
        self,
        member: str,
        *,
        required_columns: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        with zipfile.ZipFile(self.path) as archive:
            if member not in archive.namelist():
                raise ZipMemberNotFoundError(
                    f"Zip member {member!r} not found in {self.path}. "
                    f"Requested symbol: {member.removesuffix('.csv')}"
                )
            data = archive.read(member)

        return read_csv_bytes(
            data,
            source=f"{self.path}!{member}",
            required_columns=required_columns,
        )

    def read_code(
        self,
        code_or_member: str,
        *,
        required_columns: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        return self.read_member(
            self.resolve_member(code_or_member),
            required_columns=required_columns,
        )
