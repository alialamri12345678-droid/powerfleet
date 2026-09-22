import React, { useState, useEffect } from 'react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';
import { useReportLocale } from '../reports/useReportLocale';

const defaultAnalytics = { engine_model: '', nominal_frequency_hz: '', nominal_battery_voltage: '',
  generator_profile_id: 'custom', generator_manufacturer: '', generator_model: '',
  standby_kw: '', prime_kw: '', standby_kva: '', prime_kva: '', power_factor: '', speed_rpm: '', datasheet_url: '',
  fuel_curve_basis: null,
  fuel_type: 'diesel', fuel_source: 'counter', fuel_lhv_kwh_per_litre: '', tank_capacity_litres: '',
  tank_curve: [], fuel_curve: [] };

export function AddGeneratorModal({ isOpen, onClose, onGeneratorCreated, siteId, initialData = null }) {
  const { t } = useLocale();
  const { t: reportText } = useReportLocale();
  const [name, setName] = useState('');
  const [transportType, setTransportType] = useState('tcp');
  const [address, setAddress] = useState('');
  const [unitId, setUnitId] = useState('1');
  const [ratedKw, setRatedKw] = useState('500');
  const [ratedKvar, setRatedKvar] = useState('150');
  const [controllerProfile, setControllerProfile] = useState('dse_86xx_mkii');
  const [generatorProfile, setGeneratorProfile] = useState('custom');
  const [generatorProfiles, setGeneratorProfiles] = useState([{ id: 'custom', name: 'Custom generator', manufacturer: 'Custom' }]);
  const [controllerProfiles, setControllerProfiles] = useState([
    { id: 'dse_86xx_mkii', name: 'Deep Sea DSE 86xx MKII' },
  ]);
  const [maintenanceInterval, setMaintenanceInterval] = useState('250');
  const [maintenanceLimits, setMaintenanceLimits] = useState({ coolant_temperature_high_warning: 90, oil_pressure_low_warning: 2, fuel_level_percent_low_warning: 20, battery_voltage_low_warning: '' });
  const [analytics, setAnalytics] = useState(defaultAnalytics);
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
        setGeneratorProfile(initialData.analytics_config?.generator_profile_id || 'custom');
        setMaintenanceInterval(initialData.maintenance_interval_hours?.toString() || '250');
        setMaintenanceLimits({ coolant_temperature_high_warning: 90, oil_pressure_low_warning: 2, fuel_level_percent_low_warning: 20, battery_voltage_low_warning: '', ...(initialData.maintenance_limits || {}) });
        setAnalytics({ ...defaultAnalytics, ...(initialData.analytics_config || {}) });
      } else {
        setName('');
        setTransportType('tcp');
        setAddress('');
        setUnitId('1');
        setRatedKw('500');
        setRatedKvar('150');
        setControllerProfile('dse_86xx_mkii');
        setGeneratorProfile('custom');
        setMaintenanceInterval('250');
        setMaintenanceLimits({ coolant_temperature_high_warning: 90, oil_pressure_low_warning: 2, fuel_level_percent_low_warning: 20, battery_voltage_low_warning: '' });
        setAnalytics(defaultAnalytics);
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
    apiRequest('/panels/generator-profiles/available')
      .then((profiles) => {
        if (active && Array.isArray(profiles) && profiles.length) setGeneratorProfiles(profiles);
      })
      .catch(() => {});
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
        maintenance_limits: Object.fromEntries(Object.entries(maintenanceLimits).filter(([, value]) => value !== '').map(([key, value]) => [key, Number(value)])),
        analytics_config: {
          engine_model: analytics.engine_model || '', fuel_type: analytics.fuel_type,
          generator_profile_id: generatorProfile,
          generator_manufacturer: analytics.generator_manufacturer || '',
          generator_model: analytics.generator_model || '',
          standby_kw: analytics.standby_kw ? Number(analytics.standby_kw) : null,
          prime_kw: analytics.prime_kw ? Number(analytics.prime_kw) : null,
          standby_kva: analytics.standby_kva ? Number(analytics.standby_kva) : null,
          prime_kva: analytics.prime_kva ? Number(analytics.prime_kva) : null,
          power_factor: analytics.power_factor ? Number(analytics.power_factor) : null,
          speed_rpm: analytics.speed_rpm ? Number(analytics.speed_rpm) : null,
          datasheet_url: analytics.datasheet_url || '',
          fuel_curve_basis: analytics.fuel_curve_basis || null,
          fuel_source: analytics.fuel_source,
          nominal_frequency_hz: analytics.nominal_frequency_hz ? Number(analytics.nominal_frequency_hz) : null,
          nominal_battery_voltage: analytics.nominal_battery_voltage ? Number(analytics.nominal_battery_voltage) : null,
          fuel_lhv_kwh_per_litre: analytics.fuel_lhv_kwh_per_litre ? Number(analytics.fuel_lhv_kwh_per_litre) : null,
          tank_capacity_litres: analytics.tank_capacity_litres ? Number(analytics.tank_capacity_litres) : null,
          tank_curve: analytics.fuel_source === 'tank' ? analytics.tank_curve.map(p => ({ percent: Number(p.percent), litres: Number(p.litres) })) : [],
          fuel_curve: analytics.fuel_curve.filter(p => p.load_percent !== '' && p.litres_per_hour !== '').map(p => ({ load_percent: Number(p.load_percent), litres_per_hour: Number(p.litres_per_hour) })),
        },
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
      backgroundColor: 'var(--overlay-bg)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '1rem',
    }}>
      <div style={{
        backgroundColor: 'var(--card-bg)',
        borderRadius: '4px',
        border: '1px solid var(--border-subtle)',
        maxWidth: '680px',
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
            backgroundColor: 'var(--danger-bg)',
            border: '1px solid var(--danger-border)',
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
            <label className="form-label" htmlFor="generator-profile">{t('generatorEquipmentProfile')}</label>
            <select id="generator-profile" className="form-select" value={generatorProfile} onChange={(e) => {
              const id = e.target.value;
              const profile = generatorProfiles.find((item) => item.id === id);
              setGeneratorProfile(id);
              if (!profile || id === 'custom') {
                setAnalytics((current) => ({ ...current, generator_profile_id: 'custom', generator_manufacturer: '', generator_model: '', datasheet_url: '' }));
                return;
              }
              setRatedKw(String(profile.rated_kw || ''));
              setRatedKvar(String(profile.rated_kvar || 0));
              if (profile.maintenance_interval_hours) setMaintenanceInterval(String(profile.maintenance_interval_hours));
              if (!initialData && !name) setName(profile.name);
              setAnalytics((current) => ({
                ...current,
                generator_profile_id: profile.id, generator_manufacturer: profile.manufacturer,
                generator_model: profile.model, engine_model: profile.engine_model || '',
                nominal_frequency_hz: profile.frequency_hz || '',
                nominal_battery_voltage: profile.nominal_battery_voltage || '',
                standby_kw: profile.standby_kw || '', prime_kw: profile.prime_kw || '',
                standby_kva: profile.standby_kva || '', prime_kva: profile.prime_kva || '',
                power_factor: profile.power_factor || '', speed_rpm: profile.speed_rpm || '',
                datasheet_url: profile.source_url || '', fuel_type: profile.fuel_type || 'diesel',
                fuel_curve: profile.fuel_curve || [], fuel_curve_basis: profile.fuel_curve_basis || null,
              }));
            }}>
              {Object.entries(generatorProfiles.reduce((groups, profile) => {
                const group = profile.manufacturer || 'Other';
                (groups[group] ||= []).push(profile);
                return groups;
              }, {})).map(([manufacturer, profiles]) => (
                <optgroup key={manufacturer} label={manufacturer}>
                  {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.model || profile.name} {profile.frequency_hz ? `— ${profile.frequency_hz} Hz` : ''}</option>)}
                </optgroup>
              ))}
            </select>
            <small style={{ color: 'var(--text-secondary)' }}>{t('generatorProfileHelp')}</small>
            {generatorProfile !== 'custom' && <div style={{ marginTop: 8, padding: '0.65rem', borderRadius: 6, background: 'var(--surface-subtle)', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
              <div><strong>{analytics.generator_manufacturer} {analytics.generator_model}</strong> · {analytics.nominal_frequency_hz} Hz · {analytics.speed_rpm} RPM</div>
              <div>{t('standbyRating')}: {analytics.standby_kw || '—'} kW / {analytics.standby_kva || '—'} kVA · {t('primeRating')}: {analytics.prime_kw || '—'} kW / {analytics.prime_kva || '—'} kVA</div>
              <div>{t('profileEngine')}: {analytics.engine_model || '—'} · {t('publishedFuelPoints', { count: analytics.fuel_curve?.length || 0 })}</div>
            </div>}
            {analytics.datasheet_url && <div style={{ marginTop: 5 }}><a href={analytics.datasheet_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-teal)', fontSize: '0.8rem' }}>{t('viewManufacturerDatasheet')}</a></div>}
          </div>
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
              ['battery_voltage_low_warning', `${t('batteryLow')} (${reportText('optional')})`, 0.1],
            ].map(([key, label, step]) => (
              <div className="form-group" key={key}>
                <label className="form-label" htmlFor={key}>{label}</label>
                <input id={key} type="number" step={step} className="form-input" value={maintenanceLimits[key]} onChange={(e) => setMaintenanceLimits((limits) => ({ ...limits, [key]: e.target.value }))} required={key !== 'battery_voltage_low_warning'} />
              </div>
            ))}
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="maintenance-interval">{t('serviceInterval')}</label>
            <input id="maintenance-interval" type="number" min="25" max="5000" step="25" className="form-input" value={maintenanceInterval} onChange={(e) => setMaintenanceInterval(e.target.value)} required />
          </div>
          <fieldset style={{ border: '1px solid var(--border-subtle)', padding: '0.8rem', marginBottom: '1rem' }}>
            <legend style={{ fontWeight: 600 }}>{reportText('analyticsSettings')}</legend>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginBottom: '0.7rem' }}>{reportText('fuelHelp')}</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(165px,1fr))', gap: '0.6rem' }}>
              <label className="form-group">{reportText('engineModel')}<input className="form-input" value={analytics.engine_model} onChange={e => setAnalytics({ ...analytics, engine_model: e.target.value })} /></label>
              <label className="form-group">{reportText('nominalFrequency')}<select className="form-select" value={analytics.nominal_frequency_hz ?? ''} onChange={e => setAnalytics({ ...analytics, nominal_frequency_hz: e.target.value })}><option value="">—</option><option value="50">50 Hz</option><option value="60">60 Hz</option></select></label>
              <label className="form-group">{reportText('nominalBattery')}<select className="form-select" value={analytics.nominal_battery_voltage ?? ''} onChange={e => setAnalytics({ ...analytics, nominal_battery_voltage: e.target.value })}><option value="">—</option><option value="12">12 V</option><option value="24">24 V</option></select></label>
              <label className="form-group">{reportText('fuelType')}<select className="form-select" value={analytics.fuel_type} onChange={e => setAnalytics({ ...analytics, fuel_type: e.target.value })}>{['diesel','petrol','gas','other'].map(type => <option key={type} value={type}>{reportText(type)}</option>)}</select></label>
              <label className="form-group">{reportText('fuelSource')}<select className="form-select" value={analytics.fuel_source} onChange={e => setAnalytics({ ...analytics, fuel_source: e.target.value })}><option value="counter">{reportText('counter')}</option><option value="flow">{reportText('flow')}</option><option value="tank">{reportText('tank')}</option></select></label>
              <label className="form-group">{reportText('fuelLhv')}<input className="form-input" type="number" min="0.01" step="any" value={analytics.fuel_lhv_kwh_per_litre ?? ''} onChange={e => setAnalytics({ ...analytics, fuel_lhv_kwh_per_litre: e.target.value })} placeholder={reportText('optional')} /></label>
            </div>
            {analytics.fuel_source === 'tank' && <div>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', margin: '0.5rem 0' }}>{reportText('tankHelp')}</p>
              <label className="form-group">{reportText('tankCapacity')}<input type="number" min="1" className="form-input" value={analytics.tank_capacity_litres ?? ''} onChange={e => setAnalytics({ ...analytics, tank_capacity_litres: e.target.value })} /></label>
              <strong>{reportText('tankCurve')}</strong>
              {analytics.tank_curve.map((point, index) => <div key={index} style={{ display: 'flex', gap: '0.4rem', margin: '0.4rem 0' }}>
                <label>{reportText('levelPercent')}<input type="number" min="0" max="100" className="form-input" value={point.percent} onChange={e => setAnalytics({ ...analytics, tank_curve: analytics.tank_curve.map((p,i) => i === index ? { ...p, percent: e.target.value } : p) })} /></label>
                <label>{reportText('tankVolume')}<input type="number" min="0" className="form-input" value={point.litres} onChange={e => setAnalytics({ ...analytics, tank_curve: analytics.tank_curve.map((p,i) => i === index ? { ...p, litres: e.target.value } : p) })} /></label>
                <button className="btn btn-secondary" type="button" onClick={() => setAnalytics({ ...analytics, tank_curve: analytics.tank_curve.filter((_,i) => i !== index) })}>{reportText('remove')}</button>
              </div>)}
              <button className="btn btn-secondary" type="button" onClick={() => setAnalytics({ ...analytics, tank_curve: [...analytics.tank_curve, { percent: '', litres: '' }] })}>{reportText('addPoint')}</button>
            </div>}
            <div style={{ marginTop: '0.65rem' }}><strong>{reportText('fuelCurve')}</strong><p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{reportText('fuelCurveHelp')}</p>
              {analytics.fuel_curve.map((point, index) => <div key={index} style={{ display: 'flex', gap: '0.4rem', margin: '0.4rem 0' }}>
                <label>{reportText('loadPercent')}<input type="number" min="0" max="110" className="form-input" value={point.load_percent} onChange={e => setAnalytics({ ...analytics, fuel_curve: analytics.fuel_curve.map((p,i) => i === index ? { ...p, load_percent: e.target.value } : p) })} /></label>
                <label>{reportText('curveLitresHour')}<input type="number" min="0" step="any" className="form-input" value={point.litres_per_hour} onChange={e => setAnalytics({ ...analytics, fuel_curve: analytics.fuel_curve.map((p,i) => i === index ? { ...p, litres_per_hour: e.target.value } : p) })} /></label>
                <button className="btn btn-secondary" type="button" onClick={() => setAnalytics({ ...analytics, fuel_curve: analytics.fuel_curve.filter((_,i) => i !== index) })}>{reportText('remove')}</button>
              </div>)}
              <button className="btn btn-secondary" type="button" onClick={() => setAnalytics({ ...analytics, fuel_curve: [...analytics.fuel_curve, { load_percent: '', litres_per_hour: '' }] })}>{reportText('addPoint')}</button>
            </div>
          </fieldset>
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
