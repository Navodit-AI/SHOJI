"""Run the proxy: `python -m shoji`."""

import uvicorn

from shoji.app import create_app
from shoji.capture import configure_logging


def main() -> None:
    configure_logging()
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
