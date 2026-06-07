"""Utilities for reducing the large IMDb dataset."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd


logger = logging.getLogger(__name__)


class MovieDatasetReducer:
    """Reduce raw IMDb TSV dumps to a smaller CSV dataset."""

    DIRECTOR_LIMIT = 3
    CAST_LIMIT = 5
    DEFAULT_MIN_VOTES = 1000

    @staticmethod
    def weighted_rating(row: pd.Series, C: float, m: float) -> float:
        """Compute IMDb weighted rating for a single row."""
        v = row["numVotes"]
        R = row["averageRating"]
        return (v / (v + m) * R) + (m / (m + v) * C)

    @staticmethod
    def split_imdb_ids(value: object, limit: int | None = None) -> list[str]:
        """Split comma-separated IMDb identifier fields."""
        if pd.isna(value) or value == r"\N":
            return []
        ids = [item for item in str(value).split(",") if item and item != r"\N"]
        if limit is None:
            return ids
        return ids[:limit]

    @staticmethod
    def split_genres(value: object) -> list[str]:
        """Split IMDb genre strings into a typed list."""
        return MovieDatasetReducer.split_imdb_ids(value)

    @staticmethod
    def _read_tsv(
        path: str | Path,
        usecols: list[str],
        chunksize: int | None = 1000000,
    ) -> pd.DataFrame:
        """Read an IMDb TSV, preserving the existing chunked path for large files."""
        reader = pd.read_csv(
            path,
            low_memory=False,
            chunksize=chunksize,
            sep="\t",
            encoding="utf-8",
            usecols=usecols,
        )
        if chunksize is None:
            return reader
        return pd.concat(reader)

    def _apply_vote_filter(
        self,
        metadata: pd.DataFrame,
        percentage: float | None,
        min_votes: int | None,
    ) -> pd.DataFrame:
        """Filter by the quantile path and/or the explicit minimum-votes path."""
        C = metadata["averageRating"].mean()
        thresholds = []
        if percentage is not None:
            thresholds.append(metadata["numVotes"].quantile(percentage))
        if min_votes is not None:
            thresholds.append(min_votes)

        m = max(thresholds) if thresholds else 0
        metadata = metadata.loc[metadata["numVotes"] >= m].copy()
        metadata["score"] = metadata.apply(self.weighted_rating, C=C, m=m, axis=1)
        return metadata

    def _director_lists(
        self, crew: pd.DataFrame, names: pd.DataFrame
    ) -> pd.DataFrame:
        """Return top director IDs and names per title in IMDb order."""
        directors = crew[["tconst", "directors"]].copy()
        directors["director_ids"] = directors["directors"].apply(
            lambda value: self.split_imdb_ids(value, self.DIRECTOR_LIMIT)
        )
        directors = directors[["tconst", "director_ids"]].explode("director_ids")
        directors = directors.dropna(subset=["director_ids"])
        directors["position"] = directors.groupby("tconst").cumcount()
        directors = directors.merge(
            names, how="left", left_on="director_ids", right_on="nconst"
        )
        directors = directors.sort_values(["tconst", "position"])
        return (
            directors.groupby("tconst", sort=False)
            .agg(
                director_ids=("director_ids", list),
                director_names=("primaryName", list),
            )
            .reset_index()
        )

    def _cast_lists(self, principals: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
        """Return top actor/actress IDs and names per title in principal order."""
        cast = principals.loc[
            principals["category"].isin(["actor", "actress"])
        ].copy()
        if "ordering" in cast.columns:
            cast = cast.sort_values(["tconst", "ordering"])
        cast = cast.groupby("tconst", group_keys=False).head(self.CAST_LIMIT)
        cast = cast.merge(names, how="left", on="nconst")
        return (
            cast.groupby("tconst", sort=False)
            .agg(
                cast_ids=("nconst", list),
                actors=("primaryName", list),
            )
            .reset_index()
        )

    @staticmethod
    def disambiguate_duplicate_titles(metadata: pd.DataFrame) -> pd.DataFrame:
        """Append IMDb IDs to duplicate titles while preserving primary titles."""
        metadata = metadata.copy()
        metadata["primary_title"] = metadata["primaryTitle"]
        metadata["title"] = metadata["primaryTitle"]
        duplicate_titles = metadata["title"].duplicated(keep=False)
        metadata.loc[duplicate_titles, "title"] = metadata.loc[
            duplicate_titles
        ].apply(lambda row: f"{row['primary_title']} ({row['tconst']})", axis=1)
        return metadata

    def build_reduced_dataset(
        self,
        titles: pd.DataFrame,
        crew: pd.DataFrame,
        ratings: pd.DataFrame,
        names: pd.DataFrame,
        principals: pd.DataFrame,
        percentage: float | None = 0.90,
        min_votes: int | None = DEFAULT_MIN_VOTES,
    ) -> pd.DataFrame:
        """Build a typed reduced dataset from IMDb source DataFrames."""
        metadata = titles.loc[titles["titleType"] == "movie"].copy()
        metadata = metadata.merge(ratings, on="tconst")
        metadata = metadata.merge(crew[["tconst", "directors"]], on="tconst")

        metadata = self._apply_vote_filter(metadata, percentage, min_votes)
        metadata["genres"] = metadata["genres"].apply(self.split_genres)

        directors = self._director_lists(crew, names)
        cast = self._cast_lists(principals, names)
        metadata = metadata.merge(directors, how="left", on="tconst")
        metadata = metadata.merge(cast, how="left", on="tconst")

        for column in ["director_ids", "director_names", "cast_ids", "actors"]:
            metadata[column] = metadata[column].apply(
                lambda value: value if isinstance(value, list) else []
            )
        metadata["director"] = metadata["director_names"].apply(
            lambda values: values[0] if values else ""
        )
        metadata = self.disambiguate_duplicate_titles(metadata)

        columns = [
            "tconst",
            "title",
            "primary_title",
            "director",
            "director_ids",
            "director_names",
            "genres",
            "score",
            "cast_ids",
            "actors",
        ]
        return (
            metadata[columns]
            .sort_values("score", ascending=False)
            .reset_index(drop=True)
        )

    def _write_typed_output(
        self, metadata: pd.DataFrame, output_name: str | Path
    ) -> Path | None:
        """Write a typed artifact when pandas has Parquet engine support."""
        output_path = Path(f"{output_name}.parquet")
        try:
            metadata.to_parquet(output_path, index=False)
        except (ImportError, ValueError) as exc:
            logger.info("Skipped typed Parquet output: %s", exc)
            return None
        logger.info("Saved typed dataset to %s", output_path)
        return output_path

    def reduce_dataset(
        self,
        percentage: float | None,
        output_name: str | Path,
        min_votes: int | None = DEFAULT_MIN_VOTES,
        write_typed: bool = True,
        input_dir: str | Path = ".",
    ) -> pd.DataFrame:
        """Reduce the raw IMDb dump.

        Parameters
        ----------
        percentage:
            Quantile of vote counts to retain. ``0.90`` keeps roughly the top
            10%% of movies by vote count.
        output_name:
            Path prefix for the CSV file that will be written.
        min_votes:
            Explicit vote threshold to retain. ``None`` disables this path.
            When both percentage and min_votes are provided, the stricter
            threshold is used.
        write_typed:
            Write a Parquet artifact next to the CSV when optional pandas
            dependencies support it.
        input_dir:
            Directory containing the required IMDb TSV input files.
        """
        input_dir = Path(input_dir)
        logger.info("Getting movie dataset...")
        title = self._read_tsv(
            input_dir / "title.basics.tsv",
            ["tconst", "titleType", "primaryTitle", "genres"],
        )
        director = self._read_tsv(input_dir / "title.crew.tsv", ["tconst", "directors"])
        ratings = pd.read_csv(
            input_dir / "title.ratings.tsv", sep="\t", encoding="utf-8"
        )

        logger.info(
            "Reducing data to %s%% of most popular movies with at least %s votes.",
            round((1 - percentage) * 100) if percentage is not None else "all",
            min_votes,
        )

        logger.info("Getting movie directors...")
        names = self._read_tsv(input_dir / "name.basics.tsv", ["nconst", "primaryName"])

        logger.info("Getting movie cast members...")
        cast = self._read_tsv(
            input_dir / "title.principals.tsv",
            ["tconst", "ordering", "nconst", "category"],
        )

        metadata = self.build_reduced_dataset(
            title,
            director,
            ratings,
            names,
            cast,
            percentage=percentage,
            min_votes=min_votes,
        )

        output_path = Path(f"{output_name}.csv")
        metadata.to_csv(output_path, index=False)
        logger.info("Saved dataset to %s", output_path)
        if write_typed:
            self._write_typed_output(metadata, output_name)
        return metadata
