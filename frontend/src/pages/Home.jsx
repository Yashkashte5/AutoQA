import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { createSuite, triggerRun } from "../api";
import axios from "axios";

const STAGE_LABELS = {
  queued:     "Queued",
  parsing:    "Reading spec",
  generating: "Generating tests",
  executing:  "Running tests",
  reporting:  "Classifying failures",
  saving:     "Saving results",
  done:       "Complete",
  failed:     "Failed",
};

export default function Home() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [file, setFile] = useState(null);
  const [suiteId, setSuiteId] = useState(null);
  const [suiteInfo, setSuiteInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Run progress state
  const [runId, setRunId] = useState(null);
  const [progress, setProgress] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    if (!runId) return;

    pollRef.current = setInterval(async () => {
      try {
        const res = await axios.get(`http://127.0.0.1:8000/runs/${runId}/progress`);
        const p = res.data;
        setProgress(p);

        if (p.stage === "done") {
          clearInterval(pollRef.current);
          setTimeout(() => navigate(`/results/${runId}`), 800);
        }

        if (p.stage === "failed") {
          clearInterval(pollRef.current);
          setError(p.message || "Run failed");
          setRunId(null);
        }
      } catch {
        // keep polling
      }
    }, 2500);

    return () => clearInterval(pollRef.current);
  }, [runId]);

  async function handleUpload(e) {
    e.preventDefault();
    if (!name || !baseUrl || !file) return;
    setLoading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("name", name);
      fd.append("base_url", baseUrl);
      fd.append("spec_file", file);
      const res = await createSuite(fd);
      setSuiteId(res.data.suite_id);
      setSuiteInfo(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to upload suite");
    } finally {
      setLoading(false);
    }
  }

  async function handleRun() {
    setError("");
    setProgress({ stage: "queued", pct: 0, message: "Starting run..." });
    try {
      const res = await triggerRun(suiteId);
      setRunId(res.data.run_id);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to start run");
      setProgress(null);
    }
  }

  const isRunning = !!runId && progress?.stage !== "done" && progress?.stage !== "failed";

  return (
    <div>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>New test run</h1>
      <p className="muted" style={{ marginBottom: 28 }}>
        Upload an OpenAPI spec and AutoQA will generate and execute tests automatically.
      </p>

      <div className="card" style={{ maxWidth: 560 }}>
        {!suiteId ? (
          <form onSubmit={handleUpload}>
            <div className="form-group">
              <label>Suite name</label>
              <input type="text" placeholder="e.g. Petstore v2" value={name} onChange={e => setName(e.target.value)} />
            </div>
            <div className="form-group">
              <label>API base URL</label>
              <input type="text" placeholder="https://api.example.com/v1" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} />
            </div>
            <div className="form-group">
              <label>OpenAPI spec (YAML or JSON)</label>
              <input type="file" accept=".yaml,.yml,.json" onChange={e => setFile(e.target.files[0])} />
            </div>
            {error && <p className="error-msg">{error}</p>}
            <button className="btn btn-primary" type="submit" disabled={loading || !name || !baseUrl || !file}>
              {loading ? "Uploading..." : "Upload spec"}
            </button>
          </form>
        ) : (
          <div>
            {!progress ? (
              <>
                <p className="success-msg" style={{ marginBottom: 16 }}>
                  Suite created — {suiteInfo?.endpoint_count} endpoints indexed
                </p>
                <div style={{ marginBottom: 16, fontSize: 13, color: "#94a3b8" }}>
                  <div><strong style={{ color: "#e2e8f0" }}>Name:</strong> {suiteInfo?.name}</div>
                  <div><strong style={{ color: "#e2e8f0" }}>Base URL:</strong> {suiteInfo?.base_url}</div>
                  <div><strong style={{ color: "#e2e8f0" }}>Suite ID:</strong> {suiteId}</div>
                </div>
                {error && <p className="error-msg" style={{ marginBottom: 12 }}>{error}</p>}
                <button className="btn btn-primary" onClick={handleRun}>Run tests</button>
                <button className="btn btn-secondary" style={{ marginLeft: 8 }} onClick={() => { setSuiteId(null); setSuiteInfo(null); }}>
                  Upload different spec
                </button>
              </>
            ) : (
              <div>
                <div style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 14, fontWeight: 500 }}>
                    {progress.stage === "done"
                      ? "✓ Complete"
                      : progress.stage === "failed"
                      ? "✗ Failed"
                      : <><span className="status-indicator status-running" />{STAGE_LABELS[progress.stage] || progress.stage}</>
                    }
                  </span>
                  <span style={{ fontSize: 13, color: "#64748b" }}>{progress.pct}%</span>
                </div>

                {/* Progress bar */}
                <div style={{
                  width: "100%",
                  height: 6,
                  background: "#1e2535",
                  borderRadius: 3,
                  marginBottom: 12,
                  overflow: "hidden",
                }}>
                  <div style={{
                    height: "100%",
                    width: `${progress.pct}%`,
                    borderRadius: 3,
                    background: progress.stage === "failed" ? "#ef4444" : progress.stage === "done" ? "#22c55e" : "#7c6df0",
                    transition: "width 0.6s ease",
                  }} />
                </div>

                {/* Stage steps */}
                <div style={{ display: "flex", gap: 4, marginBottom: 14, flexWrap: "wrap" }}>
                  {["parsing", "generating", "executing", "reporting", "saving", "done"].map(s => {
                    const stages = ["parsing", "generating", "executing", "reporting", "saving", "done"];
                    const currentIdx = stages.indexOf(progress.stage);
                    const stepIdx = stages.indexOf(s);
                    const isDone = stepIdx < currentIdx;
                    const isCurrent = s === progress.stage;
                    return (
                      <span key={s} style={{
                        fontSize: 11,
                        padding: "2px 8px",
                        borderRadius: 4,
                        background: isDone ? "#14532d" : isCurrent ? "#3b1fa8" : "#1e2535",
                        color: isDone ? "#86efac" : isCurrent ? "#a5b4fc" : "#475569",
                        fontWeight: isCurrent ? 600 : 400,
                      }}>
                        {isDone ? "✓ " : ""}{STAGE_LABELS[s]}
                      </span>
                    );
                  })}
                </div>

                <p className="muted" style={{ fontSize: 12 }}>{progress.message}</p>

                {error && <p className="error-msg" style={{ marginTop: 8 }}>{error}</p>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}