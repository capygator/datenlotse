"""Viewer muss ohne Netz funktionieren: keine externen Skripte, Bibliotheken im Paket."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import NORDWIND
from fastapi.testclient import TestClient

from lotse.serve import create_app
from lotse.serve.app import VENDOR_FILES, viewer_html


def test_viewer_references_no_external_urls() -> None:
    assert not re.search(r"""(src|href)=["']https?://""", viewer_html())


def test_vendor_files_are_served(tmp_path: Path) -> None:
    app = create_app(NORDWIND)
    with TestClient(app) as client:
        for name in sorted(VENDOR_FILES):
            res = client.get(f"/vendor/{name}")
            assert res.status_code == 200, name
            assert len(res.content) > 1000
        assert client.get("/vendor/../app.py").status_code == 404
        assert client.get("/vendor/unbekannt.js").status_code == 404
