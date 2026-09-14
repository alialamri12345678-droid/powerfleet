import React, { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

export function OverridesPage() {
  const { t, formatDate, formatTime } = useLocale();
  const [panels, setPanels] = useState([]);
  const [overrides, setOverrides] = useState([]);
  const [selectedPanelId, setSelectedPanelId] = useState('');
  const [overrideType, setOverrideType] = useState('force_start');
  const [durationMinutes, setDurationMinutes] = useState(60);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const [panelsData, overridesData] = await Promise.all([
        apiRequest('/panels'),
        apiRequest('/diagnostics/overrides'),
      ]);
      setPanels(panelsData);
      setOverrides(overridesData);
      if (panelsData.length > 0 && !selectedPanelId) {
        setSelectedPanelId(panelsData[0].id);
      }
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    }
  }

  const handleCreateOverride = async (e) => {
    e.preventDefault();
    if (!selectedPanelId) return;

    setSubmitting(true);
    setMessage(null);
    try {
      await apiRequest(`/diagnostics/panels/${selectedPanelId}/override`, {
        method: 'POST',
        body: JSON.stringify({
          panel_id: selectedPanelId,
          override_type: overrideType,
          duration_minutes: durationMinutes,
          reason: reason || undefined,
        }),
      });
      setMessage({ type: 'success', text: t('overrideIssued', { count: durationMinutes }) });
      setReason('');
      await loadData();
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSubmitting(false);
    }
  };

  const handleRelease = async (panelId) => {
    try {
      await apiRequest(`/diagnostics/panels/${panelId}/override`, { method: 'DELETE' });
      setMessage({ type: 'success', text: t('overrideReleased') });
      await loadData();
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('overridesTitle')}</h1>
          <p className="page-subtitle">
            {t('overridesSubtitle')}
          </p>
        </div>
      </div>

      {message && (
        <div style={{
          padding: '0.625rem 1rem',
          borderRadius: '4px',
          marginBottom: '1.5rem',
          fontSize: '0.875rem',
          backgroundColor: message.type === 'success' ? 'var(--success-bg)' : 'var(--danger-bg)',
          border: `1px solid ${message.type === 'success' ? 'var(--success-border)' : 'var(--danger-border)'}`,
          color: message.type === 'success' ? 'var(--status-running)' : 'var(--status-alarm)',
        }}>
          {message.text}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem' }}>
        {/* Create Override Form */}
        <div style={{
          backgroundColor: 'var(--card-bg)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '1.75rem',
        }}>
          <h2 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '1.25rem' }}>
            {t('engageOverride')}
          </h2>

          <form onSubmit={handleCreateOverride}>
            <div className="form-group">
              <label className="form-label" htmlFor="override-panel-select">{t('targetGenerator')}</label>
              <select
                id="override-panel-select"
                className="form-select"
                value={selectedPanelId}
                onChange={(e) => setSelectedPanelId(e.target.value)}
                required
              >
                {panels.map((p) => (
                  <option key={p.id} value={p.id}>{p.name} ({p.rated_kw} kW)</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="override-action-select">{t('commandedAction')}</label>
              <select
                id="override-action-select"
                className="form-select"
                value={overrideType}
                onChange={(e) => setOverrideType(e.target.value)}
              >
                <option value="force_start">{t('forceStart')}</option>
                <option value="force_stop">{t('forceStop')}</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="override-duration-select">{t('expiryDuration')}</label>
              <select
                id="override-duration-select"
                className="form-select"
                value={durationMinutes}
                onChange={(e) => setDurationMinutes(Number(e.target.value))}
              >
                <option value="30">{t('minutes', { count: 30 })}</option>
                <option value="60">{t('hour', { count: 1 })}</option>
                <option value="120">{t('hours', { count: 2 })}</option>
                <option value="240">{t('hours', { count: 4 })}</option>
                <option value="480">{t('hours', { count: 8 })}</option>
              </select>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                {t('overrideHelp')}
              </p>
            </div>

            <div className="form-group" style={{ marginBottom: '1.5rem' }}>
              <label className="form-label" htmlFor="override-reason-input">{t('auditReason')}</label>
              <input
                id="override-reason-input"
                type="text"
                className="form-input"
                placeholder={t('reasonPlaceholder')}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%' }}
              disabled={submitting || !selectedPanelId}
            >
              {submitting ? t('engaging') : t('engageOverride')}
            </button>
          </form>
        </div>

        {/* Active Overrides List */}
        <div style={{
          backgroundColor: 'var(--card-bg)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '1.75rem',
        }}>
          <h2 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '1.25rem' }}>
            {t('activeOverrides', { count: overrides.length })}
          </h2>

          {overrides.length === 0 ? (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              {t('noOverrides')}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {overrides.map((ov) => {
                const panel = panels.find((p) => p.id === ov.panel_id);
                const expiresDate = new Date(ov.expires_at);
                const isForceStart = ov.override_type === 'force_start';

                return (
                  <div
                    key={ov.id}
                    style={{
                      border: '1px solid var(--border-subtle)',
                      borderRadius: '4px',
                      padding: '1rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.5rem',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                      <span style={{ fontWeight: 600 }}>{panel?.name || ov.panel_id}</span>
                      <span style={{
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: isForceStart ? 'var(--status-running)' : 'var(--status-alarm)',
                      }}>
                        {isForceStart ? t('forceStartLabel') : t('forceStopLabel')}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                      {t('expiresAt')} <span className="tabular-nums">{formatTime(expiresDate)}</span> ({formatDate(expiresDate)})
                    </div>

                    {ov.reason && (
                      <div style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)' }}>
                        {t('note')} {ov.reason}
                      </div>
                    )}

                    <div style={{ marginTop: '0.5rem' }}>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        style={{ fontSize: '0.75rem', padding: '0.25rem 0.625rem' }}
                        onClick={() => handleRelease(ov.panel_id)}
                      >
                        {t('releaseOverride')}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
