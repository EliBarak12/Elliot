import pytest

from elliot_core.env import env_flag, is_truthy


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", " on ", "On"])
def test_is_truthy_accepts_affirmatives(value: str) -> None:
    assert is_truthy(value) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "anything", None])
def test_is_truthy_rejects_everything_else(value: str | None) -> None:
    assert is_truthy(value) is False


def test_env_flag_unset_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELLIOT_TEST_FLAG", raising=False)
    assert env_flag("ELLIOT_TEST_FLAG") is False
    assert env_flag("ELLIOT_TEST_FLAG", default=True) is True


def test_env_flag_blank_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELLIOT_TEST_FLAG", "   ")
    assert env_flag("ELLIOT_TEST_FLAG") is False
    assert env_flag("ELLIOT_TEST_FLAG", default=True) is True


def test_env_flag_reads_set_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELLIOT_TEST_FLAG", "yes")
    assert env_flag("ELLIOT_TEST_FLAG") is True
    monkeypatch.setenv("ELLIOT_TEST_FLAG", "off")
    # A set-but-non-affirmative value is False even when default is True.
    assert env_flag("ELLIOT_TEST_FLAG", default=True) is False
