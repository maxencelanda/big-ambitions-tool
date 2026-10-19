import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, SegBusiness, SegGap, Segmentation as SegData } from "../api";
import { businessLink } from "../components/BusinessTables";
import { baseOption, Chart, ThemeColors, useThemeColors } from "../components/Chart";
import { Column, SortableTable } from "../components/SortableTable";
import { money, percent } from "../format";
import { WindowSelect } from "./Dashboard";

const PERCENT_KEYS = new Set(["margin", "cogsRatio", "payrollRatio", "rentRatio", "marketingRatio", "idleShare",
  "priceVsCeiling", "monopolyShare", "refusalRate", "trend"]);
const MONEY_KEYS = new Set(["profitPerDay", "revenuePerDay", "profitPerEmployee", "revenuePerCustomer", "profitPerSqm"]);

function fmt(key: string, v: number | null | undefined): string {
  if (v == null) return "—";
  if (PERCENT_KEYS.has(key)) return percent(v);
  if (MONEY_KEYS.has(key)) return Math.abs(v) >= 10 ? money(v) : `$${v.toFixed(2)}`;
  if (key.startsWith("sat")) return String(Math.round(v));
  return Math.abs(v) < 100 ? v.toFixed(1) : Math.round(v).toLocaleString("en-US");
}

const groupColor = (t: ThemeColors, g: number) => [t.series1, t.series2, t.series3, t.series4, t.series5][g % 5];

function structure(s: number | null): { label: string; help: string } {
  if (s == null) return { label: "—", help: "" };
  if (s < 0.25) return { label: "weak", help: "Groups overlap: read them as tendencies, not categories." };
  if (s < 0.5) return { label: "reasonable", help: "Groups are distinct but some businesses sit between two." };
  return { label: "strong", help: "Groups are clearly separated." };
}

