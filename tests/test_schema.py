from __future__ import annotations

from conftest import REPO

from lotse.model.schema import schemas


def test_committed_schemas_are_up_to_date() -> None:
    """``lotse schema`` nach Modelländerungen ausführen."""
    for name, text in schemas().items():
        assert (REPO / "schemas" / name).read_text(encoding="utf-8") == text, name
