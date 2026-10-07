"""Weather MCP Tool의 응답 계약을 외부 네트워크 없이 검증합니다."""

import httpx
import pytest

from src import server as weather_server


class FakeClient:
    """httpx.Client 대신 미리 준비한 응답을 순서대로 반환합니다."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = iter(responses)
        self.requests: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, url: str, params: dict) -> httpx.Response:
        self.requests.append((url, params))
        return next(self.responses)


def response(status_code: int, payload: dict, url: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(status_code, json=payload, request=request)


def install_fake_client(monkeypatch, responses: list[httpx.Response]) -> FakeClient:
    client = FakeClient(responses)
    monkeypatch.setattr(weather_server.httpx, "Client", lambda **_kwargs: client)
    return client


def test_get_weather_returns_tomorrow_forecast(monkeypatch) -> None:
    client = install_fake_client(
        monkeypatch,
        [
            response(
                200,
                {
                    "results": [
                        {
                            "name": "서울",
                            "country": "대한민국",
                            "latitude": 37.57,
                            "longitude": 126.98,
                        }
                    ]
                },
                weather_server.GEOCODING_API_URL,
            ),
            response(
                200,
                {
                    "daily": {
                        "time": ["2026-10-02", "2026-10-03"],
                        "temperature_2m_max": [22.0, 24.0],
                        "temperature_2m_min": [13.0, 15.0],
                        "precipitation_probability_max": [10, 30],
                        "weather_code": [1, 2],
                    }
                },
                weather_server.FORECAST_API_URL,
            ),
        ],
    )

    result = weather_server.get_weather("서울", "tomorrow")

    assert result == {
        "success": True,
        "city": "서울",
        "country": "대한민국",
        "date": "2026-10-03",
        "temperature_max": 24.0,
        "temperature_min": 15.0,
        "precipitation_probability": 30,
        "weather_code": 2,
        "source": "Open-Meteo",
    }
    assert [request[0] for request in client.requests] == [
        weather_server.GEOCODING_API_URL,
        weather_server.FORECAST_API_URL,
    ]


def test_get_weather_returns_city_not_found(monkeypatch) -> None:
    client = install_fake_client(
        monkeypatch,
        [response(200, {"results": []}, weather_server.GEOCODING_API_URL)],
    )

    result = weather_server.get_weather("없는도시", "today")

    assert result == {
        "success": False,
        "error": "CITY_NOT_FOUND",
        "city": "없는도시",
    }
    assert len(client.requests) == 1


def test_get_weather_rejects_invalid_day() -> None:
    with pytest.raises(ValueError, match="today 또는 tomorrow"):
        weather_server.get_weather("서울", "next-week")


def test_get_weather_propagates_upstream_http_error(monkeypatch) -> None:
    install_fake_client(
        monkeypatch,
        [response(503, {"error": "unavailable"}, weather_server.GEOCODING_API_URL)],
    )

    with pytest.raises(httpx.HTTPStatusError):
        weather_server.get_weather("서울", "today")
