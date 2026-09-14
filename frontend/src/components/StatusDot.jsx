import React from 'react';
import { AlertTriangle, WifiOff } from 'lucide-react';
import { useLocale } from '../i18n/LocaleContext';

export function StatusDot({ status, activeAlarms = [] }) {
  const { t } = useLocale();
  let dotClass = 'idle';
  let displayText = t('unknown');
  let showAlarmIcon = false;
  let showOfflineIcon = false;

  const lower = (status || '').toLowerCase();

  if (lower === 'unreachable') {
    dotClass = 'unreachable';
    displayText = t('unreachable');
    showOfflineIcon = true;
  } else if (activeAlarms && activeAlarms.length > 0) {
    dotClass = 'alarm';
    displayText = t('alarm');
    showAlarmIcon = true;
  } else if (lower === 'running') {
    dotClass = 'running';
    displayText = t('running');
  } else if (lower === 'starting' || lower === 'preheat' || lower === 'cranking') {
    dotClass = 'warning';
    displayText = t('starting');
  } else if (lower === 'stopping' || lower === 'cooldown') {
    dotClass = 'warning';
    displayText = t('stopping');
  } else if (lower === 'alarm' || lower === 'fault') {
    dotClass = 'alarm';
    displayText = t('alarm');
    showAlarmIcon = true;
  } else {
    dotClass = 'idle';
    displayText = t('idle');
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
