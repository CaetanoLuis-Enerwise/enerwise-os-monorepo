import argparse
import json

from agentic_loops.runtime import AgenticRuntime


def print_result(result: dict) -> None:
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Enerwise agentic loop")
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run")
    run_parser.add_argument("--task", required=True)
    run_parser.add_argument("--thread-id")
    run_parser.add_argument(
        "--approval-mode",
        choices=["risk", "always", "never"],
        default="risk",
    )
    run_parser.add_argument("--max-react-steps", type=int, default=6)
    run_parser.add_argument("--max-iterations", type=int, default=3)
    run_parser.add_argument("--quality-threshold", type=float, default=0.85)

    resume_parser = commands.add_parser("resume")
    resume_parser.add_argument("--thread-id", required=True)
    decision = resume_parser.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    decision.add_argument("--edit")

    status_parser = commands.add_parser("status")
    status_parser.add_argument("--thread-id", required=True)

    memory_parser = commands.add_parser("memory")
    memory_parser.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    try:
        runtime = AgenticRuntime()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        if args.command == "run":
            result = runtime.run(
                task=args.task,
                thread_id=args.thread_id,
                approval_mode=args.approval_mode,
                max_react_steps=args.max_react_steps,
                max_optimization_iterations=args.max_iterations,
                quality_threshold=args.quality_threshold,
            )
        elif args.command == "resume":
            selected = (
                "approve"
                if args.approve
                else "reject"
                if args.reject
                else "edit"
            )
            result = runtime.resume(
                thread_id=args.thread_id,
                decision=selected,
                candidate=args.edit,
            )
        elif args.command == "status":
            result = runtime.status(args.thread_id)
        else:
            result = {
                "status": "success",
                "episodes": runtime.memory.recent(args.limit),
            }
        print_result(result)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
