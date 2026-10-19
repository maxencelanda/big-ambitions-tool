import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Pnl as PnlData, PnlLine } from "../api";
import { CostCenterTable, ProfitCenterTable } from "../components/BusinessTables";
import { baseOption, Chart, ThemeColors, useThemeColors } from "../components/Chart";
import { money } from "../format";

const PERIOD_CHOICES = { day: [7, 14, 30, 60], week: [4, 8, 12, 26], year: [1, 2, 4] } as const;
type Granularity = keyof typeof PERIOD_CHOICES;

const SECTIONS: Record<string, string> = {
  revenue: "Businesses (profit centers)",
  overheadHeadquarters: "Overhead (cost centers)",
  healthInsurance: "Group & personal",
  allocatedHeadquarters: "Overhead allocation",
};
const OVERHEAD_KEYS = ["overheadHeadquarters", "overheadLogistics", "overheadOther"];
const ALLOCATION_KEYS = ["allocatedHeadquarters", "allocatedLogistics", "allocatedOther"];

function line(data: PnlData, key: string): PnlLine | undefined {
  return data.lines.find((l) => l.key === key);
}

function sum(data: PnlData, keys: string[]): number[] {
  return data.periods.map((_, i) => keys.reduce((s, k) => s + (line(data, k)?.values[i] ?? 0), 0));
}

function PnlChart({ data, t }: { data: PnlData; t: ThemeColors }) {
  const option = useMemo(() => {
    const group = data.scope === "group";
    const operating = line(data, "operatingProfit")?.values ?? [];
    const second = group ? sum(data, OVERHEAD_KEYS) : sum(data, ALLOCATION_KEYS);
    const third = group
      ? data.periods.map((_, i) => (line(data, "netProfit")?.values[i] ?? 0) - (line(data, "businessProfit")?.values[i] ?? 0))
      : null;
    const result = group ? line(data, "netProfit")?.values : line(data, "profitAfterOverhead")?.values;
    const radius = (v: number) => (v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4]);
    const bar = (name: string, values: number[], color: string) => ({
      name, type: "bar", stack: "pnl", barMaxWidth: 24, itemStyle: { color, borderColor: t.surface, borderWidth: 1 },
      data: values.map((v) => ({ value: Math.round(v), itemStyle: { borderRadius: radius(v) } })),
    });
    const series: object[] = [bar("Operating profit", operating, t.series1)];
    if (second.some((v) => v !== 0)) series.push(bar(group ? "Overhead" : "Allocated overhead", second, t.series2));
    if (third) series.push(bar("Group & personal", third, t.series3));
    if (result) {
      series.push({ name: group ? "Net profit" : "After overhead", type: "line", data: result.map(Math.round), symbol: "circle",
                    symbolSize: 8, lineStyle: { width: 2, color: t.text }, itemStyle: { color: t.text, borderColor: t.surface, borderWidth: 2 } });
    }
    return {
      ...baseOption(t),
      legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.secondary } },
      grid: { ...baseOption(t).grid, top: 30 },
      tooltip: { ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: t.grid, opacity: 0.4 } },
                 valueFormatter: (v: number) => money(v, { compactForm: false }) },
      xAxis: { type: "category", data: data.periods.map((p) => p.label + (p.complete ? "" : "*")), axisTick: { show: false },
               axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted, formatter: (v: number) => money(v) } },
      series,
    };
  }, [data, t]);
  return <Chart option={option} height={320} label="Profit and loss per period" />;
}

