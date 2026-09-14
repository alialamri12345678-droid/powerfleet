/**
 * REST API client with automatic JWT bearer token handling and error parsing.
 */

const API_BASE = '/api';

const ARABIC_ERRORS = {
  'Incorrect email or password': 'البريد الإلكتروني أو كلمة المرور غير صحيحة',
  'Invalid or expired refresh token': 'انتهت صلاحية جلسة الدخول',
  'User not found': 'تعذر العثور على المستخدم',
  'Generator not found': 'تعذر العثور على المولد',
  'Panel not found': 'تعذر العثور على لوحة التحكم',
  'Panel state unavailable': 'حالة لوحة التحكم غير متاحة',
  'Panel not connected': 'لوحة التحكم غير متصلة',
  'Site not found': 'تعذر العثور على الموقع',
  'Target site not found': 'تعذر العثور على الموقع المطلوب',
  'No panels configured for site': 'لا توجد لوحات تحكم مهيأة للموقع',
  'Invalid panel_id': 'معرّف لوحة التحكم غير صالح',
  'Command not found': 'تعذر العثور على الأمر',
  'Exception not found': 'تعذر العثور على الاستثناء',
  'Cannot delete the only existing site. Create another site first.': 'لا يمكن حذف الموقع الوحيد. أنشئ موقعًا آخر أولًا.',
  'Site is not available to this customer': 'هذا الموقع غير متاح لهذا العميل',
  'Account access has changed; sign in again': 'تغيرت صلاحيات الحساب؛ يرجى تسجيل الدخول مجددًا',
};

function localizeError(message, status) {
  if (localStorage.getItem('locale') !== 'ar') return message;
  if (ARABIC_ERRORS[message]) return ARABIC_ERRORS[message];
  if (/^Request failed/.test(message)) return `تعذر إكمال الطلب (${status})`;
  return `تعذر إكمال الطلب: ${message}`;
}

export async function apiRequest(endpoint, options = {}) {
  const token = localStorage.getItem('access_token');
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (response.status === 401 && !endpoint.includes('/auth/login')) {
    // Attempt token refresh or logout
    const refreshToken = localStorage.getItem('refresh_token');
    if (refreshToken && !options._isRetry) {
      try {
        const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (refreshRes.ok) {
          const data = await refreshRes.json();
          localStorage.setItem('access_token', data.access_token);
          localStorage.setItem('refresh_token', data.refresh_token);
          // Retry original request
          return apiRequest(endpoint, { ...options, _isRetry: true });
        }
      } catch (err) {
        console.error('Token refresh failed', err);
      }
    }
    // Clear storage on unrecoverable 401
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_info');
    window.location.href = '/login';
    throw new Error(localStorage.getItem('locale') === 'ar' ? 'انتهت الجلسة. يرجى تسجيل الدخول مجددًا.' : 'Session expired. Please log in again.');
  }

  if (!response.ok) {
    let errorDetail = `Request failed (${response.status})`;
    try {
      const errorJson = await response.json();
      errorDetail = errorJson.detail || errorDetail;
    } catch {
      // not JSON
    }
    throw new Error(localizeError(errorDetail, response.status));
  }

  // Return json or null for 204 No Content
  if (response.status === 204) return null;
  return response.json();
}
