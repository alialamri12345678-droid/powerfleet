import React, { useEffect, useState } from 'react';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { LoginPage } from './auth/LoginPage';
import { Navbar } from './components/Navbar';
import { DashboardPage } from './pages/DashboardPage';
import { SchedulePage } from './pages/SchedulePage';
import { SettingsPage } from './pages/SettingsPage';
import { ReportsPage } from './pages/ReportsPage';
import { DiagnosticsPage } from './pages/DiagnosticsPage';
import { OverridesPage } from './pages/OverridesPage';
import { EventLogPage } from './pages/EventLogPage';
import { AddSiteModal } from './components/AddSiteModal';
import { AddGeneratorModal } from './components/AddGeneratorModal';
import { useWebSocketTelemetry } from './api/ws';
import { apiRequest } from './api/client';

function AppContent() {
  const { user, loading } = useAuth();
  const [activeTab, setActiveTab] = useState('dashboard');
  const [sites, setSites] = useState([]);
  const [currentSite, setCurrentSite] = useState(null);
  
  // Modals state
  const [isAddSiteOpen, setIsAddSiteOpen] = useState(false);
  // editingGenerator can be null (closed), true (adding new), or an object (editing)
  const [editingGenerator, setEditingGenerator] = useState(null);
  const [siteRefreshKey, setSiteRefreshKey] = useState(0);
  const { panelStates, gatewayStatus } = useWebSocketTelemetry(siteRefreshKey);

  // Load sites whenever user is logged in
  useEffect(() => {
    if (user) {
      loadSites();
    }
  }, [user, siteRefreshKey]);

  async function loadSites() {
    try {
      const [sitesList, current] = await Promise.all([
        apiRequest('/sites'),
        apiRequest('/sites/current'),
      ]);
      setSites(sitesList);
      setCurrentSite(current);
    } catch (err) {
      console.error('Failed to load sites:', err);
    }
  }

  const handleSelectSite = async (siteId) => {
    if (!siteId || siteId === currentSite?.id) return;
    try {
      const response = await apiRequest(`/sites/switch/${siteId}`, { method: 'POST' });
      if (response.access_token) {
        localStorage.setItem('access_token', response.access_token);
        // Dispatch an event to notify hooks (like useWebSocketTelemetry) that the token changed
        window.dispatchEvent(new Event('auth_token_changed'));
      }
      setCurrentSite(response.site || response);
      setSiteRefreshKey((k) => k + 1);
    } catch (err) {
      alert(`Failed to switch site: ${err.message}`);
    }
  };

  const handleSiteCreated = async (newSite) => {
    setSites((prev) => [...prev, newSite]);
    await handleSelectSite(newSite.id);
  };

  const handleGeneratorCreated = () => {
    setSiteRefreshKey((k) => k + 1);
  };

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--text-secondary)',
      }}>
        Starting portal...
      </div>
    );
  }

  if (!user) {
    return <LoginPage onLoginSuccess={() => setActiveTab('dashboard')} />;
  }

  return (
    <div className="app-container">
      <Navbar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        currentSite={currentSite}
        sites={sites}
        onSelectSite={handleSelectSite}
        onOpenAddSite={() => setIsAddSiteOpen(true)}
      />

      <main className="main-content" key={currentSite?.id}>
        {activeTab === 'dashboard' && (
          <DashboardPage
            panelStates={panelStates}
            gatewayStatus={gatewayStatus}
            onNavigate={setActiveTab}
            currentSite={currentSite}
            onOpenAddGenerator={() => setEditingGenerator(true)}
            onEditPanel={(panel) => setEditingGenerator(panel)}
            refreshKey={siteRefreshKey}
          />
        )}
        {activeTab === 'schedule' && <SchedulePage />}
        {activeTab === 'settings' && <SettingsPage />}
        {activeTab === 'reports' && <ReportsPage />}

        {/* Diagnostics, overrides, and audit log tabs */}
        {activeTab === 'diagnostics' && <DiagnosticsPage />}
        {activeTab === 'overrides' && <OverridesPage />}
        {activeTab === 'events' && <EventLogPage />}
      </main>

      {/* Modals */}
      <AddSiteModal
        isOpen={isAddSiteOpen}
        onClose={() => setIsAddSiteOpen(false)}
        onSiteCreated={handleSiteCreated}
      />

      <AddGeneratorModal
        isOpen={!!editingGenerator}
        onClose={() => setEditingGenerator(null)}
        initialData={typeof editingGenerator === 'object' ? editingGenerator : null}
        onGeneratorCreated={handleGeneratorCreated}
        siteId={currentSite?.id}
      />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
