import React from 'react';
import { StatusDot } from './StatusDot';
import { LoadBar } from './LoadBar';
import { DayScheduleRow } from './DayScheduleRow';

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
  isTechnician = false,
}) {
  const isRunning = liveState?.engine_status === 'running';
  const displayStatus = liveState?.display_status || (isRunning ? 'Running' : 'Idle');
  const runHours = liveState?.run_hours ?? 0;

  return (
    <div className={`gen-card ${isOnDutyToday ? 'on-duty-today' : ''}`}>
      <div className="card-header">
        <div>
          <h2 className="gen-name">{panel.name}</h2>
          <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
            {panel.rated_kw} kW capacity
          </div>
        </div>
        {isOnDutyToday && (
          <span className="duty-indicator-text">On duty today</span>
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
        <span>Run time</span>
        <span className="tabular-nums hours-val">
          {runHours.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} hrs
        </span>
      </div>

      {/* Quick-action controls */}
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', paddingTop: '0.75rem', borderTop: '1px solid #F0F0EE', alignItems: 'center' }}>
        <button
          type="button"
          className="btn btn-secondary"
          style={{ flex: 1, fontSize: '0.8125rem' }}
          disabled={isRunning}
          onClick={() => onManualStart(panel.id)}
        >
          Start Unit
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          style={{ flex: 1, fontSize: '0.8125rem' }}
          disabled={!isRunning}
          onClick={() => onManualStop(panel.id)}
        >
          Stop Unit
        </button>
        {onEditPanel && (
          <button
            type="button"
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '0.375rem 0.5rem' }}
            title="Edit generator settings"
            onClick={() => onEditPanel(panel)}
          >
            Edit
          </button>
        )}
        {onDeletePanel && (
          <button
            type="button"
            className="btn btn-danger"
            style={{ fontSize: '0.75rem', padding: '0.375rem 0.5rem' }}
            title="Decommission generator"
            onClick={() => {
              if (window.confirm(`Are you sure you want to decommission ${panel.name}?`)) {
                onDeletePanel(panel.id);
              }
            }}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
