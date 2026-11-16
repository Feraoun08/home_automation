import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from influxdb_client import InfluxDBClient
import asyncio
from contextlib import asynccontextmanager

load_dotenv(Path(__file__).with_name(".env"))

INFLUX_URL = os.environ["INFLUX_URL"]
INFLUX_TOKEN = os.environ["INFLUX_TOKEN"]
INFLUX_ORG = os.environ["INFLUX_ORG"]
INFLUX_BUCKET = os.environ["INFLUX_BUCKET"]

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
ROOM = "living_room"
ALLOWED_DEVICES = {"light", "fan"}
websocket_clients = set()


async def broadcast_event(event):
    disconnected_clients = set()

    for websocket in websocket_clients.copy():
        try:
            await websocket.send_json(event)
        except Exception:
            disconnected_clients.add(websocket)

    websocket_clients.difference_update(disconnected_clients)


@asynccontextmanager
async def lifespan(app: FastAPI):
    event_loop = asyncio.get_running_loop()

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"FastAPI MQTT connected: {reason_code}")
        client.subscribe("home/#")

    def on_message(client, userdata, message):
        try:
            event = {
                "topic": message.topic,
                "payload": json.loads(message.payload.decode()),
            }

            asyncio.run_coroutine_threadsafe(
                broadcast_event(event),
                event_loop,
            )
        except json.JSONDecodeError:
            print(f"Ignored invalid JSON on {message.topic}")

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_client.loop_start()

    try:
        yield
    finally:
        mqtt_client.disconnect()
        mqtt_client.loop_stop()

app = FastAPI(
    title="Home Automation API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class DeviceCommand(BaseModel):
    state: Literal["on", "off"]


@app.websocket("/ws/events")
async def mqtt_event_stream(websocket: WebSocket):
    await websocket.accept()
    websocket_clients.add(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_clients.discard(websocket)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/readings/latest")
def get_latest_readings():
    sensor_query = f'''
    from(bucket: "{INFLUX_BUCKET}")
        |> range(start: -1h)
        |> filter(fn: (r) => r._measurement == "sensor_reading")
        |> filter(fn: (r) => r._field == "value")
        |> group(columns: ["room", "sensor_type", "device_id", "unit"])
        |> last()
    '''

    device_query = f'''
    from(bucket: "{INFLUX_BUCKET}")
        |> range(start: -1h)
        |> filter(fn: (r) => r._measurement == "device_state")
        |> filter(fn: (r) => r._field == "is_on")
        |> group(columns: ["room", "device_name", "device_id"])
        |> last()
    '''

    readings = []
    devices = []

    with InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
    ) as client:
        query_api = client.query_api()

        sensor_tables = query_api.query(query=sensor_query, org=INFLUX_ORG)
        for table in sensor_tables:
            for record in table.records:
                readings.append(
                    {
                        "room": record.values.get("room"),
                        "sensor_type": record.values.get("sensor_type"),
                        "device_id": record.values.get("device_id"),
                        "unit": record.values.get("unit"),
                        "value": record.get_value(),
                        "timestamp": record.get_time().isoformat(),
                    }
                )

        device_tables = query_api.query(query=device_query, org=INFLUX_ORG)
        for table in device_tables:
            for record in table.records:
                devices.append(
                    {
                        "room": record.values.get("room"),
                        "device_name": record.values.get("device_name"),
                        "device_id": record.values.get("device_id"),
                        "state": "on" if record.get_value() == 1 else "off",
                        "timestamp": record.get_time().isoformat(),
                    }
                )

    return {
        "readings": readings,
        "devices": devices,
    }
@app.get("/api/readings/history")
def get_reading_history(minutes: int = 30):
    if minutes < 1 or minutes > 1440:
        raise HTTPException(
            status_code=400,
            detail="minutes must be between 1 and 1440",
        )

    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
        |> range(start: -{minutes}m)
        |> filter(fn: (r) => r._measurement == "sensor_reading")
        |> filter(fn: (r) => r._field == "value")
        |> filter(fn: (r) =>
            r.sensor_type == "temperature" or
            r.sensor_type == "humidity"
        )
        |> sort(columns: ["_time"])
    '''

    points_by_time = {}

    with InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
    ) as client:
        tables = client.query_api().query(query=query, org=INFLUX_ORG)

        for table in tables:
            for record in table.records:
                timestamp = record.get_time().replace(microsecond=0).isoformat()
                sensor_type = record.values.get("sensor_type")

                point = points_by_time.setdefault(
                    timestamp,
                    {
                        "timestamp": timestamp,
                        "time": record.get_time().strftime("%H:%M:%S"),
                    },
                )

                point[sensor_type] = float(record.get_value())

    points = sorted(points_by_time.values(), key=lambda point: point["timestamp"])

    return {"points": points}
@app.get("/api/alerts")
def get_alerts(limit: int = 20):
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 100",
        )

    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
        |> range(start: -24h)
        |> filter(fn: (r) => r._measurement == "alerts")
        |> filter(fn: (r) => r._field == "message")
        |> sort(columns: ["_time"], desc: true)
        |> limit(n: {limit})
    '''

    alerts = []

    with InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
    ) as client:
        tables = client.query_api().query(query=query, org=INFLUX_ORG)

        for table in tables:
            for record in table.records:
                alerts.append(
                    {
                        "message": record.get_value(),
                        "severity": record.values.get("severity", "warning"),
                        "alert_type": record.values.get("alert_type"),
                        "room": record.values.get("room"),
                        "timestamp": record.get_time().isoformat(),
                    }
                )

    return {"alerts": alerts}
@app.post("/api/devices/{device_name}/commands")
def send_device_command(device_name: str, command: DeviceCommand):
    if device_name not in ALLOWED_DEVICES:
        raise HTTPException(status_code=404, detail="Unknown device")

    topic = f"home/{ROOM}/device/{device_name}/command"
    payload = {
        "state": command.state,
        "source": "dashboard",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()

        published = client.publish(topic, json.dumps(payload), qos=1)
        published.wait_for_publish(timeout=5)

        if not published.is_published():
            raise RuntimeError("MQTT message was not published")

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to publish MQTT command: {error}",
        ) from error

    finally:
        client.disconnect()
        client.loop_stop()

    return {
        "status": "published",
        "device": device_name,
        "state": command.state,
    }