import json
import os
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER_HOST = os.getenv("MQTT_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
ROOM = "living_room"
STATUS_TOPIC = f"home/{ROOM}/status"

temperature = 29.0
humidity = 45.0
presence = False
last_presence_change = time.time()

devices = {
    "light": "off",
    "fan": "off"
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def publish_sensor(client, sensor_type, value, unit, device_id):
    topic = f"home/{ROOM}/sensor/{sensor_type}"
    payload = {
        "device_id": device_id,
        "value": round(value, 1) if isinstance(value, float) else value,
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
        STATUS_TOPIC,
        json.dumps(
            {
                "status": "online",
                "timestamp": now_iso(),
            }
        ),
        qos=1,
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
client.will_set(
    STATUS_TOPIC,
    payload=json.dumps(
        {
            "status": "offline",
            "reason": "unexpected_disconnect",
        }
    ),
    qos=1,
    retain=True,
)
client.connect(BROKER_HOST, BROKER_PORT, 60)
client.loop_start()

print("Simulator started. Stop it with Ctrl + C.")

try:
    while True:
        if devices["fan"]=="on":
            temperature -=random.uniform(0.4,0.7)
        else :
            temperature+=random.uniform(0.15,0.45)
        
        humidity += random.uniform(-1.0, 1.0)

        temperature = max(18.0, min(32.0, temperature))
        humidity = max(30.0, min(70.0, humidity))

        # Change presence automatically every 15 seconds.
        if time.time() - last_presence_change >= 15:
            presence = not presence
            last_presence_change = time.time()
            print(f"Presence changed: {presence}")

        publish_sensor(client, "temperature", temperature, "C", "temp-01")
        publish_sensor(client, "humidity", humidity, "%", "humidity-01")
        publish_sensor(client, "presence", presence, "boolean", "presence-01")

        time.sleep(5)

except KeyboardInterrupt:
    print("\nSimulator stopped.")

finally:
    offline_message = client.publish(    STATUS_TOPIC,
    json.dumps(
        {
            "status": "offline",
            "reason": "normal_shutdown",
            "timestamp": now_iso(),
        }
    ),
    qos=1,
    retain=True,
)
    offline_message.wait_for_publish(timeout=2)
    client.loop_stop()
    client.disconnect()