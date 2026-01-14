import os
os.environ["MPLBACKEND"] = "Agg" 

import threading

from datetime import date
 
from app.pipeline.observation_workflow import run_observation_workflow
from app.pipeline.space_weather_pipeline import prepare_space_weather_data
from app.visualization.plot_settings import set_plt_def_params

DATE_STR = "2025-11-12"

def main() -> None:
    
    prepare_space_weather_data(date_str=DATE_STR, base_out_dir="files")
 
if __name__ == "__main__":
    set_plt_def_params()

    observation_thread = threading.Thread(
        target=run_observation_workflow,
        name="observation-workflow",
        kwargs={
            "dates": [date.fromisoformat(DATE_STR)],
        },
    )
    observation_thread.start()
    main()

    observation_thread.join()