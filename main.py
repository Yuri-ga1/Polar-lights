import h5py

from app.observation.observation_links_finder import ObservationLinksFinder


def find_links(file_path):
    date_list = ["2025/11/12", "2025/11/13"]

    with h5py.File(file_path, "w") as file:
        for date_str in date_list:
            date_key = date_str.replace("/", "-")  # 2025-11-12

            finder = ObservationLinksFinder()
            links = finder.get_observation_links(date_str)

            print(f"Найдено {len(links)} валидных страниц для даты: {date_key}")

            grp = file.create_group(date_key)

            grp.create_dataset(
                "links",
                data=links
            )

            grp.attrs["count"] = len(links)



if __name__ == '__main__':
    file_path = "spaceweather_observations.h5"
    find_links(file_path)
