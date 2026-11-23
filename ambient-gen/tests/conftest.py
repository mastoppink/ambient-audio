import importlib, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
import config


@pytest.fixture(autouse=True)
def fresh_config():
    importlib.reload(config)  # preset mengubah config global; mulai bersih di tiap tes
    yield
