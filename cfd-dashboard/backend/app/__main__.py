import argparse
import os
import threading
from pathlib import Path

import uvicorn

from app.config import AppConfig, DEFAULT_FUNCTION_OBJECTS
from app.main import create_app


def main():
    parser = argparse.ArgumentParser(description="CFD optimization dashboard backend")
    parser.add_argument(
        "--runs-dir",
        default=os.environ.get("CFD_RUNS_DIR", "../runs"),
        help="Directory containing OpenFOAM case folders",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=int(os.environ["CFD_BUDGET"]) if os.environ.get("CFD_BUDGET") else 40,
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--demo-run-seconds", type=float, default=25.0)
    parser.add_argument("--demo-concurrency", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fo-inlet", default=DEFAULT_FUNCTION_OBJECTS["inlet_pressure"])
    parser.add_argument("--fo-outlet", default=DEFAULT_FUNCTION_OBJECTS["outlet_pressure"])
    parser.add_argument("--fo-tmax", default=DEFAULT_FUNCTION_OBJECTS["solid_temperature"])
    parser.add_argument("--fo-tmean", default=DEFAULT_FUNCTION_OBJECTS["solid_temperature_avg"])
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = (Path.cwd() / runs_dir).resolve()
    runs_dir.mkdir(parents=True, exist_ok=True)
    if args.demo:
        from mock.generate_runs import run_generator

        generator = threading.Thread(
            target=run_generator,
            kwargs={
                "runs_dir": runs_dir,
                "budget": args.budget,
                "concurrency": args.demo_concurrency,
                "run_seconds": args.demo_run_seconds,
                "seed": args.seed,
            },
            name="cfd-mock-generator",
            daemon=True,
        )
        generator.start()

    app = create_app(
        AppConfig(
            runs_dir=runs_dir,
            budget=args.budget,
            poll_interval=args.poll_interval,
            function_objects={
                "inlet_pressure": args.fo_inlet,
                "outlet_pressure": args.fo_outlet,
                "solid_temperature": args.fo_tmax,
                "solid_temperature_avg": args.fo_tmean,
            },
        )
    )
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
