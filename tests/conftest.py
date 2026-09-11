"""Shared setup for the backend tests.

Everything here runs against captured ESPN responses rather than the network — see
services/espn/client._fixture. The variable is set before any import that reads it, so a
test can never quietly fall through to a live call and start passing or failing on
whatever happened in the real NFL that week.
"""
import os
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "espn"


@pytest.fixture(autouse=True)
def espn_fixtures(monkeypatch):
    monkeypatch.setenv("ESPN_FIXTURE_DIR", str(FIXTURES))
