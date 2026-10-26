"""Convert geographic Matplotlib contours to independent browser polylines."""

import math


def contour_paths(path):
    """Honor pen-up/close commands and split at the longitude seam.

    CLOSEPOLY's vertex is a placeholder, not a geographic coordinate. Sending
    vertices alone also loses MOVETO breaks and can create a spurious diagonal.
    """
    from matplotlib.path import Path

    paths = []
    current = []
    start = None

    def flush():
        nonlocal current
        if len(current) > 1:
            paths.append(current)
        current = []

    def append(point):
        nonlocal current
        lon, lat = map(float, point)
        if not (math.isfinite(lon) and math.isfinite(lat) and -90 <= lat <= 90):
            flush()
            return
        lon = (lon + 180) % 360 - 180 if not -180 <= lon <= 180 else lon
        point = [lon, lat]
        if current and abs(lon - current[-1][0]) > 180:
            previous_lon, previous_lat = current[-1]
            unwrapped = lon + (360 if lon < previous_lon else -360)
            edge = 180 if lon < previous_lon else -180
            delta = unwrapped - previous_lon
            t = (edge - previous_lon) / delta if delta else 0
            edge_lat = previous_lat + t * (lat - previous_lat)
            if current[-1] != [edge, edge_lat]:
                current.append([edge, edge_lat])
            flush()
            current = [[-edge, edge_lat]]
        if not current or point != current[-1]:
            current.append(point)

    for vertices, code in path.iter_segments(curves=False, simplify=False):
        if code == Path.MOVETO:
            flush()
            start = vertices[:2]
            append(start)
        elif code == Path.CLOSEPOLY:
            if start is not None and current:
                append(start)
            flush()
            start = None
        elif code == Path.STOP:
            flush()
            start = None
        else:
            append(vertices[:2])
    flush()
    return paths


def night_cap_polygons(subsolar_latitude, subsolar_longitude, shell_angle):
    """Clip the spherical night cap to the geographic map rectangle.

    Contour the solar zenith angle directly on the lon/lat grid. This preserves
    pole coverage and splits the cap at +/-180 without ambiguous ring winding.
    Angles are in radians; shell_angle matches the terminator's altitude.
    """
    import contourpy
    import numpy as np

    longitude = np.linspace(-180, 180, 721)
    latitude = np.linspace(-90, 90, 361)
    lat_radians = np.deg2rad(latitude)[:, None]
    lon_radians = np.deg2rad(longitude)[None, :]
    cosine_zenith = np.sin(lat_radians) * np.sin(subsolar_latitude) + np.cos(
        lat_radians
    ) * np.cos(subsolar_latitude) * np.cos(lon_radians - subsolar_longitude)
    points, offsets = contourpy.contour_generator(
        x=longitude, y=latitude, z=cosine_zenith, fill_type="OuterOffset"
    ).filled(-2, np.cos(shell_angle))
    # A spherical cap has no holes in this map domain. OuterOffset returns one
    # outer ring per connected piece, including pieces split at the seam.
    return [
        ring[: index[1]].astype(float).tolist() for ring, index in zip(points, offsets)
    ]
