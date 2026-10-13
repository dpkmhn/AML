import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

// The graph's nodes up to the pause, in order (app/graph/build.py). POST /cases is a single
// synchronous call, so this shows the pipeline and the elapsed time, not live per-step progress.
const STEPS: [string, "rules" | "llm" | "data"][] = [
  ["load_alert", "data"],
  ["get_profile", "data"],
  ["get_transactions", "data"],
  ["compute_features", "rules"],
  ["detect_typologies", "rules"],
  ["retrieve_guidance", "data"],
  ["assess_case", "llm"],
  ["decide_route", "rules"],
];

export function RunningOverlay({ alertId }: { alertId: string }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 250);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="overlay">
      <div className="card run-card" role="status" aria-live="polite">
        <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
          <span className="icon-tile">
            <Sparkles size={18} />
          </span>
          <div>
            <h3 style={{ fontSize: 17 }}>Preparing the investigation pack</h3>
            <p className="muted" style={{ fontSize: 13 }}>
              <span className="mono">{alertId}</span> · usually 10 to 30 seconds
            </p>
          </div>
          <span className="mono faint" style={{ marginLeft: "auto", fontSize: 15 }}>
            {elapsed}s
          </span>
        </div>
        <div className="run-steps">
          {STEPS.map(([s, kind]) => (
            <span key={s}>
              <i className={kind === "data" ? "" : kind}>{kind === "data" ? "" : kind.toUpperCase()}</i>
              {s.replace(/_/g, " ")}
            </span>
          ))}
        </div>
        <div className="progress" />
        <p className="faint" style={{ fontSize: 12, marginTop: 12 }}>
          Then it pauses for your review. Nothing closes an alert without a human decision.
        </p>
      </div>
    </div>
  );
}
