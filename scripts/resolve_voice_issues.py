#!/usr/bin/env python3
"""Helper that resolves the active voice issues file for the current config."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the repo-local voice issues file that Codex should review."
    )
    parser.add_argument(
        "--repo",
        "-r",
        help="Override the repo key/alias (or path) to target when resolving the issues file.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))

    from voice_app.config import ConfigLoader, DEFAULT_CONFIG_PATH  # pylint: disable=import-outside-toplevel

    config = ConfigLoader.load(DEFAULT_CONFIG_PATH)
    repo_key = args.repo or config.default_repo
    if not repo_key:
        parser.error("No repo provided and config.defaultRepo is unset.")

    repo_config = ConfigLoader.select_repo(config, repo_key)
    print(repo_config.issues_file, end="")


if __name__ == "__main__":
    main()
