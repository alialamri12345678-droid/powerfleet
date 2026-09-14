import React, { useEffect, useState } from 'react';
import { Download, Trash2 } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

export function EventLogPage() {
  const { t, locale, formatCode, formatDate, formatTime } = useLocale();
  const [events, setEvents] = useState([]);
  const [panels, setPanels] = useState([]);
  const [filterPanel, setFilterPanel] = useState('');
  const [filterType, setFilterType] = useState('');
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [clearing, setClearing] = useState(false);
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

  function filteredUrl(path, extraParams = {}) {
    const params = new URLSearchParams();
    if (filterPanel) params.set('panel_id', filterPanel);
    if (filterType) params.set('event_type', filterType);
    Object.entries(extraParams).forEach(([key, value]) => params.set(key, value));
    const query = params.toString();
    return query ? `${path}?${query}` : path;
  }

  async function exportEvents() {
    setExporting(true);
    setError(null);
    try {
      const token = localStorage.getItem('access_token');
      const response = await fetch(filteredUrl('/api/events/export', { locale }), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error(t('auditExportFailed'));
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const date = new Date().toISOString().slice(0, 10);
      link.download = locale === 'ar' ? `سجل_التدقيق_${date}.csv` : `audit_log_${date}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setExporting(false);
    }
  }

  async function clearEvents() {
    if (!window.confirm(t('clearAuditConfirm'))) return;
    setClearing(true);
    setError(null);
    try {
      await apiRequest(filteredUrl('/events'), { method: 'DELETE' });
      await loadEvents();
    } catch (err) {
      setError(err.message);
    } finally {
      setClearing(false);
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
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button type="button" className="btn btn-secondary" onClick={exportEvents} disabled={exporting} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
            <Download size={15} /> {exporting ? t('exportingAudit') : t('exportAuditCsv')}
          </button>
          <button type="button" className="btn btn-danger" onClick={clearEvents} disabled={clearing || events.length === 0} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
            <Trash2 size={15} /> {clearing ? t('clearingAudit') : t('clearAuditLog')}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={loadEvents}
            disabled={loading}
          >
            {loading ? t('refreshing') : t('refreshLog')}
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          padding: '0.625rem 1rem',
          borderRadius: '4px',
          marginBottom: '1.5rem',
          fontSize: '0.875rem',
          backgroundColor: 'var(--danger-bg)',
          border: '1px solid var(--danger-border)',
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
        backgroundColor: 'var(--card-bg)',
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
        backgroundColor: 'var(--card-bg)',
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
