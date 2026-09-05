import React, { useState } from 'react';
import { apiRequest } from '../api/client';

export function AddSiteModal({ isOpen, onClose, onSiteCreated }) {
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [timezone, setTimezone] = useState('UTC');
  const [maxParallelUnits, setMaxParallelUnits] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        name,
        address: address || undefined,
        timezone,
        max_parallel_units: maxParallelUnits ? Number(maxParallelUnits) : undefined,
      };
      const created = await apiRequest('/sites', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setName('');
      setAddress('');
      setMaxParallelUnits('');
      onSiteCreated(created);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(26, 29, 31, 0.4)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '1rem',
    }}>
      <div style={{
        backgroundColor: '#FFFFFF',
        borderRadius: '4px',
        border: '1px solid var(--border-subtle)',
        maxWidth: '460px',
        width: '100%',
        padding: '2rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '1.25rem' }}>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            Add New Facility Site
          </h2>
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2rem', color: 'var(--text-tertiary)' }}
          >
            &times;
          </button>
        </div>

        {error && (
          <div style={{
            padding: '0.625rem 0.875rem',
            backgroundColor: '#FDF2F2',
            border: '1px solid #F5C6C6',
            color: 'var(--status-alarm)',
            borderRadius: '4px',
            fontSize: '0.8125rem',
            marginBottom: '1rem',
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="site-name">Site / Facility Name</label>
            <input
              id="site-name"
              type="text"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Data Center - North Campus"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="site-address">Physical Address</label>
            <input
              id="site-address"
              type="text"
              className="form-input"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="e.g. 500 Enterprise Way, Suite 10"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="site-timezone">Site Timezone</label>
            <select
              id="site-timezone"
              className="form-select"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
            >
              <option value="UTC">UTC (Universal Coordinated Time)</option>
              <option value="America/New_York">America/New_York (Eastern)</option>
              <option value="America/Chicago">America/Chicago (Central)</option>
              <option value="America/Denver">America/Denver (Mountain)</option>
              <option value="America/Los_Angeles">America/Los_Angeles (Pacific)</option>
              <option value="Europe/London">Europe/London (GMT/BST)</option>
              <option value="Asia/Dubai">Asia/Dubai (GST)</option>
              <option value="Asia/Singapore">Asia/Singapore (SGT)</option>
            </select>
          </div>

          <div className="form-group" style={{ marginBottom: '1.75rem' }}>
            <label className="form-label" htmlFor="site-max-parallel">Max Simultaneous Units (Optional Cap)</label>
            <input
              id="site-max-parallel"
              type="number"
              min="1"
              max="16"
              className="form-input"
              value={maxParallelUnits}
              onChange={(e) => setMaxParallelUnits(e.target.value)}
              placeholder="e.g. 4"
            />
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
            >
              {submitting ? 'Creating Site...' : 'Create Site'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