function GroupDot({ group, t }: { group: number; t: ThemeColors }) {
  return <span className="dot" style={{ background: groupColor(t, group), display: "inline-block", marginRight: 6 }} />;
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function MapChart({ data, t }: { data: SegData; t: ThemeColors }) {
  const [x, y] = [data.axes[0], data.axes[1]];
  const option = useMemo(() => ({
    ...baseOption(t),
    grid: { left: 8, right: 96, top: 24, bottom: 32, containLabel: true },
    tooltip: {
      ...baseOption(t).tooltip, trigger: "item",
      formatter: (p: { data: { b: SegBusiness } }) => {
        const b = p.data.b;
        const g = data.groups[b.group];
        return `<b>${b.name}</b> · ${b.typeLabel}<br/>${g ? g.name : ""}${b.supplementary ? " (projected, too new)" : ""}`
          + `<br/>Profit/day ${fmt("profitPerDay", b.values.profitPerDay)} · margin ${fmt("margin", b.values.margin)}`
          + `<br/>Wages ${fmt("payrollRatio", b.values.payrollRatio)} of revenue · idle ${fmt("idleShare", b.values.idleShare)}`;
      },
    },
    xAxis: {
      type: "value", name: `Axis 1 (${percent(x.variance)}) →`, nameLocation: "middle", nameGap: 12,
      nameTextStyle: { color: t.muted, fontSize: 11 }, axisLabel: { show: false },
      splitLine: { lineStyle: { color: t.grid } }, axisLine: { lineStyle: { color: t.axis } },
    },
    yAxis: {
      type: "value", name: `↑ Axis 2 (${percent(y.variance)})`, nameTextStyle: { color: t.muted, fontSize: 11, align: "left" },
      axisLabel: { show: false }, splitLine: { lineStyle: { color: t.grid } }, axisLine: { lineStyle: { color: t.axis } },
    },
    series: data.groups.map((g) => ({
      type: "scatter", name: g.name, symbolSize: 14,
      data: data.businesses.filter((b) => b.group === g.id).map((b) => ({
        value: [b.coords[0], b.coords[1]], b,
        itemStyle: b.supplementary
          ? { color: t.surface, borderColor: groupColor(t, g.id), borderWidth: 2 }
          : { color: groupColor(t, g.id), borderColor: t.surface, borderWidth: 2 },
      })),
      label: { show: true, position: "right", formatter: (p: { data: { b: SegBusiness } }) => p.data.b.name, color: t.secondary, fontSize: 11 },
      labelLayout: { hideOverlap: true },
      emphasis: { scale: 1.3 },
    })),
  }), [data, t, x, y]);
  return <Chart option={option} height={380} label="Businesses on the first two axes of the PCA, colored by group" />;
}

function Groups({ data, t }: { data: SegData; t: ThemeColors }) {
  return (
    <div className="seg-groups">
      {data.groups.map((g) => (
        <div key={g.id} className="card seg-group">
          <div className="seg-group-head">
            <span><GroupDot group={g.id} t={t} /><b>{g.name}</b></span>
            {g.best && <span className="tag">{data.groups.length > 1 && g.performance - data.groups[1].performance < 0.3 ? "slightly more profitable" : "most profitable"}</span>}
          </div>
          <div className="muted">
            {data.businesses.filter((b) => b.group === g.id).map((b) => b.name + (b.supplementary ? "*" : "")).join(", ")}
          </div>
          <div className="seg-kpis">
            <span>Profitability <b>{g.performance > 0 ? "+" : ""}{g.performance.toFixed(2)}</b> sd</span>
            <span>Margin <b>{fmt("margin", g.means.margin)}</b></span>
            <span>Wages <b>{fmt("payrollRatio", g.means.payrollRatio)}</b></span>
            <span>Profit <b>{money(g.profitPerDay)}</b>/day</span>
          </div>
          {g.distinctive.length > 0 && (
            <table className="seg-mini">
              <thead><tr><th>Stands out on</th><th className="num">Group</th><th className="num">All</th><th className="num" title="Value-test: beyond ±2 the difference is unlikely to be chance">v-test</th></tr></thead>
              <tbody>
                {g.distinctive.map((d) => (
                  <tr key={d.key}>
                    <td>{d.label}</td>
                    <td className="num">{fmt(d.key, d.groupValue)}</td>
                    <td className="num muted">{fmt(d.key, d.overallValue)}</td>
                    <td className="num">{d.valueTest > 0 ? "+" : ""}{d.valueTest.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  );
}

type ActionRow = SegGap & { business: SegBusiness };

function Actions({ data }: { data: SegData }) {
  const rows: ActionRow[] = data.businesses.flatMap((b) => b.gaps.map((g) => ({ ...g, business: b })));
  const columns: Column<ActionRow>[] = [
    { key: "business", label: "Business", value: (r) => r.business.name, render: (r) => businessLink(r.business) },
    { key: "label", label: "Lever" },
    { key: "value", label: "Yours", num: true, render: (r) => fmt(r.key, r.value) },
    { key: "peerValue", label: "Better peers", num: true, title: "Median of the more profitable businesses with the same model", render: (r) => fmt(r.key, r.peerValue) },
    { key: "gapSd", label: "Gap", num: true, title: "In standard deviations, after centering by business model", render: (r) => r.gapSd.toFixed(1) },
    { key: "gainPerDay", label: "Gain", num: true, title: "If this lever matched your better peers, revenue unchanged", render: (r) => (r.gainPerDay ? `+${money(r.gainPerDay)}/day` : "") },
    { key: "action", label: "Action", render: (r) => <span className="muted">{r.action}</span> },
  ];
  return (
    <div className="card">
      <h2>What to change, by comparison with better peers</h2>
      <p className="hint">
        Each business is compared with the more profitable half of its peers (same model: office, shop or service shop).
        Only levers you control are listed, when the gap exceeds half a standard deviation. Wages and idle hours overlap: do not add them up.
      </p>
      {rows.length ? <SortableTable rows={rows} columns={columns} rowKey={(r) => `${r.business.address}|${r.key}`} initialSort="gainPerDay" />
        : <p className="muted">No business lags its peers on a lever you control.</p>}
    </div>
  );
}

function Businesses({ data, t }: { data: SegData; t: ThemeColors }) {
  const columns: Column<SegBusiness>[] = [
    { key: "name", label: "Business", render: (b) => <>{businessLink(b)}{b.supplementary && <span className="muted" title={`Opened day ${b.creationDay}: projected, not used to build the groups`}> · too new</span>}</> },
    { key: "modelLabel", label: "Compared with", render: (b) => <span className="muted">{b.modelLabel}</span> },
    { key: "group", label: "Group", render: (b) => <><GroupDot group={b.group} t={t} />{data.groups[b.group]?.name}</> },
    { key: "silhouette", label: "Fit", num: true, title: "Silhouette: 1 = clearly in its group, 0 = between two groups, < 0 = closer to another group",
      render: (b) => (b.silhouette == null ? "—" : <span className={b.silhouette < 0 ? "neg" : undefined}>{b.silhouette.toFixed(2)}</span>) },
    { key: "performance", label: "Profitability", num: true, title: "Mean of margin, profit per day, per employee and per m², in standard deviations within the business model",
      render: (b) => <span className={b.performance < 0 ? "neg" : undefined}>{b.performance > 0 ? "+" : ""}{b.performance.toFixed(2)}</span> },
    { key: "profitPerDay", label: "Profit/day", num: true, value: (b) => b.values.profitPerDay, render: (b) => money(b.values.profitPerDay) },
    { key: "margin", label: "Margin", num: true, value: (b) => b.values.margin, render: (b) => fmt("margin", b.values.margin) },
    { key: "payrollRatio", label: "Wages", num: true, value: (b) => b.values.payrollRatio, render: (b) => fmt("payrollRatio", b.values.payrollRatio) },
    { key: "idleShare", label: "Idle", num: true, value: (b) => b.values.idleShare, render: (b) => fmt("idleShare", b.values.idleShare) },
    { key: "trend", label: "Trend", num: true, value: (b) => b.values.trend, title: "Change in daily profit over the window (robust slope), as a share of daily revenue",
      render: (b) => {
        const v = b.values.trend == null ? null : Math.round(b.values.trend * 100) / 100;
        return v == null ? "—" : <span className={v < 0 ? "neg" : undefined}>{v > 0 ? "+" : ""}{percent(v === 0 ? 0 : v)}</span>;
      } },
    { key: "peers", label: "Benchmarked against", value: (b) => b.peers.length,
      render: (b) => (b.peers.length ? <span className="muted">{b.peers.join(", ")}</span> : <span className="tag">best of its model</span>) },
  ];
  return (
    <div className="card">
      <h2>Businesses</h2>
      <SortableTable rows={data.businesses} columns={columns} rowKey={(b) => b.address} initialSort="performance" />
    </div>
  );
}

function Axes({ data }: { data: SegData }) {
  const kept = data.axes.filter((a) => a.kept);
  const rows = kept[0].loadings.map((l, j) => ({ ...l, byAxis: kept.map((a) => a.loadings[j]) }));
  type Row = (typeof rows)[number];
  const columns: Column<Row>[] = [
    { key: "label", label: "Variable", render: (r) => (r.supplementary ? <i title="Outcome: projected on the axes, does not shape them">{r.label}</i> : r.label) },
    ...kept.map((a, i): Column<Row> => ({
      key: `axis${a.index}`, label: `Axis ${a.index} · ${percent(a.variance)}`, num: true,
      value: (r) => Math.abs(r.byAxis[i].correlation),
      render: (r) => {
        const c = r.byAxis[i].correlation;
        return <span className={Math.abs(c) >= 0.5 ? undefined : "muted"} style={{ fontWeight: Math.abs(c) >= 0.5 ? 600 : undefined }}>{c > 0 ? "+" : ""}{c.toFixed(2)}</span>;
      },
    })),
  ];
  return (
    <div className="card">
      <h2>Axes</h2>
      <p className="hint">
        {kept.length} axes keep {percent(data.varianceKept)} of the variance. Correlation of each variable with each axis
        (bold beyond ±0.5). Outcomes in <i>italics</i> are projected: they show which profile goes with profit.
      </p>
      <ul className="seg-axes">{kept.map((a) => <li key={a.index}><b>Axis {a.index}</b>: {a.name}</li>)}</ul>
      <SortableTable rows={rows} columns={columns} rowKey={(r) => r.key} initialSort="axis1" />
    </div>
  );
}

function History({ data, t }: { data: SegData; t: ThemeColors }) {
  if (data.history.length < 2) return null;
  const names = Object.fromEntries(data.businesses.map((b) => [b.address, b.name]));
  const addresses = data.businesses.map((b) => b.address);
  const moved = addresses.filter((a) => new Set(data.history.map((h) => h.groups[a]).filter((g) => g != null)).size > 1);
  return (
    <div className="card">
      <h2>Group over time</h2>
      <p className="hint">
        Each past {data.window}-day window, projected on today's model so groups are comparable. {moved.length
          ? `${moved.length} business(es) changed group: ${moved.map((a) => names[a]).join(", ")}.` : "No business changed group."}
        {data.history.some((h) => h.approximate) && " Windows marked * predate the first satisfaction snapshot and reuse it."}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Business</th>{data.history.map((h) => <th key={h.day} className="num">Day {h.day}{h.approximate ? "*" : ""}</th>)}</tr>
          </thead>
          <tbody>
            {addresses.map((a) => (
              <tr key={a}>
                <td>{names[a]}</td>
                {data.history.map((h) => (
                  <td key={h.day} className="num">
                    {h.groups[a] == null ? <span className="muted">—</span>
                      : <span title={data.groups[h.groups[a]]?.name}><GroupDot group={h.groups[a]} t={t} />{h.groups[a] + 1}</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Method({ data }: { data: SegData }) {
  const label = Object.fromEntries(data.variables.map((v) => [v.key, v.label]));
  return (
    <div className="card">
      <h2>Method</h2>
      <ol className="seg-method">
        <li>Each profit center open for at least {data.window} days is described over days {data.firstDay}–{data.lastDay}.
          Variables are centered within their business model (office, shop, service shop) and scaled.</li>
        <li>PCA on the levers ({data.variables.filter((v) => v.used && !v.supplementary).map((v) => v.label.toLowerCase()).join(", ")}).
          Outcomes ({data.variables.filter((v) => v.supplementary).map((v) => v.label.toLowerCase()).join(", ")}) are projected.</li>
        <li>Ward clustering on the {data.axesKept} kept axes. Number of groups: best silhouette, without single-business groups
          ({data.kChoices.map((c) => `${c.k} groups: ${c.silhouette.toFixed(2)}${c.smallestGroup < 2 ? " (one alone)" : ""}`).join(" · ")}).</li>
        <li>Groups are ranked by mean profitability and named after their most distinctive variables (value-tests).</li>
      </ol>
      {data.dropped.length > 0 && <p className="muted">Not used (same value everywhere): {data.dropped.map((k) => label[k]).join(", ")}.</p>}
      <p className="muted">
        With {data.sampleSize} businesses, groups are fragile: use them to prioritise, together with the attention points and recommendations, not to decide alone.
      </p>
    </div>
  );
}

export function Segmentation() {
  const [window, setWindow] = useState(14);
  const t = useThemeColors();
  const { data, isLoading, error } = useQuery({ queryKey: ["segmentation", window], queryFn: () => api.segmentation(window) });
  if (isLoading) return <div className="page"><div className="card empty">Loading…</div></div>;
  if (error || !data || data.empty) return <div className="page"><div className="card empty">{(error as Error)?.message ?? data?.reason ?? "No data"}</div></div>;
  const quality = structure(data.silhouette);
  const best = data.groups.find((g) => g.best);
  const gain = data.businesses.reduce((sum, b) => sum + Math.max(0, ...b.gaps.map((g) => g.gainPerDay ?? 0)), 0);

  return (
    <div className="page">
      <h1>Segmentation</h1>
      <p className="subtitle">PCA + Ward clustering of your profit centers · days {data.firstDay}–{data.lastDay} · <WindowSelect value={window} onChange={setWindow} /></p>
      <div className="grid tiles">
        <Tile label="Businesses" value={String(data.sampleSize)} sub={data.businesses.some((b) => b.supplementary) ? "+ projected new ones (*)" : "open for the whole window"} />
        <Tile label="Groups" value={String(data.groupsCount)} sub={`structure ${quality.label} (silhouette ${data.silhouette?.toFixed(2) ?? "—"})`} />
        <Tile label="Variance kept" value={percent(data.varianceKept)} sub={`${data.axesKept} axes`} />
        <Tile label="Most profitable profile" value={best ? `+${best.performance.toFixed(2)} sd` : "—"} sub={best ? `${best.name} (${best.size})` : undefined} />
        <Tile label="Largest gap per business" value={`+${money(gain)}/day`} sub="sum of each business's biggest quantified gap" />
      </div>
      {quality.help && <p className="hint">{quality.help}</p>}

      <div className="grid two section">
        <div className="card">
          <h2>Map</h2>
          <p className="hint">
            Close points run in a similar way. Hollow markers: too new, projected.<br />
            Axis 1 → {data.axes[0].name} · Axis 2 ↑ {data.axes[1].name}
          </p>
          <MapChart data={data} t={t} />
        </div>
        <Groups data={data} t={t} />
      </div>
      <div className="section"><Actions data={data} /></div>
      <div className="section"><Businesses data={data} t={t} /></div>
      <div className="section"><History data={data} t={t} /></div>
      <div className="grid two section">
        <Axes data={data} />
        <Method data={data} />
      </div>
    </div>
  );
}
