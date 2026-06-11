"""Tests for the safe IMDb source bootstrap helpers."""

from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from movie_recommender.data import MovieDatasetReducer
from movie_recommender.data.imdb_bootstrap import (
    REQUIRED_SOURCE_FILES,
    download_sources,
    dry_run,
    list_sources,
    write_sample_fixture,
)


class FakeDownloadResponse:
    def __init__(self, chunks: list[bytes], fail_after_chunks: bool = False) -> None:
        self.headers = {"Content-Length": str(sum(len(chunk) for chunk in chunks))}
        self.chunks = chunks
        self.fail_after_chunks = fail_after_chunks
        self.index = 0

    def __enter__(self) -> "FakeDownloadResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, chunk_size: int) -> bytes:
        if self.index < len(self.chunks):
            chunk = self.chunks[self.index]
            self.index += 1
            return chunk
        if self.fail_after_chunks:
            raise RuntimeError("download failed")
        return b""


class ImdbBootstrapTest(unittest.TestCase):
    """Bootstrap modes should stay offline and bounded unless explicitly downloading."""

    def test_bootstrap_module_import_does_not_require_pandas(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.abc\n"
                    "import sys\n"
                    "class BlockPandas(importlib.abc.MetaPathFinder):\n"
                    "    def find_spec(self, fullname, path, target=None):\n"
                    "        if fullname == 'pandas' or fullname.startswith('pandas.'):\n"
                    "            raise ModuleNotFoundError("
                    "\"No module named 'pandas'\", name='pandas')\n"
                    "        return None\n"
                    "sys.meta_path.insert(0, BlockPandas())\n"
                    "from movie_recommender.data.imdb_bootstrap import list_sources\n"
                    "assert 'pandas' not in sys.modules\n"
                    "assert list_sources.__name__ == 'list_sources'"
                ),
            ],
            cwd=repo_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_module_list_invokes_main(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "movie_recommender.cli.imdb_bootstrap",
                "--list",
            ],
            cwd="/tmp",
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("title.basics.tsv.gz", result.stdout)
        self.assertIn("https://datasets.imdbws.com/title.basics.tsv.gz", result.stdout)

    def test_list_sources_prints_required_public_urls(self) -> None:
        output = StringIO()

        list_sources(output=output)

        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 5)
        for source, line in zip(REQUIRED_SOURCE_FILES, lines):
            self.assertEqual(line, f"{source.filename}\t{source.url}")

    def test_dry_run_does_not_create_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "imdb"
            output = StringIO()

            dry_run(output_dir, output=output)
            output_dir_exists = output_dir.exists()

        self.assertIn("No files downloaded", output.getvalue())
        self.assertFalse(output_dir_exists)

    def test_download_skips_existing_files_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "imdb"
            output_dir.mkdir()
            for source in REQUIRED_SOURCE_FILES:
                (output_dir / source.filename).write_bytes(b"existing")

            with patch("movie_recommender.data.imdb_bootstrap.urlopen") as urlopen:
                paths = download_sources(output_dir, output=StringIO())

        urlopen.assert_not_called()
        self.assertEqual(len(paths), len(REQUIRED_SOURCE_FILES))

    def test_download_force_replaces_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "imdb"
            output_dir.mkdir()
            for source in REQUIRED_SOURCE_FILES:
                (output_dir / source.filename).write_bytes(b"existing")
            output = StringIO()

            with patch(
                "movie_recommender.data.imdb_bootstrap.urlopen",
                side_effect=lambda *args, **kwargs: FakeDownloadResponse([b"replacement"]),
            ) as urlopen:
                paths = download_sources(output_dir, force=True, output=output)

            contents = [(output_dir / source.filename).read_bytes() for source in REQUIRED_SOURCE_FILES]

        self.assertEqual(urlopen.call_count, len(REQUIRED_SOURCE_FILES))
        self.assertEqual(contents, [b"replacement"] * len(REQUIRED_SOURCE_FILES))
        self.assertEqual(len(paths), len(REQUIRED_SOURCE_FILES))
        self.assertIn("Refreshing", output.getvalue())

    def test_download_force_failure_preserves_existing_file_and_removes_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "imdb"
            output_dir.mkdir()
            first_source = REQUIRED_SOURCE_FILES[0]
            for source in REQUIRED_SOURCE_FILES:
                (output_dir / source.filename).write_bytes(b"existing")

            with patch(
                "movie_recommender.data.imdb_bootstrap.urlopen",
                return_value=FakeDownloadResponse([b"partial"], fail_after_chunks=True),
            ):
                with self.assertRaisesRegex(RuntimeError, "download failed"):
                    download_sources(output_dir, force=True, output=StringIO())

            preserved_content = (output_dir / first_source.filename).read_bytes()
            temp_files = [path for path in output_dir.iterdir() if path.name.startswith(".")]

        self.assertEqual(preserved_content, b"existing")
        self.assertEqual(temp_files, [])

    def test_sample_fixture_is_small_and_reducer_compatible(self) -> None:
        reducer = MovieDatasetReducer()

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "sample"
            paths = write_sample_fixture(output_dir, output=StringIO())
            dataset = reducer.reduce_dataset(
                percentage=None,
                output_name=Path(tmp) / "movies_sample",
                min_votes=0,
                write_typed=False,
                input_dir=output_dir,
            )
            max_rows = max(len(pd.read_csv(path, sep="\t")) for path in paths)

        self.assertEqual(
            {path.name for path in paths},
            {
                "title.basics.tsv",
                "title.crew.tsv",
                "title.ratings.tsv",
                "title.principals.tsv",
                "name.basics.tsv",
            },
        )
        self.assertLessEqual(max_rows, 5)
        self.assertEqual(dataset["tconst"].tolist(), ["tt0000001", "tt0000002"])


if __name__ == "__main__":
    unittest.main()
