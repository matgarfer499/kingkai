import kingkai


def test_version_is_string() -> None:
    assert isinstance(kingkai.__version__, str)
