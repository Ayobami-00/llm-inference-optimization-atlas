from __future__ import annotations

import io
from http import HTTPStatus
from unittest.mock import Mock

from atlas.graph.server import AtlasRequestHandler


def test_server_uses_branded_not_found_page(tmp_path) -> None:
    content = b"<!doctype html><title>Atlas path not found</title>"
    (tmp_path / "404.html").write_bytes(content)
    handler = object.__new__(AtlasRequestHandler)
    handler.directory = str(tmp_path)
    handler.command = "GET"
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()

    handler.send_error(HTTPStatus.NOT_FOUND)

    handler.send_response.assert_called_once_with(HTTPStatus.NOT_FOUND, None)
    handler.send_header.assert_any_call("Content-Type", "text/html; charset=utf-8")
    handler.send_header.assert_any_call("Content-Length", str(len(content)))
    assert handler.wfile.getvalue() == content
