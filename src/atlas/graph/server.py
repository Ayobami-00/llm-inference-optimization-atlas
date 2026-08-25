from __future__ import annotations

import functools
import http.server
import webbrowser
from pathlib import Path

PROJECT_BASE = "/llm-inference-optimization-atlas/"


class AtlasRequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        if path.startswith(PROJECT_BASE):
            path = "/" + path[len(PROJECT_BASE) :]
        return super().translate_path(path)


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
    handler = functools.partial(AtlasRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer((host, port), handler)
    route = f"studies/{study}/v1/" if study else ""
    url = f"http://{host}:{port}{PROJECT_BASE}{route}"
    if open_browser:
        webbrowser.open(url)
    print(f"Serving the Atlas at {url}. Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
