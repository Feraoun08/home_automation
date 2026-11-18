
import { useEffect, useState } from "react";
import "./App.css";
import SensorHistoryChart from "./SensorHistoryChart";
import AlertPanel from "./AlertPanel";
import RoomOverview from "./RoomOverview";

const API_URL = "http://localhost:8000/api";

const rooms = [
  { id: "living_room", name: "Living Room", icon: "🛋️" },
  { id: "bedroom", name: "Bedroom", icon: "🛏️" },
  { id: "kitchen", name: "Kitchen", icon: "🍳" },
  { id: "bathroom", name: "Bathroom", icon: "🚿" },
];

// Fixed display order
const SENSOR_ORDER = ["temperature", "humidity", "presence"];
const DEVICE_ORDER = ["light", "fan", "tv", "ventilation", "exhaust_fan"];

const sensorDetails = {
  temperature: { label: "Temperature", icon: "🌡️", unit: "°C" },
  humidity: { label: "Humidity", icon: "💧", unit: "%" },
  presence: { label: "Presence", icon: "🏠", unit: "" },
};

function SensorCard({ sensor }) {
  const details = sensorDetails[sensor.sensor_type];
  if (!details) return null;

  const value =
    sensor.sensor_type === "presence"
      ? sensor.value === 1 || sensor.value === true
        ? "Detected"
        : "No presence"
      : sensor.value;

  return (
    <article className="sensor-card">
      <span className="sensor-icon">{details.icon}</span>
      <div>
        <p className="sensor-label">{details.label}</p>
        <p className="sensor-value">
          {value}
          {sensor.sensor_type !== "presence" && <span>{details.unit}</span>}
        </p>
      </div>
      <p className="sensor-time">
        Updated {new Date(sensor.timestamp).toLocaleTimeString()}
      </p>
    </article>
  );
}

