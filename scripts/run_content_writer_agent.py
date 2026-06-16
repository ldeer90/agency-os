#!/usr/bin/env python3
from __future__ import annotations

import sys

from run_specialist_agent import run


if __name__ == "__main__":
    raise SystemExit(run(["content_writer_agent", *sys.argv[1:]]))
