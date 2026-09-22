import React, { useEffect, useMemo, useState } from 'react';
import { Download } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useReportLocale } from './useReportLocale';

const issueText = {
  insufficient_data: ['Not enough valid readings', 'لا توجد قراءات صالحة كافية'],
  historical_quality_unknown: ['Historical measurement quality is unknown', 'جودة القياسات التاريخية غير معروفة'],
  collection_gap: ['Collection gaps excluded', 'تم استبعاد فترات انقطاع جمع البيانات'],
  source_changed: ['Measurement source changed', 'تغير مصدر القياس'],
  counter_reset: ['Counter reset excluded', 'تم استبعاد فترة تصفير العداد'],
  fuel_unavailable: ['Fuel measurement unavailable', 'قياس الوقود غير متاح'],
  energy_unavailable: ['Energy measurement unavailable', 'قياس الطاقة غير متاح'],
  hours_unavailable: ['Running hours unavailable', 'ساعات التشغيل غير متاحة'],
  estimated_fuel: ['Fuel is estimated', 'الوقود تقديري'],
  integrated_power: ['Energy integrated from power', 'الطاقة مقدرة من القدرة'],
  boundary_estimate: ['Boundary interval estimated', 'فترة حدود التقرير تقديرية'],
  fuel_resolution: ['Insufficient fuel change for a reliable ratio', 'تغير الوقود صغير جدًا لحساب معدل موثوق'],
  zero_output: ['No electrical output', 'لا يوجد إنتاج كهربائي'],
  lhv_missing: ['Fuel heating value is not configured', 'القيمة الحرارية للوقود غير محددة'],
  unrecorded_tank_movement: ['Tank increase requires a refill record', 'ارتفاع الخزان يتطلب تسجيل التعبئة'],
  invalid_tank_calibration: ['Tank calibration is missing', 'معايرة الخزان غير متاحة'],
  meter_timing: ['Meter readings are not synchronized', 'القراءات غير متزامنة'],
};

function saveCsv(blob, name) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const card = { border: '1px solid var(--border-subtle)', background: 'var(--card-bg)', borderRadius: 4, padding: '1rem' };

