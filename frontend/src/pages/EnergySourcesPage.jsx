import React, { useEffect, useMemo, useState } from 'react';
import { Activity, Building2, RefreshCw, Send, Sun, UtilityPole } from 'lucide-react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

const copy = {
  en: {
    title: 'Energy Sources', subtitle: 'Live facility demand and contribution from every electrical source',
    facilityLoad: 'Total facility load', solar: 'Solar production', grid: 'Utility grid', generators: 'Generator output',
    import: 'Import', export: 'Export', connected: 'Connected', disconnected: 'Disconnected',
    live: 'Live', stale: 'Stale', noReading: 'No source reading received', lastReading: 'Last source reading', refresh: 'Refresh',
    balance: 'Power balance', balanceHelp: 'Load minus solar, grid, and reported generator output. A large difference can indicate timing, meter, or scaling issues.',
    demand: 'Demand', supplied: 'Measured supply', difference: 'Difference',
    commissioning: 'Commissioning / simulator input', commissioningHelp: 'Use this form to test the page. In production, the facility meter, solar inverter, and grid meter should post the same fields automatically.',
    loadKw: 'Facility load (kW)', solarKw: 'Solar output (kW)', gridKw: 'Grid power (kW)',
    gridHint: 'Positive = import, negative = export', gridConnected: 'Grid available', busEnergized: 'Facility bus energized',
    submit: 'Record reading', saving: 'Recording…', recorded: 'Reading recorded successfully.',
    apiFeed: 'External integration endpoint', apiHelp: 'Your simulator or commissioned Modbus gateway can send readings here:',
    missingGrid: 'Grid power has not been supplied yet.', fetchFailed: 'Could not load energy-source readings.', submitFailed: 'Could not record the reading.',
  },
  ar: {
    title: 'مصادر الطاقة', subtitle: 'الطلب اللحظي للمنشأة ومساهمة كل مصدر كهربائي',
    facilityLoad: 'الحمل الكلي للمنشأة', solar: 'إنتاج الطاقة الشمسية', grid: 'شبكة الكهرباء', generators: 'خرج المولدات',
    import: 'استيراد', export: 'تصدير', connected: 'متصلة', disconnected: 'غير متصلة',
    live: 'مباشر', stale: 'قراءة قديمة', noReading: 'لم تُستقبل قراءة للمصادر', lastReading: 'آخر قراءة للمصادر', refresh: 'تحديث',
    balance: 'موازنة القدرة', balanceHelp: 'الحمل مطروحًا منه إنتاج الشمس والشبكة وخرج المولدات المبلغ عنه. قد يدل الفرق الكبير على اختلاف توقيت القراءات أو إعداد العداد أو معامل التحويل.',
    demand: 'الطلب', supplied: 'الإمداد المقاس', difference: 'الفرق',
    commissioning: 'إدخال الاختبار / المحاكي', commissioningHelp: 'استخدم هذا النموذج لاختبار الصفحة. في التشغيل الفعلي ترسل عدادات المنشأة والشبكة وعاكس الطاقة الشمسية الحقول نفسها تلقائيًا.',
    loadKw: 'حمل المنشأة (كيلوواط)', solarKw: 'خرج الطاقة الشمسية (كيلوواط)', gridKw: 'قدرة الشبكة (كيلوواط)',
    gridHint: 'الموجب استيراد والسالب تصدير', gridConnected: 'الشبكة متاحة', busEnergized: 'قضبان المنشأة مكهربة',
    submit: 'تسجيل القراءة', saving: 'جارٍ التسجيل…', recorded: 'تم تسجيل القراءة بنجاح.',
    apiFeed: 'نقطة تكامل خارجية', apiHelp: 'يمكن للمحاكي أو بوابة Modbus المهيأة إرسال القراءات هنا:',
    missingGrid: 'لم تُرسل قدرة الشبكة حتى الآن.', fetchFailed: 'تعذر تحميل قراءات مصادر الطاقة.', submitFailed: 'تعذر تسجيل القراءة.',
  },
};

