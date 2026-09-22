import React from 'react';
import { Moon, Plus, Sun } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useLocale } from '../i18n/LocaleContext';
import { useTheme } from '../theme/ThemeContext';

export function Navbar({
  activeTab,
  onSelectTab,
  currentSite,
  sites = [],
  onSelectSite,
  onOpenAddSite,
}) {
  const { user, logout } = useAuth();
  const { locale, setLocale, t } = useLocale();
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="top-nav">
      <div className="brand-section">
        <span className="brand-title">Power Fleet</span>

        {/* Site Selector Dropdown */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', borderInlineStart: '1px solid var(--border-subtle)', paddingInlineStart: '0.75rem' }}>
          <select
            className="form-select"
            style={{
              padding: '0.25rem 0.5rem',
              fontSize: '0.8125rem',
              fontWeight: 500,
              backgroundColor: 'var(--bg)',
              borderColor: 'var(--border-subtle)',
              cursor: 'pointer',
            }}
            value={currentSite?.id || ''}
            onChange={(e) => onSelectSite(e.target.value)}
          >
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="btn btn-secondary"
            onClick={onOpenAddSite}
            style={{
              padding: '0.25rem 0.5rem',
              fontSize: '0.75rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem',
            }}
            title={t('addFacilityTitle')}
          >
            <Plus size={13} />
            {t('newSite')}
          </button>
        </div>
      </div>

      <nav className="nav-links">
        <button
          type="button"
          className={`nav-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => onSelectTab('dashboard')}
        >
          {t('generators')}
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'energy' ? 'active' : ''}`}
          onClick={() => onSelectTab('energy')}
        >
          {t('energySources')}
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'schedule' ? 'active' : ''}`}
          onClick={() => onSelectTab('schedule')}
        >
          {t('schedule')}
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => onSelectTab('settings')}
        >
          {t('rules')}
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'reports' ? 'active' : ''}`}
          onClick={() => onSelectTab('reports')}
        >
          {t('reports')}
        </button>
        <>
          <button
            type="button"
            className={`nav-tab ${activeTab === 'diagnostics' ? 'active' : ''}`}
            onClick={() => onSelectTab('diagnostics')}
          >
            {t('diagnostics')}
          </button>
          <button
            type="button"
            className={`nav-tab ${activeTab === 'overrides' ? 'active' : ''}`}
            onClick={() => onSelectTab('overrides')}
          >
            {t('overrides')}
          </button>
        </>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'events' ? 'active' : ''}`}
          onClick={() => onSelectTab('events')}
        >
          {t('audit')}
        </button>
      </nav>

      <div className="user-section">
        <button
          type="button"
          className="theme-toggle"
          onClick={toggleTheme}
          title={t(theme === 'dark' ? 'switchToLight' : 'switchToDark')}
          aria-label={t(theme === 'dark' ? 'switchToLight' : 'switchToDark')}
        >
          {theme === 'dark' ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
        </button>
        <button type="button" className="logout-btn" onClick={() => setLocale(locale === 'en' ? 'ar' : 'en')} title={t('language')} aria-label={t('language')}>
          {locale === 'en' ? 'العربية' : 'English'}
        </button>
        <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
          {user?.full_name || user?.email}
        </span>
        <button
          type="button"
          className="logout-btn"
          onClick={logout}
          title={t('signOut')}
        >
          {t('signOut')}
        </button>
      </div>
    </header>
  );
}
