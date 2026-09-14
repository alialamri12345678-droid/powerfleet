import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { StatusDot } from './StatusDot';
import { LoadBar } from './LoadBar';
import { DayScheduleRow } from './DayScheduleRow';
import { useLocale } from '../i18n/LocaleContext';

export function GeneratorCard({
  panel,
  liveState,
  scheduledDays = [],
  isOnDutyToday = false,
  todayIndex = 0,
  onManualStart,
  onManualStop,
  onEditPanel,
  onDeletePanel,
}) {
  const { t, formatCode, formatNumber } = useLocale();
  const [showDetails, setShowDetails] = useState(false);
  const isRunning = liveState?.engine_status === 'running';
  const displayStatus = liveState?.display_status || (isRunning ? 'Running' : 'Idle');
  const runHours = liveState?.run_hours ?? 0;
  const definitions = [
    ['fuel_level_percent', t('fuelLevel'), '%'], ['coolant_temperature', t('coolantTemperature'), '°C'],
    ['oil_pressure', t('oilPressure'), 'bar'], ['battery_voltage', t('batteryVoltage'), 'V'],
    ['engine_speed', t('engineSpeed'), 'RPM'], ['frequency', t('frequency'), 'Hz'],
    ['load_kva', t('apparentPower'), 'kVA'], ['load_kvar', t('reactivePower'), 'kVAr'],
    ['load_kvar_percent', t('reactiveLoad'), '%'], ['voltage_l1_n', t('l1Voltage'), 'V'],
    ['voltage_l2_n', t('l2Voltage'), 'V'], ['voltage_l3_n', t('l3Voltage'), 'V'],
    ['total_kwh', t('energyProduced'), 'kWh'], ['number_of_starts', t('startCount'), ''],
    ['generator_status', t('generatorState'), ''],
  ];
  const knownKeys = new Set(definitions.map(([key]) => key));
  const detailReadings = definitions.map(([key, label, unit]) => [
    label,
    liveState?.reading_quality?.[key] === 'unavailable' ? undefined : (liveState?.readings?.[key] ?? liveState?.[key]),
    liveState?.reading_units?.[key] || unit,
  ]);
  Object.entries(liveState?.readings || {})
    .filter(([key]) => !knownKeys.has(key) && !key.startsWith('alarm_word_') && !['engine_status', 'load_kw', 'load_kw_percent', 'generator_breaker', 'sync_status', 'run_hours'].includes(key))
    .forEach(([key, value]) => detailReadings.push([
      key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()),
      value,
      liveState?.reading_units?.[key] || '',
    ]));

  return (
    <div className={`gen-card ${isOnDutyToday ? 'on-duty-today' : ''}`}>
      <div className="card-header">
        <div>
          <h2 className="gen-name">{panel.name}</h2>
          <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
            {t('capacity', { value: formatNumber(panel.rated_kw) })}
          </div>
        </div>
        {isOnDutyToday && (
          <span className="duty-indicator-text">{t('onDutyToday')}</span>
        )}
      </div>

      <StatusDot
        status={displayStatus}
        activeAlarms={liveState?.active_alarms || []}
      />

      <LoadBar
        loadKw={liveState?.load_kw || 0}
        loadPct={liveState?.load_kw_percent || 0}
        ratedKw={panel.rated_kw}
        isRunning={isRunning}
      />

      <DayScheduleRow
        activeDays={scheduledDays}
        todayIndex={todayIndex}
      />

      <div className="stats-footer">
        <span>{t('runTime')}</span>
        <span className="tabular-nums hours-val">
          {formatNumber(runHours, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} {t('hoursShort')}
        </span>
      </div>

      <button
        type="button"
        className="parameter-toggle"
        aria-expanded={showDetails}
        onClick={() => setShowDetails((shown) => !shown)}
      >
        <span>{t('moreReadings')}</span>
        {showDetails ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {showDetails && (
        <div className="parameter-list">
          {detailReadings.map(([label, value, unit]) => (
            <div className="parameter-row" key={label}>
              <span>{label}</span>
              <strong className="tabular-nums">
                {value === null || value === undefined
                  ? t('notAvailable')
                  : `${typeof value === 'number' ? formatNumber(value, { maximumFractionDigits: 1 }) : formatCode(value)}${unit ? ` ${unit}` : ''}`}
              </strong>
            </div>
          ))}
          <div className="parameter-row">
            <span>{t('breaker')}</span><strong>{liveState?.generator_breaker ? t('closed') : t('open')}</strong>
          </div>
          <div className="parameter-row">
            <span>{t('synchronization')}</span><strong>{liveState?.sync_status ? t('synchronized') : t('notSynchronized')}</strong>
          </div>
        </div>
      )}

      {/* Quick-action controls */}
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', paddingTop: '0.75rem', borderTop: '1px solid #F0F0EE', alignItems: 'center' }}>
        <button
          type="button"
          className="btn btn-secondary"
          style={{ flex: 1, fontSize: '0.8125rem' }}
          disabled={isRunning}
          onClick={() => onManualStart(panel.id)}
        >
          {t('startUnit')}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          style={{ flex: 1, fontSize: '0.8125rem' }}
          disabled={!isRunning}
          onClick={() => onManualStop(panel.id)}
        >
          {t('stopUnit')}
        </button>
        {onEditPanel && (
          <button
            type="button"
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.375rem 0.5rem' }}
            title={t('editGeneratorSettings')}
            onClick={() => onEditPanel(panel)}
          >
            {t('edit')}
          </button>
        )}
        {onDeletePanel && (
          <button
            type="button"
            className="btn btn-danger"
            style={{ fontSize: '0.75rem', padding: '0.375rem 0.5rem' }}
            title={t('decommissionGenerator')}
            onClick={() => {
              if (window.confirm(t('decommissionConfirm', { name: panel.name }))) {
                onDeletePanel(panel.id);
              }
            }}
          >
            {t('delete')}
          </button>
        )}
      </div>
    </div>
  );
}
