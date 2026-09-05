import React, { useEffect, useState } from 'react';
import { Download, Calendar, Activity, Zap, Clock, ShieldCheck } from 'lucide-react';
import { apiRequest } from '../api/client';

export function ReportsPage() {
  const [report, setReport] = useState(null);
  const [period, setPeriod] = useState('30d');
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadReport();
  }, [period]);

  async function loadReport() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest(`/reports/summary?period=${period}`);
      setReport(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`/api/reports/export?period=${period}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error('Failed to generate CSV export');

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const dateStr = new Date().toISOString().slice(0, 10);
      a.download = `generator_work_report_${period}_${dateStr}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      alert(err.message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Generator Work & Operations Reports</h1>
          <p className="page-subtitle">
            Operating run times, energy output, start cycles, and duty records
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          {/* Period Filter Buttons */}
          <div style={{
            display: 'flex',
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '2px',
          }}>
            {[
              { key: 'today', label: 'Today' },
              { key: '7d', label: '7 Days' },
              { key: '30d', label: '30 Days' },
              { key: 'all', label: 'All Time' },
            ].map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => setPeriod(p.key)}
                style={{
                  background: period === p.key ? 'var(--accent-teal)' : 'none',
                  color: period === p.key ? '#FFFFFF' : 'var(--text-secondary)',
                  border: 'none',
                  padding: '0.375rem 0.75rem',
                  fontSize: '0.8125rem',
                  fontWeight: period === p.key ? 600 : 500,
                  borderRadius: '3px',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {p.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={handleExportCsv}
            disabled={exporting || loading}
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          >
            <Download size={15} />
            {exporting ? 'Generating...' : 'Export Report (CSV)'}
          </button>
        </div>
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

      {/* Fleet KPI Summary Cards */}
      {report && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '1rem',
          marginBottom: '2rem',
        }}>
          <div style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '1.25rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.8125rem' }}>
              <Clock size={15} color="var(--accent-teal)" />
              <span>Fleet Operating Hours</span>
            </div>
            <div className="tabular-nums" style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.5rem' }}>
              {report.total_fleet_hours.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
              <span style={{ fontSize: '0.875rem', fontWeight: 400, color: 'var(--text-secondary)', marginLeft: '4px' }}>hrs</span>
            </div>
          </div>

          <div style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '1.25rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.8125rem' }}>
              <Zap size={15} color="var(--accent-teal)" />
              <span>Energy Delivered</span>
            </div>
            <div className="tabular-nums" style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.5rem' }}>
              {report.total_fleet_kwh >= 1000
                ? (report.total_fleet_kwh / 1000).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                : report.total_fleet_kwh.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
              <span style={{ fontSize: '0.875rem', fontWeight: 400, color: 'var(--text-secondary)', marginLeft: '4px' }}>
                {report.total_fleet_kwh >= 1000 ? 'MWh' : 'kWh'}
              </span>
            </div>
          </div>

          <div style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '1.25rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.8125rem' }}>
              <Activity size={15} color="var(--accent-teal)" />
              <span>Start Cycles</span>
            </div>
            <div className="tabular-nums" style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.5rem' }}>
              {report.total_fleet_starts}
              <span style={{ fontSize: '0.875rem', fontWeight: 400, color: 'var(--text-secondary)', marginLeft: '4px' }}>starts</span>
            </div>
          </div>

          <div style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '1.25rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.8125rem' }}>
              <ShieldCheck size={15} color="var(--status-running)" />
              <span>Fleet Availability</span>
            </div>
            <div className="tabular-nums" style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--status-running)', marginTop: '0.5rem' }}>
              {report.fleet_availability_pct}%
            </div>
          </div>
        </div>
      )}

      {/* Generator Performance Breakdown */}
      {report && (
        <div style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          overflow: 'hidden',
          marginBottom: '2rem',
        }}>
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-subtle)', fontWeight: 600 }}>
            Generator Work & Utilization Breakdown
          </div>
          <table className="data-table" style={{ border: 'none' }}>
            <thead>
              <tr>
                <th>Generator Unit</th>
                <th>Capacity</th>
                <th>Run State</th>
                <th style={{ textAlign: 'right' }}>Operating Hours</th>
                <th style={{ textAlign: 'right' }}>Energy (kWh)</th>
                <th style={{ textAlign: 'right' }}>Starts</th>
                <th style={{ textAlign: 'right' }}>Avg Load %</th>
                <th style={{ textAlign: 'right' }}>Peak Load %</th>
                <th style={{ textAlign: 'right' }}>Faults</th>
              </tr>
            </thead>
            <tbody>
              {report.generators.map((g) => (
                <tr key={g.panel_id}>
                  <td style={{ fontWeight: 600 }}>{g.name}</td>
                  <td className="tabular-nums" style={{ color: 'var(--text-secondary)' }}>{g.rated_kw} kW</td>
                  <td>
                    <span style={{
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      color: g.current_status === 'Running' ? 'var(--status-running)' : 'var(--text-secondary)',
                    }}>
                      {g.current_status}
                    </span>
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'right', fontWeight: 500 }}>
                    {g.run_hours.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'right' }}>
                    {Math.round(g.total_kwh).toLocaleString('en-US')}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'right' }}>
                    {g.number_of_starts}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'right' }}>
                    {g.avg_load_pct > 0 ? `${g.avg_load_pct}%` : '—'}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'right' }}>
                    {g.peak_load_pct > 0 ? `${g.peak_load_pct}%` : '—'}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'right', color: g.alarm_count > 0 ? 'var(--status-alarm)' : 'var(--text-secondary)' }}>
                    {g.alarm_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Operational Work Log */}
      {report && (
        <div style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          overflow: 'hidden',
        }}>
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-subtle)', fontWeight: 600 }}>
            Recent Duty & Work Events ({period.toUpperCase()})
          </div>
          <table className="data-table" style={{ border: 'none' }}>
            <thead>
              <tr>
                <th>Timestamp (UTC)</th>
                <th>Unit</th>
                <th>Action</th>
                <th>Command / Status</th>
                <th>Trigger Source</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {report.recent_sessions.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                    No events recorded in this period.
                  </td>
                </tr>
              ) : (
                report.recent_sessions.map((s) => (
                  <tr key={s.id}>
                    <td className="tabular-nums" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                      {new Date(s.timestamp).toLocaleDateString()} {new Date(s.timestamp).toLocaleTimeString()}
                    </td>
                    <td style={{ fontWeight: 500 }}>{s.panel_name}</td>
                    <td>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-teal)' }}>
                        {s.event_type.replace('_', ' ').toUpperCase()}
                      </span>
                    </td>
                    <td className="tabular-nums" style={{ fontSize: '0.8125rem' }}>
                      {s.command ? `${s.command}: ${s.value || 'OK'}` : (s.value || '—')}
                    </td>
                    <td style={{ fontSize: '0.8125rem', textTransform: 'capitalize' }}>
                      {s.triggered_by}
                    </td>
                    <td style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                      {s.reason || '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
