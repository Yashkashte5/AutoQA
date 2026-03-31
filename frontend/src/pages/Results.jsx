import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getRunResults } from "../api";
import StatCard from "../components/StatCard";
import SeverityBadge from "../components/SeverityBadge";

const METHOD_COLORS = { GET: "GET", POST: "POST", PUT: "PUT", DELETE: "DELETE", PATCH: "PATCH" };

export default function Results() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [severityFilter, setSeverityFilter] = useState("all");

  useEffect(() => {
    getRunResults(runId)
      .then(res => setData(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return <p className="muted">Loading results...</p>;
  if (!data) return <p className="error-msg">Failed to load results.</p>;

  const { summary, by_category, by_severity, results } = data;
  const passRate = summary.total > 0 ? ((summary.passed / summary.total) * 100).toFixed(1) : 0;
  const maxCat = Math.max(...Object.values(by_category));

  const filtered = results.filter(r => {
    if (filter !== "all" && r.status !== filter) return false;
    if (severityFilter !== "all" && r.severity !== severityFilter) return false;
    return true;
  });

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 28 }}>
        <button className="btn btn-secondary" onClick={() => navigate("/")}>← New run</button>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700 }}>Run results</h1>
          <p className="muted" style={{ fontSize: 12 }}>{runId}</p>
        </div>
      </div>

      <div className="stat-grid">
        <StatCard label="Total tests" value={summary.total} type="total" />
        <StatCard label="Passed" value={summary.passed} type="pass" />
        <StatCard label="Failed" value={summary.failed} type="fail" />
        <StatCard label="Pass rate" value={`${passRate}%`} type="coverage" />
      </div>

      {/* Severity summary */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
        <div className="card">
          <div className="section-title">Failures by category</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {Object.entries(by_category).sort((a, b) => b[1] - a[1]).map(([cat, count]) => (
              <div key={cat} className="category-row">
                <span className="category-label">{cat.replace("_", " ")}</span>
                <div className="category-bar-wrap">
                  <div className="category-bar" style={{ width: `${(count / maxCat) * 100}%` }} />
                </div>
                <span className="category-count">{count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="section-title">Failures by severity</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {["critical", "high", "medium", "low"].map(sev => (
              <div key={sev} style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <SeverityBadge value={sev} />
                <span style={{ fontSize: 24, fontWeight: 700, color: sev === "critical" ? "#fca5a5" : sev === "high" ? "#fdba74" : sev === "medium" ? "#fde68a" : "#86efac" }}>
                  {by_severity[sev] || 0}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div className="section-title" style={{ marginBottom: 0 }}>
            Test results <span className="muted" style={{ fontWeight: 400 }}>({filtered.length})</span>
          </div>
        </div>

        <div className="filter-row">
          {["all", "pass", "fail", "error"].map(f => (
            <button key={f} className={`filter-btn ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
          <span style={{ margin: "0 4px", color: "#1e2535" }}>|</span>
          {["all", "critical", "high", "medium", "low"].map(s => (
            <button key={s} className={`filter-btn ${severityFilter === s ? "active" : ""}`} onClick={() => setSeverityFilter(s)}>
              {s === "all" ? "All severities" : s}
            </button>
          ))}
        </div>

        <div style={{ overflowX: "auto" }}>
          <table className="results-table">
            <thead>
              <tr>
                <th>Method</th>
                <th>Endpoint</th>
                <th>Status</th>
                <th>Code</th>
                <th>Latency</th>
                <th>Category</th>
                <th>Severity</th>
                <th>Suggestion</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={i}>
                  <td><span className={`method method-${r.method}`}>{r.method}</span></td>
                  <td style={{ fontFamily: "monospace", fontSize: 12, maxWidth: 200, wordBreak: "break-all" }}>{r.endpoint}</td>
                  <td><span className={`badge badge-${r.status}`}>{r.status}</span></td>
                  <td style={{ color: r.status_code >= 400 ? "#ef4444" : "#22c55e" }}>{r.status_code}</td>
                  <td className="muted">{r.latency_ms ? `${r.latency_ms}ms` : "—"}</td>
                  <td className="muted">{r.category ? r.category.replace("_", " ") : "—"}</td>
                  <td><SeverityBadge value={r.severity} /></td>
                  <td>
                    {r.suggestion
                      ? <span className="suggestion">{r.suggestion}</span>
                      : <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}