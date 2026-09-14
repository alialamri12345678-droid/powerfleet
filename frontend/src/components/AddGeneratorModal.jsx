import React, { useState, useEffect } from 'react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

export function AddGeneratorModal({ isOpen, onClose, onGeneratorCreated, siteId, initialData = null }) {
  const { t } = useLocale();
  const [name, setName] = useState('');
  const [transportType, setTransportType] = useState('tcp');
  const [address, setAddress] = useState('');
  const [unitId, setUnitId] = useState('1');
  const [ratedKw, setRatedKw] = useState('500');
  const [ratedKvar, setRatedKvar] = useState('150');
  const [controllerProfile, setControllerProfile] = useState('dse_86xx_mkii');
  const [controllerProfiles, setControllerProfiles] = useState([
    { id: 'dse_86xx_mkii', name: 'Deep Sea DSE 86xx MKII' },
  ]);
  const [maintenanceInterval, setMaintenanceInterval] = useState('250');
  const [maintenanceLimits, setMaintenanceLimits] = useState({ coolant_temperature_high_warning: 90, oil_pressure_low_warning: 2, fuel_level_percent_low_warning: 20, battery_voltage_low_warning: 11.8 });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen) {
      if (initialData) {
        setName(initialData.name || '');
        setTransportType(initialData.transport_type || 'tcp');
        setAddress(initialData.address || '');
        setUnitId(initialData.unit_id?.toString() || '');
        setRatedKw(initialData.rated_kw?.toString() || '');
        setRatedKvar(initialData.rated_kvar?.toString() || '');
        setControllerProfile(initialData.controller_profile || 'dse_86xx_mkii');
        setMaintenanceInterval(initialData.maintenance_interval_hours?.toString() || '250');
        setMaintenanceLimits({ coolant_temperature_high_warning: 90, oil_pressure_low_warning: 2, fuel_level_percent_low_warning: 20, battery_voltage_low_warning: 11.8, ...(initialData.maintenance_limits || {}) });
      } else {
        setName('');
        setTransportType('tcp');
        setAddress('');
        setUnitId('1');
        setRatedKw('500');
        setRatedKvar('150');
        setControllerProfile('dse_86xx_mkii');
        setMaintenanceInterval('250');
        setMaintenanceLimits({ coolant_temperature_high_warning: 90, oil_pressure_low_warning: 2, fuel_level_percent_low_warning: 20, battery_voltage_low_warning: 11.8 });
      }
    }
  }, [isOpen, initialData]);

  useEffect(() => {
    if (!isOpen) return undefined;
    let active = true;
    apiRequest('/panels/controller-profiles/available')
      .then((profiles) => {
        if (active && Array.isArray(profiles) && profiles.length) {
          setControllerProfiles(profiles);
        }
      })
      .catch(() => {
        // Keep the existing DSE8620 option if profile discovery is unavailable.
      });
    return () => { active = false; };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        name,
        transport_type: transportType,
        address,
        unit_id: Number(unitId),
        rated_kw: Number(ratedKw),
        rated_kvar: Number(ratedKvar),
        controller_profile: controllerProfile,
        maintenance_interval_hours: Number(maintenanceInterval),
        maintenance_limits: Object.fromEntries(Object.entries(maintenanceLimits).map(([key, value]) => [key, Number(value)])),
      };
      let res;
      if (initialData) {
        res = await apiRequest(`/panels/${initialData.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } else {
        res = await apiRequest('/panels', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      onGeneratorCreated(res);
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
        maxWidth: '480px',
        width: '100%',
        padding: '2rem',
        maxHeight: '90vh',
        overflowY: 'auto',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '1.25rem' }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 600 }}>{initialData ? t('editGenerator') : t('addGenerator')}</h2>
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
            <label className="form-label" htmlFor="controller-profile">{t('controllerModel')}</label>
            <select id="controller-profile" className="form-select" value={controllerProfile} onChange={(e) => setControllerProfile(e.target.value)}>
              {controllerProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
            </select>
          </div>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, margin: '0.5rem 0' }}>{t('maintenanceLimits')}</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            {[
              ['coolant_temperature_high_warning', t('coolantHigh'), 1],
              ['oil_pressure_low_warning', t('oilLow'), 0.1],
              ['fuel_level_percent_low_warning', t('fuelLow'), 1],
              ['battery_voltage_low_warning', t('batteryLow'), 0.1],
            ].map(([key, label, step]) => (
              <div className="form-group" key={key}>
                <label className="form-label" htmlFor={key}>{label}</label>
                <input id={key} type="number" step={step} className="form-input" value={maintenanceLimits[key]} onChange={(e) => setMaintenanceLimits((limits) => ({ ...limits, [key]: e.target.value }))} required />
              </div>
            ))}
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="maintenance-interval">{t('serviceInterval')}</label>
            <input id="maintenance-interval" type="number" min="25" max="5000" step="25" className="form-input" value={maintenanceInterval} onChange={(e) => setMaintenanceInterval(e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="gen-name">{t('generatorName')}</label>
            <input
              id="gen-name"
              type="text"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('generatorName')}
              required
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="gen-transport">{t('transportProtocol')}</label>
              <select
                id="gen-transport"
                className="form-select"
                value={transportType}
                onChange={(e) => {
                  setTransportType(e.target.value);
                  setAddress('');
                }}
              >
                <option value="tcp">{t('tcpOption')}</option>
                <option value="rtu">{t('rtuOption')}</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="gen-unit-id">{t('slaveId')}</label>
              <input
                id="gen-unit-id"
                type="number"
                min="1"
                max="255"
                className="form-input"
                value={unitId}
                onChange={(e) => setUnitId(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="gen-address">
              {transportType === 'tcp' ? t('tcpAddress') : t('serialAddress')}
            </label>
            <input
              id="gen-address"
              type="text"
              className="form-input"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder={transportType === 'tcp' ? '192.168.1.100:502' : '/dev/ttyUSB0 or COM3'}
              required
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="gen-kw">{t('ratedPower')}</label>
              <input
                id="gen-kw"
                type="number"
                min="1"
                step="0.1"
                className="form-input"
                value={ratedKw}
                onChange={(e) => setRatedKw(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="gen-kvar">{t('ratedReactive')}</label>
              <input
                id="gen-kvar"
                type="number"
                min="0"
                step="0.1"
                className="form-input"
                value={ratedKvar}
                onChange={(e) => setRatedKvar(e.target.value)}
              />
            </div>
          </div>



          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.5rem', justifyContent: 'flex-end' }}>
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={submitting}>{t('cancel')}</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? t('saving') : (initialData ? t('saveChanges') : t('addGenerator'))}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
