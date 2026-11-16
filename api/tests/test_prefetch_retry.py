import httpx

import app.jobs.prefetch_weather as job


def flaky(fail_times, exc):
    calls = {"n": 0}
    def fetch(batch):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc
        return [{"time": [], "cloud_cover": []} for _ in batch]
    return fetch, calls


def test_retries_connect_timeout_then_succeeds(monkeypatch):
    fetch, calls = flaky(2, httpx.ConnectTimeout("handshake timed out"))
    monkeypatch.setattr(job, "fetch_cloud_batch", fetch)
    waits = []
    assert job.fetch_with_retry([(23.0, 120.0)], "t", sleep=waits.append) is not None
    assert calls["n"] == 3 and waits == [10, 30]


def test_gives_up_after_all_backoffs(monkeypatch):
    fetch, calls = flaky(99, httpx.ConnectTimeout("x"))
    monkeypatch.setattr(job, "fetch_cloud_batch", fetch)
    assert job.fetch_with_retry([(23.0, 120.0)], "t", sleep=lambda s: None) is None
    assert calls["n"] == len(job.BACKOFF_SECONDS) + 1


def test_bad_request_is_not_retried(monkeypatch):
    req = httpx.Request("GET", "https://example.com")
    err = httpx.HTTPStatusError("400", request=req, response=httpx.Response(400, request=req))
    fetch, calls = flaky(99, err)
    monkeypatch.setattr(job, "fetch_cloud_batch", fetch)
    assert job.fetch_with_retry([(23.0, 120.0)], "t", sleep=lambda s: None) is None
    assert calls["n"] == 1


def test_429_is_retried(monkeypatch):
    req = httpx.Request("GET", "https://example.com")
    err = httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))
    fetch, calls = flaky(1, err)
    monkeypatch.setattr(job, "fetch_cloud_batch", fetch)
    assert job.fetch_with_retry([(23.0, 120.0)], "t", sleep=lambda s: None) is not None
    assert calls["n"] == 2