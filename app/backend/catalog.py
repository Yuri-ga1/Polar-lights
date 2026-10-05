"""One registry drives validation, acquisition, metadata and UI selectors."""

import re
from dataclasses import dataclass

from app.storage.timeseries import FrequencyPolicy

from .errors import BackendError


@dataclass(frozen=True)
class Column:
    name: str
    source: str
    units: str
    seconds: int
    raw_name: str

    @property
    def policy(self):
        return FrequencyPolicy(self.seconds)


OMNI = {
    "omni_bx": ("bx", "nT"),
    "omni_by": ("by", "nT"),
    "omni_bz": ("bz", "nT"),
    "omni_speed": ("speed", "km/s"),
    "omni_proton_density": ("proton density", "cm^-3"),
    "omni_flow_pressure": ("flow pressure", "nPa"),
    "omni_ae": ("ae", "nT"),
    "omni_sym_h": ("sym", "nT"),
}
COLUMNS = {
    name: Column(name, "omni", unit, 60, raw) for name, (raw, unit) in OMNI.items()
}
COLUMNS.update(
    kp=Column("kp", "kp", "", 10800, "kp"),
    kyoto_dst=Column("kyoto_dst", "kyoto", "nT", 3600, "dst"),
)
MAPS = {
    "roti-map": ("roti", "TECU/min"),
    "tec-adjusted-map": ("tec_adjusted", "TECU"),
    "gim-map": ("gim", "TECU"),
}
KEOGRAMS = {"roti-keogram": "roti-map", "tec-adjusted-keogram": "tec-adjusted-map"}
PRODUCTS = (
    "omni",
    "kp",
    "kyoto-dst",
    "nmdb",
    "giro",
    "timeseries",
    "aurora-map",
    *MAPS,
    *KEOGRAMS,
)


def column_spec(name):
    if name in COLUMNS:
        return COLUMNS[name]
    # Processed NMDB station values are relative amplitude percentages sampled
    # every ten minutes in files/processed/nmdb.csv.
    match = re.fullmatch(r"nmdb_([a-z0-9]{3,6})_amplitude_percent", name)
    if match:
        return Column(
            name, "nmdb", "relative amplitude (%)", 600, match.group(1).upper()
        )
    if re.fullmatch(r"giro_al945_(fof2|hmf2)", name):
        return Column(
            name,
            "giro",
            "MHz" if name.endswith("fof2") else "km",
            450,
            "foF2" if name.endswith("fof2") else "hmF2",
        )
    raise BackendError("INVALID_REQUEST", f"Unknown column: {name}", 422)


def check_product(product):
    if product not in PRODUCTS:
        raise BackendError(
            "PRODUCT_NOT_FOUND", "Unknown product", 404, productId=product
        )


def product_columns(product, known=()):
    if product == "omni":
        return list(OMNI)
    if product == "kp":
        return ["kp"]
    if product == "kyoto-dst":
        return ["kyoto_dst"]
    if product == "nmdb":
        return sorted(
            c
            for c in known
            if c.startswith("nmdb_") and c.endswith("_amplitude_percent")
        )
    if product == "giro":
        return ["giro_al945_fof2", "giro_al945_hmf2"]
    return list(COLUMNS)


def validate_columns(product, columns):
    check_product(product)
    expected_source = {"kyoto-dst": "kyoto"}.get(product, product)
    specs = [column_spec(c) for c in columns]
    if product != "timeseries" and any(s.source != expected_source for s in specs):
        raise BackendError(
            "INVALID_REQUEST", "Column does not belong to this product", 422
        )
    return {s.name: s for s in specs}


def catalog(known=(), remote_maps=False, station_metadata=None, aurora_default=None):
    products = []
    for product in PRODUCTS:
        if product == "aurora-map":
            products.append(
                {
                    "productId": product,
                    "title": "Aurora observations",
                    "category": "maps",
                    "graphType": "map",
                    "available": True,
                    "units": "observations",
                    "parameterSchema": [
                        {
                            "name": "timestamp",
                            "type": "datetime",
                            "required": True,
                            "default": aurora_default,
                        },
                    ],
                    "capabilities": {
                        "colorbar": False,
                        "projection": False,
                        "renderJobs": False,
                        "async": True,
                    },
                    "availabilityStrategy": "local-index-then-acquire",
                    "remoteAcquisition": True,
                }
            )
            continue
        if product in KEOGRAMS:
            products.append(
                {
                    "productId": product,
                    "title": product.upper(),
                    "category": "ionosphere",
                    "graphType": "keogram",
                    "available": True,
                    "units": MAPS[KEOGRAMS[product]][1],
                    "parameterSchema": [
                        {"name": "start", "type": "datetime", "required": True},
                        {"name": "end", "type": "datetime", "required": True},
                        {
                            "name": "timeStepMinutes",
                            "type": "select",
                            "required": False,
                            "default": 5,
                            "values": [1, 5, 10, 15, 30, 60],
                        },
                        {
                            "name": "latitudeStepDegrees",
                            "type": "select",
                            "required": False,
                            "default": 2.5,
                            "values": [1, 2.5, 5, 10],
                        },
                        {
                            "name": "hemisphere",
                            "type": "select",
                            "required": False,
                            "default": "west",
                            "values": ["west", "east", "all"],
                        },
                    ],
                    "capabilities": {"colorbar": True, "async": True},
                    "availabilityStrategy": "local-index-then-acquire",
                    "remoteAcquisition": remote_maps,
                }
            )
            continue
        is_map = product in MAPS
        columns = [] if is_map else product_columns(product, known)
        schema = (
            [
                {"name": "timestamp", "type": "datetime", "required": True},
                {
                    "name": "resolution",
                    "type": "select",
                    "required": False,
                    "default": "full",
                    "values": ["full", "medium", "low"],
                },
                {
                    "name": "format",
                    "type": "select",
                    "required": False,
                    "default": "arrow",
                    "values": ["arrow", "json"],
                },
            ]
            if is_map
            else [
                {"name": "start", "type": "datetime", "required": True},
                {"name": "end", "type": "datetime", "required": True},
                {
                    "name": "columns",
                    "type": "multiselect",
                    "required": True,
                    "values": columns,
                    "default": columns[:1],
                },
            ]
        )
        products.append(
            {
                "productId": product,
                "title": product.upper(),
                "category": "maps" if is_map else "space-weather",
                "graphType": "map" if is_map else "timeseries",
                "available": True,
                "units": MAPS[product][1]
                if is_map
                else {c: column_spec(c).units for c in columns},
                "parameterSchema": schema,
                "capabilities": {
                    "colorbar": is_map,
                    "projection": is_map,
                    "renderJobs": is_map,
                    "async": True,
                },
                "availabilityStrategy": "local-index-then-acquire",
                "remoteAcquisition": (remote_maps or product == "gim-map")
                if is_map
                else product != "nmdb",
                "columnMetadata": {
                    c: {
                        "source": column_spec(c).source,
                        "units": column_spec(c).units,
                        "frequencySeconds": column_spec(c).seconds,
                        "offsetSeconds": 0,
                        **(
                            {
                                "station": column_spec(c).raw_name,
                                **station_metadata[column_spec(c).raw_name],
                            }
                            if column_spec(c).source == "nmdb"
                            and station_metadata
                            and column_spec(c).raw_name in station_metadata
                            else {}
                        ),
                    }
                    for c in columns
                },
            }
        )
    return {"products": products}
