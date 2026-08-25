from __future__ import annotations

import functools
import http.server
import webbrowser
from pathlib import Path


def serve_site(
    directory: Path,
    *,
    study: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = False,
) -> None:
    if not (directory / "index.html").is_file():
        raise FileNotFoundError(f"No built Atlas site at {directory}; run `atlas site build`")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer((host, port), handler)
    route = f"studies/{study}/v1/" if study else ""
    url = f"http://{host}:{port}/{route}"
    if open_browser:
        webbrowser.open(url)
    print(f"Serving the Atlas at {url}. Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
