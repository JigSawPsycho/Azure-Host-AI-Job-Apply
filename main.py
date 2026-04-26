"""Local dev entrypoint: `python -m ai_apply.main` or `uvicorn main:app`.

In production, run with uvicorn/gunicorn directly:
    uvicorn ai_apply.api.app:create_app --factory --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Imported after .env so the modules see env vars.
from api.app import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
