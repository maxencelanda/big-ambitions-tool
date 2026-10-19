import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([BarChart, LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, CanvasRenderer]);

export type ThemeColors = {
  surface: string; text: string; secondary: string; muted: string; grid: string; axis: string;
  series1: string; series2: string; series3: string; series4: string; series5: string; negative: string; border: string;
};

function readTheme(): ThemeColors {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    surface: v("--surface-1"), text: v("--text-primary"), secondary: v("--text-secondary"), muted: v("--text-muted"),
    grid: v("--grid"), axis: v("--axis"), series1: v("--series-1"), series2: v("--series-2"), series3: v("--series-3"),
    series4: v("--series-4"), series5: v("--series-5"),
    negative: v("--negative"), border: v("--border"),
  };
}

/** Couleurs du thème courant ; se met à jour quand le thème clair/sombre change. */
export function useThemeColors(): ThemeColors {
  const [theme, setTheme] = useState(readTheme);
  useEffect(() => {
    const update = () => setTheme(readTheme());
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { media.removeEventListener("change", update); observer.disconnect(); };
  }, []);
  return theme;
}

/** Réglages communs : axes et grille discrets, infobulle aux couleurs du thème. */
export function baseOption(t: ThemeColors) {
  return {
    animationDuration: 300,
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: t.secondary },
    tooltip: {
      backgroundColor: t.surface, borderColor: t.border, borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 }, extraCssText: "box-shadow: 0 4px 16px rgba(0,0,0,.12); border-radius: 8px;",
    },
    grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
  };
}

export function Chart({ option, height = 260, label }: { option: echarts.EChartsCoreOption; height?: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.current?.dispose(); chart.current = null; };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={ref} className="chart" style={{ height }} role="img" aria-label={label} />;
}
