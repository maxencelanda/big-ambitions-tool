import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, BusinessRow, Dashboard as DashboardData } from "../api";
import { CostCenterTable, ProfitCenterTable } from "../components/BusinessTables";
import { baseOption, Chart, ThemeColors, useThemeColors } from "../components/Chart";
import { InsightList } from "../components/Insights";
import { change, money, signedPercent } from "../format";

function Delta({ value, label }: { value: number | null; label: string }) {
  if (value === null) return null;
  return <span className={`delta ${value >= 0 ? "up" : "down"}`}>{value >= 0 ? "▲" : "▼"} {signedPercent(value)} {label}</span>;
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card tile" title={hint}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

/** Colonnes ou barres arrondies côté valeur, carrées côté ligne de base, couleur selon le signe. */
export function signedBar(value: number, t: ThemeColors, horizontal = false, color?: string) {
  const positive = value >= 0;
  const radius = horizontal ? (positive ? [0, 4, 4, 0] : [4, 0, 0, 4]) : positive ? [4, 4, 0, 0] : [0, 0, 4, 4];
  return { value, itemStyle: { color: color ?? (positive ? t.series1 : t.negative), borderRadius: radius } };
}

function DailyProfitChart({ data, t }: { data: DashboardData; t: ThemeColors }) {
  const option = useMemo(() => ({
    ...baseOption(t),
    tooltip: {
      ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: t.grid, opacity: 0.4 } },
      valueFormatter: (v: number) => money(v, { compactForm: false }),
    },
    xAxis: {
      type: "category", data: data.dailyProfit.map((d) => `Day ${d.day}`),
      axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false },
      axisLabel: { color: t.muted, formatter: (v: string) => v.replace("Day ", "") },
    },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted, formatter: (v: number) => money(v) } },
    series: [{ name: "Net profit", type: "bar", barMaxWidth: 24, data: data.dailyProfit.map((d) => signedBar(d.totalProfit, t)) }],
  }), [data, t]);
  return <Chart option={option} height={300} label="Net profit per game day" />;
}

function BusinessProfitChart({ rows, t }: { rows: BusinessRow[]; t: ThemeColors }) {
  const sorted = useMemo(() => [...rows].sort((a, b) => a.operatingProfit - b.operatingProfit), [rows]);
  const option = useMemo(() => ({
    ...baseOption(t),
    legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.secondary } },
    tooltip: { ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: t.grid, opacity: 0.4 } },
               valueFormatter: (v: number) => money(v, { compactForm: false }) },
    grid: { ...baseOption(t).grid, top: 28, left: 4 },
    xAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted, formatter: (v: number) => money(v) } },
    yAxis: { type: "category", data: sorted.map((b) => b.name ?? b.address), axisLine: { lineStyle: { color: t.axis } },
             axisTick: { show: false }, axisLabel: { color: t.secondary } },
    series: [
      { name: "Profit", type: "bar", barMaxWidth: 10, barGap: "20%", data: sorted.map((b) => signedBar(b.operatingProfit, t, true, t.series1)) },
      { name: "After overhead", type: "bar", barMaxWidth: 10, data: sorted.map((b) => signedBar(b.profitAfterOverhead ?? 0, t, true, t.series2)) },
    ],
    color: [t.series1, t.series2],
  }), [sorted, t]);
  return <Chart option={option} height={Math.max(240, sorted.length * 30 + 50)} label="Profit and profit after overhead per business" />;
}

