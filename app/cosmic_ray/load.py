import pandas as pd

def load_cosmic_ray_data(filepath: str) -> pd.DataFrame:
    column_names = ["Date", "Time", "ID", "IRK1", "IRK2", "IRK3", "Norilsk"]

    df = pd.read_csv(
        filepath,
        sep=r"\s+",
        names=column_names,
        skiprows=1,
        comment=";",
        engine="python"
    )

    df["DateTime"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str), errors="coerce")
    return df