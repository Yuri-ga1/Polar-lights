import numpy as np
import cartopy.crs as ccrs
from datetime import datetime, timezone
import pandas as pd
import os

def geomagnetic_equator():
    """
    Возвращает lat, lon геомагнитного экватора
    """
    file_path = os.path.join('files', 'EQ2.txt')
    headers = ['lat', 'lon']
    df = pd.read_csv(file_path, delim_whitespace=True, header=None, names=headers)

    return df['lat'], df['lon']


def get_subsolar_latlon(time: datetime | None = None):
    """
    Возвращает широту и долготу подсолнечной точки
    """
    if time is None:
        time = datetime.now().replace(tzinfo=timezone.utc)
    elif time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)

    # день года
    doy = time.timetuple().tm_yday

    # солнечная деклинация
    decl = 23.44 * np.sin(np.deg2rad(360 / 365 * (doy - 81)))

    # долгота подсолнечной точки
    time_utc = time.hour + time.minute / 60 + time.second / 3600
    lon = 180 - time_utc * 15
    lon = (lon + 180) % 360 - 180  # [-180, 180]

    return decl, lon

# --- Солнечный терминатор ---
def solar_terminator(
    ax,
    time=None,
    color="black",
    alpha=0.5,
    zorder=3
):
    """
    Plot a fill on the dark side of the Earth (solar terminator).

    Parameters
    ----------
    ax : cartopy.mpl.geoaxes.GeoAxes
        Axes to plot on
    time : datetime
        UTC time
    color : str
        Fill color
    alpha : float
        Transparency
    """

    lat, lon = get_subsolar_latlon(time)

    pole_lng = lon
    if lat > 0:
        pole_lat = -90 + lat
        central_rot_lng = 180
    else:
        pole_lat = 90 + lat
        central_rot_lng = 0

    rotated_pole = ccrs.RotatedPole(
        pole_latitude=pole_lat,
        pole_longitude=pole_lng,
        central_rotated_longitude=central_rot_lng
    )

    x = [-90] * 181 + [90] * 181 + [-90]
    y = list(range(-90, 91)) + list(range(90, -91, -1)) + [-90]

    ax.fill(
        x,
        y,
        transform=rotated_pole,
        color=color,
        alpha=alpha,
        zorder=zorder
    )
