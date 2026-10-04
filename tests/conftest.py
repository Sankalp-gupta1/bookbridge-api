from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.source import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_dir():
    return FIXTURES


@pytest.fixture
def html():
    return (FIXTURES / "root.html").read_text(encoding="utf-8")


@pytest.fixture
def client():
    with TestClient(create_app(Settings(mode="fixture", min_interval=0))) as value:
        yield value
