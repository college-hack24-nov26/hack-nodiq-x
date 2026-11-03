/*import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import "./DashboardLayout.css";

function DashboardLayout() {
  const location = useLocation();
  const isHomePage = location.pathname === "/home";

  return (
    <div className="dashboard-layout">
      <Sidebar />

      <div className="dashboard-layout-shell">
        {isHomePage && <TopBar />}

        <main
          className={`dashboard-layout-content ${
            isHomePage ? "dashboard-layout-content-home" : ""
          }`}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default DashboardLayout;*/
import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import NodiqBot from "../common/NodiqBot";
import "./DashboardLayout.css";

function DashboardLayout() {
  const location = useLocation();
  const showTopBar = location.pathname === "/home";

  // Off-canvas drawer state (tablet/mobile only — CSS handles the breakpoint)
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = () => setDrawerOpen(false);

  // Close the drawer on route change and on Escape
  useEffect(() => {
    closeDrawer();
  }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e) => e.key === "Escape" && closeDrawer();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <div className="dashboard-layout">
      <a href="#main-content" className="skip-nav-link">
        Skip to main content
      </a>
      <div
        className={`sidebar-backdrop ${drawerOpen ? "sidebar-backdrop-visible" : ""}`}
        onClick={closeDrawer}
        aria-hidden="true"
      />
      <Sidebar open={drawerOpen} onNavigate={closeDrawer} />

      <div className="dashboard-layout-shell">
        {/* Always mounted: mobile needs the hamburger on EVERY route (the
           drawer is the only navigation at <=900px). Non-home routes use the
           compact variant — hidden on desktop by CSS, shown on mobile. */}
        <TopBar
          onMenuClick={() => setDrawerOpen((v) => !v)}
          compact={!showTopBar}
        />

        <main
          id="main-content"
          className={`dashboard-layout-content ${showTopBar ? "dashboard-layout-content-home" : ""}`}
        >
          <Outlet />
        </main>
      </div>

      {/* Jarvis Voice AI Floating Companion */}
      <NodiqBot />
    </div>
  );
}

export default DashboardLayout;