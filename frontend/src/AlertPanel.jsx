
import { useEffect, useState } from "react";

export default function AlertPanel({ roomId }) {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    let active = true;

    async function loadAlerts() {
      try {
        const response = await fetch(
          `http://localhost:8000/api/alerts?room_id=${roomId}`,
        );

        if (!response.ok) throw new Error("Alerts request failed");

        const data = await response.json();

        if (active) setAlerts(data.alerts || []);
      } catch {
        // Keep the dashboard available.
      }
    }

    loadAlerts();
    const intervalId = window.setInterval(loadAlerts, 5000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [roomId]);

  return (
    <section className="alerts-section">
      <div>
        <p className="eyebrow">SYSTEM EVENTS</p>
        <h2>Recent alerts</h2>
      </div>

      {alerts.length === 0 ? (
        <p className="no-alerts">No alerts during the last 24 hours.</p>
      ) : (
        <div className="alerts-list">
          {alerts.map((alert, index) => (
            <article
              className={`alert-card ${alert.severity}`}
              key={`${alert.timestamp}-${alert.message}-${index}`}
            >
              <div>
                <p className="alert-title">
                  {(alert.severity || "info").toUpperCase()} ·{" "}
                  {alert.room || roomId}
                </p>
                <p className="alert-message">{alert.message}</p>
              </div>
              <time>{new Date(alert.timestamp).toLocaleString()}</time>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
