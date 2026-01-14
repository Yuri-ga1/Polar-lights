import os
from datetime import datetime

from app.visualization.aurora_map_plotter import AuroraMapPlotter
from app.visualization.plot_settings import set_plt_def_params
from app.pipeline.observation_pipeline import (
    collect_observation_links,
    parse_and_save_observations
)

from app.omni.omni_downloader import OmniDownloader
from app.gfz.gfz_downloader import GfzDownloader
from app.kyoto.kyoto_dst_downloader import KyotoDstDownloader


def main() -> None:
    DATE = "2025-11-12"

    omni = OmniDownloader(out_dir=omni_out_dir)
    try:
        omni_file = omni.download(DATE)
        print(f"Файл OMNI сохранён: {omni_file}")
    except Exception as exc:
        print(f"Не удалось скачать данные OMNI: {exc}")

    gfz = GfzDownloader(out_dir=gfz_out_dir)
    try:
        kp_file = gfz.download(date_str=DATE, fmt="kp2")
        print(f"Файл GFZ (Kp) сохранён: {kp_file}")
    except Exception as exc:
        print(f"Не удалось скачать данные GFZ: {exc}")

    kyoto = KyotoDstDownloader(out_dir=kyoto_out_dir)
    try:
        dst_file = kyoto.download(DATE)
        print(f"Файл Dst сохранён: {dst_file}")
    except Exception as exc:
        print(f"Не удалось скачать Dst: {exc}")


if __name__ == "__main__":
    set_plt_def_params()

    base_out_dir = "files"
    omni_out_dir = os.path.join(base_out_dir, 'omni')
    gfz_out_dir = os.path.join(base_out_dir, 'kp')
    kyoto_out_dir = os.path.join(base_out_dir, 'kyoto')
    
    dates = ["2025/11/12", "2025/11/13"]
    h5_path = os.path.join(base_out_dir, "spaceweather_observations.h5")
    csv_path =  os.path.join(base_out_dir, "aurora_data.csv")

    for date in dates:
        collect_observation_links(date, h5_path)
        parse_and_save_observations(h5_path, csv_path)

    save_path = os.path.join('files', 'obs_map.png')
    plotter = AuroraMapPlotter(
        csv_path=csv_path,
        save_path=save_path,
        show_geomagnetic_equator=True,
        show_terminator=True
    )

    plotter.plot(
        time=datetime(2025, 11, 12, 2, 0)
    )