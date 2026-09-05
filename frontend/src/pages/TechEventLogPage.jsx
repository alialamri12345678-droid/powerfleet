import React, { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';

export function TechEventLogPage() {
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
    if (!panelId) return 'Site / System';
    const found = panels.find((p) => p.id === panelId);
    return found ? found.name : panelId;
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Audit Event Log</h1>
          <p className="page-subtitle">
            Immutable append-only record of all commands, alarms, and automated decisions
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={loadEvents}
          disabled={loading}
        >
          {loading ? 'Refreshing...' : 'Refresh Log'}
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
          <label htmlFor="filter-panel-select" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>Filter Unit:</label>
          <select
            id="filter-panel-select"
            className="form-select"
            style={{ padding: '0.375rem 0.5rem', fontSize: '0.8125rem' }}
            value={filterPanel}
            onChange={(e) => setFilterPanel(e.target.value)}
          >
            <option value="">All Units</option>
            {panels.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label htmlFor="filter-type-select" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>Event Type:</label>
          <select
            id="filter-type-select"
            className="form-select"
            style={{ padding: '0.375rem 0.5rem', fontSize: '0.8125rem' }}
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
          >
            <option value="">All Events</option>
            <option value="command_sent">Command Sent</option>
            <option value="alarm_active">Alarm Active</option>
            <option value="alarm_cleared">Alarm Cleared</option>
            <option value="override">Override</option>
            <option value="system">System / Alert</option>
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
              <th>Timestamp</th>
              <th>Generator</th>
              <th>Event</th>
              <th>Command / Value</th>
              <th>Triggered By</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                  {loading ? 'Loading events...' : 'No events recorded.'}
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
                      {date.toLocaleDateString()} {date.toLocaleTimeString()}
                    </td>
                    <td style={{ fontWeight: 500 }}>{getPanelName(evt.panel_id)}</td>
                    <td>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: badgeColor }}>
                        {evt.event_type.replace('_', ' ').toUpperCase()}
                      </span>
                    </td>
                    <td className="tabular-nums" style={{ fontSize: '0.8125rem' }}>
                      {evt.command ? `${evt.command}: ${evt.value || 'OK'}` : (evt.value || '—')}
                    </td>
                    <td style={{ fontSize: '0.8125rem', textTransform: 'capitalize' }}>
                      {evt.triggered_by}
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
