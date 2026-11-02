"""Opt-in one-frame JSOC integration check; never executed by CI.

python -m deploy.jsoc_check --email YOUR_REGISTERED_EMAIL --root files
"""

import argparse
from unittest.mock import patch

import matplotlib.pyplot as plt

from app.pipeline.solar_disk_pipeline import build_solar_disk, prepare_solar_disk
from app.solar.jsoc_provider import JSOCProvider
from app.solar.jsoc_transport import DRMSClient
from app.solar.models import SolarDiskConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Registered JSOC export email")
    parser.add_argument("--root", default="files")
    parser.add_argument(
        "--annotations", action="store_true", help="Also fetch historical NOAA SRS"
    )
    parser.add_argument(
        "--check-export-session",
        action="store_true",
        help="Try saved export ID with a second independent DRMS client",
    )
    args = parser.parse_args()
    config = SolarDiskConfig(
        provider="jsoc",
        jsoc_email=args.email,
        requested_time="2026-01-20T12:00:00Z",
        download_base_dir=args.root,
        annotate_active_regions=args.annotations,
    )
    first = prepare_solar_disk(config)
    print("Selected:", first.metadata["jsoc"]["record"])
    # All HTTP is forbidden on the repeated request, including NOAA when enabled.
    with patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Repeated request attempted HTTP"),
    ):
        second = prepare_solar_disk(config)
        assert second.metadata["jsoc"]["map_path"] == first.metadata["jsoc"]["map_path"]
        fig, _ = build_solar_disk(config)
        plt.close(fig)
    print("PASS: repeated request and plot used 0 HTTP calls; PNG:", config.output_path)
    if args.check_export_session:
        provider = JSOCProvider(args.root, config.sdo_product, config.jsoc)
        with provider.index.connect() as db:
            row = db.execute(
                "SELECT e.remote_id FROM exports e JOIN export_items i ON i.export=e.id JOIN observations o ON o.id=i.observation WHERE o.product=? AND e.remote_id IS NOT NULL AND e.status='ready' ORDER BY e.id DESC LIMIT 1",
                (config.sdo_product.key,),
            ).fetchone()
        if row is None:
            print("SKIP: quick path had no export ID")
        else:
            client = DRMSClient(config.jsoc)
            try:
                request = client.restore(row["remote_id"])
                print("Independent DRMS session export status:", client.state(request))
            finally:
                client.close()


if __name__ == "__main__":
    main()
