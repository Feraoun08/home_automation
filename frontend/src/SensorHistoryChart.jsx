import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const ranges = [
  { label: "30 min", value: 30 },
  { label: "1 hour", value: 60 },
  { label: "24 hours", value: 1440 },
];

export default function SensorHistoryChart() {
  const [points, setPoints] = useState([]);
  const [minutes, setMinutes] = useState(30);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function loadHistory() {
      try {
        const response = await fetch(
          `http://localhost:8000/api/readings/history?minutes=${minutes}`,
        );

        if (!response.ok) {
          throw new Error("History request failed");
        }

        const data = await response.json();

        if (active) {
          setPoints(data.points);
          setError("");
        }
      } catch {
        if (active) {
          setError("Unable to load sensor history.");
        }
      }
    }

    loadHistory();
    const intervalId = window.setInterval(loadHistory, 10000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [minutes]);

  return (
    <section className="history-section">
      <div className="chart-header">
        <div>
          <p className="eyebrow">SENSOR HISTORY</p>
          <h2>Temperature and humidity</h2>
        </div>

        <div className="range-selector">
          {ranges.map((range) => (
            <button
              className={minutes === range.value ? "active-range" : ""}
              key={range.value}
              onClick={() => setMinutes(range.value)}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <p className="error-message">{error}</p>
      ) : (
        <div className="chart-container">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points}>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#aab9cf" minTickGap={45} />
              <YAxis yAxisId="temperature" stroke="#fbbf24" unit="°C" />
              <YAxis
                yAxisId="humidity"
                orientation="right"
                stroke="#60a5fa"
                unit="%"
              />
              <Tooltip
                contentStyle={{
                  background: "#1e293b",
                  border: "1px solid #475569",
                }}
              />
              <Legend />
              <Line
                yAxisId="temperature"
                type="monotone"
                dataKey="temperature"
                name="Temperature"
                stroke="#fbbf24"
                strokeWidth={3}
                dot={false}
              />
              <Line
                yAxisId="humidity"
                type="monotone"
                dataKey="humidity"
                name="Humidity"
                stroke="#60a5fa"
                strokeWidth={3}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}