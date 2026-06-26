"""Launch the pcbforge web UI.

    python web/serve.py            # http://127.0.0.1:8765
    PCBFORGE_PORT=9000 python web/serve.py

Works from any cwd: it puts ``web/`` on sys.path so ``backend`` imports as a
package (its relative imports need that).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402
from backend.app import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PCBFORGE_PORT", "8765"))
    print(f"pcbforge web UI -> http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
