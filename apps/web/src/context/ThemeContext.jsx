import { createContext, useContext, useEffect, useState } from 'react';

const THEME_KEY = 'nodiq-theme';

/**
 * ThemeProvider — dark/light theme for the whole app.
 *
 * Persisted in localStorage under `nodiq-theme`; defaults to the user's
 * OS preference. The actual class is applied on <html> as
 * data-theme="dark" | "light" (see the no-flash script in index.html,
 * which runs before React mounts so there is no light/dark flicker).
 */
export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    try {
      const stored = localStorage.getItem(THEME_KEY);
      if (stored === 'light' || stored === 'dark') return stored;
    } catch {
      /* localStorage unavailable — fall through to OS preference */
    }
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    return 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore write failures (private mode) */
    }
  }, [theme]);

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'));

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

const ThemeContext = createContext(null);

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
