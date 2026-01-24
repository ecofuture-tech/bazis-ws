import pytest


@pytest.fixture(scope='function')
def sample_app():
    from sample.main import app
    return app
