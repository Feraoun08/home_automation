
import { useEffect, useState } from "react";

const API_URL = "http://localhost:8000/api";

const rooms = [
  { id: "living_room", name: "Living Room", icon: "🛋️" },
  { id: "bedroom", name: "Bedroom", icon: "🛏️" },
  { id: "kitchen", name: "Kitchen", icon: "🍳" },
  { id: "bathroom", name: "Bathroom", icon: "🚿" },
];

export default function RoomOverview({ onSelectRoom }) {
  const [roomData, setRoomData] = useState([]);

  useEffect(() => {
    let active = true;

    async function loadRooms() {
      try {
        const results = await Promise.all(
          rooms.map(async (room) => {
            const response = await fetch(
              `${API_URL}/readings/latest?room_id=${room.id}`,
            );
            if (!response.ok) throw new Error("Request failed");
            const data = await response.json();
            return { ...room, readings: data.readings || [], devices: data.devices || [] };
          }),
        );

        if (active) setRoomData(results);
      } catch {
        // Leave the overview available if requests fail.
      }
    }

    loadRooms();
    const intervalId = setInterval(loadRooms, 5000);

    return () => {
      active = false;
      clearInterval(intervalId);
    };
  }, []);

  return (
    <section className="overview-section">
      <p className="eyebrow">HOUSE OVERVIEW</p>
      <h2>All rooms</h2>

      <div className="overview-grid">
        {roomData.map((room) => {
          const temperature = room.readings.find(
            (r) => r.sensor_type === "temperature",
          );
          const humidity = room.readings.find(
            (r) => r.sensor_type === "humidity",
          );
          const presence = room.readings.find(
            (r) => r.sensor_type === "presence",
          );

          return (
            <button
              className="overview-card"
              key={room.id}
              onClick={() => onSelectRoom(room.id)}
            >
              <h3>{room.icon} {room.name}</h3>

              <div className="overview-values">
                <span>
                  🌡️ {temperature ? `${temperature.value} °C` : "--"}
                </span>
                <span>
                  💧 {humidity ? `${humidity.value} %` : "--"}
                </span>
                <span>
                  🏠{" "}
                  {presence
                    ? presence.value
                      ? "Occupied"
                      : "Empty"
                    : "--"}
                </span>
              </div>

              <p className="overview-device-count">
                {room.devices.length} device(s)
              </p>
            </button>
          );
        })}
      </div>
    </section>
  );
}
