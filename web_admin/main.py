from __future__ import annotations

import logging
import uvicorn

from web_admin.config import load_web_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = load_web_settings()
    uvicorn.run("web_admin.app:app", host=s.host, port=s.port, log_level="info", access_log=True)


if __name__ == "__main__":
    main()
