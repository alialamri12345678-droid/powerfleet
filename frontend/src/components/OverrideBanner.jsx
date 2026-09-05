import React from 'react';
import { AlertTriangle, WifiOff } from 'lucide-react';

export function OverrideBanner({ activeOverrides = [], gatewayStatus = 'online', onClearOverride }) {
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
              <strong>Gateway Offline</strong> — Live status disconnected. Controller safety and engine protections continue independently on-site.
            </span>
          </div>
        </div>
      )}

      {hasOverrides && (
        <div className="system-banner override">
          <div className="banner-left">
            <AlertTriangle size={16} />
            <span>
              <strong>Manual Override Active</strong> — Automated weekly schedule is currently bypassed for {activeOverrides.length} generator{activeOverrides.length > 1 ? 's' : ''}.
            </span>
          </div>
          {onClearOverride && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '0.25rem 0.625rem' }}
              onClick={onClearOverride}
            >
              View Overrides
            </button>
          )}
        </div>
      )}
    </>
  );
}
