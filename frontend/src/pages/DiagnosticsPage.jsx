import React, { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';
import { useLocale } from '../i18n/LocaleContext';

const ARABIC_REGISTER_INFO = {
  engine_status: ['حالة المحرك', 'كلمة حالة المحرك: متوقف، تسخين، تدوير، تشغيل، تبريد، أو توقف بعطل'],
  generator_status: ['حالة المولد', 'حالة المولد الكهربائي: متوقف، تسخين، محمّل، أو قيد الإيقاف'],
  generator_breaker: ['قاطع المولد', 'حالة قاطع المولد: 0 مفتوح، 1 مغلق'],
  sync_status: ['حالة المزامنة', 'حالة المزامنة: 0 غير متزامن، 1 متزامن'],
  load_kw: ['القدرة الفعالة', 'خرج القدرة الفعالة بالكيلوواط بعد تطبيق معامل التحويل'],
  load_kw_percent: ['نسبة الحمل الفعال', 'القدرة الفعالة كنسبة من القدرة المقننة'],
  load_kvar: ['القدرة غير الفعالة', 'خرج القدرة غير الفعالة بوحدة kVAr'],
  load_kvar_percent: ['نسبة الحمل غير الفعال', 'القدرة غير الفعالة كنسبة من القيمة المقننة'],
  load_kva: ['القدرة الظاهرية', 'خرج القدرة الظاهرية بوحدة kVA'],
  voltage_l1_n: ['جهد L1-N', 'جهد الطور L1 إلى المحايد'], voltage_l2_n: ['جهد L2-N', 'جهد الطور L2 إلى المحايد'], voltage_l3_n: ['جهد L3-N', 'جهد الطور L3 إلى المحايد'],
  frequency: ['تردد المولد', 'تردد خرج المولد'], coolant_temperature: ['حرارة سائل التبريد', 'درجة حرارة سائل تبريد المحرك'],
  oil_pressure: ['ضغط الزيت', 'ضغط زيت المحرك'], battery_voltage: ['جهد بطارية التشغيل', 'جهد بطارية تشغيل المحرك'],
  engine_speed: ['سرعة المحرك', 'سرعة دوران المحرك'], fuel_level_percent: ['مستوى الوقود', 'نسبة مستوى الوقود في الخزان'],
  run_hours: ['ساعات التشغيل', 'إجمالي ساعات تشغيل المحرك'], total_kwh: ['إجمالي الطاقة', 'إجمالي الطاقة المنتجة'], number_of_starts: ['عدد مرات التشغيل', 'إجمالي مرات بدء تشغيل المحرك'],
  alarm_word_1: ['كلمة الإنذار 1', 'مجموعة أعلام الإنذارات الأولى'], alarm_word_2: ['كلمة الإنذار 2', 'مجموعة أعلام الإنذارات الثانية'], alarm_word_3: ['كلمة الإنذار 3', 'مجموعة أعلام الإنذارات الثالثة'],
  remote_start: ['التشغيل عن بُعد', 'أمر تشغيل عن بُعد؛ تتولى اللوحة المزامنة وتقاسم الحمل داخليًا'], remote_stop: ['الإيقاف عن بُعد', 'أمر إيقاف عن بُعد؛ تتولى اللوحة التبريد وفتح القاطع'],
  fixed_power_setpoint_kw: ['هدف القدرة الفعالة', 'هدف القدرة الثابتة كنسبة من القدرة المقننة'], fixed_power_setpoint_kvar: ['هدف القدرة غير الفعالة', 'هدف القدرة غير الفعالة كنسبة من القيمة المقننة'],
};

export function DiagnosticsPage() {
  const { t, locale, formatTime } = useLocale();
  const [panels, setPanels] = useState([]);
  const [selectedPanelId, setSelectedPanelId] = useState(null);
  const [diagData, setDiagData] = useState(null);
  const [healthData, setHealthData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function loadPanels() {
      try {
        const data = await apiRequest('/panels');
        setPanels(data);
        if (data.length > 0) {
          setSelectedPanelId(data[0].id);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    loadPanels();
  }, []);

  useEffect(() => {
    if (selectedPanelId) {
      loadDiagnostics(selectedPanelId);
    }
  }, [selectedPanelId]);

  async function loadDiagnostics(panelId) {
    setRefreshing(true);
    setError(null);
    try {
      const [raw, health] = await Promise.all([
        apiRequest(`/diagnostics/panels/${panelId}/raw`),
        apiRequest(`/diagnostics/panels/${panelId}/health`),
      ]);
      setDiagData(raw);
      setHealthData(health);
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('diagnosticsTitle')}</h1>
          <p className="page-subtitle">
            {t('diagnosticsSubtitle')}
          </p>
        </div>
        {selectedPanelId && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => loadDiagnostics(selectedPanelId)}
            disabled={refreshing}
          >
            {refreshing ? t('readingRegisters') : t('pollNow')}
          </button>
        )}
      </div>

      {error && (
        <div style={{
          padding: '0.625rem 1rem',
          borderRadius: '4px',
          marginBottom: '1.5rem',
          fontSize: '0.875rem',
          backgroundColor: '#FDF2F2',
          border: '1px solid #F5C6C6',
          color: 'var(--status-alarm)',
        }}>
          {error}
        </div>
      )}

      {/* Panel Selector Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
        {panels.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`btn ${selectedPanelId === p.id ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setSelectedPanelId(p.id)}
          >
            {p.name}
          </button>
        ))}
      </div>

      {/* Connection Health Overview */}
      {healthData && (
        <div style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          padding: '1.25rem',
          marginBottom: '1.5rem',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1rem',
          fontSize: '0.8125rem',
        }}>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>{t('transport')}</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }}>{healthData.transport_type.toUpperCase()} ({healthData.address})</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>{t('slaveId')}</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }} className="tabular-nums">{healthData.unit_id}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>{t('linkHealth')}</div>
            <div style={{ fontWeight: 600, marginTop: '2px', color: healthData.is_reachable ? 'var(--status-running)' : 'var(--status-alarm)' }}>
              {healthData.is_reachable ? t('connected') : t('unreachable')}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>{t('failures')}</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }} className="tabular-nums">{healthData.consecutive_errors}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-secondary)' }}>{t('lastPoll')}</div>
            <div style={{ fontWeight: 600, marginTop: '2px' }} className="tabular-nums">
              {healthData.last_successful_poll ? formatTime(healthData.last_successful_poll) : t('never')}
            </div>
          </div>
        </div>
      )}

      {/* Raw Registers Table */}
      {diagData && diagData.registers && (
        <div style={{
          backgroundColor: '#FFFFFF',
          border: '1px solid var(--border-subtle)',
          borderRadius: '4px',
          overflow: 'hidden',
        }}>
          <table className="data-table" style={{ border: 'none' }}>
            <thead>
              <tr>
                <th>{t('registerName')}</th><th>{t('address')}</th><th>{t('type')}</th>
                <th style={{ textAlign: 'end' }}>{t('rawValue')}</th>
                <th style={{ textAlign: 'end' }}>{t('scaledValue')}</th>
                <th>{t('unit')}</th><th>{t('description')}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(diagData.registers).map(([name, reg]) => (
                <tr key={name}>
                  <td style={{ fontWeight: 500 }}>{locale === 'ar' ? (ARABIC_REGISTER_INFO[name]?.[0] || name) : name.replaceAll('_', ' ')}</td>
                  <td className="tabular-nums" style={{ color: 'var(--text-secondary)' }}>{reg.address}</td>
                  <td style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{reg.type}</td>
                  <td className="tabular-nums" style={{ textAlign: 'end' }}>
                    {reg.raw_value !== null ? reg.raw_value : '—'}
                  </td>
                  <td className="tabular-nums" style={{ textAlign: 'end', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {reg.scaled_value !== null ? (typeof reg.scaled_value === 'number' ? reg.scaled_value.toFixed(1) : reg.scaled_value) : '—'}
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>{reg.unit || '—'}</td>
                  <td style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', maxWidth: '280px' }}>
                    {locale === 'ar' ? (ARABIC_REGISTER_INFO[name]?.[1] || reg.description) : reg.description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
