import numpy as np
import cartopy.crs as ccrs
from datetime import datetime, timezone

# --- Геомагнитный экватор (дипольное приближение, IGRF ~2025) ---
# Наклон диполя ~11.3°
DIPOLE_TILT_DEG = 11.3
DIPOLE_LON_DEG = -72.7  # долгота северного магнитного полюса


def geomagnetic_equator(n_points: int = 360):
    """
    Возвращает lat, lon геомагнитного экватора (MLAT = 0)
    """
    lons = np.linspace(-180, 180, n_points)

    # дипольная аппроксимация
    lats = np.degrees(
        np.arctan(
            np.tan(np.deg2rad(DIPOLE_TILT_DEG)) *
            np.sin(np.deg2rad(lons - DIPOLE_LON_DEG))
        )
    )

    return lats, lons


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
