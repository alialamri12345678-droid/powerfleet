import React from 'react';
import { AlertTriangle, WifiOff } from 'lucide-react';

export function StatusDot({ status, activeAlarms = [] }) {
  let dotClass = 'idle';
  let displayText = status || 'Unknown';
  let showAlarmIcon = false;
  let showOfflineIcon = false;

  const lower = (status || '').toLowerCase();

  if (lower === 'unreachable') {
    dotClass = 'unreachable';
    displayText = 'Unreachable';
    showOfflineIcon = true;
  } else if (activeAlarms && activeAlarms.length > 0) {
    dotClass = 'alarm';
    displayText = 'Alarm';
    showAlarmIcon = true;
  } else if (lower === 'running') {
    dotClass = 'running';
    displayText = 'Running';
  } else if (lower === 'starting' || lower === 'preheat' || lower === 'cranking') {
    dotClass = 'warning';
    displayText = 'Starting';
  } else if (lower === 'stopping' || lower === 'cooldown') {
    dotClass = 'warning';
    displayText = 'Stopping';
  } else if (lower === 'alarm' || lower === 'fault') {
    dotClass = 'alarm';
    displayText = 'Alarm';
    showAlarmIcon = true;
  } else {
    dotClass = 'idle';
    displayText = 'Idle';
  }

  return (
    <div className="status-indicator">
      <span className={`status-dot ${dotClass}`} />
      <span className={`status-word ${dotClass}`}>{displayText}</span>
      {showAlarmIcon && <AlertTriangle size={14} color="var(--status-alarm)" />}
      {showOfflineIcon && <WifiOff size={14} color="var(--text-tertiary)" />}
    </div>
  );
}
