import re
import pandas as pd


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
