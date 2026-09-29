import httpx

from nightwatch.data.qwen import QwenClient


def _client(keys, statuses):
    """A client whose gateway answers with ``statuses`` in turn and records the key each request carried."""
    seen: list[str] = []
    replies = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"].removeprefix("Bearer "))
        code = next(replies)
        if code != 200:
            return httpx.Response(code, text="quota exhausted")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "model": "qwen3.8-max", "usage": {}})

    c = QwenClient(api_key="unused", rate_per_sec=0)
    c._keys, c._key_at = keys, 0
    c._client = httpx.Client(base_url="https://gw.test/v1", transport=httpx.MockTransport(handler))
    return c, seen


def test_a_refused_key_moves_to_the_spare_without_waiting():
    """A subsidy key that runs dry mid-judging should cost one retry, not the chat."""
    c, seen = _client(["main", "spare"], [402, 200])
    assert c.chat([{"role": "user", "content": "hi"}]).text == "ok"
    assert seen == ["main", "spare"]


def test_with_no_spare_a_refusal_is_raised_as_before():
    import pytest

    from nightwatch.data.qwen import QwenError

    c, seen = _client(["main"], [401])
    with pytest.raises(QwenError, match="401"):
        c.chat([{"role": "user", "content": "hi"}])
    assert seen == ["main"]


def test_both_env_keys_are_read_and_deduplicated(monkeypatch):
    from nightwatch.data import qwen

    monkeypatch.setenv(qwen.KEY_ENV, "a")
    monkeypatch.setenv(qwen.SPARE_KEY_ENV, "b")
    assert qwen._env_keys() == ["a", "b"]
    monkeypatch.setenv(qwen.SPARE_KEY_ENV, "a")
    assert qwen._env_keys() == ["a"]
    monkeypatch.delenv(qwen.KEY_ENV)
    assert qwen._env_keys() == ["a"] and qwen.credentials_present()
