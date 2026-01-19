import numpy as np
import cartopy.crs as ccrs
from datetime import datetime, timezone
import ppigrf

def _dip_latitude(Be, Bn, Bu):
    """
    Geomagnetic dip latitude:
    λ = arctan(Z / (2H))
    """
    Z = -Bu
    H = np.sqrt(Bn**2 + Be**2)
    return np.degrees(np.arctan2(Z, 2.0 * H))


def geomagnetic_lines(
    ax,
    date: datetime,
    levels: list = [-30, 30],
    height_km: float = 0.0,
    lon_step: float = 1.0,
    lat_step: float = 0.5,
    pole_margin_deg: float = 0.5,
    color: str = "orange",
):
    """
    Draw ONLY geomagnetic equator (0°) and ±30° dip-latitude isolines on given axes.
    Returns contour sets (for legend if needed).
    """

    lon = np.arange(-180, 181, lon_step)

    # IMPORTANT: exclude exact poles to avoid divisions by zero inside IGRF code
    lat = np.arange(-90.0 + pole_margin_deg, 90.0 - pole_margin_deg + 1e-9, lat_step)

    Lon, Lat = np.meshgrid(lon, lat)

    # ppigrf returns (Be, Bn, Bu) in nT, often (1, Ny, Nx)
    with np.errstate(invalid="ignore", divide="ignore"):
        Be, Bn, Bu = ppigrf.igrf(Lon, Lat, height_km, date)

    if Be.ndim == 3 and Be.shape[0] == 1:
        Be, Bn, Bu = Be[0], Bn[0], Bu[0]

    dip = _dip_latitude(Be, Bn, Bu)

    # Replace non-finite values so contour can work robustly
    dip = np.where(np.isfinite(dip), dip, np.nan)

    # --- 0° (equator) ---
    cs0 = ax.contour(
        lon, lat, dip,
        levels=[0],
        linewidths=2.0,
        colors=[color],
        transform=ccrs.PlateCarree(),
    )

    # --- ±30° ---
    cs30 = ax.contour(
        lon, lat, dip,
        levels=levels,
        linewidths=1.2,
        linestyles="--",
        colors=[color],
        transform=ccrs.PlateCarree(),
    )

    return cs0, cs30


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