function DailyProfitTable({ data }: { data: DashboardData }) {
  return (
    <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto" }}>
      <table>
        <thead><tr><th>Day</th><th className="num">Net profit</th><th className="num">Business profit</th></tr></thead>
        <tbody>
          {[...data.dailyProfit].reverse().map((d) => (
            <tr key={d.day}>
              <td>Day {d.day}</td>
              <td className={`num ${d.totalProfit < 0 ? "neg" : ""}`}>{money(d.totalProfit, { compactForm: false })}</td>
              <td className="num">{money(d.totalBusinessProfit, { compactForm: false })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ViewSwitch({ table, onChange }: { table: boolean; onChange: (table: boolean) => void }) {
  return (
    <div className="view-switch" role="group" aria-label="View">
      <button className={!table ? "on" : ""} onClick={() => onChange(false)}>Chart</button>
      <button className={table ? "on" : ""} onClick={() => onChange(true)}>Table</button>
    </div>
  );
}

export function WindowSelect({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <label className="toggle">
      window
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {[7, 14, 30].map((d) => <option key={d} value={d}>{d} days</option>)}
      </select>
    </label>
  );
}

export function Dashboard() {
  const [window, setWindow] = useState(7);
  const [dailyAsTable, setDailyAsTable] = useState(false);
  const t = useThemeColors();
  const { data, isLoading, error } = useQuery({ queryKey: ["dashboard", window], queryFn: () => api.dashboard(window) });

  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error) return <div className="page"><div className="card empty">Could not load the dashboard: {(error as Error).message}</div></div>;
  if (!data || data.empty) return <div className="page"><div className="card empty">No data yet — click “Sync now”.</div></div>;

  const k = data.kpis;
  const totalRevenue = data.businesses.reduce((s, b) => s + b.revenue, 0);
  const counts = data.insightCounts;

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="subtitle">Days {data.window.firstDay}–{data.window.lastDay} (last {data.window.days} completed game days) · <WindowSelect value={window} onChange={setWindow} /></p>

      <div className="grid two">
        <div>
          <div className="card">
            <div className="hero">
              <div>
                <div className="label">Net profit, last {data.window.days} days</div>
                <div className="value">{money(k.profitWindow, { compactForm: false })}</div>
                <Delta value={change(k.profitWindow, k.profitPreviousWindow)} label={`vs previous ${data.window.days} days`} />
              </div>
            </div>
          </div>
          <div className="grid tiles section">
            <Tile label="Businesses' profit" value={money(k.operatingProfit)} hint={`${k.businesses} profit centers (retail & office)`} />
            <Tile label="Overhead" value={money(k.overhead)} hint={`${k.costCenters} cost centers: headquarters, warehouses`} />
            <Tile label="Yesterday's net profit" value={money(k.lastDayProfit)} />
            <Tile label="Cash" value={money(k.money)} />
            <Tile label="Investments" value={money(k.investments)} />
            <Tile label="Employees" value={String(k.employees)} />
          </div>
        </div>
        <div className="card">
          <h2>Attention points</h2>
          <p className="hint">
            {counts.high} high · {counts.medium} medium · {counts.low} low — click a point for details ·{" "}
            <Link to="/businesses">all businesses</Link>
          </p>
          <InsightList insights={data.insights} maxHeight={460} />
        </div>
      </div>

      <div className="grid two section">
        <div className="card">
          <ViewSwitch table={dailyAsTable} onChange={setDailyAsTable} />
          <h2>Daily net profit</h2>
          <p className="hint">All businesses, overhead and personal costs included · <Link to="/pnl">full P&L</Link></p>
          {dailyAsTable ? <DailyProfitTable data={data} /> : <DailyProfitChart data={data} t={t} />}
        </div>
        <div className="card">
          <h2>Profit by business</h2>
          <p className="hint">Last {data.window.days} days, before and after their share of overhead</p>
          <BusinessProfitChart rows={data.businesses} t={t} />
        </div>
      </div>

      <div className="card section">
        <h2>Businesses</h2>
        <p className="hint">Profit centers over the last {data.window.days} days; “vs prev.” compares with the {data.window.days} days before</p>
        <ProfitCenterTable rows={data.businesses} />
      </div>

      <div className="card section">
        <h2>Support & overhead</h2>
        <p className="hint">Headquarters and warehouses don't sell anything: they are judged on what they cost and the businesses they serve</p>
        <CostCenterTable rows={data.costCenters} totalRevenue={totalRevenue} />
      </div>
    </div>
  );
}
