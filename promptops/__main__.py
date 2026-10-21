"""``python -m promptops serve`` entrypoint."""

from __future__ import annotations

import argparse

import uvicorn

from promptops.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="promptops", description="PromptOps Console")
    parser.add_argument("command", choices=["serve"], nargs="?", default="serve")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = get_settings()
    uvicorn.run(
        "promptops.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    main()
