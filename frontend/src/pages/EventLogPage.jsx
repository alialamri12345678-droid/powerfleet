import React, { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

export function EventLogPage() {
  const { t, formatCode, formatDate, formatTime } = useLocale();
  const [events, setEvents] = useState([]);
  const [panels, setPanels] = useState([]);
  const [filterPanel, setFilterPanel] = useState('');
  const [filterType, setFilterType] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function init() {
      try {
        const panelsData = await apiRequest('/panels');
        setPanels(panelsData);
      } catch (err) {
        console.error(err);
      }
    }
    init();
  }, []);

  useEffect(() => {
    loadEvents();
  }, [filterPanel, filterType]);

  async function loadEvents() {
    setLoading(true);
    setError(null);
    try {
      let query = '/events?limit=100';
      if (filterPanel) query += `&panel_id=${filterPanel}`;
      if (filterType) query += `&event_type=${filterType}`;
      const data = await apiRequest(query);
      setEvents(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const getPanelName = (panelId) => {
    if (!panelId) return t('siteSystem');
    const found = panels.find((p) => p.id === panelId);
    return found ? found.name : panelId;
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('auditTitle')}</h1>
          <p className="page-subtitle">
            {t('auditSubtitle')}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={loadEvents}
          disabled={loading}
        >
          {loading ? t('refreshing') : t('refreshLog')}
        </button>
      </div>

      {error && (
        <div style={{
          padding: '0.625rem 1rem',
          borderRadius: '4px',
          marginBottom: '1.5rem',
          fontSize: '0.875rem',
          backgroundColor: '#FDF2F2',
          border: '1px solid #F5C6C6',
          color: 'var(--status-alarm)',
        }}>
          {error}
        </div>
      )}

      {/* Filters */}
      <div style={{
        display: 'flex',
        gap: '1rem',
        marginBottom: '1.5rem',
        backgroundColor: '#FFFFFF',
        border: '1px solid var(--border-subtle)',
        borderRadius: '4px',
        padding: '1rem',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label htmlFor="filter-panel-select" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>{t('filterUnit')}</label>
          <select
            id="filter-panel-select"
            className="form-select"
            style={{ padding: '0.375rem 0.5rem', fontSize: '0.8125rem' }}
            value={filterPanel}
            onChange={(e) => setFilterPanel(e.target.value)}
          >
            <option value="">{t('allUnits')}</option>
            {panels.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label htmlFor="filter-type-select" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>{t('eventType')}</label>
          <select
            id="filter-type-select"
            className="form-select"
            style={{ padding: '0.375rem 0.5rem', fontSize: '0.8125rem' }}
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
          >
            <option value="">{t('allEvents')}</option><option value="command_sent">{t('commandSent')}</option>
            <option value="alarm_active">{t('alarmActive')}</option><option value="alarm_cleared">{t('alarmCleared')}</option>
            <option value="override">{t('override')}</option><option value="system">{t('systemAlert')}</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div style={{
        backgroundColor: '#FFFFFF',
        border: '1px solid var(--border-subtle)',
        borderRadius: '4px',
        overflow: 'hidden',
      }}>
        <table className="data-table" style={{ border: 'none' }}>
          <thead>
            <tr>
              <th>{t('timestamp')}</th><th>{t('generator')}</th><th>{t('event')}</th>
              <th>{t('commandValue')}</th><th>{t('triggeredBy')}</th><th>{t('reason')}</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                  {loading ? t('loadingEvents') : t('noEvents')}
                </td>
              </tr>
            ) : (
              events.map((evt) => {
                const date = new Date(evt.timestamp);
                let badgeColor = 'var(--text-secondary)';
                if (evt.event_type === 'command_sent') badgeColor = 'var(--accent-teal)';
                if (evt.event_type === 'alarm_active') badgeColor = 'var(--status-alarm)';
                if (evt.event_type === 'alarm_cleared') badgeColor = 'var(--status-running)';

                return (
                  <tr key={evt.id}>
                    <td className="tabular-nums" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                      {formatDate(date)} {formatTime(date)}
                    </td>
                    <td style={{ fontWeight: 500 }}>{getPanelName(evt.panel_id)}</td>
                    <td>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: badgeColor }}>
                        {formatCode(evt.event_type)}
                      </span>
                    </td>
                    <td className="tabular-nums" style={{ fontSize: '0.8125rem' }}>
                      {evt.command ? `${formatCode(evt.command)}: ${evt.value ? formatCode(evt.value) : t('ok')}` : (evt.value ? formatCode(evt.value) : '—')}
                    </td>
                    <td style={{ fontSize: '0.8125rem', textTransform: 'capitalize' }}>
                      {formatCode(evt.triggered_by)}
                    </td>
                    <td style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                      {evt.reason || '—'}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
