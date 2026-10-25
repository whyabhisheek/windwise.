from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import asyncio
import httpx

class ElexonClient:
    def __init__(self, base, timeout=20):
        self.base, self.timeout = base.rstrip("/"), timeout

    async def fetch(self, dataset, start, end):
        # Daily windows avoid Elexon's range/result limits (the FUELHH API rejects
        # broad historical windows). Bound concurrency to be polite to the API.
        days = []
        cursor = start
        while cursor < end:
            next_day = min(cursor + timedelta(days=1), end)
            days.append((cursor, next_day))
            cursor = next_day
        semaphore = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            async def fetch_day(lo, hi):
                params = ({"settlementDateFrom": lo.date().isoformat(), "settlementDateTo": (hi - timedelta(microseconds=1)).date().isoformat()}
                          if dataset == "FUELHH" else
                          {"publishDateTimeFrom": lo.isoformat(), "publishDateTimeTo": hi.isoformat()})
                async with semaphore:
                    for attempt in range(3):
                        response = await c.get(f"{self.base}/datasets/{dataset}", params=params)
                        if response.status_code == 429 and attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        response.raise_for_status()
                        body = response.json()
                        if isinstance(body, dict): body = body.get("data", body.get("results", []))
                        if not isinstance(body, list): raise ValueError(f"Unexpected {dataset} response shape")
                        return body
            batches = await asyncio.gather(*(fetch_day(lo, hi) for lo, hi in days))
        return [row for batch in batches for row in batch]

def as_dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

async def analyze(client, start, end, cutoff_hour=11):
    # Download a 24h lead-in because forecasts are published the day before delivery.
    forecasts, actuals = await __gather(client, start-timedelta(days=1), end)
    actual_map = {}
    for row in actuals:
        if row.get("fuelType") != "WIND": continue
        key = as_dt(row["startTime"])
        actual_map[key] = float(row["generation"])
    chosen = {}
    for row in forecasts:
        delivery = as_dt(row["startTime"])
        if not start <= delivery < end: continue
        uk_delivery_day = delivery.astimezone(ZoneInfo("Europe/London")).date()
        decision = datetime.combine(uk_delivery_day - timedelta(days=1), datetime.min.time(), ZoneInfo("Europe/London")).replace(hour=cutoff_hour)
        published = as_dt(row["publishTime"])
        if published > decision: continue
        # Keep the newest forecast that was already published at the decision time.
        if delivery not in chosen or published > chosen[delivery][0]:
            chosen[delivery] = (published, float(row["generation"]))
    intervals=[]
    for delivery in sorted(set(chosen) | set(actual_map)):
        if not start <= delivery < end: continue
        forecast=chosen.get(delivery)
        actual=actual_map.get(delivery)
        intervals.append({"startTime":delivery.isoformat(),"publishTime":forecast[0].isoformat() if forecast else None,"forecast":forecast[1] if forecast else None,"actual":actual,"absoluteError":abs(forecast[1]-actual) if forecast and actual is not None else None})
    pairs=[x for x in intervals if x["forecast"] is not None and x["actual"] is not None]
    n=len(pairs)
    mae=sum(x["absoluteError"] for x in pairs)/n if n else None
    rmse=(sum((x["forecast"]-x["actual"])**2 for x in pairs)/n)**0.5 if n else None
    nonzero=[x for x in pairs if x["actual"] != 0]
    mape=sum(x["absoluteError"]/abs(x["actual"])*100 for x in nonzero)/len(nonzero) if nonzero else None
    return {"intervals":intervals,"metrics":{"matchedIntervals":n,"maeMW":mae,"rmseMW":rmse,"mapePercent":mape,"mapeExcludedZeroActuals":n-len(nonzero),"forecastCoveragePercent":round(100*sum(x["forecast"] is not None for x in intervals)/len(intervals),2) if intervals else 0,"actualCoveragePercent":round(100*sum(x["actual"] is not None for x in intervals)/len(intervals),2) if intervals else 0},"decisionTime":{"cutoffHourUK":cutoff_hour,"rule":"11:00 Europe/London on the day before delivery; latest publishTime at or before cutoff"},"units":"MW"}

async def __gather(client, start, end):
    import asyncio
    return await asyncio.gather(client.fetch("WINDFOR",start,end),client.fetch("FUELHH",start,end))
