import pytest

from herdr_core.backoff import Backoff


def test_grows_and_caps_then_resets() -> None:
    backoff = Backoff(initial=0.5, factor=2, maximum=3)
    assert [backoff.next_delay() for _ in range(5)] == [0.5, 1, 2, 3, 3]
    backoff.reset()
    assert backoff.next_delay() == 0.5


@pytest.mark.parametrize("kwargs", [{"initial": 0}, {"factor": 0.5}, {"initial": 5, "maximum": 1}])
def test_rejects_invalid_parameters(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Backoff(**kwargs)
