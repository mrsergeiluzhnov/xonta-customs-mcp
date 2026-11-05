"""CLI: load the TN VED / ETT tariff table into the local database.

    xonta-customs-load-tariff tnved.xlsx --source "tws.by, выгрузка 05.11.2026"
    xonta-customs-load-tariff --url https://example.org/tnved.xlsx

The file needs a header row with columns for the code and the name; a duty rate
column ("Ставка пошлины", "Импортная пошлина", ...) and a unit column are used when present.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import httpx

from . import store


def main() -> None:
    ap = argparse.ArgumentParser(prog="xonta-customs-load-tariff")
    ap.add_argument("file", nargs="?", help="local .xlsx or .csv file")
    ap.add_argument("--url", help="download the file from this URL first")
    ap.add_argument("--source", help="human-readable source label stored with the data")
    args = ap.parse_args()

    if not args.file and not args.url:
        ap.error("укажите файл или --url")

    if args.url:
        suffix = ".csv" if args.url.lower().split("?")[0].endswith(".csv") else ".xlsx"
        with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "xonta-customs-mcp"}) as c:
            r = c.get(args.url)
            r.raise_for_status()
        tmp = Path(tempfile.mkdtemp()) / f"tariff{suffix}"
        tmp.write_bytes(r.content)
        path = tmp
        source = args.source or args.url
    else:
        path = Path(args.file)
        source = args.source or path.name

    n = store.load_tariff(path, source)
    print(f"Загружено кодов: {n}. База: {store.db_path()}")


if __name__ == "__main__":
    main()
