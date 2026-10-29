import os

os.environ['CLAUDE_LIGHT_FAKE'] = '1'
os.environ.setdefault('CLAUDE_LIGHT_SECRET', 'test-secret')

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from claude.app import create_app  # noqa: E402
from claude.instrument import FakeInstrument  # noqa: E402


@pytest.fixture
def instrument():
    return FakeInstrument(delay=0)


@pytest.fixture
def client(tmp_path, instrument):
    app = create_app(instrument=instrument, db_path=tmp_path / 'test.db',
                     geo_path=tmp_path / 'missing.mmdb')
    with TestClient(app) as c:
        yield c
