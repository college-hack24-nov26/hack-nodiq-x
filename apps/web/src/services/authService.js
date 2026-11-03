/**
 * Auth Service — real backend authentication.
 *
 * Accounts live in the server's SQLite DB (bcrypt-hashed passwords).
 * Sessions use the server's HttpOnly session cookie (`nodiq_session`): the
 * auth token NEVER reaches JavaScript, is never stored in localStorage and
 * never appears in a JSON body. Only non-secret display data (the user
 * object) is cached locally for fast paint. All legacy localStorage
 * "user list" behavior is gone.
 */

import { signInWithPopup, signOut } from "firebase/auth";
import { auth, googleProvider } from "../firebase";

const USER_KEY = 'nodiq_current_user';

async function authRequest(path, body) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    throw new Error(data?.error || `Request failed (${resp.status})`);
  }
  return data;
}

/**
 * Create an account. Returns the user dict. The session cookie is set by
 * the server (HttpOnly) — nothing token-shaped is returned or stored here.
 */
export const registerUser = async ({ name, phone, email, password }) => {
  const data = await authRequest('/api/auth/signup', { name, phone, email, password });
  persistSession(data.user);
  return data.user;
};

/**
 * Authenticate against the backend. Returns the user dict.
 */
export const loginWithEmail = async (email, password) => {
  const data = await authRequest('/api/auth/login', { email, password });
  persistSession(data.user);
  return data.user;
};

function persistSession(user) {
  try {
    localStorage.setItem(USER_KEY, JSON.stringify({ ...user, updatedAt: new Date().toISOString() }));
  } catch (err) {
    console.error('Error persisting session:', err);
  }
}

/**
 * Fetch the logged-in user from the server. The HttpOnly session cookie is
 * attached automatically by the browser (same-origin). Returns null when
 * there is no valid session. Only probed when a cached session exists, so
 * logged-out visitors don't spam the API with /me calls.
 */
export const fetchCurrentUser = async () => {
  const cached = getCurrentUser();
  if (!cached) return null;
  try {
    const resp = await fetch('/api/auth/me', { credentials: 'same-origin' });
    if (resp.status === 401 || resp.status === 403) {
      // Server definitively rejected the credential — the session is dead,
      // clear it. (Logout / revoked token / expired 7-day TTL.)
      clearSession();
      return null;
    }
    if (!resp.ok) {
      // 5xx / rate-limit / proxy blip: the cookie may still be perfectly
      // valid. Logging the user out here turned every server hiccup into a
      // surprise logout ("session ends after one analysis" — the next page
      // load after a heavy run hits a busy/restarting server). Keep the
      // cached user; the next successful probe refreshes it.
      return cached;
    }
    const data = await resp.json();
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    return data.user;
  } catch {
    // Network offline / server restarting / laptop sleep-wake: same policy —
    // a transient failure must never end a session the cookie still holds.
    return cached;
  }
};

export const getCurrentUser = () => {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

export const setCurrentUser = (userData) => {
  try {
    localStorage.setItem(USER_KEY, JSON.stringify({
      ...userData,
      updatedAt: new Date().toISOString(),
    }));
  } catch (err) {
    console.error('Error setting current user:', err);
  }
};

function clearSession() {
  try {
    localStorage.removeItem(USER_KEY);
  } catch (err) {
    console.error('Error clearing session:', err);
  }
}

export const logoutUser = async () => {
  // Revoke the session SERVER-SIDE first (so a copied cookie is dead) and
  // let the server clear the HttpOnly cookie. Best-effort: local logout
  // succeeds even if the network call fails (offline logout must work).
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
    });
  } catch { /* offline: server revocation skipped, local state still cleared */ }
  // End any Firebase session too (Google login users).
  try {
    if (auth) await signOut(auth);
  } catch { /* not a firebase session or already signed out */ }
  clearSession();
};

/* Kept for backwards compatibility with existing imports. */
export const saveRememberedCredentials = (email) => {
  try {
    localStorage.setItem('nodiq_remember_email', email);
  } catch { /* ignore */ }
};
export const getRememberedEmail = () => {
  try {
    return localStorage.getItem('nodiq_remember_email');
  } catch {
    return null;
  }
};
export const clearRememberedCredentials = () => {
  try {
    localStorage.removeItem('nodiq_remember_email');
  } catch { /* ignore */ }
};

export const verifyFirebaseIdToken = async (idToken) => {
  const response = await fetch("/api/auth/firebase", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idToken }),
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || "Firebase authentication failed");
  }
  persistSession(data.user);
  return data.user;
};

/* Translate cryptic Firebase auth codes into actionable guidance. */
const FIREBASE_ERROR_MESSAGES = {
  'auth/unauthorized-domain':
    "Google sign-in isn't allowed from this address. Open the app via http://localhost:8001 " +
    "or add this domain in Firebase Console → Authentication → Settings → Authorized domains.",
  'auth/popup-blocked':
    "The browser blocked the Google sign-in popup. Allow popups for this site and try again.",
  'auth/popup-closed-by-user':
    "Google sign-in was cancelled before it finished — try again.",
  'auth/operation-not-allowed':
    "Google sign-in is not enabled for this Firebase project yet (enable the Google provider in " +
    "Firebase Console → Authentication → Sign-in method).",
  'auth/network-request-failed':
    "Network error contacting Google sign-in — check your connection and retry.",
};

export const signInWithGoogle = async () => {
  if (!auth || !googleProvider) {
    throw new Error('Google sign-in is not configured. Please use email and password.');
  }
  try {
    googleProvider.setCustomParameters({
      prompt: 'select_account',
    });
    if (auth.currentUser) {
      if (auth) await signOut(auth);
    }
    const result = await signInWithPopup(auth, googleProvider);
    const idToken = await result.user.getIdToken();
    return await verifyFirebaseIdToken(idToken);
  } catch (error) {
    console.error("Google login error:", error);
    const friendly = error?.code && FIREBASE_ERROR_MESSAGES[error.code];
    if (friendly) {
      const err = new Error(friendly);
      err.code = error.code;
      throw err;
    }
    throw error;
  }
};
