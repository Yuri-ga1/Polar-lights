import pandas as pd


def load_ionosonde_data(filepath: str) -> pd.DataFrame:
    """Загружает данные ионосферных параметров."""
    df = pd.read_csv(
        filepath,
        sep="\t",
        na_values=["ccc"],
    )
    return df.apply(pd.to_numeric, errors="coerce")
