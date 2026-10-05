import re
import pandas as pd


def normalize_skill(value: str) -> str:
    """Return a consistent display name for common spreadsheet skill variants."""
    compact = re.sub(r"\s+", " ", value).strip()
    aliases = {
        "python programming": "Python",
        "python3": "Python",
        "ms excel": "Excel",
        "microsoft excel": "Excel",
        "neo 4j": "Neo4j",
    }
    return aliases.get(compact.casefold(), compact.title() if compact.islower() else compact)


def normalize_skills(value: str | None) -> list[str]:
    if not value:
        return []
    return list(dict.fromkeys(normalize_skill(skill) for skill in value.split(",") if skill.strip()))


def parse_experience_years(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Normalize column names
    df.columns = [re.sub(r"\s+", " ", str(column)).strip() for column in df.columns]

    # Normalize string values
    for column in df.select_dtypes(include="object").columns:
        df[column] = df[column].apply(
            lambda value: (
                re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else value
            )
        )

    return df
