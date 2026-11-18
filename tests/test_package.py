import shoji


def test_package_imports_with_version():
    assert shoji.__version__ == "0.1.0"
