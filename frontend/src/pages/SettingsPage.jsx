import React, { useEffect, useState, useRef, useCallback } from 'react';
import { apiRequest } from '../api/client';
import { AddSiteModal } from '../components/AddSiteModal';
import { useAuth } from '../auth/AuthContext';
import { useLocale } from '../i18n/LocaleContext';

export function SettingsPage() {
  const { logout } = useAuth();
  const { t, locale } = useLocale();
  const displayDayIndexes = locale === 'ar' ? [5, 6, 0, 1, 2, 3, 4] : [0, 1, 2, 3, 4, 5, 6];
  const [site, setSite] = useState(null);
  const [threshold, setThreshold] = useState(null);
  const [startPct, setStartPct] = useState(70);
  const [stopPct, setStopPct] = useState(50);
  const [dwellMinutes, setDwellMinutes] = useState(2);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [isEditSiteOpen, setIsEditSiteOpen] = useState(false);
  
  const [panels, setPanels] = useState([]);
  const [dailyPriorities, setDailyPriorities] = useState([]);
  const [savingPriorities, setSavingPriorities] = useState(false);

  // Release thresholds state
  const [releaseThresholds, setReleaseThresholds] = useState([]);
  const [savingRelease, setSavingRelease] = useState(false);

  // Start thresholds state
  const [startThresholds, setStartThresholds] = useState([]);
  const [savingStart, setSavingStart] = useState(false);

  useEffect(() => {
    async function loadData() {
      try {
        const [siteData, threshData, panelsData, prioData, releaseData, startData] = await Promise.all([
          apiRequest('/sites/current'),
          apiRequest('/thresholds'),
          apiRequest('/panels'),
          apiRequest('/panels/priorities/daily'),
          apiRequest('/thresholds/release'),
          apiRequest('/thresholds/start'),
        ]);
        setSite(siteData);
        setThreshold(threshData);
        setPanels(panelsData);
        setDailyPriorities(prioData);
        setReleaseThresholds(releaseData);
        setStartThresholds(startData);
        setStartPct(threshData.start_pct);
        setStopPct(threshData.stop_pct);
        setDwellMinutes(Math.round(threshData.dwell_seconds / 60));
      } catch (err) {
        setMessage({ type: 'error', text: err.message });
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const handleStartChange = (val) => {
    const num = Number(val);
    setStartPct(num);
    if (stopPct >= num) {
      setStopPct(Math.max(10, num - 10));
    }
  };

  const handleStopChange = (val) => {
    const num = Number(val);
    if (num < startPct) {
      setStopPct(num);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);

    if (stopPct >= startPct) {
      setMessage({
        type: 'error',
        text: t('thresholdValidation'),
      });
      setSaving(false);
      return;
    }

    try {
      await apiRequest('/thresholds', {
        method: 'PUT',
        body: JSON.stringify({
          start_pct: startPct,
          stop_pct: stopPct,
          dwell_seconds: dwellMinutes * 60,
        }),
      });
      setMessage({ type: 'success', text: t('thresholdsSaved') });
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteSite = async () => {
    if (!window.confirm(t('deleteSiteConfirm', { name: site?.name }))) {
      return;
    }
    try {
      await apiRequest(`/sites/${site.id}`, { method: 'DELETE' });
      alert(t('siteDeleted'));
      logout();
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const handlePriorityChange = (dayOfWeek, panelId, newPriority) => {
    setDailyPriorities((prev) => {
      const copy = [...prev];
      const currentIdx = copy.findIndex((p) => p.panel_id === panelId && p.day_of_week === dayOfWeek);
      const oldPriority = currentIdx >= 0 ? copy[currentIdx].priority : 1;

      const conflictIdx = copy.findIndex(
        (p) => p.panel_id !== panelId && p.day_of_week === dayOfWeek && p.priority === newPriority
      );
      if (conflictIdx >= 0) {
        copy[conflictIdx].priority = oldPriority;
      }

      if (currentIdx >= 0) {
        copy[currentIdx].priority = newPriority;
      } else {
        copy.push({ panel_id: panelId, day_of_week: dayOfWeek, priority: newPriority });
      }
      return copy;
    });
  };

  const handleSavePriorities = async (e) => {
    e.preventDefault();
    setSavingPriorities(true);
    setMessage(null);

    const dayNames = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
    const n = panels.length;
    for (let d = 0; d < 7; d++) {
      const dayItems = dailyPriorities.filter((p) => p.day_of_week === d);
      const prios = dayItems.map((p) => p.priority);
      for (const p of prios) {
        if (p < 1 || p > n) {
          setMessage({
            type: 'error',
            text: t('invalidPriority', { priority: p, day: t(dayNames[d]), count: n }),
          });
          setSavingPriorities(false);
          return;
        }
      }
      const unique = new Set(prios);
      if (unique.size !== prios.length) {
        setMessage({
          type: 'error',
          text: t('duplicatePriority', { day: t(dayNames[d]), count: n }),
        });
        setSavingPriorities(false);
        return;
      }
    }

    try {
      await apiRequest('/panels/priorities/daily/bulk', {
        method: 'POST',
        body: JSON.stringify({ priorities: dailyPriorities }),
      });
      setMessage({ type: 'success', text: t('prioritiesSaved') });
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSavingPriorities(false);
    }
  };

  // ── Release Threshold Bar Logic ──
  const handleReleaseChange = (panelId, newPct) => {
    setReleaseThresholds((prev) =>
      prev.map((rt) =>
        rt.panel_id === panelId ? { ...rt, release_pct: Math.max(5, Math.min(95, newPct)) } : rt
      )
    );
  };

  const handleSaveRelease = async () => {
    setSavingRelease(true);
    setMessage(null);
    try {
      const payload = {
        thresholds: releaseThresholds.map((rt) => ({
          panel_id: rt.panel_id,
          release_pct: rt.release_pct,
          priority_order: rt.priority_order,
        })),
      };
      const result = await apiRequest('/thresholds/release', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setReleaseThresholds(result);
      setMessage({ type: 'success', text: t('releaseRulesSaved') });
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSavingRelease(false);
    }
  };

  // Sort release thresholds by priority_order descending (last backup released first = shown leftmost)
  const sortedReleaseThresholds = [...releaseThresholds].sort(
    (a, b) => b.priority_order - a.priority_order
  );

  // ── Start Threshold Bar Logic ──
  const handleStartThresholdChange = (panelId, newPct) => {
    setStartThresholds((prev) =>
      prev.map((st) =>
        st.panel_id === panelId ? { ...st, start_pct: Math.max(5, Math.min(95, newPct)) } : st
      )
    );
  };

  const handleSaveStartThresholds = async () => {
    setSavingStart(true);
    setMessage(null);
    try {
      const payload = {
        thresholds: startThresholds.map((st) => ({
          panel_id: st.panel_id,
          start_pct: st.start_pct,
          priority_order: st.priority_order,
        })),
      };
      const result = await apiRequest('/thresholds/start', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setStartThresholds(result);
      setMessage({ type: 'success', text: t('startRulesSaved') });
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSavingStart(false);
    }
  };

  // Sort start thresholds by priority_order ascending (first backup started first = shown leftmost)
  const sortedStartThresholds = [...startThresholds].sort(
    (a, b) => a.priority_order - b.priority_order
  );

  // Color palette for indicators
  const indicatorColors = [
    '#E74C3C', '#E67E22', '#F1C40F', '#2ECC71', '#3498DB', '#9B59B6', '#1ABC9C', '#E91E63',
  ];

  return (
    <div style={{ maxWidth: '680px' }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('settings')}</h1>
          <p className="page-subtitle">
            {t('settingsSubtitle')}
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

      {loading ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          {t('loadingSettings')}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          
          {/* Site Settings Card */}
          <div style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '2rem',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
              <div>
                <h2 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>{t('facilityDetails')}</h2>
                <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{t('facilityDetailsText')}</p>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setIsEditSiteOpen(true)}
              >
                {t('editDetails')}
              </button>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
              <div>
                <label className="form-label" style={{ color: 'var(--text-secondary)' }}>{t('siteName')}</label>
                <div style={{ fontWeight: 500 }}>{site?.name}</div>
              </div>
              <div>
                <label className="form-label" style={{ color: 'var(--text-secondary)' }}>{t('timezone')}</label>
                <div style={{ fontWeight: 500 }}>{site?.timezone}</div>
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <label className="form-label" style={{ color: 'var(--text-secondary)' }}>{t('addressLocation')}</label>
                <div style={{ fontWeight: 500 }}>{site?.address || t('notSpecified')}</div>
              </div>
            </div>
          </div>

          <form onSubmit={handleSave} style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '2rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '2rem',
          }}>
            <div style={{ marginBottom: '-1rem' }}>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>{t('loadRules')}</h2>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{t('loadRulesText')}</p>
            </div>
          {/* Start thresholds are now handled by the Start Thresholds Card */}

          {/* Dwell Time */}
          <div className="form-group">
            <label className="form-label" htmlFor="dwell-select">{t('minRunDuration')}</label>
            <select
              id="dwell-select"
              className="form-select"
              value={dwellMinutes}
              onChange={(e) => setDwellMinutes(Number(e.target.value))}
            >
              <option value="1">{t('minute', { count: 1 })}</option>
              <option value="2">{t('minutes', { count: 2 })} ({t('recommended')})</option>
              <option value="5">{t('minutes', { count: 5 })}</option>
              <option value="10">{t('minutes', { count: 10 })}</option>
            </select>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              {t('dwellHelp')}
            </p>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving}
            >
              {saving ? t('saving') : t('saveRules')}
            </button>
          </div>
        </form>

        {/* ── Backup Start Thresholds Card ── */}
        <div style={{
          backgroundColor: 'var(--card-bg)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '2rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.5rem',
          marginBottom: '2rem'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                {t('startThresholds')}
              </h2>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                {t('startThresholdsText')}
              </p>
            </div>
            <button
              className="btn btn-secondary"
              onClick={handleSaveStartThresholds}
              disabled={savingStart}
            >
              {savingStart ? t('saving') : t('saveStartRules')}
            </button>
          </div>

          <ThresholdBar
            thresholds={sortedStartThresholds}
            valueKey="start_pct"
            indicatorColors={indicatorColors}
            onChange={handleStartThresholdChange}
            type="start"
          />

          {/* Legend */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', fontSize: '0.8125rem' }}>
            {sortedStartThresholds.map((st, idx) => (
              <div key={st.panel_id} style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                <span style={{
                  width: '12px', height: '12px', borderRadius: '50%',
                  backgroundColor: indicatorColors[idx % indicatorColors.length],
                  display: 'inline-block', flexShrink: 0,
                }} />
                <span style={{ color: 'var(--text-secondary)' }}>
                  {st.panel_name || t('generatorShort', { number: st.priority_order })}: <strong>{st.start_pct}%</strong>
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Backup Release Thresholds Card ── */}
        <div style={{
          backgroundColor: 'var(--card-bg)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '2rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.5rem',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                {t('releaseThresholds')}
              </h2>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                {t('releaseThresholdsText')}
              </p>
            </div>
            <button
              className="btn btn-secondary"
              onClick={handleSaveRelease}
              disabled={savingRelease}
            >
              {savingRelease ? t('saving') : t('saveReleaseRules')}
            </button>
          </div>

          {/* Release Bar */}
          <ThresholdBar
            thresholds={sortedReleaseThresholds}
            valueKey="release_pct"
            indicatorColors={indicatorColors}
            onChange={handleReleaseChange}
            type="release"
          />

          {/* Legend */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', fontSize: '0.8125rem' }}>
            {sortedReleaseThresholds.map((rt, idx) => (
              <div key={rt.panel_id} style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                <span style={{
                  width: '12px', height: '12px', borderRadius: '50%',
                  backgroundColor: indicatorColors[idx % indicatorColors.length],
                  display: 'inline-block', flexShrink: 0,
                }} />
                <span style={{ color: 'var(--text-secondary)' }}>
                  {rt.panel_name || t('generatorShort', { number: rt.priority_order })}: <strong>{rt.release_pct}%</strong>
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Daily Priorities */}
        <form onSubmit={handleSavePriorities} style={{
            backgroundColor: 'var(--card-bg)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            padding: '2rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '2rem',
          }}>
            <div style={{ marginBottom: '-1rem' }}>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>{t('dailyBackupOrder')}</h2>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                {t('dailyBackupOrderText')}
              </p>
            </div>
            
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: '180px' }}>{t('generator')}</th>
                    {displayDayIndexes.map((dayIndex) => (
                      <th key={dayIndex} style={{ textAlign: 'center' }}>{t(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][dayIndex])}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {panels.map((panel) => (
                    <tr key={panel.id}>
                      <td>
                        <div style={{ fontWeight: 500 }}>{panel.name}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{panel.rated_kw} kW</div>
                      </td>
                      {displayDayIndexes.map((dayOfWeek) => {
                        const prio = dailyPriorities.find(p => p.panel_id === panel.id && p.day_of_week === dayOfWeek)?.priority || 1;
                        return (
                          <td key={dayOfWeek} style={{ textAlign: 'center' }}>
                            <select
                              value={prio}
                              onChange={(e) => handlePriorityChange(dayOfWeek, panel.id, Number(e.target.value))}
                              style={{
                                width: '52px',
                                textAlign: 'center',
                                padding: '0.25rem',
                                border: '1px solid var(--border-subtle)',
                                borderRadius: '4px',
                                background: 'var(--card-bg)',
                                fontWeight: 600,
                                cursor: 'pointer'
                              }}
                            >
                              {panels.map((_, idx) => (
                                <option key={idx + 1} value={idx + 1}>
                                  {idx + 1}
                                </option>
                              ))}
                            </select>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={savingPriorities}
              >
                {savingPriorities ? t('saving') : t('savePriorities')}
              </button>
            </div>
        </form>

        <div style={{
          backgroundColor: 'var(--danger-bg)',
          border: '1px solid var(--danger-border)',
          borderRadius: '4px',
          padding: '2rem',
          marginTop: '2rem'
        }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--status-alarm)', marginBottom: '0.5rem' }}>{t('dangerZone')}</h2>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            {t('dangerText')}
          </p>
          <button
            type="button"
            className="btn btn-danger"
            onClick={handleDeleteSite}
          >
            {t('deleteSite')}
          </button>
        </div>

        </div>
      )}
      
      {isEditSiteOpen && (
        <AddSiteModal
          isOpen={isEditSiteOpen}
          onClose={() => setIsEditSiteOpen(false)}
          initialData={site}
          onSiteCreated={(updatedSite) => {
            setSite(updatedSite);
            setMessage({ type: 'success', text: t('siteUpdated') });
          }}
        />
      )}
    </div>
  );
}


/**
 * Threshold Bar — horizontal bar with draggable indicators for each backup generator.
 */
function ThresholdBar({ thresholds, valueKey, indicatorColors, onChange, type }) {
  const { t: translate } = useLocale();
  const barRef = useRef(null);
  const [dragging, setDragging] = useState(null); // panel_id being dragged

  const handleMouseDown = (e, panelId) => {
    e.preventDefault();
    setDragging(panelId);
  };

  useEffect(() => {
    if (!dragging) return;

    const handleMouseMove = (e) => {
      if (!barRef.current) return;
      const rect = barRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const pct = Math.max(0, Math.min(100, Math.round((x / rect.width) * 100)));
      onChange(dragging, pct);
    };

    const handleMouseUp = () => {
      setDragging(null);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragging, onChange]);

  // Touch support
  const handleTouchStart = (e, panelId) => {
    e.preventDefault();
    setDragging(panelId);
  };

  useEffect(() => {
    if (!dragging) return;

    const handleTouchMove = (e) => {
      if (!barRef.current) return;
      const touch = e.touches[0];
      const rect = barRef.current.getBoundingClientRect();
      const x = touch.clientX - rect.left;
      const pct = Math.max(0, Math.min(100, Math.round((x / rect.width) * 100)));
      onChange(dragging, pct);
    };

    const handleTouchEnd = () => {
      setDragging(null);
    };

    window.addEventListener('touchmove', handleTouchMove, { passive: false });
    window.addEventListener('touchend', handleTouchEnd);
    return () => {
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('touchend', handleTouchEnd);
    };
  }, [dragging, onChange]);

  return (
    <div style={{ padding: '1rem 0' }}>
      {/* Bar container */}
      <div
        ref={barRef}
        dir="ltr"
        style={{
          position: 'relative',
          height: '48px',
          background: 'var(--threshold-gradient)',
          borderRadius: '8px',
          border: '1px solid var(--border-subtle)',
          cursor: dragging ? 'grabbing' : 'default',
          userSelect: 'none',
        }}
      >
        {/* Percentage ticks */}
        {[0, 25, 50, 75, 100].map((tick) => (
          <div
            key={tick}
            style={{
              position: 'absolute',
              left: `${tick}%`,
              bottom: '-20px',
              transform: 'translateX(-50%)',
              fontSize: '0.625rem',
              color: 'var(--text-secondary)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {tick}%
          </div>
        ))}

        {/* Indicators */}
        {thresholds.map((t, idx) => {
          const color = indicatorColors[idx % indicatorColors.length];
          const isDraggingThis = dragging === t.panel_id;
          const val = t[valueKey];
          return (
            <div
              key={t.panel_id}
              style={{
                position: 'absolute',
                left: `${val}%`,
                top: '50%',
                transform: 'translate(-50%, -50%)',
                zIndex: isDraggingThis ? 20 : 10,
                cursor: isDraggingThis ? 'grabbing' : 'grab',
                transition: isDraggingThis ? 'none' : 'left 0.15s ease',
              }}
              onMouseDown={(e) => handleMouseDown(e, t.panel_id)}
              onTouchStart={(e) => handleTouchStart(e, t.panel_id)}
            >
              <div style={{
                width: 0,
                height: 0,
                borderLeft: '10px solid transparent',
                borderRight: '10px solid transparent',
                borderTop: type === 'start' ? 'none' : `16px solid ${color}`,
                borderBottom: type === 'start' ? `16px solid ${color}` : 'none',
              }}>
                <span style={{
                  position: 'absolute',
                  top: type === 'start' ? '2px' : '-16px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  color: '#FFFFFF',
                }}>
                  {t.priority_order}
                </span>
              </div>
              <div style={{
                position: 'absolute',
                top: type === 'start' ? '-24px' : '18px',
                left: '50%',
                transform: 'translateX(-50%)',
                fontSize: '0.625rem',
                fontWeight: 600,
                color: color,
                whiteSpace: 'nowrap',
                fontVariantNumeric: 'tabular-nums',
              }}>
                {val}%
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ height: '32px' }} />

      {/* Individual inputs for precise control */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: '0.75rem',
        marginTop: '0.5rem',
      }}>
        {thresholds.map((t, idx) => (
          <div key={t.panel_id} style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0.5rem',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            backgroundColor: 'var(--surface-subtle)'
          }}>
            <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
              {t.panel_name || translate('generatorShort', { number: t.priority_order })}
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <input
                type="number"
                min="0"
                max="100"
                value={t[valueKey]}
                onChange={(e) => onChange(t.panel_id, Number(e.target.value))}
                style={{ width: '60px', padding: '0.25rem', textAlign: 'right', border: '1px solid var(--border-subtle)', borderRadius: '4px' }}
              />
              <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
