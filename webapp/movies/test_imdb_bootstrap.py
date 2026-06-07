"""Tests for the safe IMDb source bootstrap helpers."""

from io import StringIO
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.dataset_reducer import MovieDatasetReducer
from src.imdb_bootstrap import (
    REQUIRED_SOURCE_FILES,
    dry_run,
    list_sources,
    write_sample_fixture,
)


class ImdbBootstrapTest(unittest.TestCase):
    """Bootstrap modes should stay offline and bounded unless explicitly downloading."""

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
