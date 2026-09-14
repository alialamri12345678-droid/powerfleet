import React from 'react';
import { AlertTriangle, WifiOff } from 'lucide-react';
import { useLocale } from '../i18n/LocaleContext';

export function OverrideBanner({ activeOverrides = [], gatewayStatus = 'online', onClearOverride }) {
  const { t } = useLocale();
  const isOffline = gatewayStatus === 'offline';
  const hasOverrides = activeOverrides.length > 0;

  if (!isOffline && !hasOverrides) return null;

  return (
    <>
      {isOffline && (
        <div className="system-banner offline">
          <div className="banner-left">
            <WifiOff size={16} />
            <span>
              <strong>{t('gatewayOffline')}</strong> — {t('gatewayOfflineText')}
            </span>
          </div>
        </div>
      )}

      {hasOverrides && (
        <div className="system-banner override">
          <div className="banner-left">
            <AlertTriangle size={16} />
            <span>
              <strong>{t('manualOverrideActive')}</strong> — {t('overrideBanner', { count: activeOverrides.length })}
            </span>
          </div>
          {onClearOverride && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '0.25rem 0.625rem' }}
              onClick={onClearOverride}
            >
              {t('viewOverrides')}
            </button>
          )}
        </div>
      )}
    </>
  );
}
