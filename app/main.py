from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from .service import ElexonClient, analyze

app = FastAPI(title="WindWise API", version="1.0.0", description="Day-ahead UK wind forecast accuracy, backed by Elexon BMRS.")
origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])
client = ElexonClient(os.getenv("ELEXON_API_BASE", "https://data.elexon.co.uk/bmrs/api/v1"), float(os.getenv("API_TIMEOUT", "20")))

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "windwise-api"}

def bounds(start_date: date, end_date: date):
    if start_date > end_date or start_date < date(2026, 1, 1) or end_date > date(2026, 1, 31):
        raise HTTPException(422, "Dates must be within January 2026 and start_date must not exceed end_date.")
    return datetime.combine(start_date, time.min, ZoneInfo("Europe/London")).astimezone(timezone.utc), datetime.combine(end_date + timedelta(days=1), time.min, ZoneInfo("Europe/London")).astimezone(timezone.utc)

async def load(s, e, cutoff):
    lo, hi = bounds(s,e)
    try:
        return await analyze(client, lo, hi, cutoff)
    except Exception as exc:
        raise HTTPException(502, f"Elexon data unavailable or invalid: {exc}") from exc

@app.get("/api/accuracy")
async def accuracy(start_date: date = Query(date(2026,1,1)), end_date: date = Query(date(2026,1,31)), cutoff_hour: int = Query(11, ge=0, le=23)):
    return await load(start_date,end_date,cutoff_hour)

@app.get("/api/forecasts")
async def forecasts(start_date: date = Query(date(2026,1,1)), end_date: date = Query(date(2026,1,31)), cutoff_hour: int = Query(11, ge=0, le=23)):
    return (await load(start_date,end_date,cutoff_hour))["intervals"]

@app.get("/api/actuals")
async def actuals(start_date: date = Query(date(2026,1,1)), end_date: date = Query(date(2026,1,31)), cutoff_hour: int = Query(11, ge=0, le=23)):
    return [{"startTime":x["startTime"],"generation":x["actual"]} for x in (await load(start_date,end_date,cutoff_hour))["intervals"] if x["actual"] is not None]
