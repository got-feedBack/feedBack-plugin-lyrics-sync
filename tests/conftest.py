import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routes  # noqa: E402


@pytest.fixture
def config_dir(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture
def client(config_dir):
    app = FastAPI()
    routes.setup(app, {"config_dir": config_dir, "get_dlc_dir": lambda: None})
    with TestClient(app) as c:
        yield c
