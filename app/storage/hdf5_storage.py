import h5py
import numpy as np
import os

class ObservationHDF5Storage:
    def __init__(self, path: str):
        self.path = path

    @staticmethod
    def _date_key(date_str: str) -> str:
        return date_str.replace("/", "-")

    def has_date(self, date_str: str) -> bool:
        if not os.path.isfile(self.path):
            return False

        date_key = self._date_key(date_str)

        with h5py.File(self.path, "r") as f:
            return date_key in f

    def get_links(self, date_str: str) -> list[str]:
        if not os.path.isfile(self.path):
            return []

        date_key = self._date_key(date_str)

        with h5py.File(self.path, "r") as f:
            if date_key not in f:
                return []

            return [link.decode("utf-8") for link in f[date_key]["links"]]

    def save_links(self, date_str: str, links: list[str]):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        date_key = self._date_key(date_str)

        with h5py.File(self.path, "a") as f:
            if date_key in f:
                del f[date_key]

            grp = f.create_group(date_key)
            dt = h5py.string_dtype("utf-8")

            grp.create_dataset("links", data=np.array(links, dtype=dt))
            grp.attrs["count"] = len(links)

    def iter_links(self, date_str: str | None = None):
        if not os.path.isfile(self.path):
            return

        with h5py.File(self.path, "r") as f:
            if date_str:
                date_key = self._date_key(date_str)
                if date_key not in f:
                    return
                for link in f[date_key]["links"]:
                    yield date_key, link.decode("utf-8")
                return

            for date in f:
                for link in f[date]["links"]:
                    yield date, link.decode("utf-8")
