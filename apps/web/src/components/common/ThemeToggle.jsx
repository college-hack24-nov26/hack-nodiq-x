import { useTheme } from '../../context/ThemeContext';
import './ThemeToggle.css';

/**
 * Accessible dark/light switch. Shows the icon of the theme you will
 * switch TO (moon in light mode, sun in dark mode) with a rotating
 * cross-fade. Announces the action, not the current state.
 */
export default function ThemeToggle({ className = '' }) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      type="button"
      className={`theme-toggle ${className}`}
      onClick={toggleTheme}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={`theme-toggle__icon ${isDark ? 'theme-toggle__icon--moon' : 'theme-toggle__icon--sun'}`}
        aria-hidden="true"
      >
        {/* Sun (visible in dark mode = click for light) */}
        <g className="theme-toggle__sun">
          <circle cx="12" cy="12" r="4" />
          <line x1="12" y1="2.5" x2="12" y2="5" />
          <line x1="12" y1="19" x2="12" y2="21.5" />
          <line x1="2.5" y1="12" x2="5" y2="12" />
          <line x1="19" y1="12" x2="21.5" y2="12" />
          <line x1="5.3" y1="5.3" x2="7" y2="7" />
          <line x1="17" y1="17" x2="18.7" y2="18.7" />
          <line x1="5.3" y1="18.7" x2="7" y2="17" />
          <line x1="17" y1="7" x2="18.7" y2="5.3" />
        </g>
        {/* Moon (visible in light mode = click for dark) */}
        <g className="theme-toggle__moon">
          <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z" />
        </g>
      </svg>
    </button>
  );
}
