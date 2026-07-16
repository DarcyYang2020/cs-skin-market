\"\"\"
Unified CLI for CS skin market pipeline (v2).
Four-factor model + sector + momentum + events.

Usage:
    python -m pipeline.cli analyze <name> --rarity <r> --source <s> [--discontinued <y>]
    python -m pipeline.cli index
    python -m pipeline.cli sector
    python -m pipeline.cli search <query> [--detail]
    python -m pipeline.cli list
    python -m pipeline.cli history <name>
\"\"\"

import argparse
import sys
sys.stdout.reconfigure(encoding=\"utf-8\")
from pathlib import Path

from . import config, db, collector, scorer, reporter, backtest, portfolio, watchlist, regime
