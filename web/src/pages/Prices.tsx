import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, PriceHistory, PriceRow } from "../api";
import { businessLink } from "../components/BusinessTables";
import { baseOption, Chart, ThemeColors, useThemeColors } from "../components/Chart";
import { Column, SortableTable } from "../components/SortableTable";
import { money, percent } from "../format";

const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(2)}`);

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function HistoryCharts({ history, t }: { history: PriceHistory; t: ThemeColors }) {
  const series = history.series;
  const days = series.map((s) => String(s.day));
  const priceOption = useMemo(() => {
    const line = (name: string, values: (number | null | undefined)[], color: string, dashed = false) => ({
      name, type: "line", data: values.map((v) => v ?? null), connectNulls: false, symbol: "circle", symbolSize: 8,
      showSymbol: values.filter((v) => v != null).length < 4,
      lineStyle: { width: 2, color, type: dashed ? "dashed" : "solid" }, itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
    });
    return {
      ...baseOption(t),
      legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.secondary } },
      grid: { ...baseOption(t).grid, top: 30 },
      tooltip: { ...baseOption(t).tooltip, trigger: "axis", valueFormatter: (v: number) => usd(v) },
      xAxis: { type: "category", data: days, axisTick: { show: false }, axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted, formatter: (v: number) => `$${v}` } },
      series: [
        line("Average price sold", series.map((s) => s.soldPrice), t.series1),
        line("Ceiling", series.map((s) => s.ceiling), t.series2),
        line("Cheapest competitor", series.map((s) => s.minCompetitor ?? s.lowestCompetitorPrice), t.series3),
      ],
    };
  }, [series, days, t]);
  const unitsOption = useMemo(() => ({
    ...baseOption(t),
    tooltip: { ...baseOption(t).tooltip, trigger: "axis" },
    xAxis: { type: "category", data: days, axisTick: { show: false }, axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted } },
    series: [{ name: "Units sold", type: "bar", barMaxWidth: 24, itemStyle: { color: t.series1, borderRadius: [4, 4, 0, 0] },
               data: series.map((s) => s.units ?? null) }],
  }), [series, days, t]);
  return (
    <div className="grid two">
      <div><Chart option={priceOption} height={260} label="Price, ceiling and competitor price per day" /></div>
      <div>
        <p className="hint" style={{ margin: "4px 0" }}>Units sold per day</p>
        <Chart option={unitsOption} height={226} label="Units sold per day" />
      </div>
    </div>
  );
}

export function Prices() {
  const [business, setBusiness] = useState("all");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<PriceRow | null>(null);
  const t = useThemeColors();
  const { data, isLoading, error } = useQuery({ queryKey: ["prices"], queryFn: () => api.prices(7) });
  const { data: history } = useQuery({
    queryKey: ["price-history", selected?.address, selected?.item],
    queryFn: () => api.priceHistory(selected!.address, selected!.item),
    enabled: Boolean(selected),
  });

  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error || !data) return <div className="page"><div className="card empty">{(error as Error)?.message ?? "No data"}</div></div>;

  const businesses = [...new Set(data.prices.map((p) => p.business))].sort();
  const rows = data.prices.filter((p) =>
    (business === "all" || p.business === business)
    && (filter === "all"
      || (filter === "below" && p.headroom >= 0.01)
      || (filter === "above" && p.headroom <= -0.01)
      || (filter === "monopoly" && Boolean(p.monopoly))
      || (filter === "capped" && p.cappedByCompetitor)
      || (filter === "refused" && (p.refusalRate ?? 0) >= 0.1)));
  const s = data.summary;

  const columns: Column<PriceRow>[] = [
    { key: "business", label: "Business", render: (p) => businessLink({ address: p.address, name: p.business }) },
    { key: "itemLabel", label: "Product", render: (p) => (
      <><button className="linklike" onClick={() => setSelected(p)} title="Show price history">{p.itemLabel}</button>
        {p.activeEvents && <> <span className="tag">{p.activeEvents}</span></>}</>) },
    { key: "unitsPerDay", label: "Units/day", num: true },
    { key: "revenuePerDay", label: "Revenue/day", num: true, render: (p) => money(p.revenuePerDay, { compactForm: false }) },
    { key: "price", label: "Price", num: true, render: (p) => usd(p.price) },
    { key: "ceiling", label: "Ceiling", num: true, title: "Highest price every customer of the neighborhood accepts (hover: ceiling without cheaper rivals)",
      render: (p) => <span title={`Without rivals below the base price: ${usd(p.optimal)}`}>{usd(p.ceiling)}</span> },
    { key: "headroom", label: "Headroom", num: true, className: (p) => (p.headroom < -0.005 ? "neg" : undefined), render: (p) => usd(p.headroom) },
    { key: "lowestCompetitorPrice", label: "Cheapest rival", num: true,
      render: (p) => (p.lowestCompetitorPrice != null ? <span title={p.lowestCompetitor ?? ""}>{usd(p.lowestCompetitorPrice)}</span> : "—") },
    { key: "rivalSellers", label: "Rival shops", num: true, title: "Rival-owned shops stocking it: they block the monopoly" },
    { key: "monopoly", label: "", render: (p) => (p.monopoly ? <span className="tag">monopoly</span> : p.cappedByCompetitor ? <span className="tag">capped</span> : "") },
    { key: "unitMargin", label: "Unit margin", num: true, render: (p) => usd(p.unitMargin) },
    { key: "refusalRate", label: "Refused", num: true, className: (p) => ((p.refusalRate ?? 0) >= 0.1 ? "neg" : undefined), render: (p) => percent(p.refusalRate) },
    { key: "gainPerDay", label: "Gain/day", num: true, title: "Extra revenue per day at the ceiling", render: (p) => (p.gainPerDay ? money(p.gainPerDay) : "—") },
  ];

  return (
    <div className="page">
      <h1>Prices</h1>
      <p className="subtitle">Your prices against the game's acceptance ceiling (exact game formula), competitors and monopolies. Click a product for its history.</p>
      <div className="grid tiles">
        <Tile label="Products priced" value={String(s.products)} sub={`${s.atCeiling} exactly at the ceiling`} />
        <Tile label="Below ceiling" value={String(s.belowCeiling)} sub={s.gainPerDay ? `${money(s.gainPerDay)}/day left on the table` : "nothing left on the table"} />
        <Tile label="Above ceiling" value={String(s.aboveCeiling)} sub="customers refuse these" />
        <Tile label="Monopolies" value={String(s.monopolies)} sub="+30 % of base price on the ceiling" />
        <Tile label="Capped by a rival" value={String(s.cappedByCompetitor)} sub="a competitor sells below base price" />
      </div>

      {selected && history && (
        <div className="card section">
          <button className="btn" style={{ float: "right" }} onClick={() => setSelected(null)}>Close</button>
          <h2>{history.label ?? selected.itemLabel} — {selected.business}</h2>
          <p className="hint">Average price sold comes from daily sales; ceiling and competitor prices are recorded at each import, so their history grows from now on.</p>
          <HistoryCharts history={history} t={t} />
        </div>
      )}

      <div className="card section">
        <div className="controls" style={{ marginBottom: 8 }}>
          <label>Business
            <select value={business} onChange={(e) => setBusiness(e.target.value)}>
              <option value="all">All</option>
              {businesses.map((b) => <option key={b}>{b}</option>)}
            </select>
          </label>
          <label>Show
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="all">All products</option>
              <option value="below">Below ceiling</option>
              <option value="above">Above ceiling</option>
              <option value="monopoly">Monopolies</option>
              <option value="capped">Capped by a rival</option>
              <option value="refused">Price refused ≥ 10 %</option>
            </select>
          </label>
          <span className="muted">{rows.length} product(s)</span>
        </div>
        <SortableTable rows={rows} columns={columns} rowKey={(p) => `${p.address}|${p.item}`} initialSort="revenuePerDay" />
      </div>
    </div>
  );
}
