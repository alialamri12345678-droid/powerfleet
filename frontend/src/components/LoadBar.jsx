import React from 'react';

export function LoadBar({ loadKw = 0, loadPct = 0, ratedKw = 500, isRunning = false }) {
  const clampPct = Math.min(100, Math.max(0, loadPct));
  let barColorClass = 'normal';

  if (!isRunning) {
    barColorClass = 'off';
  } else if (clampPct >= 85) {
    barColorClass = 'critical';
  } else if (clampPct >= 70) {
    barColorClass = 'high';
  }

  return (
    <div className="load-section">
      <div className="load-header">
        <span>Load</span>
        <span className="tabular-nums load-value">
          {isRunning ? `${Math.round(loadKw)} kW (${Math.round(clampPct)}%)` : '0 kW (0%)'}
        </span>
      </div>
      <div className="load-bar-track">
        <div
          className={`load-bar-fill ${barColorClass}`}
          style={{ width: isRunning ? `${clampPct}%` : '0%' }}
        />
      </div>
    </div>
  );
}
