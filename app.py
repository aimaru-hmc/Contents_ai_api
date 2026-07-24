from __future__ import annotations

import argparse
import os

try:
    from fastapi import FastAPI
except ImportError as error:
    raise RuntimeError(
        "FastAPI dependencies are missing. Install them with: "
        "pip install fastapi uvicorn python-multipart"
    ) from error

from routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Full TOC API", version="4.0")
    app.include_router(router)
    return app


app = create_app()


def parse_server_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full TOC FastAPI server")
    parser.add_argument("--host", default=os.getenv("FULL_TOC_API_HOST", "127.0.0.1"), help="REST API host")
    parser.add_argument("--port", type=int, default=int(os.getenv("FULL_TOC_API_PORT", "8080")), help="REST API port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    return parser.parse_args(argv)


def main() -> None:
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError("uvicorn is missing. Install it with: pip install uvicorn") from error
    args = parse_server_args()
    uvicorn.run("app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