export default function App() {
  const [roomId, setRoomId] = useState("living_room");
  const [readings, setReadings] = useState([]);
  const [devices, setDevices] = useState([]);
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const [error, setError] = useState("");
  const [commandMessage, setCommandMessage] = useState("");

  useEffect(() => {
    let active = true;

    async function loadReadings() {
      try {
        const response = await fetch(
          `${API_URL}/readings/latest?room_id=${roomId}`,
        );

        if (!response.ok) throw new Error("API request failed");

        const data = await response.json();

        if (active) {
          setReadings(data.readings || []);
          setDevices(data.devices || []);
          setError("");
        }
      } catch {
        if (active) setError("Unable to reach the Home Automation API.");
      }
    }

    loadReadings();
    const intervalId = window.setInterval(loadReadings, 5000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [roomId]);

  useEffect(() => {
    let active = true;
    const socket = new WebSocket("ws://localhost:8000/ws/events");

    socket.onopen = () => {
      if (active) setRealtimeConnected(true);
    };

    socket.onclose = () => {
      if (active) setRealtimeConnected(false);
    };

    socket.onerror = () => {
      if (active) setRealtimeConnected(false);
    };

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        const parts = message.topic.split("/");
        const payload = message.payload;
        const incomingRoom = parts[1];

        if (incomingRoom !== roomId) return;

        if (parts.length === 4 && parts[2] === "sensor") {
          const sensorType = parts[3];

          const reading = {
            room: incomingRoom,
            sensor_type: sensorType,
            device_id: payload.device_id,
            unit: payload.unit,
            value:
              sensorType === "presence"
                ? payload.value
                  ? 1
                  : 0
                : payload.value,
            timestamp: payload.timestamp,
          };

          setReadings((current) => {
            const updated = current.filter(
              (item) => item.sensor_type !== sensorType,
            );
            updated.push(reading);

            // Always preserve the display order
            return updated.sort(
              (a, b) =>
                SENSOR_ORDER.indexOf(a.sensor_type) -
                SENSOR_ORDER.indexOf(b.sensor_type),
            );
          });
        }

        if (
          parts.length === 5 &&
          parts[2] === "device" &&
          parts[4] === "state"
        ) {
          const device = {
            room: incomingRoom,
            device_name: parts[3],
            device_id: payload.device_id,
            state: payload.state,
            timestamp: payload.timestamp,
          };

          setDevices((current) => {
            const updated = current.filter(
              (item) =>
                item.device_id !== device.device_id &&
                item.device_name !== device.device_name,
            );

            updated.push(device);

            // Always preserve the display order
            return updated.sort(
              (a, b) =>
                DEVICE_ORDER.indexOf(a.device_name) -
                DEVICE_ORDER.indexOf(b.device_name),
            );
          });
        }
      } catch {
        // Ignore malformed messages
      }
    };

    return () => {
      active = false;
      socket.close();
    };
  }, [roomId]);

  async function sendCommand(deviceName, state, deviceId) {
    try {
      const response = await fetch(
        `${API_URL}/devices/${deviceName}/commands`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            state,
            room_id: roomId,
            device_id: deviceId,
          }),
        },
      );

      if (!response.ok) throw new Error("Command failed");

      setCommandMessage(`${deviceName} command sent: ${state.toUpperCase()}`);
    } catch {
      setCommandMessage("Unable to publish the command.");
    }
  }

  // Sort on every render as an extra safeguard
  const sortedReadings = [...readings].sort(
    (a, b) =>
      SENSOR_ORDER.indexOf(a.sensor_type) -
      SENSOR_ORDER.indexOf(b.sensor_type),
  );

  const sortedDevices = [...devices].sort(
    (a, b) =>
      DEVICE_ORDER.indexOf(a.device_name) -
      DEVICE_ORDER.indexOf(b.device_name),
  );

  const selectedRoom = rooms.find((room) => room.id === roomId);

  return (
    <main className="dashboard">
      <header className="header">
        <div>
          <p className="eyebrow">SMART HOME SIMULATION</p>
          <h1>{selectedRoom?.name} Dashboard</h1>
          <p className="subtitle">
            Live sensor data from MQTT, Node-RED, and InfluxDB.
          </p>
        </div>

        <span
          className={`connection-status ${
            realtimeConnected ? "connected" : "disconnected"
          }`}
        >
          ● {realtimeConnected ? "Real-time connected" : "Disconnected"}
        </span>
      </header>
      <RoomOverview onSelectRoom={setRoomId} />

      <section className="room-selector-section">
        <p className="eyebrow">ROOM SELECTION</p>
        <div className="room-selector">
          {rooms.map((room) => (
            <button
              key={room.id}
              className={`room-button ${
                roomId === room.id ? "active-room" : ""
              }`}
              onClick={() => {
                setRoomId(room.id);
                setCommandMessage("");
              }}
            >
              {room.icon} {room.name}
            </button>
          ))}
        </div>
      </section>

      {error ? (
        <p className="error-message">{error}</p>
      ) : (
        <section className="sensor-grid">
          {sortedReadings.map((sensor) => (
            <SensorCard key={sensor.sensor_type} sensor={sensor} />
          ))}
          {sortedReadings.length === 0 && (
            <p>No sensor readings available for this room.</p>
          )}
        </section>
      )}

      <SensorHistoryChart roomId={roomId} />
      <AlertPanel roomId={roomId} />

      <section className="controls">
        <div>
          <p className="eyebrow">DEVICE CONTROL</p>
          <h2>Appliances</h2>
        </div>

        {sortedDevices.length === 0 ? (
          <p>No devices found for this room.</p>
        ) : (
          <div className="device-grid">
            {sortedDevices.map((device) => {
              const key = device.device_id || device.device_name;
              const deviceName = device.device_name;
              const state = device.state || "unknown";

              return (
                <article className="device-card" key={key}>
                  <h3>
                    {deviceName === "light" ? "💡" : "⚙️"}{" "}
                    {deviceName.replaceAll("_", " ")}
                  </h3>

                  <p className={`device-state ${state}`}>
                    Confirmed state: {state}
                  </p>

                  <div className="button-row">
                    <button
                      onClick={() =>
                        sendCommand(deviceName, "on", device.device_id)
                      }
                    >
                      Turn on
                    </button>

                    <button
                      className="off-button"
                      onClick={() =>
                        sendCommand(deviceName, "off", device.device_id)
                      }
                    >
                      Turn off
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        {commandMessage && <p className="command-message">{commandMessage}</p>}
      </section>
    </main>
  );
}
