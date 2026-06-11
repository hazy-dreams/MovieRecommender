"""Simple content based movie recommendation utilities."""

from __future__ import annotations

import pandas as pd
from pathlib import Path
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class MovieRecommender:
    """Load movie data and generate recommendations."""

    REQUIRED_COLUMNS = {"title", "director", "genres", "score", "actors"}

    def __init__(self):
        self.df = None
        self.indices = None
        self.cosine_sim = None

    @staticmethod
    def clean_data(value: list[str] | str | None) -> list[str] | str:
        """Normalize strings used for similarity calculations."""
        if isinstance(value, list):
            return [str.lower(i.replace(" ", "")) for i in value]
        if isinstance(value, str):
            return str.lower(value.replace(" ", ""))
        return ""

    @staticmethod
    def create_soup(row: pd.Series) -> str:
        """Combine actors, director and genres into a single text field."""
        return " ".join(
            ["".join(row["actors"]), "".join(row["director"]), "".join(row["genres"])]
        )

    @staticmethod
    def _disambiguate_duplicate_titles(df: pd.DataFrame) -> pd.DataFrame:
        """Use tconst suffixes when duplicate title rows would break lookup."""
        if "tconst" not in df.columns or not df["title"].duplicated(keep=False).any():
            return df

        df = df.copy()
        duplicate_titles = df["title"].duplicated(keep=False)
        df.loc[duplicate_titles, "title"] = df.loc[duplicate_titles].apply(
            lambda row: f"{row['title']} ({row['tconst']})", axis=1
        )
        return df

    def load_dataset(self, dataset: str | Path) -> pd.DataFrame:
        """Read the reduced CSV dataset and prepare similarity matrix."""
        df = pd.read_csv(dataset, sep=",", encoding="utf-8")
        missing_columns = sorted(self.REQUIRED_COLUMNS - set(df.columns))
        if missing_columns:
            raise ValueError(
                "Dataset is missing required column(s): " + ", ".join(missing_columns)
            )

        df = self._disambiguate_duplicate_titles(df)
        if df["title"].duplicated().any():
            raise ValueError(
                "Dataset contains duplicate title values and no tconst values to "
                "disambiguate them."
            )

        df = df[["title", "director", "genres", "score", "actors"]].copy()
        df["director"] = df["director"].apply(lambda x: [x, x])
        for column in ["actors", "genres", "director"]:
            df[column] = df[column].astype("str").apply(self.clean_data)
        df["soup"] = df.apply(self.create_soup, axis=1)
        count = CountVectorizer(stop_words="english")
        count_matrix = count.fit_transform(df["soup"])
        self.cosine_sim = cosine_similarity(count_matrix, count_matrix)
        df = df.reset_index(drop=True)
        self.indices = pd.Series(df.index, index=df["title"])
        self.df = df
        return df

    def recommend(self, title: str, top_n: int = 10) -> pd.Series:
        """Return ``top_n`` movie titles similar to ``title``."""
        if self.df is None:
            raise ValueError("Dataset not loaded. Call load_dataset first.")
        if title not in self.indices:
            raise ValueError("This movie is not in the dataset.")
        idx = self.indices[title]
        sim_scores = list(enumerate(self.cosine_sim[idx]))
        sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)
        sim_scores = sim_scores[1 : top_n + 1]
        movie_indices = [i[0] for i in sim_scores]
        return self.df["title"].iloc[movie_indices]
