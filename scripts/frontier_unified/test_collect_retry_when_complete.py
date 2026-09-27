import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_collector():
    path = HERE / "collect_retry_when_complete.py"
    spec = importlib.util.spec_from_file_location("retry_collector", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collector_freezes_tiering_import_closure():
    sources = {path.resolve() for path in load_collector().collector_sources()}
    assert (HERE.parent / "frontier_dla" / "import_website.py").resolve() in sources
