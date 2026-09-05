import React, { createContext, useContext, useState, useEffect } from 'react';
import { apiRequest } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('user_info');
    return saved ? JSON.parse(saved) : null;
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function checkAuth() {
      const token = localStorage.getItem('access_token');
      if (!token) {
        setUser(null);
        setLoading(false);
        return;
      }
      try {
        const profile = await apiRequest('/auth/me');
        const userInfo = {
          id: profile.id,
          email: profile.email,
          role: profile.role,
          site_id: profile.site_id,
          full_name: profile.full_name,
        };
        setUser(userInfo);
        localStorage.setItem('user_info', JSON.stringify(userInfo));
      } catch (err) {
        console.warn('Auth check failed:', err);
        setUser(null);
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user_info');
      } finally {
        setLoading(false);
      }
    }
    checkAuth();
  }, []);

  const login = async (email, password) => {
    const data = await apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });

    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);

    const userInfo = {
      id: data.user_id,
      role: data.role,
      site_id: data.site_id,
      full_name: data.full_name,
      email,
    };
    setUser(userInfo);
    localStorage.setItem('user_info', JSON.stringify(userInfo));
    return userInfo;
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_info');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading, isTechnician: true }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
