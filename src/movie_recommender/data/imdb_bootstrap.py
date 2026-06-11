"""Resource-safe bootstrap helpers for IMDb source datasets."""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


IMDB_DATASET_BASE_URL = "https://datasets.imdbws.com"
DEFAULT_OUTPUT_DIR = Path("data/imdb")
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_CHUNK_SIZE_BYTES = 1024 * 1024
DEFAULT_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class ImdbSourceFile:
    """A required public IMDb source dataset file."""

    filename: str

    @property
    def url(self) -> str:
        return f"{IMDB_DATASET_BASE_URL}/{self.filename}"


REQUIRED_SOURCE_FILES = [
    ImdbSourceFile("title.basics.tsv.gz"),
    ImdbSourceFile("title.crew.tsv.gz"),
    ImdbSourceFile("title.ratings.tsv.gz"),
    ImdbSourceFile("title.principals.tsv.gz"),
    ImdbSourceFile("name.basics.tsv.gz"),
]


SAMPLE_TABLES = {
    "title.basics.tsv": [
        {
            "tconst": "tt0000001",
            "titleType": "movie",
            "primaryTitle": "Sample Movie",
            "genres": "Drama",
        },
        {
            "tconst": "tt0000002",
            "titleType": "movie",
            "primaryTitle": "Sample Sequel",
            "genres": "Comedy,Drama",
        },
        {
            "tconst": "tt0000003",
            "titleType": "short",
            "primaryTitle": "Sample Short",
            "genres": "Documentary",
        },
    ],
    "title.crew.tsv": [
        {"tconst": "tt0000001", "directors": "nm0000001"},
        {"tconst": "tt0000002", "directors": "nm0000002"},
        {"tconst": "tt0000003", "directors": "nm0000003"},
    ],
    "title.ratings.tsv": [
        {"tconst": "tt0000001", "averageRating": "8.0", "numVotes": "1500"},
        {"tconst": "tt0000002", "averageRating": "7.5", "numVotes": "1200"},
        {"tconst": "tt0000003", "averageRating": "6.0", "numVotes": "10"},
    ],
    "title.principals.tsv": [
        {
            "tconst": "tt0000001",
            "ordering": "1",
            "nconst": "nm0000101",
            "category": "actor",
        },
        {
            "tconst": "tt0000001",
            "ordering": "2",
            "nconst": "nm0000102",
            "category": "actress",
        },
        {
            "tconst": "tt0000002",
            "ordering": "1",
            "nconst": "nm0000103",
            "category": "actor",
        },
        {
            "tconst": "tt0000003",
            "ordering": "1",
            "nconst": "nm0000104",
            "category": "actor",
        },
    ],
    "name.basics.tsv": [
        {"nconst": "nm0000001", "primaryName": "Sample Director"},
        {"nconst": "nm0000002", "primaryName": "Second Director"},
        {"nconst": "nm0000101", "primaryName": "Sample Actor"},
        {"nconst": "nm0000102", "primaryName": "Sample Actress"},
        {"nconst": "nm0000103", "primaryName": "Sequel Actor"},
        {"nconst": "nm0000003", "primaryName": "Short Director"},
        {"nconst": "nm0000104", "primaryName": "Short Actor"},
    ],
}


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ["B", "KiB", "MiB", "GiB"]:
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def list_sources(output=sys.stdout) -> None:
    """Print required IMDb source files and official public URLs."""
    for source in REQUIRED_SOURCE_FILES:
        print(f"{source.filename}\t{source.url}", file=output)


def dry_run(output_dir: Path, output=sys.stdout) -> None:
    """Print the download plan without opening network connections."""
    print(f"Would store compressed IMDb source files in: {output_dir}", file=output)
    for source in REQUIRED_SOURCE_FILES:
        print(f"Would download {source.url} -> {output_dir / source.filename}", file=output)
    print("No files downloaded; no TSVs decompressed or loaded into memory.", file=output)


