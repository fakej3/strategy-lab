"""EdgeLab web server entry point.

Usage
-----
    python serve.py                      # default: 0.0.0.0:8000
    python serve.py --host 127.0.0.1 --port 9000
    python serve.py --reload             # development hot-reload

Environment variables
---------------------
    EDGELAB_USERNAME        Login username (default: admin)
    EDGELAB_PASSWORD_HASH   PBKDF2 hash of the password (default: accepts 'admin')
    EDGELAB_SECRET_KEY      Session signing key (auto-generated + persisted if unset)
    EDGELAB_DB              Path to SQLite database (default: research.db)
    EDGELAB_REPORTS         Path to reports directory (default: reports)
    EDGELAB_DATA_DIR        Path to market data cache (default: data/bars)
    EDGELAB_LOG             Path to log file (default: logs/research.log)

Generate a password hash
------------------------
    python -c "from server.auth import hash_password; print(hash_password('yourpass'))"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="EdgeLab Web Server")
    parser.add_argument("--host",   default="0.0.0.0",  help="Bind host")
    parser.add_argument("--port",   default=8000, type=int, help="Bind port")
    parser.add_argument("--reload", action="store_true",    help="Hot-reload (dev)")
    parser.add_argument("--log-level", default="info",
                        choices=["debug","info","warning","error"])
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: pip install uvicorn[standard]", file=sys.stderr)
        return 1

    # Warn if using default credentials
    from server.auth import USING_DEFAULT_CREDS
    if USING_DEFAULT_CREDS:
        print(
            "\n  ⚠  WARNING: No password configured. Default credentials: admin / admin\n"
            "     Set EDGELAB_PASSWORD_HASH to secure this server.\n"
            "     Generate: python -c \"from server.auth import hash_password; "
            "print(hash_password('yourpassword'))\"\n",
            file=sys.stderr,
        )

    print(f"  EdgeLab starting on http://{args.host}:{args.port}", flush=True)

    uvicorn.run(
        "server.app:app",
        host      = args.host,
        port      = args.port,
        reload    = args.reload,
        log_level = args.log_level,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
