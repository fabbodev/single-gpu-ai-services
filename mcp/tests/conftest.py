import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
os.environ["AI_CLIENT_TOKENS_FILE"] = str(
    REPO / "tests" / "fixtures" / "client-tokens.json"
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
