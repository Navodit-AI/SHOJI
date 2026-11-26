import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SHOJI_TEST_MODEL") == "1":
        return
    skip = pytest.mark.skip(reason="real-model test; set SHOJI_TEST_MODEL=1 to run")
    for item in items:
        if "model" in item.keywords:
            item.add_marker(skip)
