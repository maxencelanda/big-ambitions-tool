import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useServerEvents } from "./api";
import { StatusBar } from "./components/StatusBar";
import { BusinessDetail } from "./pages/BusinessDetail";
import { Businesses } from "./pages/Businesses";
import { Dashboard } from "./pages/Dashboard";
import { Market } from "./pages/Market";
import { Placeholder } from "./pages/Placeholder";
import { Pnl } from "./pages/Pnl";
import { Prices } from "./pages/Prices";
import { Recommendations } from "./pages/Recommendations";
import { Recruitment } from "./pages/Recruitment";
import { Segmentation } from "./pages/Segmentation";

type Theme = "system" | "light" | "dark";

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try { return (localStorage.getItem("theme") as Theme) || "system"; } catch { return "system"; }
  });
  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("theme", theme); } catch { /* stockage indisponible : réglage non mémorisé */ }
  }, [theme]);
  return [theme, setTheme];
}

export function App() {
  const lastEvent = useServerEvents();
  const [theme, setTheme] = useTheme();

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">Big Ambitions<small>Analytics</small></div>
        <NavLink to="/" end className="nav-link">Dashboard</NavLink>
        <NavLink to="/recommendations" className="nav-link">Recommendations</NavLink>
        <NavLink to="/pnl" className="nav-link">P&L</NavLink>
        <NavLink to="/businesses" className="nav-link">Businesses</NavLink>
        <NavLink to="/prices" className="nav-link">Prices</NavLink>
        <NavLink to="/market" className="nav-link">Market</NavLink>
        <NavLink to="/recruitment" className="nav-link">Recruitment</NavLink>
        <NavLink to="/segments" className="nav-link">Segmentation</NavLink>
        <div className="sidebar-footer">
          <label className="toggle">
            Theme
            <select value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
        </div>
      </nav>
      <div className="main">
        <StatusBar lastEvent={lastEvent} />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/pnl" element={<Pnl />} />
          <Route path="/businesses" element={<Businesses />} />
          <Route path="/businesses/:address" element={<BusinessDetail />} />
          <Route path="/prices" element={<Prices />} />
          <Route path="/market" element={<Market />} />
          <Route path="/recruitment" element={<Recruitment />} />
          <Route path="/recommendations" element={<Recommendations />} />
          <Route path="/segments" element={<Segmentation />} />
          <Route path="*" element={<Placeholder title="Not found" phase={0} about="This page does not exist." />} />
        </Routes>
      </div>
    </div>
  );
}
