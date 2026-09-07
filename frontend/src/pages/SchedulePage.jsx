import React, { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';

const DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export function SchedulePage() {
  const [panels, setPanels] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [site, setSite] = useState(null);

  // Load panels and existing schedules
  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      setLoading(true);
      const [panelsData, schedData, siteData] = await Promise.all([
        apiRequest('/panels'),
        apiRequest('/schedules'),
        apiRequest('/sites/current').catch(() => null),
      ]);
      setPanels(panelsData);
      setSchedules(schedData);
      setSite(siteData);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setLoading(false);
    }
  }

  // Get schedule for a specific panel on a given day
  const getSchedule = (panelId, dayIndex) => {
    return schedules.find((s) => s.panel_id === panelId && s.day_of_week === dayIndex && s.is_active);
  };

  // Toggle duty assignment for a panel on a day
  const handleToggleDay = (panelId, dayIndex) => {
    setSchedules((prev) => {
      const existingIdx = prev.findIndex((s) => s.panel_id === panelId && s.day_of_week === dayIndex);
      if (existingIdx >= 0) {
        // Remove or deactivate
        return prev.filter((_, i) => i !== existingIdx);
      } else {
        // Add
        return [
          ...prev,
          {
            panel_id: panelId,
            day_of_week: dayIndex,
            start_time: '07:00',
            end_time: '19:00',
            is_active: true,
          },
        ];
      }
    });
  };

  const handleTimeChange = (panelId, dayIndex, field, value) => {
    setSchedules((prev) => {
      const idx = prev.findIndex((s) => s.panel_id === panelId && s.day_of_week === dayIndex);
      if (idx === -1) return prev;
      const copy = [...prev];
      copy[idx] = { ...copy[idx], [field]: value };
      return copy;
    });
  };

  // Save changes via bulk API
  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const payload = {
        schedules: schedules.map((s) => ({
          panel_id: s.panel_id,
          day_of_week: s.day_of_week,
          start_time: s.start_time || '07:00',
          end_time: s.end_time || '19:00',
          is_active: true,
        })),
      };
      await apiRequest('/schedules/bulk', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setMessage({ type: 'success', text: 'Schedule saved and synced with controller.' });
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  };

  // One-click presets
  const handleApplyPreset = async (presetName) => {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await apiRequest('/schedules/presets', {
        method: 'POST',
        body: JSON.stringify({ preset_name: presetName }),
      });
      setSchedules(updated);
      const names = {
        daily_rotation: 'Daily Rotation',
        load_following_only: 'Load-Following Only',
        manual_only: 'Manual Operation Only',
      };
      setMessage({ type: 'success', text: `Applied "${names[presetName]}" preset.` });
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  };

  // Safety validations
  const warnings = [];
  panels.forEach((p) => {
    const activeDaysCount = schedules.filter((s) => s.panel_id === p.id && s.is_active).length;
    if (activeDaysCount === 7) {
      warnings.push(`${p.name} is scheduled 7 days a week with no rest days.`);
    }
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Duty Schedule</h1>
          <p className="page-subtitle">
            Choose which generators are on primary duty throughout the week &bull; Facility Timezone: <strong style={{ color: 'var(--text-primary)' }}>{site?.timezone || 'UTC'}</strong>
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSave}
          disabled={saving || loading}
        >
          {saving ? 'Saving...' : 'Save Schedule'}
        </button>
      </div>

      {message && (
        <div style={{
          padding: '0.625rem 1rem',
          borderRadius: '4px',
          marginBottom: '1.5rem',
          fontSize: '0.875rem',
          backgroundColor: message.type === 'success' ? '#EDF7F2' : '#FDF2F2',
          border: `1px solid ${message.type === 'success' ? '#B8E2D1' : '#F5C6C6'}`,
          color: message.type === 'success' ? 'var(--status-running)' : 'var(--status-alarm)',
        }}>
          {message.text}
        </div>
      )}

      {/* Preset Buttons */}
      <div style={{
        backgroundColor: '#FFFFFF',
        border: '1px solid var(--border-subtle)',
        borderRadius: '4px',
        padding: '1.25rem',
        marginBottom: '1.5rem',
      }}>
        <div style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
          Quick Schedule Presets
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => handleApplyPreset('daily_rotation')}
          >
            Daily Rotation
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => handleApplyPreset('load_following_only')}
          >
            Load-Following Only
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => handleApplyPreset('manual_only')}
          >
            Manual (No Schedule)
          </button>
        </div>
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={{
          backgroundColor: '#FEF8EC',
          border: '1px solid #F2DEC0',
          color: 'var(--status-warning)',
          padding: '0.75rem 1rem',
          borderRadius: '4px',
          marginBottom: '1.5rem',
          fontSize: '0.8125rem',
        }}>
          {warnings.map((w, idx) => (
            <div key={idx}>&bull; {w}</div>
          ))}
        </div>
      )}

      {/* Weekly Matrix */}
      <div style={{
        backgroundColor: '#FFFFFF',
        border: '1px solid var(--border-subtle)',
        borderRadius: '4px',
        overflow: 'hidden',
      }}>
        <table className="data-table" style={{ border: 'none' }}>
          <thead>
            <tr>
              <th style={{ width: '220px' }}>Generator</th>
              {DAY_LABELS.map((day, idx) => (
                <th key={idx} style={{ textAlign: 'center' }}>
                  {day.slice(0, 3)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {panels.map((panel) => (
              <tr key={panel.id}>
                <td>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{panel.name}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{panel.rated_kw} kW</div>
                </td>
                {DAY_LABELS.map((_, dayIdx) => {
                  const schedule = getSchedule(panel.id, dayIdx);
                  const assigned = !!schedule;
                  return (
                    <td key={dayIdx} style={{ textAlign: 'center', verticalAlign: 'top', padding: '0.75rem 0.25rem' }}>
                      <button
                        type="button"
                        onClick={() => handleToggleDay(panel.id, dayIdx)}
                        style={{
                          width: '100%',
                          maxWidth: '60px',
                          height: '32px',
                          borderRadius: '4px',
                          border: assigned ? '1px solid var(--accent-teal)' : '1px solid var(--border-subtle)',
                          backgroundColor: assigned ? 'var(--accent-teal)' : '#FFFFFF',
                          color: assigned ? '#FFFFFF' : 'var(--text-secondary)',
                          cursor: 'pointer',
                          fontWeight: assigned ? 600 : 400,
                          fontSize: '0.75rem',
                          fontFamily: 'inherit',
                          transition: 'all 0.15s ease',
                          marginBottom: assigned ? '0.5rem' : '0',
                        }}
                      >
                        {assigned ? 'ON' : 'off'}
                      </button>
                      
                      {assigned && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', alignItems: 'center' }}>
                          <input
                            type="time"
                            value={schedule.start_time}
                            onChange={(e) => handleTimeChange(panel.id, dayIdx, 'start_time', e.target.value)}
                            style={{ width: '85px', fontSize: '0.7rem', padding: '2px', border: '1px solid var(--border-subtle)', borderRadius: '3px' }}
                            title="Start Time"
                          />
                          <input
                            type="time"
                            value={schedule.end_time}
                            onChange={(e) => handleTimeChange(panel.id, dayIdx, 'end_time', e.target.value)}
                            style={{ width: '85px', fontSize: '0.7rem', padding: '2px', border: '1px solid var(--border-subtle)', borderRadius: '3px' }}
                            title="End Time"
                          />
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
