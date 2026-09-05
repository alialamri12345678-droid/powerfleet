import React, { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';

export function TechDiagPage() {
  const [panels, setPanels] = useState([]);
  const [selectedPanelId, setSelectedPanelId] = useState(null);
  const [diagData, setDiagData] = useState(null);
  const [healthData, setHealthData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function loadPanels() {
      try {
        const data = await apiRequest('/panels');
        setPanels(data);
        if (data.length > 0) {
          setSelectedPanelId(data[0].id);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    loadPanels();
  }, []);

  useEffect(() => {
    if (selectedPanelId) {
      loadDiagnostics(selectedPanelId);
    }
  }, [selectedPanelId]);

  async function loadDiagnostics(panelId) {
    setRefreshing(true);
    setError(null);
    try {
      const [raw, health] = await Promise.all([
        apiRequest(`/diagnostics/panels/${panelId}/raw`),
        apiRequest(`/diagnostics/panels/${panelId}/health`),
      ]);
      setDiagData(raw);
      setHealthData(health);
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Diagnostic Telemetry</h1>
          <p className="page-subtitle">
            Raw register memory and Modbus connection diagnostics
          </p>
        </div>
        {selectedPanelId && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => loadDiagnostics(selectedPanelId)}
            disabled={refreshing}
          >
            {refreshing ? 'Reading registers...' : 'Poll Now'}
          </button>
        )}
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

      {/* Panel Selector Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
        {panels.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`btn ${selectedPanelId === p.id ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setSelectedPanelId(p.id)}
          >
            {p.name}
          </button>
        ))}
      </div>

      {/* Connection Health Overview */}
      {healthData && (
        <div style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '1.25rem',
          marginBottom: '1.5rem',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1rem',
          fontSize: '0.8125rem',
        }}>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>Transport</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }}>{healthData.transport_type.toUpperCase()} ({healthData.address})</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>Slave Unit ID</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }} className="tabular-nums">{healthData.unit_id}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>Link Health</div>
            <div style={{ fontWeight: 600, marginTop: '2px', color: healthData.is_reachable ? 'var(--status-running)' : 'var(--status-alarm)' }}>
              {healthData.is_reachable ? 'Connected' : 'Unreachable'}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>Consecutive Failures</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }} className="tabular-nums">{healthData.consecutive_errors}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>Last Successful Poll</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }} className="tabular-nums">
              {healthData.last_successful_poll ? new Date(healthData.last_successful_poll).toLocaleTimeString() : 'Never'}
            </div>
          </div>
        </div>
      )}

      {/* Raw Registers Table */}
      {diagData && diagData.registers && (
        <div style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          overflow: 'hidden',
        }}>
          <table className="data-table" style={{ border: 'none' }}>
            <thead>
              <tr>
                <th>Register Name</th>
                <th>Address</th>
                <th>Type</th>
                <th style={{ textAlign: 'right' }}>Raw Value</th>
                <th style={{ textAlign: 'right' }}>Scaled Engineering Value</th>
                <th>Unit</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(diagData.registers).map(([name, reg]) => (
                <tr key={name}>
                  <td style={{ fontWeight: 500 }}>{name}</td>
                  <td className="tabular-nums" style={{ color: 'var(--text-secondary)' }}>{reg.address}</td>
                  <td style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{reg.type}</td>
                  <td className="tabular-nums" style={{ textAlign: 'right' }}>
                    {reg.raw_value !== null ? reg.raw_value : '—'}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {reg.scaled_value !== null ? (typeof reg.scaled_value === 'number' ? reg.scaled_value.toFixed(1) : reg.scaled_value) : '—'}
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>{reg.unit || '—'}</td>
                  <td style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', maxWidth: '280px' }}>
                    {reg.description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
