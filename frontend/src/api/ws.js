import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './client';

/**
 * Custom React hook for live WebSocket telemetry stream.
 */
export function useWebSocketTelemetry(refreshKey = 0) {
  const [panelStates, setPanelStates] = useState({});
  const [gatewayStatus, setGatewayStatus] = useState('connecting');
  const [lastUpdate, setLastUpdate] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  useEffect(() => {
    let isMounted = true;

    async function connect() {
      if (!localStorage.getItem('access_token')) {
        setGatewayStatus('unauthorized');
        return;
      }

      let token;
      try {
        token = (await apiRequest('/auth/stream-token')).token;
      } catch {
        if (isMounted) setGatewayStatus('unauthorized');
        return;
      }
      if (!isMounted) return;
      // Determine websocket URL
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/status?token=${encodeURIComponent(token)}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMounted) return;
        setGatewayStatus('online');
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'initial_state') {
            const stateMap = {};
            (data.panels || []).forEach((p) => {
              stateMap[p.panel_id] = p;
            });
            setPanelStates(stateMap);
            setGatewayStatus(data.gateway_status || 'online');
            setLastUpdate(new Date());
          } else if (data.type === 'panel_update') {
            setPanelStates((prev) => ({
              ...prev,
              [data.panel_id]: data.state,
            }));
            setLastUpdate(new Date());
          }
        } catch (err) {
          console.error('Error parsing WebSocket message:', err);
        }
      };

      ws.onerror = () => {
        if (!isMounted) return;
        setGatewayStatus('offline');
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setGatewayStatus('offline');
        // Auto-reconnect after 3s
        reconnectTimeoutRef.current = setTimeout(() => {
          if (isMounted) connect();
        }, 3000);
      };
    }

    connect();

    // Heartbeat ping interval
    const pingInterval = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 15000);

    return () => {
      isMounted = false;
      clearInterval(pingInterval);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [refreshKey]);

  return { panelStates, gatewayStatus, lastUpdate };
}
