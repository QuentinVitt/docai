from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from docai.llm.datatypes import LLMProfile, LogConfig, ModelConfig
from docai.llm.service import LLMService
from tests.evals.framework.cases import load_cases
from tests.evals.framework.reporter import print_results, save_results
from tests.evals.framework.runner import PROJECT_ROOT, run

RESULTS_ROOT = PROJECT_ROOT / "tests" / "evals" / "results"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tests.evals",
        description="Run DocAI eval suite against real LLM API.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="Run eval cases and report results.")
    run_cmd.add_argument("--area", default=None, help="Eval area to run (default: all)")
    run_cmd.add_argument("--case", default=None, help="Comma-separated case IDs to run")
    run_cmd.add_argument("--model", required=True, help="LiteLLM model string, e.g. gemini/gemini-2.5-flash")
    run_cmd.add_argument("--api-key", required=True, dest="api_key", help="API key for the model provider")
    run_cmd.add_argument("-j", type=int, default=10, dest="concurrency", help="Parallel concurrency (default: 10)")

    return parser.parse_args(argv)


def _load_all_cases(area: str | None, ids: list[str] | None) -> list:
    areas_root = PROJECT_ROOT / "tests" / "evals" / "cases"
    if area:
        return load_cases(area, ids=ids)
    if not areas_root.is_dir():
        return []
    all_cases = []
    for area_dir in sorted(areas_root.iterdir()):
        if area_dir.is_dir():
            all_cases.extend(load_cases(area_dir.name, ids=ids))
    return all_cases


async def _run(args: argparse.Namespace) -> int:
    ids = [s.strip() for s in args.case.split(",")] if args.case else None

    cases = _load_all_cases(args.area, ids)
    if not cases:
        print("No cases found.", file=sys.stderr)
        return 1

    log_dir = PROJECT_ROOT / "tests" / "evals" / ".llm_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    profile = LLMProfile(
        models=[ModelConfig(model=args.model, api_key=args.api_key)],
    )
    log_config = LogConfig(log_dir=log_dir, clean_on_start=True)
    service = LLMService(profile=profile, log_config=log_config)

    print(f"Running {len(cases)} cases with model={args.model}, concurrency={args.concurrency}\n")
    results = await run(cases, service, concurrency=args.concurrency)

    print_results(results)

    stats = service.stats()
    print(f"\nLLM calls: {stats.total_calls}  |  cost: ${stats.total_cost_usd:.4f}"
          if stats.total_cost_usd is not None
          else f"\nLLM calls: {stats.total_calls}")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = RESULTS_ROOT / ts
    save_results(results, run_dir=run_dir)
    print(f"\nResults saved to {run_dir.relative_to(PROJECT_ROOT)}")

    return 0


def main() -> None:
    args = _parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
