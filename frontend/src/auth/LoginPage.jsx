import React, { useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { useAuth } from './AuthContext';
import { useLocale } from '../i18n/LocaleContext';
import { useTheme } from '../theme/ThemeContext';

export function LoginPage({ onLoginSuccess }) {
  const { login } = useAuth();
  const { t, locale, setLocale } = useLocale();
  const { theme, toggleTheme } = useTheme();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      if (onLoginSuccess) onLoginSuccess();
    } catch (err) {
      setError(err.message || t('loginFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'var(--bg)',
      padding: '1.5rem',
    }}>
      <div style={{
        backgroundColor: 'var(--card-bg)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '4px',
        padding: '2.5rem',
        maxWidth: '420px',
        width: '100%',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.5rem', marginBottom: '0.75rem' }}>
          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={t(theme === 'dark' ? 'switchToLight' : 'switchToDark')}
            title={t(theme === 'dark' ? 'switchToLight' : 'switchToDark')}
          >
            {theme === 'dark' ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
          </button>
          <button type="button" className="logout-btn" onClick={() => setLocale(locale === 'en' ? 'ar' : 'en')} aria-label={t('language')} title={t('language')}>
            {locale === 'en' ? 'العربية' : 'English'}
          </button>
        </div>
        <div style={{ marginBottom: '1.75rem' }}>
          <h1 style={{ fontSize: '1.35rem', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
            Power Fleet
          </h1>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            {t('signInSubtitle')}
          </p>
        </div>

        {error && (
          <div style={{
            backgroundColor: 'var(--danger-bg)',
            border: '1px solid var(--danger-border)',
            color: 'var(--status-alarm)',
            padding: '0.625rem 0.875rem',
            borderRadius: '4px',
            fontSize: '0.8125rem',
            marginBottom: '1.25rem',
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="email">{t('email')}</label>
            <input
              id="email"
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@facility.com"
              required
            />
          </div>

          <div className="form-group" style={{ marginBottom: '1.5rem' }}>
            <label className="form-label" htmlFor="password">{t('password')}</label>
            <input
              id="password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', padding: '0.625rem' }}
            disabled={submitting}
          >
            {submitting ? t('signingIn') : t('signIn')}
          </button>
        </form>
      </div>
    </div>
  );
}
