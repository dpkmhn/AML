import { useQuery } from "@tanstack/react-query";
import { Inbox, Moon, ShieldCheck, Sun } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api";

function useTheme() {
  const initial = () =>
    (document.documentElement.dataset.theme as "light" | "dark" | undefined) ??
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const [theme, setTheme] = useState<"light" | "dark">(initial);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* storage blocked */
    }
    setTheme(next);
  };
  return { theme, toggle };
}

export function Layout() {
  const { theme, toggle } = useTheme();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts });
  const open = alerts.data?.filter((a) => a.status !== "closed").length;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <ShieldCheck size={19} />
          </span>
          <div>
            <div className="brand-name">Triage Copilot</div>
            <div className="brand-sub">Falcon Digital Bank · AML</div>
          </div>
        </div>
        <nav className="nav">
          <div className="nav-label">Workspace</div>
          <NavLink to="/" end>
            <Inbox size={17} />
            Alert queue
            {open !== undefined && <span className="nav-count">{open}</span>}
          </NavLink>
        </nav>
        <div className="sidebar-foot">
          <div className="health">
            <div className="health-row">
              <span className={`dot ${health.isError ? "bad" : health.data ? "ok" : ""}`} />
              {health.isError ? "API unreachable" : health.data ? "All systems normal" : "Checking…"}
            </div>
            {health.data && (
              <div className="health-meta">
                <span className="mono">{health.data.model_small}</span> · prompt v
                {health.data.prompt_version}
              </div>
            )}
          </div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={toggle}
            style={{ justifyContent: "flex-start" }}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
            <span className="theme-label">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
