import React, { createContext, useContext, useState, useEffect } from 'react';
import { getCurrentUser, setCurrentUser, logoutUser, fetchCurrentUser } from '../services/authService';

const AuthContext = createContext();

/**
 * AuthProvider — session state backed by the real backend. The locally cached
 * user is shown immediately (fast paint), then re-validated against
 * GET /api/auth/me so stale/invalid tokens clear themselves.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => getCurrentUser());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const fresh = await fetchCurrentUser();
      if (!cancelled) {
        setUser(fresh);
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const login = (userData) => {
    setCurrentUser(userData);
    setUser(userData);
  };

  const signup = (userData) => {
    setCurrentUser(userData);
    setUser(userData);
  };

  const updateProfile = (updatedData) => {
    const mergedUser = { ...user, ...updatedData };
    setCurrentUser(mergedUser);
    setUser(mergedUser);
  };

  const logout = async () => {
    await logoutUser();   // server-side revocation + local clear
    setUser(null);
  };

  const value = {
    user,
    loading,
    login,
    signup,
    updateProfile,
    logout,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Custom hook to use auth context
 */
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