export function PerformanceReport({ kind, generators = [] }) {
  const { t, locale, formatNumber, formatDate } = useReportLocale();
  const [panelId, setPanelId] = useState('');
  const [period, setPeriod] = useState('30d');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [movementOpen, setMovementOpen] = useState(false);
  const [movement, setMovement] = useState({ occurred_at: '', litres: '', notes: '' });

  const params = useMemo(() => {
    if (period === 'custom' && (!startDate || !endDate || startDate > endDate)) return null;
    const query = new URLSearchParams({ period });
    if (panelId) query.set('panel_id', panelId);
    if (period === 'custom') { query.set('start_date', startDate); query.set('end_date', endDate); }
    return query.toString();
  }, [panelId, period, startDate, endDate]);

  async function refresh() {
    if (params === null) { setError(t('invalidDates')); return; }
    setLoading(true);
    setError('');
    try { setReport(await apiRequest(`/reports/${kind}?${params}`)); }
    catch (exception) { setError(exception.message); setReport(null); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    if (params !== null) refresh();
    else { setReport(null); setError(t('invalidDates')); }
  }, [kind, params]);

  async function exportCsv() {
    if (params === null) return;
    try {
      const token = localStorage.getItem('access_token');
      const result = await fetch(`/api/reports/${kind}/export?${params}&locale=${locale}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!result.ok) throw new Error(t('exportFailed'));
      saveCsv(await result.blob(), `${locale === 'ar' ? (kind === 'fuel' ? 'استهلاك_الوقود' : 'كفاءة_المولد') : kind}_${period}.csv`);
    } catch (exception) { setError(exception.message); }
  }

  async function saveMovement(event) {
    event.preventDefault();
    try {
      await apiRequest(`/reports/fuel/movements/${panelId}`, { method: 'POST', body: JSON.stringify({
        occurred_at: new Date(movement.occurred_at).toISOString(), litres: Number(movement.litres), notes: movement.notes,
      }) });
      setMovementOpen(false);
      setMovement({ occurred_at: '', litres: '', notes: '' });
      await refresh();
    } catch (exception) { setError(exception.message); }
  }

  const current = panelId ? report?.generators?.[0] : report?.fleet;
  const indicators = kind === 'fuel'
    ? [['fuelLitres', 'fuel_litres', 'litresUnit'], ['runHoursNew', 'run_hours', 'hoursShort'], ['litresPerHour', 'litres_per_hour', 'litresHourUnit'], ['coverageHelp', 'coverage_percent', '%']]
    : [['energyKwhNew', 'energy_kwh', 'kWh'], ['fuelLitres', 'matched_fuel_litres', 'litresUnit'], ['kwhPerLitre', 'kwh_per_litre', 'kwhLitreUnit'], ['litresPerKwh', 'litres_per_kwh', 'litresKwhUnit'], ['averageOutput', 'average_output_kw', 'kW'], ['conversionEfficiency', 'efficiency_percent', '%'], ['matchedCoverage', 'matched_coverage_percent', '%']];
  const daily = current?.daily || [];
  const maxDaily = Math.max(...daily.map((row) => row[kind === 'fuel' ? 'fuel_litres' : 'energy_kwh'] || 0), 1);
  const show = (value, digits = 2) => value === null || value === undefined ? '—' : formatNumber(value, { maximumFractionDigits: digits });

  return <section>
    <div className="page-header" style={{ alignItems: 'center' }}>
      <div><h2 className="page-title">{t(kind === 'fuel' ? 'fuelReport' : 'efficiencyReport')}</h2>
        <p className="page-subtitle">{t(kind === 'fuel' ? 'fuelHelp' : 'efficiencyHelp')}</p></div>
      <button className="btn btn-primary" onClick={exportCsv} disabled={!report || loading}><Download size={15} /> {t('exportReport')}</button>
    </div>
    <div style={{ ...card, display: 'flex', gap: '0.75rem', alignItems: 'end', flexWrap: 'wrap', marginBottom: '1rem' }}>
      <label className="form-group" style={{ margin: 0 }}>{t('selectGenerator')}
        <select className="form-select" value={panelId} onChange={(e) => setPanelId(e.target.value)}>
          <option value="">{t('allGenerators')}</option>{generators.map((g) => <option value={g.panel_id || g.id} key={g.panel_id || g.id}>{g.name}</option>)}
        </select></label>
      <label className="form-group" style={{ margin: 0 }}>{t('period')}
        <select className="form-select" value={period} onChange={(e) => setPeriod(e.target.value)}>
          {[['today', t('today')], ['7d', t('sevenDays')], ['30d', t('thirtyDays')], ['all', t('allTime')], ['custom', t('customRange')]].map(([key,label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
      {period === 'custom' && <>
        <label className="form-group" style={{ margin: 0 }}>{t('fromDate')}<input className="form-input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></label>
        <label className="form-group" style={{ margin: 0 }}>{t('toDate')}<input className="form-input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></label>
      </>}
      <button className="btn btn-secondary" onClick={refresh} disabled={loading}>{t('refresh')}</button>
      {kind === 'fuel' && panelId && <button className="btn btn-secondary" onClick={() => setMovementOpen(!movementOpen)}>{t('recordFuelMovement')}</button>}
    </div>
    {movementOpen && panelId && <form onSubmit={saveMovement} style={{ ...card, marginBottom: '1rem' }}>
      <strong>{t('recordFuelMovement')}</strong><p style={{ color: 'var(--text-secondary)', margin: '0.5rem 0' }}>{t('movementHelp')}</p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem' }}>
        <label>{t('movementDate')} <input required type="datetime-local" className="form-input" value={movement.occurred_at} onChange={e => setMovement({ ...movement, occurred_at: e.target.value })} /></label>
        <label>{t('movementLitres')} <input required type="number" step="0.01" className="form-input" value={movement.litres} onChange={e => setMovement({ ...movement, litres: e.target.value })} /></label>
        <label>{t('serviceNotes')} <input className="form-input" value={movement.notes} onChange={e => setMovement({ ...movement, notes: e.target.value })} /></label>
        <button className="btn btn-primary" type="submit">{t('saveService')}</button>
      </div>
    </form>}
    {error && <p role="alert" style={{ ...card, background: 'var(--danger-bg)', color: 'var(--status-alarm)', marginBottom: '1rem' }}>{error}</p>}
    {loading && <p>{t('loadingReport')}</p>}
    {report && <>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>{t('reportTimezone')}: {report.timezone} · {t('unavailableNote')}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
        {indicators.map(([label, value, unit]) => <div key={value} style={card}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{t(label)}</div>
          <div className="tabular-nums" style={{ fontSize: '1.3rem', fontWeight: 600 }}>{show(current?.[value])} <small>{unit === '%' || unit === 'kWh' || unit === 'kW' ? unit : t(unit)}</small></div>
        </div>)}
      </div>
      {current?.estimated && <p style={{ color: 'var(--status-warning)', marginBottom: '0.75rem' }}>{t('estimated')} · {t('source')}: {current.source}</p>}
      <div style={{ ...card, marginBottom: '1rem' }}>
        <strong>{t('qualityNotes')}</strong>
        {current?.issues?.length ? <ul style={{ margin: '0.5rem 1.25rem', color: 'var(--text-secondary)' }}>{current.issues.map((issue) => <li key={issue}>{issueText[issue]?.[locale === 'ar' ? 1 : 0] || issue}</li>)}</ul> : <p style={{ marginTop: '0.5rem' }}>{t('noData')}</p>}
      </div>
      {daily.length > 0 && <div style={{ ...card, marginBottom: '1rem' }}>
        <strong>{t('dailyTrend')}</strong>
        <div role="img" aria-label={t('dailyTrend')} style={{ display: 'flex', alignItems: 'end', gap: 3, height: 110, marginTop: '0.75rem', overflowX: 'auto' }}>
          {daily.map((row) => <div key={row.date} title={`${row.date}: ${show(row[kind === 'fuel' ? 'fuel_litres' : 'energy_kwh'])}`} style={{ flex: '1 0 4px', height: `${Math.max(2, 100 * (row[kind === 'fuel' ? 'fuel_litres' : 'energy_kwh'] || 0) / maxDaily)}%`, background: 'var(--accent-teal)', borderRadius: '2px 2px 0 0' }} />)}
        </div>
        <div style={{ overflowX: 'auto', maxHeight: 280 }}><table className="data-table"><thead><tr><th>{t('dateColumn')}</th><th>{t('fuelLitres')}</th><th>{t('energyKwhNew')}</th><th>{t('matchedCoverage')}</th></tr></thead>
          <tbody>{daily.map((row) => <tr key={row.date}><td>{formatDate(`${row.date}T12:00:00`)}</td><td>{show(row.fuel_litres)}</td><td>{show(row.energy_kwh)}</td><td>{show(row.matched_coverage_percent)}%</td></tr>)}</tbody></table></div>
      </div>}
      {!panelId && report.generators.length > 0 && <div style={{ ...card, marginBottom: '1rem', overflowX: 'auto' }}>
        <strong>{t('generatorBreakdown')}</strong><table className="data-table"><thead><tr><th>{t('generatorUnit')}</th><th>{t('fuelLitres')}</th><th>{t('energyKwhNew')}</th><th>{t('litresPerHour')}</th><th>{t('kwhPerLitre')}</th><th>{t('matchedCoverage')}</th></tr></thead>
        <tbody>{report.generators.map((row) => <tr key={row.panel_id}><td>{row.name}</td><td>{show(row.fuel_litres)}</td><td>{show(row.energy_kwh)}</td><td>{show(row.litres_per_hour)}</td><td>{show(row.kwh_per_litre)}</td><td>{show(row.matched_coverage_percent)}%</td></tr>)}</tbody></table>
      </div>}
      {kind === 'efficiency' && panelId && current?.load_bands?.length > 0 && <div style={{ ...card, overflowX: 'auto' }}>
        <strong>{t('loadBands')}</strong><table className="data-table"><thead><tr><th>{t('loadBand')}</th><th>{t('fuelLitres')}</th><th>{t('energyKwhNew')}</th><th>{t('litresPerKwh')}</th></tr></thead>
        <tbody>{current.load_bands.map((band) => <tr key={band.label}><td>{band.label}</td><td>{show(band.fuel_litres)}</td><td>{show(band.energy_kwh)}</td><td>{show(band.litres_per_kwh)}</td></tr>)}</tbody></table>
      </div>}
      {kind === 'efficiency' && current?.efficiency_percent == null && <p style={{ color: 'var(--text-secondary)', marginTop: '0.75rem' }}>{t('lhvHelp')}</p>}
    </>}
  </section>;
}
