"""A guard on the guard.

If any test here starts reaching ESPN, it will pass or fail on whatever the real NFL did
that week rather than on the code. This makes that impossible to do by accident.
"""
import datetime

import pytest
import requests

from services.espn.client import fetch_boxscore, fetch_slate_games


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached the network instead of a fixture")
    monkeypatch.setattr(requests, "get", refuse)


def test_the_suite_never_calls_espn(no_network):
    assert fetch_slate_games(datetime.date(2026, 9, 9))[0].state == "post"
    assert fetch_boxscore("401872656")["SEA"]
