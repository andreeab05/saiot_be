# server.py
import os
import socket
from fastapi import FastAPI, Request, Header, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from influxdb_client import InfluxDBClient, Point, WritePrecision
from dotenv import load_dotenv

load_dotenv()

INFLUX_URL = os.getenv("INFLUX_URL")  # e.g. https://us-west-2-1.aws.cloud2.influxdata.com
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_ORG = os.getenv("INFLUX_ORG", "")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "public-data") # optional: if set, require clients to send x-api-key

if not INFLUX_URL or not INFLUX_TOKEN or not INFLUX_ORG:
    raise RuntimeError("INFLUX_URL, INFLUX_TOKEN and INFLUX_ORG must be set in env")

app = FastAPI(title="Public Submit API")

# CORS: allow your frontend origin(s)
FRONTEND_ORIGINS = os.getenv("FRONTEND_ORIGINS", "*").split(",")  # set to your deployed frontend URL(s)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = client.write_api()

class Submission(BaseModel):
    value: int = Field(..., ge=1, le=10, description="1..10 score")
    label: str | None = None
    meta: dict | None = None

# def check_api_key(x_api_key: str | None):
#     if API_KEY:
#         if not x_api_key or x_api_key != API_KEY:
#             raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/api/submit")
async def submit(payload: Submission):

    # Create InfluxDB point
    p = Point("fatigue") \
        .field("value", int(payload.value)) \
        .tag("source", payload.label or "anon") \
        .tag("host", socket.gethostname())

    if payload.meta and isinstance(payload.meta, dict):
        ua = payload.meta.get("userAgent")
        if ua:
            p.field("ua", str(ua)[:512])

    # Write (non-blocking buffer)
    try:
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"influx write error: {e}")

    return {"success": True}

# graceful shutdown to flush writes (optional)
@app.on_event("shutdown")
def shutdown():
    try:
        write_api.flush()
    except Exception:
        pass
    try:
        client.close()
    except Exception:
        pass
