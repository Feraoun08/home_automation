import { useEffect, useState } from "react";
import "./App.css";
import SensorHistoryChart from "./SensorHistoryChart";
import AlertPanel from "./AlertPanel";

const API_URL = "http://localhost:8000/api";

const sensorDetails = {
  temperature: { label: "Temperature", icon: "🌡️", unit: "°C" },
  humidity: { label: "Humidity", icon: "💧", unit: "%" },
  presence: { label: "Presence", icon: "🏠", unit: "" },
};

function SensorCard({ sensor }) {
  const details = sensorDetails[sensor.sensor_type];

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
  const [readings, setReadings] = useState([]);
  const [devices, setDevices] = useState([])
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const [error, setError] = useState("");
  const [commandMessage, setCommandMessage] = useState("");

  useEffect(() => {
    let active = true;

    async function loadReadings() {
      try {
        const response = await fetch(`${API_URL}/readings/latest`);

        if (!response.ok) {
          throw new Error("API request failed");
        }

        const data = await response.json();

        if (active) {
          setReadings(data.readings);
          setDevices(data.devices);
          setError("");
        }
      } catch {
        if (active) {
          setError("Unable to reach the Home Automation API.");
        }
      }
    }

    loadReadings();
    const intervalId = window.setInterval(loadReadings, 5000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, []);
useEffect(() => {
  let active = true;

  const socket = new WebSocket("ws://localhost:8000/ws/events");

  socket.onopen = () => {
    if (active) {
      setRealtimeConnected(true);
    }
  };

  socket.onclose = () => {
    if (active) {
      setRealtimeConnected(false);
    }
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    const topicParts = message.topic.split("/");
    const payload = message.payload;

    // Sensor event:
    // home/living_room/sensor/temperature
    if (
      topicParts.length === 4 &&
      topicParts[2] === "sensor"
    ) {
      const sensorType = topicParts[3];

      const reading = {
        room: topicParts[1],
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

      setReadings((currentReadings) => [
        ...currentReadings.filter(
          (item) => item.sensor_type !== sensorType,
        ),
        reading,
      ]);
    }

    // Device-state event:
    // home/living_room/device/light/state
    if (
      topicParts.length === 5 &&
      topicParts[2] === "device" &&
      topicParts[4] === "state"
    ) {
      const deviceName = topicParts[3];

      const device = {
        room: topicParts[1],
        device_name: deviceName,
        device_id: payload.device_id,
        state: payload.state,
        timestamp: payload.timestamp,
      };

      setDevices((currentDevices) => [
        ...currentDevices.filter(
          (item) => item.device_name !== deviceName,
        ),
        device,
      ]);
    }
  };

  return () => {
    active = false;
    socket.close();
  };
}, []);
  async function sendCommand(deviceName, state) {
    try {
      const response = await fetch(
        `${API_URL}/devices/${deviceName}/commands`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ state }),
        },
      );

      if (!response.ok) {
        throw new Error("Command failed");
      }

      setCommandMessage(
        `${deviceName} command published: ${state.toUpperCase()}`,
      );
    } catch {
      setCommandMessage("Unable to publish the command.");
    }
  }
  const deviceStates = Object.fromEntries(
  devices.map((device) => [device.device_name, device]),
);

  return (
    <main className="dashboard">
      <header className="header">
        <div>
          <p className="eyebrow">SMART HOME SIMULATION</p>
          <h1>Living Room Dashboard</h1>
          <p className="subtitle">
            Live sensor data from MQTT, Node-RED, and InfluxDB.
          </p>
        </div>
        <span
  className={`connection-status ${
            realtimeConnected ? "connected" : "disconnected"
          }`}
        >
          ● {realtimeConnected ? "Real-time connected" : "Connecting..."}
</span>
        
      </header>

      {error ? (
        <p className="error-message">{error}</p>
      ) : (
        <section className="sensor-grid">
          {readings.map((sensor) => (
            <SensorCard key={sensor.sensor_type} sensor={sensor} />
          ))}
        </section>
      )}
      <SensorHistoryChart />
      <AlertPanel />

      <section className="controls">
        <div>
          <p className="eyebrow">DEVICE CONTROL</p>
          <h2>Appliances</h2>
        </div>

        <div className="device-grid">
          {["light", "fan"].map((deviceName) => (
            <article className="device-card" key={deviceName}>
              <h3>{deviceName === "light" ? "💡 Light" : "🌀 Fan"}</h3>
              <p className={`device-state ${deviceStates[deviceName]?.state || "off"}`}>
  Confirmed state: {deviceStates[deviceName]?.state || "unknown"}
</p>
              <div className="button-row">
                <button onClick={() => sendCommand(deviceName, "on")}>
                  Turn on
                </button>
                <button
                  className="off-button"
                  onClick={() => sendCommand(deviceName, "off")}
                >
                  Turn off
                </button>
              </div>
            </article>
          ))}
        </div>

        {commandMessage && <p className="command-message">{commandMessage}</p>}
      </section>
    </main>
  );
}