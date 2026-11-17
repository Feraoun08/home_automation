import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

BROKER_HOST = os.getenv("MQTT_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))

CONFIG_PATH = Path(__file__).with_name("house.json")
SYSTEM_STATUS_TOPIC = "home/system/status"

SUPPORTED_SENSOR_TYPES = {"temperature", "humidity", "presence"}
STATE_LOCK = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_house_config(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError as error:
        raise RuntimeError(f"Configuration file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid JSON in {path}: {error}") from error

    validate_house_config(config)
    return config


def validate_range(value: Any, field_name: str) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, (int, float)) for item in value)
    ):
        raise ValueError(f"{field_name} must be a list containing two numbers")


def validate_house_config(config: dict[str, Any]) -> None:
    house = config.get("house", {})
    rooms = config.get("rooms")

    if not isinstance(house.get("id"), str) or not house["id"]:
        raise ValueError("house.id must be a non-empty string")

    if not isinstance(rooms, list) or not rooms:
        raise ValueError("rooms must be a non-empty list")

    room_ids = set()

    for room in rooms:
        room_id = room.get("id")

        if not isinstance(room_id, str) or not room_id:
            raise ValueError("Every room must have a non-empty id")

        if room_id in room_ids:
            raise ValueError(f"Duplicate room id: {room_id}")

        room_ids.add(room_id)

        sensors = room.get("sensors", [])
        devices = room.get("devices", [])
        profile = room.get("profile", {})

        if not isinstance(sensors, list):
            raise ValueError(f"{room_id}.sensors must be a list")

        if not isinstance(devices, list):
            raise ValueError(f"{room_id}.devices must be a list")

        sensor_types = set()
        sensor_ids = set()

        for sensor in sensors:
            sensor_id = sensor.get("id")
            sensor_type = sensor.get("type")

            if not isinstance(sensor_id, str) or not sensor_id:
                raise ValueError(f"{room_id}: every sensor needs an id")

            if sensor_id in sensor_ids:
                raise ValueError(f"{room_id}: duplicate sensor id {sensor_id}")

            if sensor_type not in SUPPORTED_SENSOR_TYPES:
                raise ValueError(
                    f"{room_id}: unsupported sensor type {sensor_type}"
                )

            if sensor_type in sensor_types:
                raise ValueError(
                    f"{room_id}: sensor type {sensor_type} can appear only once"
                )

            sensor_ids.add(sensor_id)
            sensor_types.add(sensor_type)

            if sensor_type in {"temperature", "humidity"}:
                sensor_profile = profile.get(sensor_type, {})

                for field_name in ("initial", "minimum", "maximum", "idle_delta"):
                    if field_name not in sensor_profile:
                        raise ValueError(
                            f"{room_id}: missing {sensor_type}.{field_name}"
                        )

                validate_range(
                    sensor_profile["idle_delta"],
                    f"{room_id}.{sensor_type}.idle_delta",
                )

            if sensor_type == "presence":
                presence_profile = profile.get("presence", {})

                if "toggle_every_seconds" not in presence_profile:
                    raise ValueError(
                        f"{room_id}: missing presence.toggle_every_seconds"
                    )

        device_ids = set()
        device_types = set()

        for device in devices:
            device_id = device.get("id")
            device_type = device.get("type")
            initial_state = device.get("initial_state")

            if not isinstance(device_id, str) or not device_id:
                raise ValueError(f"{room_id}: every device needs an id")

            if device_id in device_ids:
                raise ValueError(f"{room_id}: duplicate device id {device_id}")

            if not isinstance(device_type, str) or not device_type:
                raise ValueError(f"{room_id}: every device needs a type")

            # MQTT topics use the device type, so it must be unique per room.
            if device_type in device_types:
                raise ValueError(
                    f"{room_id}: duplicate device type {device_type}"
                )

            if initial_state not in {"on", "off"}:
                raise ValueError(
                    f"{room_id}: initial_state must be on or off"
                )

            effects = device.get("effects", {})

            for effect_name, effect_value in effects.items():
                if effect_name not in {
                    "temperature_delta",
                    "humidity_delta",
                }:
                    raise ValueError(
                        f"{room_id}: unsupported device effect {effect_name}"
                    )

                validate_range(
                    effect_value,
                    f"{room_id}.{device_id}.{effect_name}",
                )

            device_ids.add(device_id)
            device_types.add(device_type)


def random_from_range(value_range: list[float]) -> float:
    return random.uniform(float(value_range[0]), float(value_range[1]))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(maximum), value))


