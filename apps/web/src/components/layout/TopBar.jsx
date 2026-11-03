import { useNavigate } from "react-router-dom";
import ThemeToggle from "../common/ThemeToggle";

function TopBar({ onMenuClick, compact = false }) {
  const navigate = useNavigate();

  const handleNotifications = () => navigate("/anomalies");
  const handleHistory = () => navigate("/analyses");
  const handleExport = () => navigate("/reports/generate");

  return (
    <header className={`topbar ${compact ? "topbar--compact" : ""}`}>
      <div className="topbar-left">
        {/* Hamburger — visible only on tablet/mobile (CSS), opens the drawer */}
        <button
          type="button"
          className="icon-button topbar-menu-button"
          onClick={onMenuClick}
          aria-label="Open navigation menu"
        >
          <span className="material-symbols-outlined">menu</span>
        </button>

        <div className="topbar-brand">NODIQ-X</div>
      </div>

      <div className="topbar-actions">
        {/* Anomalies icon matches the sidebar's destination icon */}
        <button className="icon-button" onClick={handleNotifications} title="Anomalies" aria-label="Anomalies">
          <span className="material-symbols-outlined">
            warning
          </span>
        </button>

        <button className="icon-button" onClick={handleHistory} title="Analysis history" aria-label="Analysis history">
          <span className="material-symbols-outlined">history</span>
        </button>

        <ThemeToggle className="theme-toggle--topbar" />

        <button
          type="button"
          className="topbar-export-btn secondary-button"
          onClick={handleExport}
          title="Export reports"
        >
          Export
        </button>

        <button
          type="button"
          className="topbar-new-btn primary-button"
          onClick={() => navigate('/new-analysis')}
          title="Start new analysis"
        >
          <span className="material-symbols-outlined">add</span>
          New Analysis
        </button>

        <button
          type="button"
          className="avatar topbar-avatar-btn"
          onClick={() => navigate("/profile")}
          title="Account profile"
          aria-label="Account profile"
        >
          <span className="material-symbols-outlined">account_circle</span>
        </button>
      </div>
    </header>
  );
}

export default TopBar;
