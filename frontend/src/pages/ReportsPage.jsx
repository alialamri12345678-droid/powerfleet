import React, { useEffect, useState } from 'react';
import { Download, Activity, Zap, Clock, ShieldCheck, Wrench, AlertTriangle } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

export function ReportsPage() {
  const { t, translateText, formatCode, formatNumber, formatDate, formatTime } = useLocale();
  const [report, setReport] = useState(null);
  const [period, setPeriod] = useState('30d');
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);
  const [maintenance, setMaintenance] = useState(null);
  const [maintenanceLoading, setMaintenanceLoading] = useState(null);

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
      if (!res.ok) throw new Error(t('exportFailed'));

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

  const loadMaintenance = async (panelId) => {
    setMaintenanceLoading(panelId);
    try {
      setMaintenance(await apiRequest(`/reports/preventive-maintenance/${panelId}?period=${period}`));
    } catch (err) {
      alert(err.message);
    } finally {
      setMaintenanceLoading(null);
    }
  };

  const exportMaintenance = async (panelId, generatorName) => {
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`/api/reports/preventive-maintenance/${panelId}/export?period=${period}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(t('maintenanceExportFailed'));
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${generatorName.replace(/[^a-z0-9]+/gi, '_').toLowerCase()}_preventive_maintenance.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(err.message);
    }
  };

  const recordMaintenance = async () => {
    const serviceDate = window.prompt(t('serviceDatePrompt'), new Date().toISOString().slice(0, 10));
    if (!serviceDate) return;
    const hours = window.prompt(t('serviceHoursPrompt'), maintenance.service.current_run_hours);
    if (hours === null || Number.isNaN(Number(hours))) return;
    const performedBy = window.prompt(t('serviceByPrompt'), '') || null;
    const notes = window.prompt(t('serviceNotesPrompt'), '') || null;
    try {
      await apiRequest(`/reports/preventive-maintenance/${maintenance.panel_id}/records`, {
        method: 'POST',
        body: JSON.stringify({ service_date: serviceDate, run_hours: Number(hours), service_type: t('routineService'), performed_by: performedBy, notes }),
      });
      await loadMaintenance(maintenance.panel_id);
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('reportsTitle')}</h1>
          <p className="page-subtitle">
            {t('reportsSubtitle')}
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
              { key: 'today', label: t('today') }, { key: '7d', label: t('sevenDays') },
              { key: '30d', label: t('thirtyDays') }, { key: 'all', label: t('allTime') },
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
            {exporting ? t('generating') : t('exportCsv')}
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
              <span>{t('fleetHours')}</span>
            </div>
            <div className="tabular-nums" style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.5rem' }}>
              {formatNumber(report.total_fleet_hours, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
              <span style={{ fontSize: '0.875rem', fontWeight: 400, color: 'var(--text-secondary)', marginInlineStart: '4px' }}>{t('hoursShort')}</span>
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
              <span>{t('energyDelivered')}</span>
            </div>
            <div className="tabular-nums" style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.5rem' }}>
              {report.total_fleet_kwh >= 1000
                ? formatNumber(report.total_fleet_kwh / 1000, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                : formatNumber(report.total_fleet_kwh, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
              <span style={{ fontSize: '0.875rem', fontWeight: 400, color: 'var(--text-secondary)', marginInlineStart: '4px' }}>
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
              <span>{t('startCycles')}</span>
            </div>
            <div className="tabular-nums" style={{ fontSize: '1.65rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.5rem' }}>
              {report.total_fleet_starts}
              <span style={{ fontSize: '0.875rem', fontWeight: 400, color: 'var(--text-secondary)', marginInlineStart: '4px' }}>{t('starts')}</span>
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
              <span>{t('fleetAvailability')}</span>
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
            {t('utilizationBreakdown')}
          </div>
          <table className="data-table" style={{ border: 'none' }}>
            <thead>
              <tr>
                <th>{t('generatorUnit')}</th><th>{t('capacityLabel')}</th><th>{t('runState')}</th>
                <th style={{ textAlign: 'end' }}>{t('operatingHours')}</th><th style={{ textAlign: 'end' }}>{t('energyKwh')}</th>
                <th style={{ textAlign: 'end' }}>{t('starts')}</th><th style={{ textAlign: 'end' }}>{t('avgLoad')}</th>
                <th style={{ textAlign: 'end' }}>{t('peakLoad')}</th><th style={{ textAlign: 'end' }}>{t('faults')}</th><th>{t('maintenance')}</th>
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
                      {formatCode(g.current_status || 'unknown')}
                    </span>
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'end', fontWeight: 500 }}>
                    {formatNumber(g.run_hours, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'end' }}>
                    {formatNumber(Math.round(g.total_kwh))}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'end' }}>
                    {g.number_of_starts}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'end' }}>
                    {g.avg_load_pct > 0 ? `${g.avg_load_pct}%` : '—'}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'end' }}>
                    {g.peak_load_pct > 0 ? `${g.peak_load_pct}%` : '—'}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'end', color: g.alarm_count > 0 ? 'var(--status-alarm)' : 'var(--text-secondary)' }}>
                    {g.alarm_count}
                  </td>
                  <td>
                    <button type="button" className="btn btn-secondary" onClick={() => loadMaintenance(g.panel_id)} disabled={maintenanceLoading === g.panel_id} style={{ fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                      {maintenanceLoading === g.panel_id ? t('analyzing') : t('viewReport')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {maintenance && (
        <div style={{ background: '#FFFFFF', border: '1px solid var(--border-subtle)', borderRadius: '4px', padding: '1.25rem', marginBottom: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
            <div>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontWeight: 600 }}><Wrench size={17} /> {t('preventiveMaintenance')} — {maintenance.generator_name}</div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem', marginTop: '0.3rem' }}>
                {t('basedOnReadings', { count: formatNumber(maintenance.sample_count), period: period.toUpperCase() })}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button type="button" className="btn btn-secondary" onClick={recordMaintenance}>{t('recordService')}</button>
              <button type="button" className="btn btn-primary" onClick={() => exportMaintenance(maintenance.panel_id, maintenance.generator_name)} style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                <Download size={15} /> {t('exportThisReport')}
              </button>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: '1rem', marginBottom: '1.25rem' }}>
            <div style={{ padding: '1rem', background: '#FAF9F7', borderRadius: '4px', textAlign: 'center' }}>
              <div style={{ fontSize: '2rem', fontWeight: 700, color: maintenance.condition_score >= 80 ? 'var(--status-running)' : 'var(--status-warning)' }}>{maintenance.condition_score}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{t('conditionScore')}</div>
            </div>
            <div style={{ padding: '1rem', background: '#FAF9F7', borderRadius: '4px' }}>
              <strong>{translateText(maintenance.condition)}</strong>
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                {t('nextService', { next: formatNumber(maintenance.service.next_service_hours), remaining: formatNumber(maintenance.service.hours_remaining) })}
              </div>
            </div>
          </div>
          {maintenance.findings.length === 0 ? (
            <div style={{ padding: '0.9rem', background: '#EDF7F2', color: 'var(--status-running)', borderRadius: '4px' }}>{t('noWarning')}</div>
          ) : maintenance.findings.map((finding, index) => (
            <div key={`${finding.metric}-${index}`} style={{ display: 'grid', gridTemplateColumns: '24px 1fr', gap: '0.75rem', padding: '0.9rem 0', borderTop: '1px solid var(--border-subtle)' }}>
              <AlertTriangle size={18} color={finding.severity === 'critical' ? 'var(--status-alarm)' : 'var(--status-warning)'} />
              <div>
                <strong>{translateText(finding.title)}</strong>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem', marginTop: '0.2rem' }}>{translateText(finding.detail)}</div>
                <div style={{ fontSize: '0.8125rem', marginTop: '0.35rem' }}>{t('recommendedAction')} {translateText(finding.recommendation)}</div>
              </div>
            </div>
          ))}
          <div style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem', marginTop: '1rem' }}>{translateText(maintenance.limitations[0])}</div>
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
            {t('recentEvents', { period: period.toUpperCase() })}
          </div>
          <table className="data-table" style={{ border: 'none' }}>
            <thead>
              <tr>
                <th>{t('timestampUtc')}</th><th>{t('unit')}</th><th>{t('action')}</th>
                <th>{t('commandStatus')}</th><th>{t('triggerSource')}</th><th>{t('reason')}</th>
              </tr>
            </thead>
            <tbody>
              {report.recent_sessions.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                    {t('noEventsPeriod')}
                  </td>
                </tr>
              ) : (
                report.recent_sessions.map((s) => (
                  <tr key={s.id}>
                    <td className="tabular-nums" style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                      {formatDate(s.timestamp)} {formatTime(s.timestamp)}
                    </td>
                    <td style={{ fontWeight: 500 }}>{s.panel_name}</td>
                    <td>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-teal)' }}>
                        {formatCode(s.event_type)}
                      </span>
                    </td>
                    <td className="tabular-nums" style={{ fontSize: '0.8125rem' }}>
                      {s.command ? `${formatCode(s.command)}: ${s.value ? formatCode(s.value) : t('ok')}` : (s.value ? formatCode(s.value) : '—')}
                    </td>
                    <td style={{ fontSize: '0.8125rem', textTransform: 'capitalize' }}>
                      {formatCode(s.triggered_by)}
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
