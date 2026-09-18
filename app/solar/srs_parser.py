"""Parse section I (regions with spots), not plages or expected returns."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from app.solar.models import ActiveRegion, SRSReport

logger = logging.getLogger(__name__)
LOCATION = r"([NS])\s*(\d{1,2})\s*([EW])\s*(\d{1,2})"


def parse_location(value: str) -> tuple[float, float]:
    """Return Stonyhurst (latitude, longitude) in degrees: N/W positive, S/E negative.

    Thus N15E20 -> (15, -20), S11W35 -> (-11, 35), N00E00 -> (0, 0).
    Spaces inside fixed-width SRS locations are accepted.
    """
    match = re.fullmatch(LOCATION, value.strip(), flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid SRS location: {value!r}")
    ns, lat, ew, lon = match.groups()
    latitude, longitude = int(lat), int(lon)
    if latitude > 90 or longitude > 90:
        raise ValueError(f"SRS location outside the visible hemisphere: {value}")
    return latitude * (1 if ns.upper() == "N" else -1), longitude * (
        1 if ew.upper() == "W" else -1
    )


def parse_srs(text: str) -> SRSReport:
    issued_match = re.search(
        r":Issued:\s*(\d{4}\s+\w{3}\s+\d{1,2}\s+\d{4})\s+UTC", text
    )
    section = re.search(
        r"^I\.\s+Regions with Sunspots.*?Locations Valid at\s+(\d{1,2})/(\d{2})(\d{2})Z",
        text,
        re.MULTILINE,
    )
    if not issued_match or not section:
        raise ValueError("SRS is missing its issue date or section-I coordinate epoch")
    issued = datetime.strptime(issued_match[1], "%Y %b %d %H%M").replace(tzinfo=UTC)
    day, hour, minute = map(int, section.groups())
    if not (0 <= hour <= 24 and 0 <= minute < 60) or (hour == 24 and minute):
        raise ValueError("Invalid SRS validity time")
    # Day belongs to the report's current or preceding month, including year rollover.
    candidates = []
    for offset in range(32):
        candidate = issued.replace(hour=0, minute=0) - timedelta(days=offset)
        if candidate.day == day:
            candidates.append(candidate + timedelta(hours=hour, minutes=minute))
    candidates = [
        value
        for value in candidates
        if abs((issued - value).total_seconds()) <= 2 * 86400
    ]
    if not candidates:
        raise ValueError("SRS coordinate epoch is inconsistent with the issue date")
    epoch = min(candidates, key=lambda value: abs((issued - value).total_seconds()))
    body = re.split(
        r"^IA\.|^II\.", text[section.end() :], maxsplit=1, flags=re.MULTILINE
    )[0]
    regions = []
    for line in body.splitlines():
        if not re.match(r"\s*\d", line):
            continue
        try:
            match = re.match(
                rf"\s*(\d{{1,5}})\s+({LOCATION})\s+(.*)$", line, flags=re.IGNORECASE
            )
            if not match:
                raise ValueError("Malformed region row")
            number = int(match[1])
            if issued > datetime(2002, 6, 15, tzinfo=UTC) and number < 10000:
                number += 10000
            latitude, longitude = parse_location(match[2])
            fields = match[
                7
            ].split()  # Carrington longitude, area, Z, LL, NN, magnetic class

            def optional_int(index, fields=fields):
                return (
                    int(fields[index])
                    if len(fields) > index and fields[index].isdigit()
                    else None
                )

            regions.append(
                ActiveRegion(
                    number=number,
                    latitude=latitude,
                    longitude=longitude,
                    epoch=epoch,
                    area=optional_int(1),
                    spot_count=optional_int(4),
                    magnetic_class=" ".join(fields[5:]) or None,
                    mcintosh_class=fields[2] if len(fields) > 2 else None,
                    raw_line=line,
                )
            )
        except (ValueError, IndexError) as exc:
            logger.warning("Skipping invalid SRS region %r: %s", line, exc)
    if not regions and not re.search(r"\bNone\b", body, re.IGNORECASE):
        raise ValueError("No usable SRS region rows and no explicit 'None' report")
    return SRSReport(issued, epoch, tuple(regions))
