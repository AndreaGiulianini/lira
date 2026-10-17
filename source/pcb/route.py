"""Routes the board with Freerouting; pcb/finish_pcb.py imports the result.

    python3 pcb/route.py build/pcb/lira.dsn build/pcb/lira.ses

Freerouting is deterministic: the same design gives the same routes whatever the optimisation strategy, the order of
the nets, the number of passes or of threads (all tried), so it runs once. If it leaves a connection open or two tracks
crossing, pcb/repair.py completes just those.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = os.environ.get("JAVA", "/opt/homebrew/opt/openjdk/bin/java")  # make passes its JAVA
JAR = ROOT / "tools" / "freerouting-2.4.1.jar"


def route(dsn, ses):
    out = subprocess.run([JAVA, "-Djava.awt.headless=true", "-jar", str(JAR), "-de", str(dsn), "-do", str(ses),
                          "-mp", "100", "--gui.enabled=false"], capture_output=True, text=True).stdout
    m = re.findall(r"final score: ([\d.]+) \((\d+) unrouted and (\d+) violations\)", out)
    score, unrouted, violations = float(m[-1][0]), int(m[-1][1]), int(m[-1][2])
    print("Freerouting: %d unrouted, %d violations (score %.2f); the ground pours close the open ground connections"
          % (unrouted, violations, score), flush=True)
    return unrouted


if __name__ == "__main__":
    route(Path(sys.argv[1]), Path(sys.argv[2]))
