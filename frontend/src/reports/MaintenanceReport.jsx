import React, { useEffect, useState } from 'react';
import { Download, Wrench, AlertTriangle } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useReportLocale } from './useReportLocale';

const components = ['oil', 'oil_filter', 'fuel_filter', 'air_filter', 'coolant', 'battery', 'belts', 'hoses', 'custom'];
const card = { background: 'var(--card-bg)', border: '1px solid var(--border-subtle)', borderRadius: 4, padding: '1rem', marginBottom: '1rem' };
const blankTask = { component: 'oil', name: '', interval_hours: '', interval_days: '', baseline_date: '', baseline_run_hours: '', manufacturer_reference: '', active: true };
const arabicFindings = {
  coolant_temperature: ['ارتفاع حرارة سائل التبريد عند حمل مماثل', 'افحص سائل التبريد وتدفق الهواء والثرموستات والمروحة.'],
  oil_pressure: ['انخفاض ضغط الزيت عند حمل مماثل', 'افحص مستوى الزيت ونوعه والمرشحات والتسربات وتحقق بمقياس معاير.'],
  oil_temperature: ['ارتفاع حرارة الزيت عند حمل مماثل', 'افحص نظام التزييت والتبريد أثناء الحمل.'],
  battery_voltage: ['انخفاض جهد بطارية التشغيل', 'افحص نظام الشحن والأطراف والبطارية وأداء بدء التشغيل.'],
  fuel_efficiency: ['ازدياد استهلاك الوقود للإنتاج نفسه', 'افحص الوقود والمرشحات وتوزيع الحمل وحالة المحرك.'],
  alarms: ['إنذارات وحدة التحكم تستلزم الفحص', 'عالج سبب الإنذار وتحقق منه فنيًا.'],
};

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function MaintenanceReport({ generators = [], selectedPanel = '', onSelectPanel }) {
  const { t, locale, formatNumber, formatDate, translateText } = useReportLocale();
  const [panelId, setPanelId] = useState(selectedPanel);
  const [period, setPeriod] = useState('30d');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [task, setTask] = useState(null);
  const [selected, setSelected] = useState([]);
  const [service, setService] = useState({ service_date: new Date().toISOString().slice(0, 10), run_hours: '', service_type: 'Preventive service', performed_by: '', notes: '', checklist_confirmed: false });
  const [findingForm, setFindingForm] = useState(null);
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => { if (selectedPanel) setPanelId(selectedPanel); }, [selectedPanel]);
  useEffect(() => {
    if (!panelId && generators.length) setPanelId(generators[0].panel_id || generators[0].id);
  }, [generators, panelId]);
  useEffect(() => { if (panelId) refresh(panelId); }, [panelId, period, startDate, endDate]);

  const reportParams = () => {
    if (period === 'custom' && (!startDate || !endDate || startDate > endDate)) return null;
    const query = new URLSearchParams({ period });
    if (period === 'custom') { query.set('start_date', startDate); query.set('end_date', endDate); }
    return query.toString();
  };

  async function refresh(id = panelId) {
    const params = reportParams();
    if (!params) { setReport(null); setError(t('invalidDates')); setLoading(false); return; }
    setLoading(true); setError('');
    try {
      const data = await apiRequest(`/reports/maintenance/${id}?${params}`);
      setReport(data);
      if (data.current_run_hours !== null) setService(previous => ({ ...previous, run_hours: previous.run_hours || String(data.current_run_hours) }));
    }
    catch (exception) { setError(exception.message); setReport(null); }
    finally { setLoading(false); }
  }

  async function exportCsv() {
    const params = reportParams();
    if (!params) { setError(t('invalidDates')); return; }
    try {
      const token = localStorage.getItem('access_token');
      const result = await fetch(`/api/reports/maintenance/${panelId}/export?${params}&locale=${locale}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!result.ok) throw new Error(t('maintenanceExportFailed'));
      download(await result.blob(), `${locale === 'ar' ? 'الصيانة_الوقائية' : 'preventive_maintenance'}_${report.generator_name}.csv`);
    } catch (exception) { setError(exception.message); }
  }

  async function saveTask(event) {
    event.preventDefault();
    if ((!task.interval_hours && !task.interval_days) || (task.interval_hours && task.baseline_run_hours === '') || (task.interval_days && !task.baseline_date)) {
      setError(t('taskValidation')); return;
    }
    const body = { component: task.component, name: task.name.trim(),
      interval_hours: task.interval_hours ? Number(task.interval_hours) : null,
      interval_days: task.interval_days ? Number(task.interval_days) : null,
      baseline_date: task.baseline_date || null,
      baseline_run_hours: task.baseline_run_hours === '' ? null : Number(task.baseline_run_hours),
      manufacturer_reference: task.manufacturer_reference.trim() || null, active: true };
    try {
      await apiRequest(`/reports/maintenance/${panelId}/tasks${task.id ? `/${task.id}` : ''}`, { method: task.id ? 'PATCH' : 'POST', body: JSON.stringify(body) });
      setTask(null); setError(''); await refresh();
    } catch (exception) { setError(exception.message); }
  }

  async function archiveTask(id) {
    if (!window.confirm(t('archiveConfirm'))) return;
    try { await apiRequest(`/reports/maintenance/${panelId}/tasks/${id}`, { method: 'DELETE' }); await refresh(); }
    catch (exception) { setError(exception.message); }
  }

  async function complete(event) {
    event.preventDefault();
    if (!selected.length) { setError(t('selectTaskRequired')); return; }
    try {
      await apiRequest(`/reports/maintenance/${panelId}/complete`, { method: 'POST', body: JSON.stringify({
        service_date: service.service_date, run_hours: Number(service.run_hours), task_ids: selected,
        checklist_confirmed: service.checklist_confirmed, service_type: service.service_type,
        performed_by: service.performed_by || null, notes: service.notes || null,
      }) });
      setSelected([]); setService({ ...service, checklist_confirmed: false, notes: '' });
      setNotice(t('serviceSavedNew')); await refresh();
    } catch (exception) { setError(exception.message); }
  }

  async function recordWork(event) {
    event.preventDefault();
    try {
      const path = findingForm.status === 'awaiting_verification' && findingForm.verification_kind === 'inspection' ? 'verify' : 'work';
      await apiRequest(`/reports/maintenance/${panelId}/findings/${findingForm.id}/${path}`, { method: 'POST', body: JSON.stringify({ resolution_note: note.trim(), inspection_confirmed: confirmed }) });
      setFindingForm(null); setNote(''); setConfirmed(false); setNotice(t('findingSaved')); await refresh();
    } catch (exception) { setError(exception.message); }
  }

  const value = (v, digits = 1) => v === null || v === undefined ? '—' : formatNumber(v, { maximumFractionDigits: digits });
  const findingText = (finding) => {
    if (locale !== 'ar' || !arabicFindings[finding.metric]) return [translateText(finding.title), translateText(finding.detail), translateText(finding.recommendation)];
    const evidence = finding.evidence || {};
    const detail = evidence.baseline !== undefined && evidence.trigger !== undefined
      ? `تغيرت القراءة من ${value(evidence.baseline, 2)} إلى ${value(evidence.trigger, 2)} في ظروف تشغيل مماثلة.`
      : 'إنذارات نشطة بوحدة التحكم تحتاج للفحص.';
    return [arabicFindings[finding.metric][0], detail, arabicFindings[finding.metric][1]];
  };
  return <section>
    <div className="page-header" style={{ alignItems: 'center' }}><div>
      <h2 className="page-title"><Wrench size={20} /> {t('preventiveMaintenance')}</h2>
      <p className="page-subtitle">{t('taskScheduleHelp')}</p></div>
      <button type="button" className="btn btn-primary" onClick={exportCsv} disabled={!report}><Download size={15} /> {t('exportReport')}</button>
    </div>
    <div style={{ ...card, display: 'flex', gap: '0.75rem', alignItems: 'end', flexWrap: 'wrap' }}>
      <label className="form-group" style={{ margin: 0 }}>{t('selectGenerator')}
        <select className="form-select" value={panelId} onChange={(event) => { setPanelId(event.target.value); onSelectPanel?.(event.target.value); setTask(null); }}>
          {generators.map((g) => <option key={g.panel_id || g.id} value={g.panel_id || g.id}>{g.name}</option>)}
        </select></label>
      <label className="form-group" style={{ margin: 0 }}>{t('period')}
        <select className="form-select" value={period} onChange={(event) => setPeriod(event.target.value)}>
          {[['today', t('today')], ['7d', t('sevenDays')], ['30d', t('thirtyDays')], ['all', t('allTime')], ['custom', t('customRange')]].map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
      {period === 'custom' && <>
        <label className="form-group" style={{ margin: 0 }}>{t('fromDate')}<input className="form-input" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
        <label className="form-group" style={{ margin: 0 }}>{t('toDate')}<input className="form-input" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
      </>}
      <button className="btn btn-secondary" type="button" onClick={() => refresh()} disabled={!panelId || loading}>{t('refresh')}</button>
    </div>
    <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{t('maintenanceDateScope')}</p>
    {!generators.length && <p>{t('noGenerators')}</p>}
    {loading && <p>{t('loadingReport')}</p>}
    {error && <p role="alert" style={{ ...card, background: 'var(--danger-bg)', color: 'var(--status-alarm)' }}>{error}</p>}
    {notice && <p role="status" style={{ ...card, background: 'var(--success-bg)', color: 'var(--status-running)' }}>{notice}</p>}
    {report && <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: '0.75rem' }}>
        {[[t('maintenanceCompliance'), report.maintenance_compliance_percent === null ? '—' : `${value(report.maintenance_compliance_percent)}%`, t('complianceHelp')],
          [t('monitoredCondition'), t(report.monitored_condition), t('conditionHelp')],
          [t('dataCoverage'), `${value(report.data_coverage_percent)}%`, t('coverageHelp')]].map(([label, v, help]) => <div key={label} style={card}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{label}</div><strong style={{ fontSize: '1.4rem' }}>{v}</strong>
            <div style={{ color: 'var(--text-tertiary)', fontSize: '0.75rem' }}>{help}</div></div>)}
      </div>
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}><div><strong>{t('taskSchedules')}</strong><p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{t('manufacturerHelp')}</p></div>
          <button type="button" className="btn btn-secondary" onClick={() => setTask({ ...blankTask })}>{t('addTask')}</button></div>
        {!report.tasks.length && <p style={{ color: 'var(--text-secondary)', marginTop: '0.75rem' }}>{t('noTasks')}</p>}
        <div style={{ overflowX: 'auto' }}><table className="data-table"><thead><tr><th>{t('taskName')}</th><th>{t('component')}</th><th>{t('condition')}</th><th>{t('dueAt')}</th><th>{t('remaining')}</th><th>{t('actions')}</th></tr></thead>
          <tbody>{report.tasks.map((row) => <tr key={row.id}>
            <td>{row.name}</td><td>{t(row.component)}</td><td>{t(row.status)}</td>
            <td>{row.next_due_date || '—'} {row.next_due_run_hours !== null && `· ${value(row.next_due_run_hours)} ${t('hoursUnit')}`}</td>
            <td>{row.remaining_days !== null && `${value(row.remaining_days)} ${t('daysUnit')}`} {row.remaining_hours !== null && `· ${value(row.remaining_hours)} ${t('hoursUnit')}`}</td>
            <td><button type="button" className="btn btn-secondary" onClick={() => setTask({ ...row, interval_hours: row.interval_hours ?? '', interval_days: row.interval_days ?? '', baseline_date: row.baseline_date || '', baseline_run_hours: row.baseline_run_hours ?? '', manufacturer_reference: row.manufacturer_reference || '' })}>{t('editTask')}</button>
              {' '}<button type="button" className="btn btn-danger" onClick={() => archiveTask(row.id)}>{t('archiveTask')}</button></td>
          </tr>)}</tbody></table></div>
        {task && <form onSubmit={saveTask} style={{ marginTop: '1rem', padding: '1rem', background: 'var(--surface-subtle)' }}>
          <h3>{t(task.id ? 'editTask' : 'addTask')}</h3><p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{t('intervalHelp')}</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: '0.6rem' }}>
            <label className="form-group">{t('component')}<select className="form-select" value={task.component} onChange={e => setTask({ ...task, component: e.target.value })}>{components.map(c => <option key={c} value={c}>{t(c)}</option>)}</select></label>
            <label className="form-group">{t('taskName')}<input required className="form-input" value={task.name} onChange={e => setTask({ ...task, name: e.target.value })} /></label>
            <label className="form-group">{t('intervalHours')}<input type="number" min="0.1" step="0.1" className="form-input" value={task.interval_hours} onChange={e => setTask({ ...task, interval_hours: e.target.value })} /></label>
            <label className="form-group">{t('intervalDays')}<input type="number" min="1" className="form-input" value={task.interval_days} onChange={e => setTask({ ...task, interval_days: e.target.value })} /></label>
            <label className="form-group">{t('baselineDate')}<input type="date" className="form-input" value={task.baseline_date} onChange={e => setTask({ ...task, baseline_date: e.target.value })} /></label>
            <label className="form-group">{t('baselineHours')}<input type="number" min="0" step="0.1" className="form-input" value={task.baseline_run_hours} onChange={e => setTask({ ...task, baseline_run_hours: e.target.value })} /></label>
            <label className="form-group">{t('manufacturerReference')}<input className="form-input" value={task.manufacturer_reference} onChange={e => setTask({ ...task, manufacturer_reference: e.target.value })} /></label>
          </div><button className="btn btn-primary" type="submit">{t('saveService')}</button>{' '}
          <button className="btn btn-secondary" type="button" onClick={() => setTask(null)}>{t('cancel')}</button>
        </form>}
      </div>
      <div style={card}>
        <strong>{t('recordSelectedService')}</strong><p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{t('taskCompletionHelp')}</p>
        <form onSubmit={complete}>
          {report.tasks.map(row => <label key={row.id} style={{ display: 'inline-flex', margin: '0.5rem 1rem 0.5rem 0', gap: '0.35rem' }}>
            <input type="checkbox" checked={selected.includes(row.id)} onChange={e => setSelected(e.target.checked ? [...selected, row.id] : selected.filter(id => id !== row.id))} />{row.name}</label>)}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: '0.6rem', marginTop: '0.8rem' }}>
            <label>{t('serviceDate')}<input required type="date" className="form-input" value={service.service_date} onChange={e => setService({ ...service, service_date: e.target.value })} /></label>
            <label>{t('runningHoursAtService')}<input required type="number" min="0" step="0.1" className="form-input" value={service.run_hours} onChange={e => setService({ ...service, run_hours: e.target.value })} /></label>
            <label>{t('serviceType')}<input required className="form-input" value={service.service_type} onChange={e => setService({ ...service, service_type: e.target.value })} /></label>
            <label>{t('performedBy')}<input className="form-input" value={service.performed_by} onChange={e => setService({ ...service, performed_by: e.target.value })} /></label>
            <label>{t('serviceNotes')}<input className="form-input" value={service.notes} onChange={e => setService({ ...service, notes: e.target.value })} /></label>
          </div>
          <label style={{ display: 'block', margin: '0.7rem 0' }}><input type="checkbox" required checked={service.checklist_confirmed} onChange={e => setService({ ...service, checklist_confirmed: e.target.checked })} /> {t('completionChecklist')}</label>
          <button className="btn btn-primary" type="submit" disabled={!selected.length}>{t('saveService')}</button>
        </form>
      </div>
      <div style={card}>
        <strong>{t('findings')}</strong>
        {!report.findings.length && <p style={{ color: 'var(--text-secondary)', marginTop: '0.5rem' }}>{t('noFindings')}</p>}
        {report.findings.map(finding => <div key={finding.id} style={{ borderTop: '1px solid var(--border-subtle)', padding: '0.8rem 0' }}>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}><AlertTriangle size={18} color="var(--status-warning)" /><strong>{findingText(finding)[0]}</strong> · {t(finding.status)}</div>
          <p style={{ color: 'var(--text-secondary)' }}>{findingText(finding)[1]}</p>
          <p>{t('recommendedAction')} {findingText(finding)[2]}</p>
          <button type="button" className="btn btn-secondary" onClick={() => { setFindingForm(finding); setNote(''); setConfirmed(false); }}>{t(finding.verification_kind === 'inspection' ? 'verifyInspection' : 'workAction')}</button>
        </div>)}
        {findingForm && <form onSubmit={recordWork} style={{ background: 'var(--surface-subtle)', padding: '1rem' }}>
          <strong>{t(findingForm.verification_kind === 'inspection' ? 'verifyInspection' : 'workAction')}</strong>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{t(findingForm.verification_kind === 'inspection' ? 'verifyHelp' : 'workHelp')}</p>
          <label className="form-group">{t('workNote')}<textarea required minLength={3} className="form-input" value={note} onChange={e => setNote(e.target.value)} /></label>
          {findingForm.verification_kind === 'inspection' && <label><input required type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> {t('verifyChecklist')}</label>}
          <div><button className="btn btn-primary" type="submit">{t('saveService')}</button>{' '}<button className="btn btn-secondary" type="button" onClick={() => setFindingForm(null)}>{t('cancel')}</button></div>
        </form>}
      </div>
      <div style={{ ...card, overflowX: 'auto' }}><strong>{t('completedServiceHistory')}</strong><table className="data-table"><thead><tr><th>{t('serviceDate')}</th><th>{t('runningHours')}</th><th>{t('serviceType')}</th><th>{t('performedBy')}</th><th>{t('serviceNotes')}</th><th>{t('classifiedTasks')}</th></tr></thead>
        <tbody>{report.service_history.map(record => <tr key={record.id}><td>{formatDate(`${record.service_date}T12:00:00`)}</td><td>{value(record.run_hours)}</td><td>{record.service_type}</td><td>{record.performed_by || '—'}</td><td>{record.notes || '—'}</td><td>{record.task_ids.length ? record.task_ids.map(id => report.tasks.find(task => task.id === id)?.name || id).join(', ') : t('legacyRecord')}</td></tr>)}</tbody></table>
        <button className="btn btn-secondary" type="button" onClick={async () => {
          try { const params = reportParams(); if (!params) throw new Error(t('invalidDates')); const token = localStorage.getItem('access_token'); const response = await fetch(`/api/reports/preventive-maintenance/${panelId}/records/export?${params}&locale=${locale}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} }); if (!response.ok) throw new Error(t('serviceExportFailed')); download(await response.blob(), `${locale === 'ar' ? 'سجل_الصيانة' : 'service_history'}.csv`); }
          catch (exception) { setError(exception.message); }
        }}>{t('exportServiceHistory')}</button>
      </div>
      <p style={{ color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>{t('conditionHelp')} {t('unavailableNote')}</p>
    </>}
  </section>;
}
