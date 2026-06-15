import argparse
import json
import logging
import time
from urllib.request import Request, urlopen


logger = logging.getLogger("enerwise-control-loop")


def run_cycle(api_url: str, mode: str, site_id: str) -> dict:
    payload_data = {
        "source": "dataset",
        "history_points": 336,
        "horizon_hours": 24,
        "execution_mode": mode,
    }
    endpoint = "/operations/control-cycle"
    if mode != "dry_run":
        endpoint = "/operations/live-cycle"
        payload_data["site_id"] = site_id

    payload = json.dumps(payload_data).encode("utf-8")
    request = Request(
        f"{api_url.rstrip('/')}{endpoint}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Enerwise battery controller in safe dry-run mode."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval-minutes", type=int, default=30)
    parser.add_argument(
        "--mode",
        choices=["dry_run", "shadow", "simulated"],
        default="dry_run",
    )
    parser.add_argument("--site-id", default="demo-site")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.interval_minutes < 1:
        raise SystemExit("interval-minutes must be positive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    while True:
        try:
            result = run_cycle(args.api_url, args.mode, args.site_id)
            logger.info(
                "mode=%s action=%s power_kw=%s target_soc=%s safety=%s sent=%s",
                args.mode,
                result["command"]["action"],
                result["command"].get(
                    "battery_power_kw",
                    result["command"].get("requested_power_kw"),
                ),
                result["command"]["target_soc"],
                result["safety"]["passed"],
                result["execution"]["command_sent"],
            )
        except Exception:
            logger.exception("Control cycle failed")

        if args.once:
            break
        time.sleep(args.interval_minutes * 60)


if __name__ == "__main__":
    main()