def download_sources(
    output_dir: Path,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    chunk_size_bytes: int = DEFAULT_CHUNK_SIZE_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    force: bool = False,
    output=sys.stdout,
) -> list[Path]:
    """Stream required compressed IMDb files into ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded_paths = []
    for source in REQUIRED_SOURCE_FILES:
        destination = output_dir / source.filename
        temp_path = None
        if destination.exists() and not force:
            print(f"Skipping existing file: {destination}", file=output)
            downloaded_paths.append(destination)
            continue

        action = "Refreshing" if destination.exists() else "Downloading"
        print(f"{action} {source.url} -> {destination}", file=output)
        try:
            with urlopen(source.url, timeout=timeout_seconds) as response:
                length_header = response.headers.get("Content-Length")
                if length_header:
                    content_length = int(length_header)
                    if content_length > max_file_size_bytes:
                        raise RuntimeError(
                            f"{source.filename} is {_format_bytes(content_length)}, "
                            f"above the configured limit of "
                            f"{_format_bytes(max_file_size_bytes)}."
                        )

                with tempfile.NamedTemporaryFile(
                    dir=output_dir, prefix=f".{source.filename}.", delete=False
                ) as tmp:
                    temp_path = Path(tmp.name)
                    bytes_written = 0
                    while True:
                        chunk = response.read(chunk_size_bytes)
                        if not chunk:
                            break
                        bytes_written += len(chunk)
                        if bytes_written > max_file_size_bytes:
                            raise RuntimeError(
                                f"{source.filename} exceeded the configured limit of "
                                f"{_format_bytes(max_file_size_bytes)}."
                            )
                        tmp.write(chunk)
        except (HTTPError, URLError, TimeoutError) as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to download {source.url}: {exc}") from exc
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

        temp_path.replace(destination)
        downloaded_paths.append(destination)
        print(f"Saved {destination} ({_format_bytes(destination.stat().st_size)})", file=output)
    return downloaded_paths


def write_sample_fixture(
    output_dir: Path,
    rows_per_file: int = 5,
    output=sys.stdout,
) -> list[Path]:
    """Write a tiny decompressed IMDb-compatible fixture set."""
    if rows_per_file < 1:
        raise ValueError("--sample-rows must be at least 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths = []
    for filename, rows in SAMPLE_TABLES.items():
        path = output_dir / filename
        selected_rows = rows[:rows_per_file]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(selected_rows[0]), delimiter="\t"
            )
            writer.writeheader()
            writer.writerows(selected_rows)
        written_paths.append(path)
        print(f"Wrote sample fixture: {path}", file=output)
    print("Sample fixture is intentionally tiny and offline-only.", file=output)
    return written_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap required IMDb source data without loading it into memory."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="List required files and URLs.")
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the download plan without network access.",
    )
    mode.add_argument(
        "--download",
        action="store_true",
        help="Stream compressed IMDb source files into the output directory.",
    )
    mode.add_argument(
        "--sample",
        action="store_true",
        help="Write a tiny decompressed fixture set for local tests/development.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Destination directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--max-file-size-mib",
        type=int,
        default=DEFAULT_MAX_FILE_SIZE_BYTES // (1024 * 1024),
        help="Fail closed if any compressed download exceeds this size.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "With --download, redownload and atomically replace existing "
            "compressed source files."
        ),
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=5,
        help="Maximum rows to write per sample fixture file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        if args.force:
            parser.error("--force can only be used with --download")
        list_sources()
        return 0
    if args.dry_run:
        if args.force:
            parser.error("--force can only be used with --download")
        dry_run(args.output_dir)
        return 0
    if args.sample:
        if args.force:
            parser.error("--force can only be used with --download")
        write_sample_fixture(args.output_dir, rows_per_file=args.sample_rows)
        return 0
    if args.download:
        max_file_size_bytes = args.max_file_size_mib * 1024 * 1024
        download_sources(
            args.output_dir,
            max_file_size_bytes=max_file_size_bytes,
            force=args.force,
        )
        return 0

    parser.error("select exactly one mode")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