def build_runtime_state(
    house_config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    runtime_rooms = {}

    for room in house_config["rooms"]:
        room_id = room["id"]
        sensor_values = {}

        for sensor in room["sensors"]:
            sensor_type = sensor["type"]

            if sensor_type in {"temperature", "humidity"}:
                sensor_values[sensor_type] = float(
                    room["profile"][sensor_type]["initial"]
                )
            elif sensor_type == "presence":
                sensor_values[sensor_type] = False

        devices_by_id = {}
        devices_by_type = {}

        for device_config in room["devices"]:
            runtime_device = {
                "config": device_config,
                "state": device_config["initial_state"],
            }

            devices_by_id[device_config["id"]] = runtime_device
            devices_by_type[device_config["type"]] = runtime_device

        runtime_rooms[room_id] = {
            "config": room,
            "sensor_values": sensor_values,
            "devices_by_id": devices_by_id,
            "devices_by_type": devices_by_type,
            "last_presence_toggle": time.monotonic(),
        }

    return runtime_rooms


HOUSE_CONFIG = load_house_config(CONFIG_PATH)
HOUSE_ID = HOUSE_CONFIG["house"]["id"]
PUBLISH_INTERVAL = float(
    HOUSE_CONFIG.get("simulation", {}).get("publish_interval_seconds", 5)
)
ROOMS = build_runtime_state(HOUSE_CONFIG)


def publish_json(
    client: mqtt.Client,
    topic: str,
    payload: dict[str, Any],
    *,
    retain: bool = False,
    qos: int = 0,
) -> None:
    client.publish(topic, json.dumps(payload), retain=retain, qos=qos)
    print(f"Published: {topic} -> {payload}")


def publish_system_status(
    client: mqtt.Client,
    status: str,
    reason: str | None = None,
) -> None:
    payload = {
        "house_id": HOUSE_ID,
        "status": status,
        "timestamp": now_iso(),
    }

    if reason:
        payload["reason"] = reason

    publish_json(
        client,
        SYSTEM_STATUS_TOPIC,
        payload,
        retain=True,
        qos=1,
    )


def publish_room_status(
    client: mqtt.Client,
    room_id: str,
    status: str,
    reason: str | None = None,
) -> None:
    room = ROOMS[room_id]["config"]
    topic = f"home/{room_id}/status"

    payload = {
    "house_id": HOUSE_ID,
    "room_id": room_id,
    "room_name": room["name"],
    "sensor_types": [
        sensor["type"]
        for sensor in room["sensors"]
    ],
    "devices": [
        {
            "id": device["id"],
            "type": device["type"]
        }
        for device in room["devices"]
    ],
    "status": status,
    "timestamp": now_iso(),
}

    if reason:
        payload["reason"] = reason

    publish_json(client, topic, payload, retain=True, qos=1)


def publish_sensor(
    client: mqtt.Client,
    room_id: str,
    sensor_config: dict[str, Any],
    value: float | bool,
) -> None:
    sensor_type = sensor_config["type"]
    topic = f"home/{room_id}/sensor/{sensor_type}"

    payload = {
        "house_id": HOUSE_ID,
        "room_id": room_id,
        "sensor_id": sensor_config["id"],
        "sensor_type": sensor_type,
        "value": round(value, 1) if isinstance(value, float) else value,
        "unit": sensor_config["unit"],
        "timestamp": now_iso(),
    }

    publish_json(client, topic, payload)


def publish_device_state(
    client: mqtt.Client,
    room_id: str,
    runtime_device: dict[str, Any],
) -> None:
    device_config = runtime_device["config"]
    device_type = device_config["type"]
    topic = f"home/{room_id}/device/{device_type}/state"

    payload = {
        "house_id": HOUSE_ID,
        "room_id": room_id,
        "device_id": device_config["id"],
        "device_type": device_type,
        "state": runtime_device["state"],
        "timestamp": now_iso(),
    }

    publish_json(client, topic, payload, retain=True, qos=1)


def publish_room_device_states(
    client: mqtt.Client,
    room_id: str,
) -> None:
    for runtime_device in ROOMS[room_id]["devices_by_id"].values():
        publish_device_state(client, room_id, runtime_device)


def publish_room_readings(
    client: mqtt.Client,
    room_id: str,
) -> None:
    room_runtime = ROOMS[room_id]
    room = room_runtime["config"]

    for sensor in room["sensors"]:
        sensor_type = sensor["type"]
        value = room_runtime["sensor_values"][sensor_type]
        publish_sensor(client, room_id, sensor, value)


def apply_device_effects(
    room_runtime: dict[str, Any],
    metric: str,
) -> float:
    effect_key = f"{metric}_delta"
    total_delta = 0.0

    for runtime_device in room_runtime["devices_by_id"].values():
        if runtime_device["state"] != "on":
            continue

        effect = runtime_device["config"].get("effects", {}).get(effect_key)

        if effect:
            total_delta += random_from_range(effect)

    return total_delta


def update_environment_for_room(room_id: str) -> None:
    room_runtime = ROOMS[room_id]
    room = room_runtime["config"]
    profile = room["profile"]
    sensor_values = room_runtime["sensor_values"]

    for metric in ("temperature", "humidity"):
        if metric not in sensor_values:
            continue

        metric_profile = profile[metric]
        idle_delta = random_from_range(metric_profile["idle_delta"])
        device_delta = apply_device_effects(room_runtime, metric)

        sensor_values[metric] = clamp(
            sensor_values[metric] + idle_delta + device_delta,
            metric_profile["minimum"],
            metric_profile["maximum"],
        )

    if "presence" in sensor_values:
        presence_profile = profile["presence"]
        elapsed = time.monotonic() - room_runtime["last_presence_toggle"]

        if elapsed >= float(presence_profile["toggle_every_seconds"]):
            sensor_values["presence"] = not sensor_values["presence"]
            room_runtime["last_presence_toggle"] = time.monotonic()

            print(
                f"Presence changed: {room_id} -> "
                f"{sensor_values['presence']}"
            )


def on_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: Any,
    reason_code: Any,
    properties: Any,
) -> None:
    print(f"Connected to MQTT broker with code: {reason_code}")

    command_topic = "home/+/device/+/command"
    client.subscribe(command_topic, qos=1)
    print(f"Listening for commands on: {command_topic}")

    with STATE_LOCK:
        publish_system_status(client, "online")

        for room_id in ROOMS:
            publish_room_status(client, room_id, "online")
            publish_room_device_states(client, room_id)


