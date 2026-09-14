import json
import pytest
from trace_grabber.analytics import (graphql, fetch_game_moments, user_hash_key,
                                     GQL_URL, GAME_Q)

class _Resp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p

class _FakeRequest:
    """Records POSTs and returns queued payloads in order."""
    def __init__(self, payloads): self._payloads = list(payloads); self.calls = []
    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": json.loads(data)})
        return _Resp(self._payloads.pop(0))
    def get(self, url, timeout=None):
        return _Resp(self._payloads.pop(0))

def test_graphql_returns_data_and_posts_to_endpoint():
    req = _FakeRequest([{"data": {"ping": 1}}])
    out = graphql(req, "query { ping }", {"x": 2})
    assert out == {"ping": 1}
    assert req.calls[0]["url"] == GQL_URL
    assert req.calls[0]["data"] == {"query": "query { ping }", "variables": {"x": 2}}

def test_graphql_raises_on_errors():
    req = _FakeRequest([{"errors": [{"message": "nope"}]}])
    with pytest.raises(RuntimeError):
        graphql(req, "q", {})

def test_fetch_game_moments_reports_access_and_list():
    payload = {"data": {"game": {"access": {"allowed": True},
                                 "moments": [{"type": "touch_chain"}]}}}
    req = _FakeRequest([payload])
    allowed, moments = fetch_game_moments(req, 13787132, "hk",
                                          {"user_id": 1, "token": "t", "timestamp": 0})
    assert allowed is True and len(moments) == 1

def test_fetch_game_moments_denied():
    payload = {"data": {"game": {"access": {"allowed": False}, "moments": []}}}
    req = _FakeRequest([payload])
    allowed, moments = fetch_game_moments(req, 1, "hk",
                                          {"user_id": 1, "token": "t", "timestamp": 0})
    assert allowed is False and moments == []

def test_game_query_passes_hash_key_to_moments():
    # Regression: the `moments` field itself requires the hash_key argument;
    # omitting it makes Trace reject every game query.
    assert "moments(hash_key: $hash_key)" in GAME_Q

def test_user_hash_key_reads_profile_graphql():
    # Regression: hash_key comes from the GraphQL profile, not users/self.
    req = _FakeRequest([{"data": {"profile": {"hash_key": "Jz6Derozv"}}}])
    hk = user_hash_key(req, {"user_id": 42, "token": "t", "timestamp": 0})
    assert hk == "Jz6Derozv"
    assert req.calls[0]["url"] == GQL_URL
    assert req.calls[0]["data"]["variables"] == {"user_id": 42,
                                                 "token": {"user_id": 42, "token": "t", "timestamp": 0}}
