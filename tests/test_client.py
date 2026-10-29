import pytest
import requests

from nba_pipeline.client import Blocked, EspnClient, FetchError, NotAvailable
from tests.conftest import FakeResponse

URL = "https://espn.test/nba/x"


def test_returns_json_on_200(client, session):
    session.add(URL, FakeResponse(200, {"ok": True}))
    assert client.get_json(URL) == {"ok": True}
    assert client.request_count == 1


def test_urls():
    c = EspnClient()
    assert c.scoreboard_url("20261028").endswith("/scoreboard?limit=100&dates=20261028")
    assert c.summary_url("401909881").endswith("/summary?event=401909881")
    assert c.scoreboard_url().endswith("/scoreboard?limit=100")


@pytest.mark.parametrize("status", [401, 403])
def test_blocked_raises_immediately(client, session, status):
    session.add(URL, FakeResponse(status))
    with pytest.raises(Blocked, match=str(status)):
        client.get_json(URL)
    assert session.calls == [URL]  # no retries against a block


def test_404_is_not_available(client, session):
    session.add(URL, FakeResponse(404))
    with pytest.raises(NotAvailable):
        client.get_json(URL)


def test_retries_transient_errors_then_succeeds(client, session):
    session.add(URL, FakeResponse(503), requests.ConnectionError("boom"), FakeResponse(200, {"ok": 1}))
    assert client.get_json(URL) == {"ok": 1}
    assert len(session.calls) == 3


def test_gives_up_after_max_retries(client, session):
    session.add(URL, FakeResponse(429))
    with pytest.raises(FetchError, match="after 3 attempts"):
        client.get_json(URL)


def test_non_retryable_status_fails_fast(client, session):
    session.add(URL, FakeResponse(400))
    with pytest.raises(FetchError, match="HTTP 400"):
        client.get_json(URL)
    assert len(session.calls) == 1


def test_non_json_200_is_an_error(client, session):
    session.add(URL, FakeResponse(200, ValueError("html page")))
    with pytest.raises(FetchError, match="non-JSON"):
        client.get_json(URL)


def test_exponential_backoff(settings, session):
    sleeps = []
    c = EspnClient(settings, session=session, sleep=sleeps.append)
    session.add(URL, FakeResponse(500), FakeResponse(500), FakeResponse(200, {}))
    c.get_json(URL)
    backoffs = [s for s in sleeps if s >= 1]
    assert len(backoffs) == 2 and 1 <= backoffs[0] < 1.6 and 2 <= backoffs[1] < 2.6


def test_rate_limit_spaces_requests(settings, session):
    from dataclasses import replace

    t, sleeps = [100.0], []
    c = EspnClient(replace(settings, min_request_interval=0.5), session=session,
                   sleep=lambda s: (sleeps.append(s), t.__setitem__(0, t[0] + s)), clock=lambda: t[0])
    session.add(URL, FakeResponse(200, {}))
    c.get_json(URL)
    c.get_json(URL)
    assert sleeps == [pytest.approx(0.5)]
