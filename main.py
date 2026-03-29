from __future__ import annotations

import os

import uvicorn

from backend.app.main import app, create_app

__all__ = ["app", "create_app"]


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=port, reload=False)
