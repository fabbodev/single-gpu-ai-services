import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
os.environ["AI_CLIENT_TOKENS_FILE"] = str(
    REPO / "tests" / "fixtures" / "client-tokens.json"
)
os.environ["AI_DISPATCHER_TOKEN_FILE"] = str(
    REPO / "tests" / "fixtures" / "dispatcher-token.txt"
)
sys.path.insert(0, str(ROOT))
