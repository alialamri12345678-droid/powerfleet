import React, { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';

export function SettingsPage() {
  const [threshold, setThreshold] = useState(null);
  const [startPct, setStartPct] = useState(70);
  const [stopPct, setStopPct] = useState(50);
  const [dwellMinutes, setDwellMinutes] = useState(2);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    async function loadThreshold() {
      try {
        const data = await apiRequest('/thresholds');
        setThreshold(data);
        setStartPct(data.start_pct);
        setStopPct(data.stop_pct);
        setDwellMinutes(Math.round(data.dwell_seconds / 60));
      } catch (err) {
        setMessage({ type: 'error', text: err.message });
      } finally {
        setLoading(false);
      }
    }
    loadThreshold();
  }, []);

  const handleStartChange = (val) => {
    const num = Number(val);
    setStartPct(num);
    // Enforce stopPct < startPct
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
        text: 'The stop threshold must be lower than the start threshold to prevent rapid engine cycling.',
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
      setMessage({ type: 'success', text: 'Load management thresholds updated successfully.' });
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: '680px' }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">Load Management Rules</h1>
          <p className="page-subtitle">
            Configure automated backup assistance when facility power demand rises
          </p>
        </div>
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

      {loading ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          Loading rule settings...
        </div>
      ) : (
        <form onSubmit={handleSave} style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '2rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '2rem',
        }}>
          {/* Start Backup Slider */}
          <div className="slider-container">
            <div className="slider-labels">
              <label htmlFor="start-pct-slider" style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
                Start a backup generator when site load reaches:
              </label>
              <span className="tabular-nums slider-val">{startPct}%</span>
            </div>
            <input
              id="start-pct-slider"
              type="range"
              min="30"
              max="95"
              step="5"
              value={startPct}
              onChange={(e) => handleStartChange(e.target.value)}
            />
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
              When the active generators reach this utilization level, the system will automatically signal the next available unit with the fewest accumulated hours.
            </p>
          </div>

          {/* Stop Backup Slider */}
          <div className="slider-container">
            <div className="slider-labels">
              <label htmlFor="stop-pct-slider" style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
                Release the backup unit when load drops back below:
              </label>
              <span className="tabular-nums slider-val">{stopPct}%</span>
            </div>
            <input
              id="stop-pct-slider"
              type="range"
              min="10"
              max={Math.max(10, startPct - 5)}
              step="5"
              value={stopPct}
              onChange={(e) => handleStopChange(e.target.value)}
            />
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
              Keeps a safety margin (hysteresis) to ensure generators do not start and stop repeatedly during minor demand fluctuations.
            </p>
          </div>

          {/* Dwell Time */}
          <div className="form-group">
            <label className="form-label" htmlFor="dwell-select">Minimum run duration before stopping backup</label>
            <select
              id="dwell-select"
              className="form-select"
              value={dwellMinutes}
              onChange={(e) => setDwellMinutes(Number(e.target.value))}
            >
              <option value="1">1 minute</option>
              <option value="2">2 minutes (recommended)</option>
              <option value="5">5 minutes</option>
              <option value="10">10 minutes</option>
            </select>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Ensures the backup engine reaches stable operating temperature before being shut down.
            </p>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving}
            >
              {saving ? 'Saving...' : 'Save Rules'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
