import React, { memo, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { ArrowClockwise } from "@phosphor-icons/react/ArrowClockwise";
import { ArrowSquareOut } from "@phosphor-icons/react/ArrowSquareOut";
import { FileText } from "@phosphor-icons/react/FileText";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";

const REFRESH_INTERVAL_MS = 15_000;
const enter = { hidden: { opacity: 0, y: 10 }, shown: { opacity: 1, y: 0 } };

function timestamp(value) {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toISOString().replace("T", " ");
}

function shortHash(value) {
  return value ? `${value.slice(0, 8)}…${value.slice(-5)}` : "Not present";
}

function deriveMode(snapshot) {
  if (snapshot?.shutdown) return "stopped";
  if (snapshot?.host_bootstrap?.validation_error) return "mismatch";
  if (snapshot?.mismatches?.length) return "mismatch";
  const canonicalPresent = Object.values(snapshot?.canonical ?? {}).some(
    (value) => value && typeof value === "object" && value.present,
  );
  const runtimePresent = (snapshot?.schedulers ?? []).some((item) => item.present);
  if (!canonicalPresent && !runtimePresent && !snapshot?.workers?.length) return "empty";
  if (!snapshot?.canonical?.staged_state?.present) return "partial";
  return "live";
}

function scheduler(snapshot, kind) {
  return snapshot.schedulers?.find((item) => item.kind === kind);
}

function layerState(item) {
  if (!item?.present) return { label: "Absent", tone: "quiet" };
  if (item.state_matches_scheduler === false) return { label: "Mismatch", tone: "danger" };
  if (item.loaded === true) return { label: "Loaded", tone: "active" };
  if (item.loaded === false) return { label: "Unloaded", tone: "danger" };
  return { label: item.active ? "Active" : "Inactive", tone: item.active ? "active" : "quiet" };
}

const LiveDot = memo(function LiveDot({ animate = true }) {
  return <span className={`live-dot${animate ? " is-live" : ""}`} aria-hidden="true" />;
});

function StatusBadge({ mode, refreshing }) {
  const labels = {
    live: "Fresh observation",
    stale: "Stale snapshot",
    empty: "Empty runtime",
    partial: "Partial observation",
    mismatch: "Mismatch detected",
    stopped: "Plan stopped",
    error: "Observation unavailable",
  };
  return (
    <div className={`status-badge status-${mode}`}>
      <LiveDot animate={mode === "live" && !refreshing} />
      <strong>{refreshing ? "Refreshing" : labels[mode]}</strong>
    </div>
  );
}

function LoadingView() {
  return (
    <main className="shell" aria-busy="true">
      <header className="top"><div className="wordmark">Autoresearch Paper <span>operator view</span></div></header>
      <section className="state-panel skeleton" aria-label="Loading observation">
        <span className="eyebrow">Reading canonical and host state</span><i /><i /><i />
      </section>
    </main>
  );
}

function ErrorView({ error, retry }) {
  return (
    <main className="shell">
      <header className="top"><div className="wordmark">Autoresearch Paper <span>operator view</span></div></header>
      <section className="state-panel"><div className="error-rule" /><h1>Observation unavailable</h1><p>{error}</p><button className="refresh-button" onClick={retry}><ArrowClockwise size={18} />Try again</button></section>
    </main>
  );
}

function EmptyView() {
  return <section className="state-panel inline-state"><span className="eyebrow">No runtime resources</span><h2>Nothing has been scheduled</h2><p>Canonical records may still exist. Empty runtime state is not a success or completion claim.</p></section>;
}

function RuntimeRow({ code, title, detail, state, index }) {
  return (
    <motion.div className="ledger-row" variants={enter} custom={index}>
      <span className="row-code mono">{code}</span>
      <div className="row-main"><b>{title}</b><span>{detail}</span></div>
      <span className={`row-state tone-${state.tone}`}>{state.label}</span>
    </motion.div>
  );
}

function EvidenceFile({ label, file }) {
  return (
    <div className="evidence-row">
      <b>{label}</b>
      <span className="mono">{file?.present ? `${shortHash(file.sha256)} · ${file.size_bytes?.toLocaleString() ?? "?"} bytes` : "Not present"}</span>
      {file?.present && file.relative_path && <small className="mono">{file.relative_path}</small>}
    </div>
  );
}

function LogLinks({ snapshot }) {
  const links = useMemo(() => {
    const values = [];
    snapshot.schedulers?.forEach((item) => {
      [item.stdout, item.stderr].forEach((log) => {
        if (log?.bound && log.exists) values.push({ ...log, label: `${item.kind} · ${log === item.stdout ? "stdout" : "stderr"}` });
      });
    });
    snapshot.workers?.forEach((item) => {
      [item.stdout, item.stderr].forEach((log) => {
        if (log?.bound && log.exists) values.push({ ...log, label: `${item.run_id} · ${log === item.stdout ? "stdout" : "stderr"}` });
      });
    });
    return values;
  }, [snapshot]);
  if (!links.length) return <p className="notice">Logs are not bound or not present for this observation. The Dashboard does not manufacture a path.</p>;
  return <div className="log-links">{links.map((log) => <a key={log.api_path} href={log.api_path} target="_blank" rel="noreferrer"><ArrowSquareOut size={16} />{log.label}</a>)}</div>;
}

function Dossier({ dossier }) {
  if (!dossier?.present) return null;
  return (
    <details className="dossier">
      <summary><span><FileText size={18} />Research dossier</span><small>Rebuildable projection · not transition authority</small></summary>
      <pre>{dossier.content}</pre>
      {dossier.truncated && <p>Preview truncated at the bounded read limit.</p>}
    </details>
  );
}

function Dashboard({ snapshot, mode, error, refreshing, refresh, dossier }) {
  const bootstrap = snapshot.host_bootstrap;
  const l0 = scheduler(snapshot, "l0_runtime_assurance");
  const l1 = scheduler(snapshot, "l1_durable_trigger");
  const retry = scheduler(snapshot, "frontier_retry_trigger");
  const workers = snapshot.workers ?? [];
  const workerState = workers.length
    ? { label: `${workers.length} observed`, tone: workers.some((item) => item.process?.identity_match === false) ? "danger" : "active" }
    : { label: "Empty", tone: "quiet" };
  const bootstrapState = bootstrap?.validation_error
    ? { label: "Invalid", tone: "danger" }
    : bootstrap?.status === "READY"
      ? { label: "Ready", tone: "active" }
      : { label: bootstrap?.present ? (bootstrap.status ?? "Partial") : "Absent", tone: "quiet" };
  const heartbeatState = bootstrap?.live_l2_worker_evidence
    ? { label: "Live evidence", tone: "active" }
    : { label: "Pending field run", tone: "quiet" };
  const agreement = snapshot.mismatches?.length ? `${snapshot.mismatches.length} recorded` : "0 recorded";
  const staged = snapshot.canonical?.staged_status ?? "STATE UNAVAILABLE";
  return (
    <main className="shell">
      <header className="top">
        <div className="wordmark">Autoresearch Paper <span>operator view</span></div>
        <span className="plan-id mono">{snapshot.plan_id ?? "Unknown plan"}</span>
        <button className="refresh-button" onClick={refresh} disabled={refreshing}><ArrowClockwise size={18} className={refreshing ? "spin" : ""} />Refresh</button>
      </header>
      <AnimatePresence mode="wait">
        {mode === "empty" ? <EmptyView key="empty" /> : (
          <motion.div key={snapshot.observed_at} initial="hidden" animate="shown" transition={{ staggerChildren: 0.07 }}>
            {error && <div className="stale-banner" role="status"><b>Refresh failed.</b> The last successful snapshot remains visible and is labeled stale.</div>}
            {mode === "mismatch" && <div className="mismatch-banner" role="alert"><b>State and host disagree.</b> Inspect the affected runtime layer before interpreting this plan as healthy.</div>}
            {mode === "stopped" && <div className="stopped-banner" role="status"><b>Shutdown receipt present.</b> Residual resources remain visible below.</div>}
            <section className="hero">
              <motion.div className="stage" variants={enter}><span className="eyebrow">Canonical staged state</span><h1>{staged}</h1><p>Plan <strong className="mono">{snapshot.plan_id}</strong> is shown from one fresh correlated inspection. Missing controller or durable-loop pointers remain <strong>not present</strong>; this view never infers completion from absence.</p></motion.div>
              <motion.aside className="freshness" variants={enter}><StatusBadge mode={mode} refreshing={refreshing} /><dl><div><dt>Observed</dt><dd className="mono">{timestamp(snapshot.observed_at)}</dd></div><div><dt>Authority</dt><dd>Observation only</dd></div><div><dt>Mismatches</dt><dd className="mono">{agreement}</dd></div></dl></motion.aside>
            </section>
            <section className="ledger">
              <motion.div variants={enter}><div className="section-head"><h2>Runtime ledger</h2><span className="mono">state vs host</span></div><RuntimeRow code="HS" title="Host bootstrap" detail={bootstrap?.validation_error ?? (bootstrap?.last_health_action ? `Last action · ${bootstrap.last_health_action}` : "No committed host bootstrap receipt")} state={bootstrapState} index={0} /><RuntimeRow code="L0" title="Runtime assurance" detail={l0?.present ? (l0.label ?? "Activation record present") : "No activation record present"} state={layerState(l0)} index={1} /><RuntimeRow code="L1" title="Durable work trigger" detail={l1?.present ? (l1.label ?? "Schedule record present") : "No schedule record present"} state={layerState(l1)} index={2} /><RuntimeRow code="L2" title="Worker heartbeat" detail={workers.length ? workers.map((item) => `${item.run_id} · ${item.status ?? "unknown"}`).join(", ") : "No live Worker heartbeat evidence yet"} state={heartbeatState} index={3} /><RuntimeRow code="FR" title="Frontier retry" detail={retry?.present ? `Generation ${retry.generation ?? "?"} · receipt ${retry.receipt?.present ? "bound" : "missing"}` : "No retry record present"} state={layerState(retry)} index={4} /><RuntimeRow code="WK" title="Workers" detail={workers.length ? `${workers.length} Worker record(s)` : "No Worker run discovered"} state={workerState} index={5} /></motion.div>
              <motion.aside className="evidence" variants={enter}><h2>Evidence addresses</h2><EvidenceFile label="Host bootstrap receipt" file={bootstrap?.receipt} /><EvidenceFile label="Latest L0 health tick" file={bootstrap?.last_health_tick} /><EvidenceFile label="Staged state" file={snapshot.canonical?.staged_state} /><EvidenceFile label="Durable head" file={snapshot.canonical?.durable_head} /><EvidenceFile label="Frontier retry receipt" file={retry?.receipt} /><div className="evidence-row"><b>Scheduler agreement</b><span>{snapshot.mismatches?.length ? "Mismatch requires attention" : "No mismatch recorded"}</span></div><LogLinks snapshot={snapshot} /></motion.aside>
            </section>
            <Dossier dossier={dossier} />
          </motion.div>
        )}
      </AnimatePresence>
      <footer><span>Read-only local Dashboard · no lifecycle authority</span><span className="mono">Research Ledger / MVP</span></footer>
    </main>
  );
}

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [dossier, setDossier] = useState(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(true);
  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await fetch("/api/snapshot", { cache: "no-store" });
      if (!response.ok) throw new Error(`Snapshot request failed (${response.status})`);
      const value = await response.json();
      setSnapshot(value);
      setError("");
      fetch("/api/dossier", { cache: "no-store" }).then((result) => result.ok ? result.json() : null).then(setDossier).catch(() => setDossier(null));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Snapshot request failed");
    } finally {
      setRefreshing(false);
    }
  }, []);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);
  if (!snapshot && refreshing) return <LoadingView />;
  if (!snapshot) return <ErrorView error={error || "No snapshot was returned."} retry={refresh} />;
  const mode = error ? "stale" : deriveMode(snapshot);
  return <Dashboard snapshot={snapshot} mode={mode} error={error} refreshing={refreshing} refresh={refresh} dossier={dossier} />;
}

createRoot(document.getElementById("root")).render(<MotionConfig reducedMotion="user"><App /></MotionConfig>);
