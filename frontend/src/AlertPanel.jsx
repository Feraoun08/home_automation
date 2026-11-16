import { useEffect, useState } from "react";

const ALERTS_URL = "http://localhost:8000/api/alerts";

export default function AlertPanel() {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    let active = true;

    async function loadAlerts() {
      try {
        const response = await fetch(ALERTS_URL);

        if (!response.ok) {
          throw new Error("Alerts request failed");
        }

        const data = await response.json();

        if (active) {
          setAlerts(data.alerts);
        }
      } catch {
        // The main dashboard remains available if alerts cannot load.
      }
    }

    loadAlerts();
    const intervalId = window.setInterval(loadAlerts, 5000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, []);

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
          {alerts.map((alert) => (
            <article
              className={`alert-card ${alert.severity}`}
              key={`${alert.timestamp}-${alert.message}`}
            >
              <div>
                <p className="alert-title">
                  {alert.severity.toUpperCase()} · {alert.room}
                </p>
                <p className="alert-message">{alert.message}</p>
              </div>
              <time>
                {new Date(alert.timestamp).toLocaleString()}
              </time>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}