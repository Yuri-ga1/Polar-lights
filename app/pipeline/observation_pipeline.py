from app.observation.observation_links_finder import ObservationLinksFinder
from app.observation.observation_parser import ObservationParser
from app.observation.observation_processor import ObservationProcessor
from app.storage.hdf5_storage import ObservationHDF5Storage


def collect_observation_links(date: str, h5_path: str):
    finder = ObservationLinksFinder()
    storage = ObservationHDF5Storage(h5_path)

    links = finder.get_observation_links(date)
    print(f"{date}: найдено {len(links)} наблюдений")
    storage.save_links(date, links)


def parse_and_save_observations(h5_path: str, csv_path: str):
    parser = ObservationParser()
    processor = ObservationProcessor(csv_path)
    storage = ObservationHDF5Storage(h5_path)

    for date, link in storage.iter_links():
        raw = parser.parse(link)
        processor.process(raw)
