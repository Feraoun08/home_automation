
import json
import os
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt



# MQTT CONFIGURATION


BROKER_HOST = os.getenv("MQTT_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))

HOUSE_ID = "house-01"



# ROOM CONFIGURATION


ROOMS = {
    "living_room": {
        "room_name": "Living Room",
        "sensors": {
            "temperature": {"device_id": "temp-01", "unit": "C"},
            "humidity": {"device_id": "humidity-01", "unit": "%"},
            "presence": {"device_id": "presence-01", "unit": "boolean"},
        },
        "devices": {
            "light": "off",
            "fan": "off",
            "tv": "off",
        },
    },

    "bedroom": {
        "room_name": "Bedroom",
        "sensors": {
            "temperature": {"device_id": "bedroom-temp-01", "unit": "C"},
            "presence": {"device_id": "bedroom-presence-01", "unit": "boolean"},
        },
        "devices": {
            "light": "off",
            "fan": "off",
        },
    },

    "kitchen": {
        "room_name": "Kitchen",
        "sensors": {
            "temperature": {"device_id": "kitchen-temp-01", "unit": "C"},
            "humidity": {"device_id": "kitchen-humidity-01", "unit": "%"},
        },
        "devices": {
            "light": "off",
            "ventilation": "off",
        },
    },

    "bathroom": {
        "room_name": "Bathroom",
        "sensors": {
            "humidity": {"device_id": "bathroom-humidity-01", "unit": "%"},
            "presence": {"device_id": "bathroom-presence-01", "unit": "boolean"},
        },
        "devices": {
            "light": "off",
            "exhaust_fan": "off",
        },
    },
}



# SENSOR VALUES


sensor_values = {
    "living_room": {
        "temperature": 25.0,
        "humidity": 45.0,
        "presence": False,
    },
    "bedroom": {
        "temperature": 23.0,
        "presence": False,
    },
    "kitchen": {
        "temperature": 27.0,
        "humidity": 50.0,
    },
    "bathroom": {
        "humidity": 55.0,
        "presence": False,
    },
}

last_presence_change = {
    room_id: time.time()
    for room_id in ROOMS
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()



# ROOM STATUS


def publish_room_status(client, room_id, status="online"):

    room = ROOMS[room_id]

    payload = {
        "house_id": HOUSE_ID,
        "room_id": room_id,
        "room_name": room["room_name"],
        "status": status,
        "sensor_types": list(room["sensors"].keys()),
        "devices": [
            {
                "type": device_type,
                "device_id": f"{room_id}-{device_type}-01",
            }
            for device_type in room["devices"]
        ],
        "timestamp": now_iso(),
    }

    topic = f"home/{room_id}/status"

    client.publish(
        topic,
        json.dumps(payload),
        qos=1,
        retain=True,
    )

    print(f"Published room status: {topic}")



# SENSOR PUBLISHING


def publish_sensor(client, room_id, sensor_type):

    room = ROOMS[room_id]
    sensor = room["sensors"][sensor_type]

    value = sensor_values[room_id][sensor_type]

    payload = {
        "device_id": sensor["device_id"],
        "value": round(value, 1) if isinstance(value, float) else value,
        "unit": sensor["unit"],
        "timestamp": now_iso(),
    }

    topic = f"home/{room_id}/sensor/{sensor_type}"

    client.publish(
        topic,
        json.dumps(payload),
        qos=1,
    )

    print(f"Sensor: {topic} -> {payload['value']}")



# DEVICE STATE PUBLISHING


def publish_device_state(client, room_id, device_type):

    state = ROOMS[room_id]["devices"][device_type]

    device_id = f"{room_id}-{device_type}-01"

    payload = {
        "house_id": HOUSE_ID,
        "room_id": room_id,
        "device_id": device_id,
        "device_type": device_type,
        "state": state,
        "timestamp": now_iso(),
    }

    topic = f"home/{room_id}/device/{device_type}/state"

    client.publish(
        topic,
        json.dumps(payload),
        qos=1,
        retain=True,
    )

    print(f"Device: {topic} -> {state}")



# MQTT CONNECTION


def on_connect(client, userdata, flags, reason_code, properties):

    print(f"Connected to MQTT broker: {reason_code}")

    client.subscribe("home/+/device/+/command")

    print("Listening for device commands: home/+/device/+/command")

    for room_id, room in ROOMS.items():

        publish_room_status(client, room_id)

        for device_type in room["devices"]:
            publish_device_state(client, room_id, device_type)



# DEVICE COMMAND HANDLING


def on_message(client, userdata, message):

    try:

        payload = json.loads(message.payload.decode())

        parts = message.topic.split("/")

        if len(parts) != 5:
            return

        room_id = parts[1]
        device_type = parts[3]

        if room_id not in ROOMS:
            print(f"Unknown room: {room_id}")
            return

        if device_type not in ROOMS[room_id]["devices"]:
            print(f"Unknown device: {device_type} in {room_id}")
            return

        requested_state = payload.get("state")

        if not isinstance(requested_state, str):
            print("Invalid command state")
            return

        requested_state = requested_state.lower()

        if requested_state not in ("on", "off"):
            print(f"Invalid state: {requested_state}")
            return

        expected_device_id = f"{room_id}-{device_type}-01"
        received_device_id = payload.get("device_id")

        if received_device_id and received_device_id != expected_device_id:
            print(f"Device ID mismatch: {received_device_id}")
            return

        ROOMS[room_id]["devices"][device_type] = requested_state

        print(
            f"Command received: "
            f"{room_id}/{device_type} -> {requested_state}"
        )

        publish_device_state(client, room_id, device_type)

    except (json.JSONDecodeError, KeyError, IndexError) as error:
        print(f"Invalid MQTT command: {error}")



# SENSOR SIMULATION


def update_sensors():

    for room_id, room in ROOMS.items():

        values = sensor_values[room_id]
        devices = room["devices"]

        # Temperature simulation
        if "temperature" in values:

            cooling_device = (
                devices.get("fan") == "on"
                or devices.get("ventilation") == "on"
            )

            if cooling_device:
                values["temperature"] -= random.uniform(0.3, 0.6)
            else:
                values["temperature"] += random.uniform(0.1, 0.3)

            values["temperature"] = max(
                18.0,
                min(35.0, values["temperature"]),
            )

        # Humidity simulation
        if "humidity" in values:

            values["humidity"] += random.uniform(-1.0, 1.0)

            if devices.get("exhaust_fan") == "on":
                values["humidity"] -= random.uniform(0.5, 1.0)

            values["humidity"] = max(
                25.0,
                min(85.0, values["humidity"]),
            )

        # Presence simulation
        if "presence" in values:

            if time.time() - last_presence_change[room_id] >= 15:

                values["presence"] = not values["presence"]

                last_presence_change[room_id] = time.time()

                print(
                    f"Presence in {room_id}: "
                    f"{values['presence']}"
                )



# MQTT CLIENT


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

client.on_connect = on_connect
client.on_message = on_message

client.will_set(
    "home/living_room/status",
    payload=json.dumps({
        "house_id": HOUSE_ID,
        "room_id": "living_room",
        "room_name": "Living Room",
        "status": "offline",
        "timestamp": now_iso(),
    }),
    qos=1,
    retain=True,
)

client.connect(BROKER_HOST, BROKER_PORT, 60)
client.loop_start()

print("Multi-room simulator started.")
print("Rooms: living_room, bedroom, kitchen, bathroom")
print("Press Ctrl + C to stop.")



# MAIN LOOP


try:

    while True:

        update_sensors()

        for room_id, room in ROOMS.items():

            for sensor_type in room["sensors"]:
                publish_sensor(client, room_id, sensor_type)

        time.sleep(5)


except KeyboardInterrupt:

    print("\nStopping simulator...")


finally:

    for room_id in ROOMS:

        offline_payload = {
            "house_id": HOUSE_ID,
            "room_id": room_id,
            "room_name": ROOMS[room_id]["room_name"],
            "status": "offline",
            "timestamp": now_iso(),
        }

        client.publish(
            f"home/{room_id}/status",
            json.dumps(offline_payload),
            qos=1,
            retain=True,
        )

    time.sleep(1)

    client.loop_stop()
    client.disconnect()

    print("Simulator stopped.")
