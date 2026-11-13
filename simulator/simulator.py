import json
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883
ROOM = "living_room"

temperature = 22.0
humidity = 45.0
devices = {
    "light": "off",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def publish_sensor(client, sensor_type, value, unit, device_id):
    topic = f"home/{ROOM}/sensor/{sensor_type}"
    payload = {
        "device_id": device_id,
        "value": round(value, 1),
        "unit": unit,
        "timestamp": now_iso(),
    }

    client.publish(topic, json.dumps(payload))
    print(f"Published: {topic} -> {payload}")


def publish_device_state(client, device_name):
    topic = f"home/{ROOM}/device/{device_name}/state"
    payload = {
        "device_id": f"{device_name}-01",
        "state": devices[device_name],
        "timestamp": now_iso(),
    }

    client.publish(topic, json.dumps(payload), retain=True)
    print(f"Published: {topic} -> {payload}")


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to MQTT broker with code: {reason_code}")

    command_topic = f"home/{ROOM}/device/+/command"
    client.subscribe(command_topic)
    print(f"Listening for commands on: {command_topic}")

    client.publish(
        f"home/{ROOM}/status",
        json.dumps({"status": "online", "timestamp": now_iso()}),
        retain=True,
    )

    for device_name in devices:
        publish_device_state(client, device_name)


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        topic_parts = message.topic.split("/")
        device_name = topic_parts[3]
        requested_state = payload["state"].lower()

        if device_name not in devices:
            print(f"Unknown device: {device_name}")
            return

        if requested_state not in ("on", "off"):
            print(f"Invalid state: {requested_state}")
            return

        devices[device_name] = requested_state
        print(f"Command received: {device_name} -> {requested_state}")
        publish_device_state(client, device_name)

    except (json.JSONDecodeError, KeyError, IndexError) as error:
        print(f"Invalid command received: {error}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_HOST, BROKER_PORT, 60)
client.loop_start()

print("Simulator started. Stop it with Ctrl + C.")

try:
    while True:
        temperature += random.uniform(-0.4, 0.4)
        humidity += random.uniform(-1.0, 1.0)

        temperature = max(18.0, min(32.0, temperature))
        humidity = max(30.0, min(70.0, humidity))

        publish_sensor(client, "temperature", temperature, "C", "temp-01")
        publish_sensor(client, "humidity", humidity, "%", "humidity-01")

        time.sleep(5)

except KeyboardInterrupt:
    print("\nSimulator stopped.")

finally:
    client.publish(
        f"home/{ROOM}/status",
        json.dumps({"status": "offline", "timestamp": now_iso()}),
        retain=True,
    )
    client.loop_stop()
    client.disconnect()