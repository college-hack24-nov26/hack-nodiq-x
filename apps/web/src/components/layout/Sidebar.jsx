import { useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import "./Sidebar.css";



/* Grouped information architecture: same routes, labeled sections so the
   14 destinations scan instead of overwhelm. Collapsed (72px) rail shows
   icons only; labels appear on hover-expand. */
const navigationGroups = [
  {
    label: null,   // top-level: no heading
    items: [
      { label: "Home", icon: "home", path: "/home" },
      { label: "Dashboard", icon: "dashboard", path: "/dashboard" },
    ],
  },
  {
    label: "Analysis",
    items: [
      { label: "Cast Iron Nodularity", icon: "add_box", path: "/new-analysis" },
      { label: "Steel Grain Size", icon: "grain", path: "/steel-analysis" },
      { label: "White Cast Iron (Carbide)", icon: "category", path: "/white-cast-iron" },
      { label: "Gray Cast Iron (Flake)", icon: "blur_on", path: "/gray-cast-iron" },
      { label: "Batch Analysis", icon: "layers", path: "/batch-analysis" },
      { label: "My Analyses", icon: "inventory_2", path: "/analyses" },
      { label: "Sessions", icon: "history", path: "/sessions" },
    ],
  },
  {
    label: "Insights",
    items: [
      { label: "Analytics", icon: "analytics", path: "/analytics" },
      { label: "Compare", icon: "compare_arrows", path: "/compare" },
      { label: "Anomalies", icon: "warning", path: "/anomalies" },
      { label: "Lots", icon: "inventory", path: "/lots" },
    ],
  },
  {
    label: "Quality",
    items: [
      { label: "Review Center", icon: "rate_review", path: "/review-center" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "NODIQ Copilot", icon: "smart_toy", path: "/copilot" },
      { label: "Reports", icon: "description", path: "/reports" },
    ],
  },
  {
    label: "System",
    items: [
      { label: "Settings", icon: "settings", path: "/settings" },
      { label: "Profile", icon: "account_circle", path: "/profile" },
    ],
  },
];

const footerItems = [
  {
    label: "Support",
    icon: "help",
    path: "/copilot",
  },
];

const PIN_KEY = "nodiq-sidebar-pinned";

function Sidebar({ open = false, onNavigate }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout } = useAuth();

  /* Audit issue 12: persistent pin. Hover-expansion still works; pinning
     keeps the rail expanded without the pointer. Mobile drawer ignores it. */
  const [pinned, setPinned] = useState(() => {
    try {
      return localStorage.getItem(PIN_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(PIN_KEY, pinned ? "1" : "0");
    } catch {
      /* private mode — pin just won't persist */
    }
  }, [pinned]);

  const handleLogout = () => {
    logout();                       // clears token + user state
    navigate("/login", { replace: true });
  };

  const handleNavigation = (path) => {
    navigate(path);
    if (onNavigate) onNavigate();   // close the mobile drawer after selecting
  };

  return (
    <aside
      className={`nodiq-sidebar ${open ? "sidebar-open" : ""} ${pinned ? "sidebar-pinned" : ""
        }`}
      aria-label="Primary"
    >
      {/* Brand */}
      <div className="sidebar-brand-row">
        <div
          className="sidebar-brand"
          onClick={() => handleNavigation("/dashboard")}
        >
          <div className="sidebar-brand-icon">
            <img
              src="/nodiq-x-flame.png"
              alt="NODIQ-X"
              className="sidebar-brand-logo"
            />
          </div>
          <div className="sidebar-brand-text">
            <span className="sidebar-brand-name">NODIQ-X</span>
            <span className="sidebar-brand-subtitle">Industrial AI</span>
          </div>
        </div>

        {/* Persistent expand/collapse pin (audit issue 12) — desktop only;
            hidden in the mobile drawer where the drawer itself is the control */}
        <button
          type="button"
          className="sidebar-pin icon-button"
          onClick={() => setPinned((v) => !v)}
          aria-pressed={pinned}
          aria-label={pinned ? "Collapse sidebar" : "Expand sidebar"}
          title={pinned ? "Collapse sidebar" : "Expand sidebar"}
        >
          <span className="material-symbols-outlined" aria-hidden="true">
            {pinned ? "keyboard_double_arrow_left" : "keyboard_double_arrow_right"}
          </span>
        </button>
      </div>

      {/* Main Navigation — grouped */}
      <nav className="sidebar-navigation">
        {navigationGroups.map((group, gi) => (
          <div className="sidebar-group" key={gi}>
            {group.label && (
              <div className="sidebar-group-label mono" aria-hidden="true">
                {group.label}
              </div>
            )}
            {group.items.map((item) => (
              <button
                key={item.path}
                type="button"
                className={`sidebar-item ${location.pathname === item.path ? "active" : ""
                  }`}
                onClick={() => handleNavigation(item.path)}
                title={item.label}
              >
                <span className="material-symbols-outlined sidebar-icon">
                  {item.icon}
                </span>

                <span className="sidebar-label">{item.label}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        {footerItems.map((item) => (
          <button
            key={item.path}
            className="sidebar-item"
            onClick={() => handleNavigation(item.path)}
            title={item.label}
            aria-label={item.label}
          >
            <span className="material-symbols-outlined sidebar-icon">
              {item.icon}
            </span>

            <span className="sidebar-label">{item.label}</span>
          </button>
        ))}

        <button
          type="button"
          className="sidebar-item"
          onClick={handleLogout}
          title="Logout"
          aria-label="Logout"
        >
          <span className="material-symbols-outlined sidebar-icon">logout</span>
          <span className="sidebar-label">Logout</span>
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;