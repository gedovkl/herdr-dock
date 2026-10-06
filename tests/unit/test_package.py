import herdr_core


def test_version_is_exposed() -> None:
    assert herdr_core.__version__ == "0.1.0"
