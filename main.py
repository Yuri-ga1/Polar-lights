import os
from datetime import datetime

from app.visualization.aurora_map_plotter import AuroraMapPlotter
from app.visualization.plot_settings import set_plt_def_params
from app.pipeline.observation_pipeline import (
    collect_observation_links,
    parse_and_save_observations
)

from app.gfz.gfz_downloader import GfzDownloader
from app.gfz.gfz_processor import GfzProcessor

from app.omni.omni_downloader import OmniDownloader
from app.omni.omni_processor import OmniProcessor

from app.kyoto.kyoto_dst_downloader import KyotoDstDownloader
from app.kyoto.kyoto_dst_processor import KyotoProcessor


def main() -> None:
    DATE = "2025-11-12"
    base_out_dir = "files"
    omni_out_dir = os.path.join(base_out_dir, 'omni')
    gfz_out_dir = os.path.join(base_out_dir, 'kp')
    kyoto_out_dir = os.path.join(base_out_dir, 'kyoto')

    # omni = OmniDownloader(out_dir=omni_out_dir)
    # try:
    #     omni_file = omni.download(DATE)
    #     print(f"Файл OMNI сохранён: {omni_file}")
    # except Exception as exc:
    #     print(f"Не удалось скачать данные OMNI: {exc}")

    # proc = OmniProcessor(folder_path=omni_out_dir)
    # df = proc.load(date_str="2025-11-12")
    # print(df)

    # gfz = GfzDownloader(out_dir=gfz_out_dir)
    # try:
    #     kp_file = gfz.download(date_str=DATE)
    #     print(f"Файл GFZ (Kp) сохранён: {kp_file}")
    # except Exception as exc:
    #     print(f"Не удалось скачать данные GFZ: {exc}")
    
    
    # proc = GfzProcessor(folder_path=gfz_out_dir)
    # df_month = proc.load(date_str=DATE)
    # print(df_month.head() if df_month is not None else "нет данных")

    

    # kyoto = KyotoDstDownloader(out_dir=kyoto_out_dir)
    # try:
    #     dst_file = kyoto.download(DATE)
    #     print(f"Файл Dst сохранён: {dst_file}")
    # except Exception as exc:
    #     print(f"Не удалось скачать Dst: {exc}")

    proc = KyotoProcessor(folder_path=kyoto_out_dir)
    df_day = proc.load(date_str='2025-11-12')

if __name__ == "__main__":
    set_plt_def_params()
    main()

    # base_out_dir = "files"
    # omni_out_dir = os.path.join(base_out_dir, 'omni')
    # gfz_out_dir = os.path.join(base_out_dir, 'kp')
    # kyoto_out_dir = os.path.join(base_out_dir, 'kyoto')
    
    # dates = ["2025/11/12", "2025/11/13"]
    # h5_path = os.path.join(base_out_dir, "spaceweather_observations.h5")
    # csv_path =  os.path.join(base_out_dir, "aurora_data.csv")

    # for date in dates:
    #     collect_observation_links(date, h5_path)
    #     parse_and_save_observations(h5_path, csv_path)

    # save_path = os.path.join('files', 'obs_map.png')
    # plotter = AuroraMapPlotter(
    #     csv_path=csv_path,
    #     save_path=save_path,
    #     show_geomagnetic_equator=True,
    #     show_terminator=True
    # )

    # plotter.plot(
    #     time=datetime(2025, 11, 12, 2, 0)
    # )