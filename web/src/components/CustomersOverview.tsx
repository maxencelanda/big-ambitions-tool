import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CustomersData } from "../api";
import { businessLink } from "./BusinessTables";
import { baseOption, Chart, ThemeColors, useThemeColors } from "./Chart";
import { change, signedPercent } from "../format";

type BusinessSeries = CustomersData["businesses"][number];

/** Petit graphique par commerce : même axe des jours pour tous, échelle propre à chacun. */
function Sparkline({ b, days, t }: { b: BusinessSeries; days: number[]; t: ThemeColors }) {
  const option = useMemo(() => {
    const byDay = new Map(b.series.map((p) => [p.day, p.customers]));
    return {
      ...baseOption(t),
      grid: { left: 2, right: 2, top: 6, bottom: 2, containLabel: false },
      tooltip: { ...baseOption(t).tooltip, trigger: "axis", formatter: (items: { name: string; value: number | null }[]) =>
        `Day ${items[0].name}: ${items[0].value ?? "—"} customers` },
      xAxis: { type: "category", data: days.map(String), show: false, boundaryGap: false },
      yAxis: { type: "value", show: false, min: 0 },
      series: [{ type: "line", data: days.map((d) => byDay.get(d) ?? null), showSymbol: false, symbolSize: 8,
                 lineStyle: { width: 2, color: t.series1 }, itemStyle: { color: t.series1 }, areaStyle: { color: t.series1, opacity: 0.1 } }],
    };
  }, [b, days, t]);
  return <Chart option={option} height={64} label={`Customers per day, ${b.name}`} />;
}

function TotalChart({ data, t }: { data: CustomersData; t: ThemeColors }) {
  const option = useMemo(() => ({
    ...baseOption(t),
    tooltip: { ...baseOption(t).tooltip, trigger: "axis" },
    xAxis: { type: "category", data: data.total.map((p) => String(p.day)), axisTick: { show: false },
             axisLine: { lineStyle: { color: t.axis } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.muted } },
    series: [{ name: "Customers", type: "bar", barMaxWidth: 24, itemStyle: { color: t.series1, borderRadius: [4, 4, 0, 0] },
               data: data.total.map((p) => p.customers) }],
  }), [data, t]);
  return <Chart option={option} height={200} label="Customers per day, all businesses" />;
}

export function CustomersOverview() {
  const t = useThemeColors();
  const { data } = useQuery({ queryKey: ["customers", 60], queryFn: () => api.customers(60) });
  if (!data || data.empty) return null;
  const days = data.total.map((p) => p.day);
  return (
    <div className="card section">
      <h2>Customers per day</h2>
      <p className="hint">Days {data.firstDay}–{data.lastDay}. The game keeps about 16 days of sales; the history grows with every import.</p>
      <TotalChart data={data} t={t} />
      <div className="spark-grid">
        {data.businesses.map((b) => {
          const delta = change(b.avg7, b.avgPrev7);
          return (
            <div key={b.address} className="spark">
              <div className="spark-head">
                <span>{businessLink(b)}</span>
                <span><b>{b.avg7 ?? "—"}</b>/day{" "}
                  {delta !== null && <span className={`delta ${delta >= 0 ? "up" : "down"}`}>{signedPercent(delta)}</span>}</span>
              </div>
              <Sparkline b={b} days={days} t={t} />
            </div>
          );
        })}
      </div>
      <p className="footnote">Average over the last 7 days, change vs the 7 days before. Each mini chart has its own scale.</p>
    </div>
  );
}
