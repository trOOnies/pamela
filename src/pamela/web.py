"""Command-line entry point: ``python -m pamela.web`` (or ``pamela``)."""

from __future__ import annotations

import argparse

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pamela", description="Run the Pamela web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = parser.parse_args(argv)

    uvicorn.run(
        "pamela.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=["src"] if args.reload else None,
    )


if __name__ == "__main__":
    main()
