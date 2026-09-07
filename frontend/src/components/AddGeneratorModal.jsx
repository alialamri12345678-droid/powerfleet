import React, { useState, useEffect } from 'react';
import { apiRequest } from '../api/client';

export function AddGeneratorModal({ isOpen, onClose, onGeneratorCreated, siteId, initialData = null }) {
  const [name, setName] = useState('');
  const [transportType, setTransportType] = useState('tcp');
  const [address, setAddress] = useState('127.0.0.1:5020');
  const [unitId, setUnitId] = useState('4');
  const [ratedKw, setRatedKw] = useState('500');
  const [ratedKvar, setRatedKvar] = useState('150');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen) {
      if (initialData) {
        setName(initialData.name || '');
        setTransportType(initialData.transport_type || 'tcp');
        setAddress(initialData.address || '');
        setUnitId(initialData.unit_id?.toString() || '');
        setRatedKw(initialData.rated_kw?.toString() || '');
        setRatedKvar(initialData.rated_kvar?.toString() || '');
      } else {
        setName('');
        setTransportType('tcp');
        setAddress('127.0.0.1:5020');
        setUnitId('4');
        setRatedKw('500');
        setRatedKvar('150');
      }
    }
  }, [isOpen, initialData]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        name,
        transport_type: transportType,
        address,
        unit_id: Number(unitId),
        rated_kw: Number(ratedKw),
        rated_kvar: Number(ratedKvar),
      };
      let res;
      if (initialData) {
        res = await apiRequest(`/panels/${initialData.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } else {
        res = await apiRequest('/panels', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      onGeneratorCreated(res);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(26, 29, 31, 0.4)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '1rem',
    }}>
      <div style={{
        backgroundColor: '#FFFFFF',
        borderRadius: '4px',
        border: '1px solid var(--border-subtle)',
        maxWidth: '480px',
        width: '100%',
        padding: '2rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '1.25rem' }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 600 }}>{initialData ? 'Edit Generator' : 'Add Generator'}</h2>
          <button type="button" onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
            ✕
          </button>
        </div>

        {error && (
          <div style={{
            padding: '0.625rem 0.875rem',
            backgroundColor: '#FDF2F2',
            border: '1px solid #F5C6C6',
            color: 'var(--status-alarm)',
            borderRadius: '4px',
            fontSize: '0.8125rem',
            marginBottom: '1rem',
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="gen-name">Generator Label / Name</label>
            <input
              id="gen-name"
              type="text"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Generator 4 (Standby Aux)"
              required
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="gen-transport">Transport Protocol</label>
              <select
                id="gen-transport"
                className="form-select"
                value={transportType}
                onChange={(e) => {
                  setTransportType(e.target.value);
                  if (e.target.value === 'rtu' && address === '127.0.0.1:5020') {
                    setAddress('/dev/ttyUSB0');
                  } else if (e.target.value === 'tcp' && address === '/dev/ttyUSB0') {
                    setAddress('127.0.0.1:5020');
                  }
                }}
              >
                <option value="tcp">Modbus TCP (Ethernet)</option>
                <option value="rtu">Modbus RTU (RS485 Serial)</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="gen-unit-id">Modbus Slave ID</label>
              <input
                id="gen-unit-id"
                type="number"
                min="1"
                max="255"
                className="form-input"
                value={unitId}
                onChange={(e) => setUnitId(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="gen-address">
              {transportType === 'tcp' ? 'IP Address & Port (host:port)' : 'Serial Port Device Path'}
            </label>
            <input
              id="gen-address"
              type="text"
              className="form-input"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder={transportType === 'tcp' ? '127.0.0.1:5020' : '/dev/ttyUSB0 or COM3'}
              required
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="gen-kw">Rated Active Power (kW)</label>
              <input
                id="gen-kw"
                type="number"
                min="1"
                step="0.1"
                className="form-input"
                value={ratedKw}
                onChange={(e) => setRatedKw(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="gen-kvar">Rated Reactive (kVAr)</label>
              <input
                id="gen-kvar"
                type="number"
                min="0"
                step="0.1"
                className="form-input"
                value={ratedKvar}
                onChange={(e) => setRatedKvar(e.target.value)}
              />
            </div>
          </div>



          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.5rem', justifyContent: 'flex-end' }}>
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={submitting}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Saving...' : (initialData ? 'Save Changes' : 'Add Generator')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