def on_message(
    client: mqtt.Client,
    userdata: Any,
    message: mqtt.MQTTMessage,
) -> None:
    try:
        topic_parts = message.topic.split("/")

        if (
            len(topic_parts) != 5
            or topic_parts[0] != "home"
            or topic_parts[2] != "device"
            or topic_parts[4] != "command"
        ):
            print(f"Ignored invalid command topic: {message.topic}")
            return

        room_id = topic_parts[1]
        device_type = topic_parts[3]
        payload = json.loads(message.payload.decode())

        requested_state = str(payload.get("state", "")).lower()
        requested_device_id = payload.get("device_id")

        if requested_state not in {"on", "off"}:
            print(f"Invalid device state on {message.topic}: {requested_state}")
            return

        with STATE_LOCK:
            room_runtime = ROOMS.get(room_id)

            if room_runtime is None:
                print(f"Unknown room: {room_id}")
                return

            runtime_device = room_runtime["devices_by_type"].get(device_type)

            if runtime_device is None:
                print(
                    f"Unknown device type in {room_id}: {device_type}"
                )
                return

            configured_device_id = runtime_device["config"]["id"]

            # device_id is optional temporarily to preserve the old API.
            # When present, it must match the configured device exactly.
            if (
                requested_device_id is not None
                and requested_device_id != configured_device_id
            ):
                print(
                    "Rejected command: "
                    f"{requested_device_id} does not belong to {room_id}"
                )
                return

            runtime_device["state"] = requested_state

        print(
            f"Command received: {room_id} / "
            f"{configured_device_id} -> {requested_state}"
        )
        publish_device_state(client, room_id, runtime_device)

    except json.JSONDecodeError:
        print(f"Invalid JSON command on {message.topic}")
    except Exception as error:
        print(f"Unable to process command on {message.topic}: {error}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

# MQTT permits one Last Will per client. This status represents
# the availability of the multi-room simulator process as a whole.
client.will_set(
    SYSTEM_STATUS_TOPIC,
    payload=json.dumps(
        {
            "house_id": HOUSE_ID,
            "status": "offline",
            "reason": "unexpected_disconnect",
        }
    ),
    qos=1,
    retain=True,
)

client.connect(BROKER_HOST, BROKER_PORT, 60)
client.loop_start()

print(
    f"Simulator started for {len(ROOMS)} rooms. "
    "Stop it with Ctrl + C."
)

try:
    while True:
        with STATE_LOCK:
            for current_room_id in ROOMS:
                update_environment_for_room(current_room_id)
                publish_room_readings(client, current_room_id)

        time.sleep(PUBLISH_INTERVAL)

except KeyboardInterrupt:
    print("\nSimulator stopped.")

finally:
    with STATE_LOCK:
        for current_room_id in ROOMS:
            publish_room_status(
                client,
                current_room_id,
                "offline",
                reason="normal_shutdown",
            )

        publish_system_status(
            client,
            "offline",
            reason="normal_shutdown",
        )

    client.loop_stop()
    client.disconnect()