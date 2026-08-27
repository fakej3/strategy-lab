"use client";

import { useState } from "react";

export default function Home() {
  const [status, setStatus] = useState<string>("Ready");

  async function validate() {
    setStatus("Validating research request…");
    try {
      const response = await fetch("/api/research/validate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          symbol: "BTCUSDT",
          timeframe: "1h",
          start: "2025-01-01",
          end: "2026-01-01",
          initial_capital: 10000,
        }),
      });
      const data = await response.json();
      setStatus(data.accepted ? "Request accepted by Python engine" : "Request rejected");
    } catch {
      setStatus("API unavailable");
    }
  }

  return (
    <main style={{ maxWidth: 1180, margin: "0 auto", padding: "48px 24px" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 24 }}>
        <div>
          <div style={{ fontSize: 13, letterSpacing: 2, textTransform: "uppercase", opacity: 0.55 }}>Quantitative Research</div>
          <h1 style={{ fontSize: 42, margin: "8px 0" }}>Strategy Labs</h1>
          <p style={{ color: "#a1a1aa", maxWidth: 680, lineHeight: 1.6 }}>
            A browser-based research workspace backed by the Python V2 quant engine.
            Your device is the interface; the server does the numerical work.
          </p>
        </div>
        <button onClick={validate} style={{ padding: "12px 18px", borderRadius: 10, border: "1px solid #3f3f46", background: "#18181b", color: "inherit", cursor: "pointer" }}>
          Test Python Engine
        </button>
      </header>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 14, marginTop: 42 }}>
        {["Data Quality", "Research", "Backtests", "Robustness"].map((name) => (
          <div key={name} style={{ border: "1px solid #27272a", borderRadius: 14, padding: 20, background: "#111113" }}>
            <div style={{ color: "#a1a1aa", fontSize: 13 }}>MODULE</div>
            <h2 style={{ margin: "8px 0" }}>{name}</h2>
            <div style={{ color: "#71717a" }}>V2 foundation</div>
          </div>
        ))}
      </section>

      <section style={{ marginTop: 28, border: "1px solid #27272a", borderRadius: 14, padding: 20 }}>
        <div style={{ color: "#a1a1aa", fontSize: 13 }}>SYSTEM STATUS</div>
        <p style={{ fontFamily: "monospace" }}>{status}</p>
      </section>
    </main>
  );
}
