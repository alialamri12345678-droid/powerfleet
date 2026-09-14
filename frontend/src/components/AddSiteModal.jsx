import React, { useState, useEffect } from 'react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

export function AddSiteModal({ isOpen, onClose, onSiteCreated, initialData = null }) {
  const { t } = useLocale();
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [timezone, setTimezone] = useState('UTC');
  const [maxParallelUnits, setMaxParallelUnits] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen) {
      if (initialData) {
        setName(initialData.name || '');
        setAddress(initialData.address || '');
        setTimezone(initialData.timezone || 'UTC');
        setMaxParallelUnits(initialData.max_parallel_units || '');
      } else {
        setName('');
        setAddress('');
        setTimezone('UTC');
        setMaxParallelUnits('');
      }
    }
  }, [isOpen, initialData]);

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
      
      let res;
      if (initialData) {
        res = await apiRequest(`/sites/${initialData.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } else {
        res = await apiRequest('/sites', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }

      onSiteCreated(res);
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
          <h2 style={{ fontSize: '1.125rem', fontWeight: 600 }}>{initialData ? t('editSite') : t('newFacility')}</h2>
          <button type="button" onClick={onClose} aria-label={t('close')} title={t('close')} style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
            ✕
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
            <label className="form-label" htmlFor="site-name">{t('siteName')}</label>
            <input
              id="site-name"
              type="text"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('siteName')}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="site-address">{t('physicalAddress')}</label>
            <input
              id="site-address"
              type="text"
              className="form-input"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder={t('physicalAddress')}
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="site-timezone">{t('siteTimezone')}</label>
            <select
              id="site-timezone"
              className="form-select"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
            >
              {['UTC', 'Asia/Riyadh', 'Asia/Dubai', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'Europe/London', 'Asia/Singapore'].map((zone) => (
                <option key={zone} value={zone}>{zone}</option>
              ))}
            </select>
          </div>

          <div className="form-group" style={{ marginBottom: '1.75rem' }}>
            <label className="form-label" htmlFor="site-max-parallel">{t('maxUnits')}</label>
            <input
              id="site-max-parallel"
              type="number"
              min="1"
              max="16"
              className="form-input"
              value={maxParallelUnits}
              onChange={(e) => setMaxParallelUnits(e.target.value)}
              placeholder="4"
            />
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.5rem', justifyContent: 'flex-end' }}>
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={submitting}>{t('cancel')}</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? t('saving') : (initialData ? t('saveChanges') : t('createSite'))}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
