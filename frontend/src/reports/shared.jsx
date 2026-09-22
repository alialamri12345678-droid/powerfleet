import React from 'react';
import { apiRequest } from '../api/client';
import { useReportLocale } from './useReportLocale';

export function reportQuery({ period, startDate, endDate, panelId, locale }) {
  const query = new URLSearchParams({ period, locale });
  if (panelId) query.set('panel_id', panelId);
  if (period === 'custom') {
    query.set('start_date', startDate);
    query.set('end_date', endDate);
  }
  return query.toString();
}

export async function downloadReport(endpoint, name) {
  const blob = await apiRequest(endpoint, { _responseType: 'blob' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${name.replace(/[^\p{L}\p{N}_-]+/gu, '_')}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function Metric({ label, value, unit, note, tone }) {
  return <div className="report-metric"><div className="report-muted">{label}</div><div className={`report-metric-value ${tone ? `report-tone-${tone}` : ''}`}>{value}<small>{unit}</small></div>{note && <p className="report-muted">{note}</p>}</div>;
}

export function Status({ value }) {
  const { t } = useReportLocale();
  return <span className={`report-status report-status-${value}`}>{t(value || 'unavailable')}</span>;
}

export function Feedback({ value }) {
  if (!value) return null;
  return <div role={value.type === 'error' ? 'alert' : 'status'} className={`report-feedback ${value.type === 'error' ? 'report-feedback-error' : ''}`}>{value.text}</div>;
}

export function localDateToday() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
