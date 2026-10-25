import asyncio
from datetime import datetime, timezone
from app.service import analyze

class Client:
    async def fetch(self, dataset, start, end):
        if dataset == "FUELHH":
            return [{"fuelType":"WIND","startTime":"2026-01-02T00:00:00Z","generation":100},{"fuelType":"GAS","startTime":"2026-01-02T00:00:00Z","generation":20}]
        return [{"startTime":"2026-01-02T00:00:00Z","publishTime":"2026-01-01T10:00:00Z","generation":90},{"startTime":"2026-01-02T00:00:00Z","publishTime":"2026-01-01T12:00:00Z","generation":999}]

class PartialClient:
    async def fetch(self, dataset, start, end):
        if dataset == "FUELHH":
            return [{"fuelType":"WIND","startTime":"2026-01-02T00:00:00Z","generation":0}]
        return [{"startTime":"2026-01-02T00:00:00Z","publishTime":"2026-01-01T10:00:00Z","generation":10}]

class EmptyClient:
    async def fetch(self, dataset, start, end): return []

def test_selects_forecast_available_at_cutoff_and_metrics():
    result=asyncio.run(analyze(Client(),datetime(2026,1,2,tzinfo=timezone.utc),datetime(2026,1,3,tzinfo=timezone.utc),11))
    assert result["intervals"][0]["forecast"] == 90
    assert result["metrics"]["matchedIntervals"] == 1
    assert result["metrics"]["maeMW"] == 10
    assert result["metrics"]["rmseMW"] == 10
    assert result["metrics"]["mapePercent"] == 10

def test_zero_actual_excluded_from_mape_and_missing_records_remain_empty():
    result=asyncio.run(analyze(PartialClient(),datetime(2026,1,2,tzinfo=timezone.utc),datetime(2026,1,3,tzinfo=timezone.utc),11))
    assert result["metrics"]["matchedIntervals"] == 1
    assert result["metrics"]["mapePercent"] is None
    assert result["metrics"]["mapeExcludedZeroActuals"] == 1
    assert result["intervals"][0]["absoluteError"] == 10

def test_empty_window_has_null_metrics_and_zero_coverage():
    result=asyncio.run(analyze(EmptyClient(),datetime(2026,1,2,tzinfo=timezone.utc),datetime(2026,1,3,tzinfo=timezone.utc),11))
    assert result["intervals"] == []
    assert result["metrics"]["matchedIntervals"] == 0
    assert result["metrics"]["maeMW"] is None
    assert result["metrics"]["forecastCoveragePercent"] == 0
