import pytest


def pytest_addoption(parser):
    """Add a --run-integration option to pytest."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests",
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests if --run-integration is not given."""
    if config.getoption("--run-integration"):
        # --run-integration is given, do not skip tests.
        return

    # --run-integration is NOT given, skip all tests marked with "integration".
    skipper = pytest.mark.skip(reason="add --run-integration option to run this test")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skipper)
