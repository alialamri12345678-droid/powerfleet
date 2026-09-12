import React from 'react';
import { Plus } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';

export function Navbar({
  activeTab,
  onSelectTab,
  currentSite,
  sites = [],
  onSelectSite,
  onOpenAddSite,
}) {
  const { user, logout } = useAuth();

  return (
    <header className="top-nav">
      <div className="brand-section">
        <span className="brand-title">Power Fleet</span>

        {/* Site Selector Dropdown */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', borderLeft: '1px solid var(--border-subtle)', paddingLeft: '0.75rem' }}>
          <select
            className="form-select"
            style={{
              padding: '0.25rem 0.5rem',
              fontSize: '0.8125rem',
              fontWeight: 500,
              backgroundColor: '#FAFAF8',
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
            title="Add New Facility Site"
          >
            <Plus size={13} />
            New Site
          </button>
        </div>
      </div>

      <nav className="nav-links">
        <button
          type="button"
          className={`nav-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => onSelectTab('dashboard')}
        >
          Generators
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'schedule' ? 'active' : ''}`}
          onClick={() => onSelectTab('schedule')}
        >
          Duty Schedule
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => onSelectTab('settings')}
        >
          Rules & Thresholds
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'reports' ? 'active' : ''}`}
          onClick={() => onSelectTab('reports')}
        >
          Reports & Work Logs
        </button>
        <>
          <button
            type="button"
            className={`nav-tab ${activeTab === 'diagnostics' ? 'active' : ''}`}
            onClick={() => onSelectTab('diagnostics')}
          >
            Diagnostics
          </button>
          <button
            type="button"
            className={`nav-tab ${activeTab === 'overrides' ? 'active' : ''}`}
            onClick={() => onSelectTab('overrides')}
          >
            Overrides
          </button>
        </>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'events' ? 'active' : ''}`}
          onClick={() => onSelectTab('events')}
        >
          Audit Log
        </button>
      </nav>

      <div className="user-section">
        <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
          {user?.full_name || user?.email}
        </span>
        <button
          type="button"
          className="logout-btn"
          onClick={logout}
          title="Sign out"
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
