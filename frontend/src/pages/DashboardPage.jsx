import React, { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { apiRequest } from '../api/client';
import { GeneratorCard } from '../components/GeneratorCard';
import { OverrideBanner } from '../components/OverrideBanner';
import { useLocale } from '../i18n/LocaleContext';

export function DashboardPage({
  panelStates = {},
  gatewayStatus = 'online',
  onNavigate,
  currentSite,
  onOpenAddGenerator,
  onEditPanel,
  refreshKey,
}) {
  const { t, formatNumber } = useLocale();
  const [panels, setPanels] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [overrides, setOverrides] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionMessage, setActionMessage] = useState(null);

  // ISO day of week: Monday is 0, Sunday is 6
  const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  let siteWeekday = new Intl.DateTimeFormat('en-US', {
    weekday: 'short', timeZone: currentSite?.timezone || 'UTC',
  }).format(new Date()).slice(0, 3);
  const todayIndex = Math.max(0, weekdayNames.indexOf(siteWeekday));

  useEffect(() => {
    loadData();
  }, [currentSite?.id, refreshKey]);

  async function loadData() {
    try {
      setLoading(true);
      const [panelsData, schedData, ovData] = await Promise.all([
        apiRequest('/panels'),
        apiRequest('/schedules'),
        apiRequest('/diagnostics/overrides'),
      ]);
      setPanels(panelsData);
      setSchedules(schedData);
      setOverrides(ovData);
    } catch (err) {
      console.error('Error loading dashboard data:', err);
    } finally {
      setLoading(false);
    }
  }

  const handleManualStart = async (panelId) => {
    try {
      const res = await apiRequest(`/panels/${panelId}/start`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'Manual start from dashboard' }),
      });
      setActionMessage({ type: 'success', text: t('startSent') });
      setTimeout(() => setActionMessage(null), 5000);
    } catch (err) {
      const msg = typeof err === 'string' ? err : (err?.message || JSON.stringify(err));
      setActionMessage({ type: 'error', text: msg });
      setTimeout(() => setActionMessage(null), 6000);
    }
  };

  const handleManualStop = async (panelId) => {
    try {
      const res = await apiRequest(`/panels/${panelId}/stop`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'Manual stop from dashboard' }),
      });
      setActionMessage({ type: 'success', text: t('stopSent') });
      setTimeout(() => setActionMessage(null), 5000);
    } catch (err) {
      const msg = typeof err === 'string' ? err : (err?.message || JSON.stringify(err));
      setActionMessage({ type: 'error', text: msg });
      setTimeout(() => setActionMessage(null), 6000);
    }
  };

  const handleDeleteGenerator = async (panelId) => {
    try {
      await apiRequest(`/panels/${panelId}`, { method: 'DELETE' });
      setActionMessage({ type: 'success', text: t('generatorDeleted') });
      loadData();
      setTimeout(() => setActionMessage(null), 4000);
    } catch (err) {
      setActionMessage({ type: 'error', text: err.message });
    }
  };

  // Group schedules by panel_id
  const panelScheduledDays = {};
  schedules.forEach((s) => {
    if (!panelScheduledDays[s.panel_id]) {
      panelScheduledDays[s.panel_id] = [];
    }
    if (s.is_active) {
      panelScheduledDays[s.panel_id].push(s.day_of_week);
    }
  });

  // Calculate summary stats
  const totalCapacity = panels.reduce((acc, p) => acc + (p.rated_kw || 0), 0);
  let totalLiveKw = 0;
  let runningCount = 0;

  panels.forEach((p) => {
    const live = panelStates[p.id];
    if (live?.is_running || live?.engine_status === 'running') {
      totalLiveKw += live.load_kw || 0;
      runningCount += 1;
    }
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{currentSite?.name || t('generatorFleet')}</h1>
          <p className="page-subtitle">
            {t('fleetSummary', { running: formatNumber(runningCount), total: formatNumber(panels.length), output: formatNumber(Math.round(totalLiveKw)), capacity: formatNumber(totalCapacity) })}
          </p>
        </div>

        {/* Action Button: Add Generator */}
        {onOpenAddGenerator && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={onOpenAddGenerator}
            style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
          >
            <Plus size={16} />
            {t('addGenerator')}
          </button>
        )}
      </div>

      <OverrideBanner
        activeOverrides={overrides}
        gatewayStatus={gatewayStatus}
        onClearOverride={() => onNavigate('overrides')}
      />

      {actionMessage && (
        <div style={{
          padding: '0.625rem 1rem',
          borderRadius: '4px',
          marginBottom: '1.25rem',
          fontSize: '0.875rem',
          backgroundColor: actionMessage.type === 'success' ? 'var(--success-bg)' : 'var(--danger-bg)',
          border: `1px solid ${actionMessage.type === 'success' ? 'var(--success-border)' : 'var(--danger-border)'}`,
          color: actionMessage.type === 'success' ? 'var(--status-running)' : 'var(--status-alarm)',
        }}>
          {actionMessage.text}
        </div>
      )}

      {loading ? (
        <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          {t('loadingGenerators')}
        </div>
      ) : panels.length === 0 ? (
        <div style={{
          backgroundColor: 'var(--card-bg)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '3rem',
          textAlign: 'center',
        }}>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>
            {t('noGenerators')}
          </p>
          {onOpenAddGenerator && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={onOpenAddGenerator}
            >
              {t('addFirstGenerator')}
            </button>
          )}
        </div>
      ) : (
        <div className="generator-grid">
          {panels.map((panel) => {
            const scheduledDays = panelScheduledDays[panel.id] || [];
            const isOnDutyToday = scheduledDays.includes(todayIndex);
            const liveState = panelStates[panel.id];

            return (
              <GeneratorCard
                key={panel.id}
                panel={panel}
                liveState={liveState}
                scheduledDays={scheduledDays}
                isOnDutyToday={isOnDutyToday}
                todayIndex={todayIndex}
                onManualStart={handleManualStart}
                onManualStop={handleManualStop}
                onEditPanel={onEditPanel}
                onDeletePanel={handleDeleteGenerator}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
