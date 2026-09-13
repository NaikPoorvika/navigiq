import sys
from pathlib import Path

# ai/benchmarks on the path so `import nq027` works from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
