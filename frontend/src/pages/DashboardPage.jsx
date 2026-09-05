import React, { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { GeneratorCard } from '../components/GeneratorCard';
import { OverrideBanner } from '../components/OverrideBanner';

export function DashboardPage({
  panelStates = {},
  gatewayStatus = 'online',
  onNavigate,
  currentSite,
  onOpenAddGenerator,
  refreshKey,
}) {
  const { user } = useAuth();
  const [panels, setPanels] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [overrides, setOverrides] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionMessage, setActionMessage] = useState(null);

  // ISO day of week: Monday is 0, Sunday is 6
  const todayIndex = (new Date().getDay() + 6) % 7;

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
      const res = await apiRequest(`/panels/${panelId}/start`, { method: 'POST' });
      setActionMessage({ type: 'success', text: res.message });
      setTimeout(() => setActionMessage(null), 5000);
    } catch (err) {
      setActionMessage({ type: 'error', text: err.message });
      setTimeout(() => setActionMessage(null), 6000);
    }
  };

  const handleManualStop = async (panelId) => {
    try {
      const res = await apiRequest(`/panels/${panelId}/stop`, { method: 'POST' });
      setActionMessage({ type: 'success', text: res.message });
      setTimeout(() => setActionMessage(null), 5000);
    } catch (err) {
      setActionMessage({ type: 'error', text: err.message });
      setTimeout(() => setActionMessage(null), 6000);
    }
  };

  const handleDeleteGenerator = async (panelId) => {
    try {
      await apiRequest(`/panels/${panelId}`, { method: 'DELETE' });
      setActionMessage({ type: 'success', text: 'Generator decommissioned successfully.' });
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
    if (live?.is_running) {
      totalLiveKw += live.load_kw || 0;
      runningCount += 1;
    }
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{currentSite?.name || 'Generator Fleet'}</h1>
          <p className="page-subtitle">
            {runningCount} of {panels.length} generators active &bull; Total output: <span className="tabular-nums" style={{ fontWeight: 600 }}>{Math.round(totalLiveKw)} kW</span> of <span className="tabular-nums">{totalCapacity} kW</span>
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
            Add Generator
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
          backgroundColor: actionMessage.type === 'success' ? '#EDF7F2' : '#FDF2F2',
          border: `1px solid ${actionMessage.type === 'success' ? '#B8E2D1' : '#F5C6C6'}`,
          color: actionMessage.type === 'success' ? 'var(--status-running)' : 'var(--status-alarm)',
        }}>
          {actionMessage.text}
        </div>
      )}

      {loading ? (
        <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          Loading generator status...
        </div>
      ) : panels.length === 0 ? (
        <div style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '3rem',
          textAlign: 'center',
        }}>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>
            No generators configured for this facility site yet.
          </p>
          {onOpenAddGenerator && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={onOpenAddGenerator}
            >
              Add First Generator
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
                onDeletePanel={handleDeleteGenerator}
                isTechnician={true}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