function PnlTable({ data }: { data: PnlData }) {
  return (
    <div className="table-wrap">
      <table className="pnl">
        <thead>
          <tr>
            <th>Line</th>
            {data.periods.map((p) => (
              <th key={p.key} className={`num ${p.complete ? "" : "partial"}`} title={`Days ${p.firstDay}–${p.lastDay}, ${p.daysCovered} day(s) of data`}>
                {p.label}
              </th>
            ))}
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {data.lines.map((l) => (
            <PnlRows key={l.key} line={l} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PnlRows({ line: l }: { line: PnlLine }) {
  const section = SECTIONS[l.key];
  const cell = (v: number, i?: number) => (
    <td key={i ?? "total"} className={`num ${v < -0.005 ? "neg" : ""}`}>{Math.abs(v) < 0.005 ? <span className="muted">–</span> : money(v, { compactForm: false })}</td>
  );
  return (
    <>
      {section && <tr className="section"><td colSpan={99}>{section}</td></tr>}
      <tr className={l.kind}>
        <td className={l.kind === "line" ? "indent" : undefined}>{l.label}</td>
        {l.values.map(cell)}
        {cell(l.total)}
      </tr>
    </>
  );
}

export function Pnl() {
  const [granularity, setGranularity] = useState<Granularity>("week");
  const [periods, setPeriods] = useState(8);
  const [scope, setScope] = useState("group");
  const [allocate, setAllocate] = useState(true);
  const t = useThemeColors();

  const { data, error, isLoading } = useQuery({
    queryKey: ["pnl", granularity, periods, scope, allocate],
    queryFn: () => api.pnl(granularity, periods, scope, allocate),
  });
  const { data: list } = useQuery({ queryKey: ["businesses", 7], queryFn: () => api.businesses(7) });
  const range = data && !data.empty ? { first: data.periods[0]?.firstDay, last: data.dataTo } : null;
  const { data: byBusiness } = useQuery({
    queryKey: ["pnl-businesses", range?.first, range?.last],
    queryFn: () => api.pnlBusinesses(range!.first, range!.last),
    enabled: Boolean(range && scope === "group"),
  });

  const changeGranularity = (g: Granularity) => {
    setGranularity(g);
    setPeriods(PERIOD_CHOICES[g][Math.min(1, PERIOD_CHOICES[g].length - 1)]);
  };
  const businesses = list?.businesses ?? [];
  const profitCenters = byBusiness?.businesses.filter((b) => !b.costCenter && (b.status === "active" || b.revenue)) ?? [];
  const costCenters = byBusiness?.businesses.filter((b) => b.costCenter && (b.status === "active" || b.operatingProfit)) ?? [];
  const scopeIsCostCenter = scope.startsWith("segment:headquarters") || scope.startsWith("segment:logistics")
    || businesses.some((b) => `business:${b.address}` === scope && b.costCenter);

  return (
    <div className="page">
      <h1>Profit & loss</h1>
      <p className="subtitle">
        Built from the game's daily financial summaries{data && !data.empty ? ` (days ${data.dataFrom}–${data.dataTo}; history grows with every import)` : ""}.
      </p>

      <div className="controls">
        <div className="segmented" role="group" aria-label="Granularity">
          {(Object.keys(PERIOD_CHOICES) as Granularity[]).map((g) => (
            <button key={g} className={g === granularity ? "on" : ""} onClick={() => changeGranularity(g)}>{g[0].toUpperCase() + g.slice(1)}</button>
          ))}
        </div>
        <label>Last
          <select value={periods} onChange={(e) => setPeriods(Number(e.target.value))}>
            {PERIOD_CHOICES[granularity].map((n) => <option key={n} value={n}>{n} {granularity}{n > 1 ? "s" : ""}</option>)}
          </select>
        </label>
        <label>Scope
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="group">Whole group</option>
            <optgroup label="Segments">
              <option value="segment:retail">Retail</option>
              <option value="segment:office">Office</option>
              <option value="segment:headquarters">Headquarters</option>
              <option value="segment:logistics">Warehouses</option>
            </optgroup>
            <optgroup label="Businesses">
              {businesses.map((b) => <option key={b.address} value={`business:${b.address}`}>{b.name ?? b.address}</option>)}
            </optgroup>
          </select>
        </label>
        {!scopeIsCostCenter && (
          <label className="toggle" title="Spread headquarters, warehouses and group staff costs over the businesses they serve">
            <input type="checkbox" checked={allocate} onChange={(e) => setAllocate(e.target.checked)} /> Allocate overhead
          </label>
        )}
      </div>

      {isLoading && <div className="card empty">Loading…</div>}
      {error && <div className="card empty">Could not load the P&L: {(error as Error).message}</div>}
      {data && !data.empty && (
        <>
          <div className="card">
            <h2>{scope === "group" ? "Net profit by period" : "Profit by period"}</h2>
            <p className="hint">{scope === "group" ? "Operating profit of the businesses, minus overhead and group & personal costs" : "Operating profit, and what remains after its share of overhead"}</p>
            <PnlChart data={data} t={t} />
          </div>
          <div className="card section">
            <h2>Income statement</h2>
            <p className="hint">Signed amounts: income positive, costs negative. * = period not finished yet.</p>
            <PnlTable data={data} />
            {data.reconciliationGap !== null && (
              <p className="footnote">
                Net profit matches the game's own daily total to within {money(data.reconciliationGap, { compactForm: false })}
                {data.allocated && " · Allocation: headquarters and group staff costs by headcount, each warehouse by the revenue of the businesses it supplies, the rest by revenue."}
              </p>
            )}
          </div>
          {scope === "group" && byBusiness && (
            <>
              <div className="card section">
                <h2>By business</h2>
                <p className="hint">Days {byBusiness.firstDay}–{byBusiness.lastDay}</p>
                <ProfitCenterTable rows={profitCenters} period />
              </div>
              <div className="card section">
                <h2>Cost centers</h2>
                <p className="hint">Days {byBusiness.firstDay}–{byBusiness.lastDay}; closed buildings appear while they are in the history</p>
                <CostCenterTable rows={costCenters} totalRevenue={profitCenters.reduce((s, b) => s + b.revenue, 0)} period />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