function MetricCard({ icon, label, value, detail, tone = 'var(--accent-teal)' }) {
  return (
    <section style={{ background: 'var(--card-bg)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '1.25rem', minHeight: 150 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: 'var(--text-secondary)' }}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span style={{ color: tone }}>{icon}</span>
      </div>
      <div className="tabular-nums" style={{ fontSize: '2rem', fontWeight: 700, marginTop: '1.25rem' }}>{value}</div>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem', marginTop: '0.35rem' }}>{detail}</div>
    </section>
  );
}

export function EnergySourcesPage({ currentSite, panelStates = {} }) {
  const { locale, formatNumber, formatTime } = useLocale();
  const text = copy[locale] || copy.en;
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState({ load_kw: '', solar_kw: '0', grid_kw: '0', grid_connected: true, bus_energized: true });

  const generatorKw = useMemo(() => Object.values(panelStates).reduce((sum, state) => {
    const running = state?.is_running || ['running', 'on_load'].includes(state?.engine_status);
    return sum + (running ? Number(state?.load_kw || 0) : 0);
  }, 0), [panelStates]);

  async function loadReading(showError = true) {
    if (!currentSite?.id) return;
    try {
      const result = await apiRequest(`/sites/${currentSite.id}/dispatch`);
      setData(result);
      setError('');
    } catch (err) {
      if (showError) setError(err.message || text.fetchFailed);
    }
  }

  useEffect(() => {
    loadReading();
    const timer = window.setInterval(() => loadReading(false), 3000);
    return () => window.clearInterval(timer);
  }, [currentSite?.id, locale]);

  const reading = data?.measurement;
  const loadKw = Number(reading?.load_kw || 0);
  const solarKw = Number(reading?.solar_kw || 0);
  const gridKw = reading?.grid_kw === null || reading?.grid_kw === undefined ? null : Number(reading.grid_kw);
  const suppliedKw = solarKw + (gridKw || 0) + generatorKw;
  const differenceKw = loadKw - suppliedKw;
  const gridDirection = gridKw === null ? text.missingGrid : `${gridKw >= 0 ? text.import : text.export} · ${reading?.grid_connected ? text.connected : text.disconnected}`;

  async function submitReading(event) {
    event.preventDefault();
    setSaving(true);
    setNotice('');
    setError('');
    try {
      await apiRequest(`/sites/${currentSite.id}/dispatch/measurement`, {
        method: 'POST',
        body: JSON.stringify({
          measured_at: new Date().toISOString(),
          load_kw: Number(form.load_kw), solar_kw: Number(form.solar_kw), grid_kw: Number(form.grid_kw),
          grid_connected: form.grid_connected, bus_energized: form.bus_energized,
        }),
      });
      setNotice(text.recorded);
      await loadReading();
    } catch (err) {
      setError(err.message || text.submitFailed);
    } finally {
      setSaving(false);
    }
  }

  const number = (value) => `${formatNumber(value, { maximumFractionDigits: 1 })} kW`;
  return (
    <div>
      <div className="page-header">
        <div><h1 className="page-title">{text.title}</h1><p className="page-subtitle">{text.subtitle}</p></div>
        <button type="button" className="btn btn-secondary" onClick={() => loadReading()} style={{ display: 'flex', gap: 7, alignItems: 'center' }}><RefreshCw size={15} />{text.refresh}</button>
      </div>

      {error && <div style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', padding: '0.8rem 1rem', borderRadius: 8, marginBottom: '1rem' }}>{error}</div>}
      {notice && <div style={{ background: 'var(--success-bg)', border: '1px solid var(--success-border)', padding: '0.8rem 1rem', borderRadius: 8, marginBottom: '1rem' }}>{notice}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '1rem' }}>
        <MetricCard icon={<Building2 size={23} />} label={text.facilityLoad} value={reading ? number(loadKw) : '—'} detail={data?.measurement_fresh ? text.live : (reading ? text.stale : text.noReading)} />
        <MetricCard icon={<Sun size={23} />} label={text.solar} value={reading ? number(solarKw) : '—'} detail={reading ? text.live : text.noReading} tone="var(--status-warning)" />
        <MetricCard icon={<UtilityPole size={23} />} label={text.grid} value={gridKw === null ? '—' : number(Math.abs(gridKw))} detail={gridDirection} />
        <MetricCard icon={<Activity size={23} />} label={text.generators} value={number(generatorKw)} detail={text.live} tone="var(--status-running)" />
      </div>

      {reading && <section style={{ marginTop: '1rem', background: 'var(--card-bg)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '1.25rem' }}>
        <h2 style={{ fontSize: '1.05rem' }}>{text.balance}</h2>
        <p style={{ color: 'var(--text-secondary)', marginTop: 4, fontSize: '0.875rem' }}>{text.balanceHelp}</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2rem', marginTop: '1rem' }}>
          <span>{text.demand}: <strong className="tabular-nums">{number(loadKw)}</strong></span>
          <span>{text.supplied}: <strong className="tabular-nums">{gridKw === null ? '—' : number(suppliedKw)}</strong></span>
          <span>{text.difference}: <strong className="tabular-nums">{gridKw === null ? '—' : number(differenceKw)}</strong></span>
          <span style={{ color: 'var(--text-secondary)' }}>{text.lastReading}: {data.measured_at ? formatTime(data.measured_at) : '—'}</span>
        </div>
      </section>}

      <section style={{ marginTop: '1rem', background: 'var(--card-bg)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '1.25rem' }}>
        <h2 style={{ fontSize: '1.05rem' }}>{text.commissioning}</h2>
        <p style={{ color: 'var(--text-secondary)', marginTop: 4 }}>{text.commissioningHelp}</p>
        <form onSubmit={submitReading} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '1rem', alignItems: 'end', marginTop: '1rem' }}>
          {['load_kw', 'solar_kw', 'grid_kw'].map((field) => <label key={field} className="form-group" style={{ margin: 0 }}><span>{field === 'load_kw' ? text.loadKw : field === 'solar_kw' ? text.solarKw : text.gridKw}</span><input className="form-input" type="number" step="0.1" required value={form[field]} onChange={(e) => setForm({ ...form, [field]: e.target.value })} /><small style={{ color: 'var(--text-tertiary)' }}>{field === 'grid_kw' ? text.gridHint : ' '}</small></label>)}
          <div style={{ display: 'grid', gap: 8 }}><label><input type="checkbox" checked={form.grid_connected} onChange={(e) => setForm({ ...form, grid_connected: e.target.checked })} /> {text.gridConnected}</label><label><input type="checkbox" checked={form.bus_energized} onChange={(e) => setForm({ ...form, bus_energized: e.target.checked })} /> {text.busEnergized}</label></div>
          <button className="btn btn-primary" disabled={saving} type="submit" style={{ display: 'flex', gap: 7, justifyContent: 'center', alignItems: 'center' }}><Send size={15} />{saving ? text.saving : text.submit}</button>
        </form>
      </section>

      <section style={{ marginTop: '1rem', padding: '1rem 1.25rem', background: 'var(--surface-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
        <strong>{text.apiFeed}</strong><div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>{text.apiHelp}</div>
        <code dir="ltr" style={{ display: 'inline-block', marginTop: 8 }}>POST /api/sites/{currentSite?.id || '{site_id}'}/dispatch/measurement</code>
      </section>
    </div>
  );
}
