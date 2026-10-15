/**
 * HROne ENTERPRISE ATTENDANCE & ANALYTICS - CORE FRONTEND CLIENT
 * Enterprise Authentication Gateway, Role Management, Live IST Clock,
 * Kiosk Actions, REST API Calls, Aggregation Dashboards,
 * SVG Trend Visualizations, and Modal Dialogs.
 */

// Global State
const state = {
  currentUser: null, // { role: 'admin' | 'employee', emp_code, name, department, email, shift_start, shift_end }
  activeTab: 'dashboard',
  employees: [],
  currentEmpPage: 1,
  empTotal: 0,
  currentAttPage: 1,
  attTotal: 0,
  selectedEmpForMonthly: null,
  loginRoleMode: 'employee',
};

// IST Offset in ms (5 hours 30 mins)
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

// Format epoch ms to IST string: "YYYY-MM-DD HH:mm:ss"
function formatEpochMsToIST(ms) {
  if (!ms) return '--';
  const istDate = new Date(ms + IST_OFFSET_MS);
  return istDate.toISOString().replace('T', ' ').substring(0, 19);
}

// Format epoch ms to IST time only: "HH:mm:ss"
function formatEpochMsToISTTime(ms) {
  if (!ms) return '--';
  const istDate = new Date(ms + IST_OFFSET_MS);
  return istDate.toISOString().substring(11, 19);
}

// Convert local datetime-local value to epoch milliseconds
function localInputToEpochMs(val) {
  if (!val) return null;
  const d = new Date(val);
  return Math.floor(d.getTime() / 1000) * 1000;
}

// ============================================================================
// TOAST NOTIFICATIONS
// ============================================================================
function showToast(title, message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <div>
      <div class="toast-title">${title}</div>
      <div class="toast-message">${message}</div>
    </div>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(50px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ============================================================================
// AUTHENTICATION & SESSION MANAGEMENT
// ============================================================================
function initAuth() {
  // Login Role Tabs (Employee vs Admin)
  const tabEmp = document.getElementById('tab-login-emp');
  const tabAdmin = document.getElementById('tab-login-admin');
  const labelId = document.getElementById('label-login-id');
  const inputUser = document.getElementById('login-username');

  if (tabEmp && tabAdmin) {
    tabEmp.addEventListener('click', () => {
      state.loginRoleMode = 'employee';
      tabEmp.classList.add('active');
      tabAdmin.classList.remove('active');
      if (labelId) labelId.textContent = 'Corporate Email or Employee ID';
      if (inputUser) {
        inputUser.placeholder = 'name@company.com or EMP ID';
        inputUser.value = '';
      }
    });

    tabAdmin.addEventListener('click', () => {
      state.loginRoleMode = 'admin';
      tabAdmin.classList.add('active');
      tabEmp.classList.remove('active');
      if (labelId) labelId.textContent = 'Administrator Corporate Email or ID';
      if (inputUser) {
        inputUser.placeholder = 'admin@company.com';
        inputUser.value = '';
      }
    });
  }

  // Form submit
  const formLogin = document.getElementById('form-login');
  if (formLogin) {
    formLogin.addEventListener('submit', (e) => {
      e.preventDefault();
      const val = inputUser.value.trim();

      if (state.loginRoleMode === 'admin' || val.toLowerCase().includes('admin')) {
        loginAsAdmin();
      } else if (!val) {
        showToast('Identification Required', 'Please enter your Corporate Email or Employee ID (e.g. EMP0001).', 'warning');
      } else {
        loginAsEmployeeCode(val);
      }
    });
  }

  // Corporate SSO Button
  const btnSSO = document.getElementById('btn-sso-login');
  if (btnSSO) {
    btnSSO.addEventListener('click', () => {
      if (state.loginRoleMode === 'admin') {
        loginAsAdmin();
      } else {
        loginAsEmployeeCode('EMP0001');
      }
      showToast('Corporate SSO Authenticated', 'Single Sign-On session established via Okta / SAML 2.0 gateway.', 'success');
    });
  }

  // Logout button
  document.getElementById('btn-logout')?.addEventListener('click', logout);

  // Restore saved session if any
  const saved = localStorage.getItem('hrone_user');
  if (saved) {
    try {
      state.currentUser = JSON.parse(saved);
      applyAuthenticatedState();
      return;
    } catch (e) {
      localStorage.removeItem('hrone_user');
    }
  }

  // Show login screen by default
  showLoginScreen();
}

function showLoginScreen() {
  document.getElementById('view-login-screen')?.classList.remove('hidden');
  document.getElementById('app-portal')?.classList.add('hidden');
}

function loginAsAdmin() {
  state.currentUser = {
    role: 'admin',
    name: 'HR Administrator',
    email: 'admin@hrone.internal',
    department: 'People Operations',
  };
  saveAndLaunchSession();
}

function loginAsEmployeeCode(codeOrEmail) {
  const target = codeOrEmail.trim().toLowerCase();
  let emp = state.employees.find(e =>
    e.emp_code.toLowerCase() === target ||
    e.email.toLowerCase() === target
  );

  // Default fallback if not loaded yet
  if (!emp && state.employees.length > 0) {
    emp = state.employees[0];
  }

  state.currentUser = {
    role: 'employee',
    emp_code: emp ? emp.emp_code : 'EMP0001',
    name: emp ? emp.name : 'Asha Rao',
    email: emp ? emp.email : 'asha@example.com',
    department: emp ? emp.department : 'Engineering',
    shift_start: emp ? emp.shift_start : '09:30',
    shift_end: emp ? emp.shift_end : '18:30',
    joined_on: emp ? emp.joined_on : '2026-01-05',
  };

  saveAndLaunchSession();
}

function quickLoginAs(identifier) {
  if (identifier === 'HR') {
    loginAsAdmin();
  } else {
    loginAsEmployeeCode(identifier);
  }
}

function saveAndLaunchSession() {
  const remember = document.getElementById('login-remember')?.checked;
  if (remember) {
    localStorage.setItem('hrone_user', JSON.stringify(state.currentUser));
  } else {
    localStorage.removeItem('hrone_user');
  }

  applyAuthenticatedState();
  showToast('Access Granted', `Signed in as ${state.currentUser.name} (${state.currentUser.role === 'admin' ? 'HR Administrator' : 'Staff Member'})`, 'success');
}

function logout() {
  state.currentUser = null;
  localStorage.removeItem('hrone_user');
  showLoginScreen();
  showToast('Signed Out', 'You have been securely signed out of the portal.', 'info');
}

function applyAuthenticatedState() {
  const loginScr = document.getElementById('view-login-screen');
  const portalApp = document.getElementById('app-portal');

  if (loginScr) loginScr.classList.add('hidden');
  if (portalApp) portalApp.classList.remove('hidden');

  const u = state.currentUser;
  if (!u) return;

  // Header user widget
  const avatarEl = document.getElementById('header-user-avatar');
  const nameEl = document.getElementById('header-user-name');
  const roleEl = document.getElementById('header-user-role');

  if (nameEl) nameEl.textContent = u.name;

  if (u.role === 'admin') {
    if (avatarEl) avatarEl.textContent = 'HR';
    if (roleEl) roleEl.textContent = 'HR Administrator';

    // Labels
    const tabKioskText = document.getElementById('tab-kiosk-text');
    if (tabKioskText) tabKioskText.textContent = 'Punch Clock Kiosk';
    const tabAttText = document.getElementById('tab-attendance-text');
    if (tabAttText) tabAttText.textContent = 'Attendance Logs & Audit';

    // Hide welcome banner
    document.getElementById('emp-welcome-banner')?.classList.add('hidden');

    // Default tab
    switchTab('dashboard');
  } else {
    // Employee
    const initials = u.name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
    if (avatarEl) avatarEl.textContent = initials;
    if (roleEl) roleEl.textContent = `Employee • ${u.department || 'Operations'}`;

    // Update banner
    const banner = document.getElementById('emp-welcome-banner');
    if (banner) {
      banner.classList.remove('hidden');
      document.getElementById('banner-emp-avatar').textContent = initials;
      document.getElementById('banner-emp-name').textContent = u.name;
      document.getElementById('banner-emp-code').textContent = u.emp_code;
      document.getElementById('banner-emp-dept').textContent = u.department || 'General';
      document.getElementById('banner-emp-shift').textContent = `${u.shift_start || '09:30'} - ${u.shift_end || '18:30'} IST`;
    }

    // Tab labels
    const tabKioskText = document.getElementById('tab-kiosk-text');
    if (tabKioskText) tabKioskText.textContent = 'My Attendance Terminal';
    const tabAttText = document.getElementById('tab-attendance-text');
    if (tabAttText) tabAttText.textContent = 'My Timesheet & Logs';

    // Auto-fill and lock kiosk
    const inSel = document.getElementById('punch-in-emp');
    const outSel = document.getElementById('punch-out-emp');
    if (inSel) inSel.value = u.emp_code;
    if (outSel) outSel.value = u.emp_code;
    updatePunchInPreview();

    // Auto-filter attendance
    const attEmp = document.getElementById('att-filter-emp');
    if (attEmp) attEmp.value = u.emp_code;

    // Land directly on Kiosk / Attendance Terminal!
    switchTab('kiosk');
  }
}

function openSelfMonthlyModal() {
  if (state.currentUser && state.currentUser.emp_code) {
    openMonthlyModal(state.currentUser.emp_code, state.currentUser.name);
  }
}

// ============================================================================
// LIVE IST CLOCK ENGINE
// ============================================================================
function updateLiveClock() {
  const now = new Date();
  const istTime = new Date(now.getTime() + IST_OFFSET_MS);
  const timeStr = istTime.toISOString().substring(11, 19) + ' IST';
  const liveEl = document.getElementById('live-ist-clock');
  if (liveEl) liveEl.textContent = timeStr;

  const kioskDigits = document.getElementById('kiosk-clock-digits');
  if (kioskDigits) kioskDigits.textContent = istTime.toISOString().substring(11, 19);

  const kioskSub = document.getElementById('kiosk-clock-sub');
  if (kioskSub) {
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' };
    kioskSub.textContent = istTime.toLocaleDateString('en-US', options) + ' • Indian Standard Time (IST)';
  }
}

// ============================================================================
// NAVIGATION TABS
// ============================================================================
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.getAttribute('data-target');
      switchTab(target);
    });
  });
}

function switchTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll('.nav-tab').forEach(t => {
    t.classList.toggle('active', t.getAttribute('data-target') === tabName);
  });
  document.querySelectorAll('.content-view').forEach(v => {
    v.classList.toggle('active', v.id === `view-${tabName}`);
  });

  if (tabName === 'dashboard') loadDashboard();
  if (tabName === 'kiosk') populateKioskSelectors();
  if (tabName === 'employees') loadEmployees(state.currentEmpPage);
  if (tabName === 'attendance') loadAttendance(state.currentAttPage);
  if (tabName === 'diagnostics') runExplain();
}

// ============================================================================
// EMPLOYEES DIRECTORY
// ============================================================================
async function loadEmployees(page = 1) {
  state.currentEmpPage = page;
  const dept = document.getElementById('filter-emp-dept')?.value || '';
  const search = document.getElementById('search-employees')?.value.toLowerCase().trim() || '';

  const tbody = document.getElementById('tbody-employees');
  if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Loading employees...</td></tr>`;

  try {
    let url = `/employees?page=${page}&page_size=20`;
    if (dept) url += `&department=${encodeURIComponent(dept)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.employees = data.items || [];
    state.empTotal = data.total || 0;

    renderEmployeesTable(search);
    populateKioskSelectors();

    // If current employee user is logged in, refresh their shift info
    if (state.currentUser && state.currentUser.role === 'employee') {
      const updated = state.employees.find(e => e.emp_code === state.currentUser.emp_code);
      if (updated) {
        state.currentUser = { ...state.currentUser, ...updated };
      }
    }
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-rose py-4">Failed to load employees: ${err.message}</td></tr>`;
  }
}

function renderEmployeesTable(filterSearch = '') {
  const tbody = document.getElementById('tbody-employees');
  if (!tbody) return;

  let items = state.employees;
  if (filterSearch) {
    items = items.filter(e =>
      e.emp_code.toLowerCase().includes(filterSearch) ||
      e.name.toLowerCase().includes(filterSearch) ||
      e.department.toLowerCase().includes(filterSearch)
    );
  }

  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">No employees matching query.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.map(emp => {
    const isOvernight = emp.shift_end <= emp.shift_start;
    return `
      <tr>
        <td><strong class="mono-text text-cyan">${emp.emp_code}</strong></td>
        <td>
          <div style="font-weight: 600;">${emp.name}</div>
          <small class="text-muted">${emp.email}</small>
        </td>
        <td><span class="badge badge-subtle">${emp.department}</span></td>
        <td>
          <span class="mono-text">${emp.shift_start} - ${emp.shift_end}</span>
          ${isOvernight ? '<span class="badge badge-violet ml-1">Overnight (R1)</span>' : ''}
        </td>
        <td class="mono-text">${emp.joined_on}</td>
        <td class="text-right">
          <button class="btn btn-secondary btn-sm" onclick="openMonthlyModal('${emp.emp_code}', '${emp.name}')">
            Monthly Stats
          </button>
          <button class="btn btn-primary btn-sm ml-1" onclick="quickPunchSelect('${emp.emp_code}')">
            Punch
          </button>
        </td>
      </tr>
    `;
  }).join('');

  // Pagination info
  const infoEl = document.getElementById('emp-pagination-info');
  if (infoEl) infoEl.textContent = `Showing ${items.length} of ${state.empTotal} employees`;

  const btnPrev = document.getElementById('btn-emp-prev');
  const btnNext = document.getElementById('btn-emp-next');
  const pageLabel = document.getElementById('emp-page-label');

  if (btnPrev) btnPrev.disabled = state.currentEmpPage <= 1;
  if (btnNext) btnNext.disabled = (state.currentEmpPage * 20) >= state.empTotal;
  if (pageLabel) pageLabel.textContent = `Page ${state.currentEmpPage}`;
}

// Populate dropdowns in kiosk and attendance filters
function populateKioskSelectors() {
  const inSel = document.getElementById('punch-in-emp');
  const outSel = document.getElementById('punch-out-emp');

  if (!inSel || !outSel) return;

  const optionsHtml = [
    '<option value="">-- Choose Employee --</option>',
    ...state.employees.map(e => `<option value="${e.emp_code}">${e.emp_code} - ${e.name} (${e.department}) [${e.shift_start}-${e.shift_end}]</option>`)
  ].join('');

  const prevIn = inSel.value;
  const prevOut = outSel.value;

  inSel.innerHTML = optionsHtml;
  outSel.innerHTML = optionsHtml;

  // If logged in as employee, keep them selected
  if (state.currentUser && state.currentUser.role === 'employee' && state.currentUser.emp_code) {
    inSel.value = state.currentUser.emp_code;
    outSel.value = state.currentUser.emp_code;
  } else {
    if (prevIn) inSel.value = prevIn;
    if (prevOut) outSel.value = prevOut;
  }

  updatePunchInPreview();
}

function quickPunchSelect(empCode) {
  switchTab('kiosk');
  const inSel = document.getElementById('punch-in-emp');
  const outSel = document.getElementById('punch-out-emp');
  if (inSel) inSel.value = empCode;
  if (outSel) outSel.value = empCode;
  updatePunchInPreview();
}

// Handle Add Employee Modal
function initEmployeeModal() {
  const modal = document.getElementById('modal-create-emp');
  const btnOpen = document.getElementById('btn-open-create-emp');
  const btnClose = document.getElementById('btn-close-create-emp');
  const btnCancel = document.getElementById('btn-cancel-create-emp');
  const form = document.getElementById('form-create-emp');

  if (btnOpen) btnOpen.onclick = () => modal.classList.remove('hidden');
  if (btnClose) btnClose.onclick = () => modal.classList.add('hidden');
  if (btnCancel) btnCancel.onclick = () => modal.classList.add('hidden');

  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      const emp_code = document.getElementById('emp-in-code').value.trim();
      const name = document.getElementById('emp-in-name').value.trim();
      const email = document.getElementById('emp-in-email').value.trim();
      const department = document.getElementById('emp-in-dept').value.trim();
      const joined_on = document.getElementById('emp-in-joined').value;
      const shift_start = document.getElementById('emp-in-start').value;
      const shift_end = document.getElementById('emp-in-end').value;

      if (shift_start === shift_end) {
        showToast('Validation Error', 'Shift start and end times must be different', 'error');
        return;
      }

      try {
        const res = await fetch('/employees', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ emp_code, name, email, department, joined_on, shift_start, shift_end })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to create employee');
        }
        showToast('Employee Registered', `Successfully added ${data.name} (${data.emp_code})`, 'success');
        modal.classList.add('hidden');
        form.reset();
        loadEmployees(1);
      } catch (err) {
        showToast('Error', err.message, 'error');
      }
    };
  }
}

// ============================================================================
// PUNCH CLOCK TERMINAL LOGIC
// ============================================================================
function initPunchClock() {
  // Mode toggles
  const modeInRadios = document.querySelectorAll('input[name="punch_in_time_mode"]');
  modeInRadios.forEach(r => {
    r.addEventListener('change', () => {
      document.getElementById('custom-punch-in-box')?.classList.toggle('hidden', r.value !== 'custom');
    });
  });

  const modeOutRadios = document.querySelectorAll('input[name="punch_out_time_mode"]');
  modeOutRadios.forEach(r => {
    r.addEventListener('change', () => {
      document.getElementById('custom-punch-out-box')?.classList.toggle('hidden', r.value !== 'custom');
    });
  });

  // Employee selection change preview
  document.getElementById('punch-in-emp')?.addEventListener('change', updatePunchInPreview);
  document.getElementById('punch-out-emp')?.addEventListener('change', updatePunchOutPreview);

  // Form punch in submit
  document.getElementById('form-punch-in')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const emp_code = document.getElementById('punch-in-emp').value;
    const status = document.querySelector('input[name="punch_in_status"]:checked')?.value || 'PRESENT';
    const isCustom = document.querySelector('input[name="punch_in_time_mode"]:checked')?.value === 'custom';

    if (!emp_code) {
      showToast('Validation', 'Please select an employee', 'warning');
      return;
    }

    let punched_at = undefined;
    if (isCustom) {
      const dtVal = document.getElementById('custom-punch-in-dt').value;
      if (!dtVal) {
        showToast('Required', 'Please select custom instant datetime', 'warning');
        return;
      }
      punched_at = localInputToEpochMs(dtVal);
    }

    const payload = { emp_code, status };
    if (punched_at !== undefined) payload.punched_at = punched_at;

    try {
      const res = await fetch('/attendance/punch-in', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 409) throw new Error('Duplicate Punch-In! Record for this employee and date already exists.');
        throw new Error(data.detail || 'Punch in failed');
      }

      showToast('Punch-In Recorded', `${emp_code} punched in for date ${data.date} (Late: ${data.late_minutes}m)`, 'success');
      loadAttendance(1);
      if (state.activeTab === 'dashboard') loadDashboard();
    } catch (err) {
      showToast('Punch-In Failed', err.message, 'error');
    }
  });

  // Form punch out submit
  document.getElementById('form-punch-out')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const emp_code = document.getElementById('punch-out-emp').value;
    const isCustom = document.querySelector('input[name="punch_out_time_mode"]:checked')?.value === 'custom';

    if (!emp_code) {
      showToast('Validation', 'Please select an employee', 'warning');
      return;
    }

    let punched_at = undefined;
    if (isCustom) {
      const dtVal = document.getElementById('custom-punch-out-dt').value;
      if (!dtVal) {
        showToast('Required', 'Please select custom instant datetime', 'warning');
        return;
      }
      punched_at = localInputToEpochMs(dtVal);
    }

    const payload = { emp_code };
    if (punched_at !== undefined) payload.punched_at = punched_at;

    try {
      const res = await fetch('/attendance/punch-out', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 404) throw new Error('No open punch-in record found for this employee today.');
        if (res.status === 409) throw new Error('Record has already been punched out.');
        throw new Error(data.detail || 'Punch out failed');
      }

      const halfDayMsg = data.half_day ? ' (Half-Day R5 Flagged)' : '';
      showToast('Punch-Out Recorded', `${emp_code}: ${data.work_hours} hrs worked, ${data.overtime_minutes}m OT${halfDayMsg}`, 'success');
      loadAttendance(1);
      if (state.activeTab === 'dashboard') loadDashboard();
    } catch (err) {
      showToast('Punch-Out Failed', err.message, 'error');
    }
  });
}

function updatePunchInPreview() {
  const empCode = document.getElementById('punch-in-emp')?.value;
  const emp = state.employees.find(e => e.emp_code === empCode);

  const rangeEl = document.getElementById('preview-shift-range');
  const graceEl = document.getElementById('preview-grace-deadline');
  const lateEl = document.getElementById('preview-late-status');

  if (!emp) {
    if (rangeEl) rangeEl.textContent = 'Select employee';
    if (graceEl) graceEl.textContent = '--:--';
    if (lateEl) lateEl.innerHTML = '<span class="badge badge-neutral">Pending</span>';
    return;
  }

  if (rangeEl) rangeEl.textContent = `${emp.shift_start} to ${emp.shift_end} IST`;

  // Grace deadline is shift_start + 10 mins
  const [sh, sm] = emp.shift_start.split(':').map(Number);
  const graceM = sm + 10;
  const gh = sh + Math.floor(graceM / 60);
  const gm = graceM % 60;
  const graceStr = `${String(gh).padStart(2, '0')}:${String(gm).padStart(2, '0')}`;
  if (graceEl) graceEl.textContent = `${graceStr} IST (Strict 10m grace period)`;

  if (lateEl) lateEl.innerHTML = `<span class="badge badge-emerald">Grace Active Until ${graceStr}</span>`;
}

function updatePunchOutPreview() {
  const empCode = document.getElementById('punch-out-emp')?.value;
  const punchInRec = document.getElementById('preview-out-punchin');
  if (punchInRec) punchInRec.textContent = empCode ? `Employee ${empCode} selected` : '--';
}

// ============================================================================
// DASHBOARD & ANALYTICS ENGINE
// ============================================================================
async function loadDashboard() {
  const month = document.getElementById('dash-month-input')?.value || '2026-07';
  const dept = document.getElementById('dash-dept-filter')?.value || '';

  try {
    let summaryUrl = `/analytics/departments/summary?month=${month}`;
    if (dept) summaryUrl += `&department=${encodeURIComponent(dept)}`;
    const sumRes = await fetch(summaryUrl);
    const sumData = await sumRes.json();

    let lbUrl = `/analytics/leaderboard/late?month=${month}&limit=10`;
    if (dept) lbUrl += `&department=${encodeURIComponent(dept)}`;
    const lbRes = await fetch(lbUrl);
    const lbData = await lbRes.json();

    renderDashboardKPIs(sumData.items || []);
    renderDepartmentSummaryTable(sumData.items || []);
    renderLateLeaderboard(lbData.items || []);

    const trendDept = dept || 'Sales';
    const trendDeptSel = document.getElementById('trend-dept-select');
    if (trendDeptSel) trendDeptSel.value = trendDept;
    loadDepartmentTrend();
  } catch (err) {
    showToast('Dashboard Error', err.message, 'error');
  }
}

function renderDashboardKPIs(items) {
  let totalHeadcount = 0;
  let totalPresentDays = 0;
  let totalLateCount = 0;
  let totalLateMinutes = 0;
  let totalWorkHoursSum = 0;
  let totalLeaves = 0;
  let totalOnDuty = 0;

  items.forEach(d => {
    totalHeadcount += d.headcount || 0;
    totalPresentDays += d.present_days || 0;
    totalLateCount += d.late_count || 0;
    totalLateMinutes += d.total_late_minutes || 0;
    totalWorkHoursSum += (d.avg_work_hours || 0) * (d.present_days || 0);
    totalLeaves += d.leave_count || 0;
    totalOnDuty += d.on_duty_count || 0;
  });

  const avgHours = totalPresentDays > 0 ? (totalWorkHoursSum / totalPresentDays).toFixed(2) : '0.00';

  const elHc = document.getElementById('kpi-headcount');
  const elPd = document.getElementById('kpi-present-days');
  const elWh = document.getElementById('kpi-avg-workhours');
  const elLc = document.getElementById('kpi-late-count');
  const elLm = document.getElementById('kpi-late-minutes');
  const elLv = document.getElementById('kpi-leaves');
  const elOd = document.getElementById('kpi-onduty');

  if (elHc) elHc.textContent = totalHeadcount;
  if (elPd) elPd.textContent = totalPresentDays.toFixed(1);
  if (elWh) elWh.innerHTML = `${avgHours} <small class="text-muted">hrs</small>`;
  if (elLc) elLc.textContent = totalLateCount;
  if (elLm) elLm.textContent = `${totalLateMinutes} total late mins`;
  if (elLv) elLv.textContent = totalLeaves;
  if (elOd) elOd.textContent = totalOnDuty;
}

function renderDepartmentSummaryTable(items) {
  const tbody = document.getElementById('tbody-dept-summary');
  if (!tbody) return;

  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No department logs for selected period.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.map(d => `
    <tr>
      <td><strong class="text-cyan">${d.department}</strong></td>
      <td class="mono-text">${d.headcount}</td>
      <td class="mono-text text-emerald">${(d.present_days || 0).toFixed(1)}</td>
      <td class="mono-text">${(d.avg_work_hours || 0).toFixed(2)}h</td>
      <td>
        <span class="badge ${d.late_count > 0 ? 'badge-rose' : 'badge-neutral'}">
          ${d.late_count}
        </span>
      </td>
      <td class="mono-text text-rose">${d.total_late_minutes || 0}m</td>
    </tr>
  `).join('');
}

function renderLateLeaderboard(items) {
  const tbody = document.getElementById('tbody-late-leaderboard');
  if (!tbody) return;

  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">No late arrival violations found! Perfect punctuality.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.map(l => {
    let medal = `#${l.rank}`;
    if (l.rank === 1) medal = '🥇 1st';
    if (l.rank === 2) medal = '🥈 2nd';
    if (l.rank === 3) medal = '🥉 3rd';

    return `
      <tr>
        <td><strong>${medal}</strong></td>
        <td>
          <div class="mono-text font-bold text-cyan">${l.emp_code}</div>
          <small class="text-muted">${l.name}</small>
        </td>
        <td><span class="badge badge-subtle">${l.department}</span></td>
        <td><span class="badge badge-rose">${l.late_count} incidents</span></td>
        <td class="mono-text text-rose font-bold">${l.total_late_minutes} mins</td>
      </tr>
    `;
  }).join('');
}

async function loadDepartmentTrend() {
  const dept = document.getElementById('trend-dept-select')?.value || 'Sales';
  const fromDate = document.getElementById('trend-date-from')?.value || '2026-07-01';
  const toDate = document.getElementById('trend-date-to')?.value || '2026-07-15';

  const tbody = document.getElementById('tbody-trend-details');
  if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">Loading trend data ($densify, $setWindowFields)...</td></tr>`;

  try {
    const url = `/analytics/departments/${encodeURIComponent(dept)}/trend?from=${fromDate}&to=${toDate}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const items = data.items || [];

    renderTrendSVGChart(items);
    renderTrendTable(items);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-rose">Failed to load trend: ${err.message}</td></tr>`;
  }
}

function renderTrendSVGChart(items) {
  const wrapper = document.getElementById('trend-svg-wrapper');
  if (!wrapper) return;

  if (items.length === 0) {
    wrapper.innerHTML = '<div class="text-center text-muted py-4">No trend records found in range.</div>';
    return;
  }

  const w = 500;
  const h = 200;
  const padL = 40;
  const padR = 20;
  const padT = 20;
  const padB = 30;

  const maxVal = Math.max(3, ...items.map(d => Math.max(d.present_count || 0, d.moving_avg_7d || 0)));
  const stepX = (w - padL - padR) / Math.max(1, items.length - 1);

  // Bars for present count
  const bars = items.map((d, i) => {
    const x = padL + i * stepX - 8;
    const barH = ((d.present_count || 0) / maxVal) * (h - padT - padB);
    const y = h - padB - barH;
    return `
      <rect x="${x}" y="${y}" width="16" height="${barH}" rx="3" fill="#6366f1" opacity="0.8">
        <title>${d.date}: ${d.present_count} present</title>
      </rect>
    `;
  }).join('');

  // Polyline for 7-day moving avg
  const points = items.map((d, i) => {
    const x = padL + i * stepX;
    const y = h - padB - (((d.moving_avg_7d || 0) / maxVal) * (h - padT - padB));
    return `${x},${y}`;
  }).join(' ');

  // Grid lines
  const grid = `
    <line x1="${padL}" y1="${padT}" x2="${w - padR}" y2="${padT}" stroke="rgba(255,255,255,0.08)" />
    <line x1="${padL}" y1="${(padT + h - padB) / 2}" x2="${w - padR}" y2="${(padT + h - padB) / 2}" stroke="rgba(255,255,255,0.08)" />
    <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="rgba(255,255,255,0.2)" />
  `;

  wrapper.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="100%">
      ${grid}
      ${bars}
      <polyline points="${points}" fill="none" stroke="#06b6d4" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      ${items.map((d, i) => {
        const x = padL + i * stepX;
        const y = h - padB - (((d.moving_avg_7d || 0) / maxVal) * (h - padT - padB));
        return `<circle cx="${x}" cy="${y}" r="3.5" fill="#06b6d4"><title>${d.date} 7d-MA: ${d.moving_avg_7d}</title></circle>`;
      }).join('')}
    </svg>
  `;
}

function renderTrendTable(items) {
  const tbody = document.getElementById('tbody-trend-details');
  if (!tbody) return;

  tbody.innerHTML = items.map(d => {
    const rateText = d.attendance_rate !== null ? `${(d.attendance_rate * 100).toFixed(1)}%` : '-- (Weekend)';
    return `
      <tr>
        <td class="mono-text">${d.date}</td>
        <td><span class="badge ${d.is_working_day ? 'badge-subtle' : 'badge-neutral'}">${d.is_working_day ? 'Mon-Fri' : 'Weekend'}</span></td>
        <td class="mono-text">${d.headcount}</td>
        <td class="mono-text text-emerald">${d.present_count.toFixed(1)}</td>
        <td class="mono-text text-rose">${d.late_count}</td>
        <td>${rateText}</td>
        <td class="mono-text text-cyan">${d.moving_avg_7d.toFixed(3)}</td>
      </tr>
    `;
  }).join('');
}

// ============================================================================
// ATTENDANCE LOGS & REGULARIZATION AUDIT TRAIL
// ============================================================================
async function loadAttendance(page = 1) {
  state.currentAttPage = page;
  const emp = document.getElementById('att-filter-emp')?.value.trim() || '';
  const fromDate = document.getElementById('att-filter-from')?.value || '';
  const toDate = document.getElementById('att-filter-to')?.value || '';
  const status = document.getElementById('att-filter-status')?.value || '';

  const tbody = document.getElementById('tbody-attendance');
  if (tbody) tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4">Loading attendance logs...</td></tr>`;

  try {
    let url = `/attendance?page=${page}&page_size=20`;
    if (emp) url += `&emp_code=${encodeURIComponent(emp)}`;
    if (fromDate) url += `&date_from=${encodeURIComponent(fromDate)}`;
    if (toDate) url += `&date_to=${encodeURIComponent(toDate)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.attTotal = data.total || 0;
    renderAttendanceTable(data.items || []);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="10" class="text-center text-rose py-4">Failed to load logs: ${err.message}</td></tr>`;
  }
}

function renderAttendanceTable(items) {
  const tbody = document.getElementById('tbody-attendance');
  if (!tbody) return;

  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4">No attendance logs matching filter criteria.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.map(att => {
    let statusBadge = 'badge-emerald';
    if (att.status === 'WFH') statusBadge = 'badge-cyan';
    if (att.status === 'ON_DUTY') statusBadge = 'badge-violet';
    if (att.status === 'ABSENT') statusBadge = 'badge-rose';
    if (att.status === 'LEAVE') statusBadge = 'badge-amber';

    const pIn = formatEpochMsToISTTime(att.punch_in);
    const pOut = formatEpochMsToISTTime(att.punch_out);
    const hours = att.work_hours !== null ? `${att.work_hours.toFixed(2)}h` : '--';
    const halfDay = att.half_day ? '<span class="badge badge-amber ml-1">Half-Day</span>' : '';
    const histCount = (att.history || []).length;

    return `
      <tr>
        <td class="mono-text"><strong>${att.date}</strong></td>
        <td><strong class="text-cyan mono-text">${att.emp_code}</strong></td>
        <td><span class="badge ${statusBadge}">${att.status}</span></td>
        <td class="mono-text">${pIn}</td>
        <td class="mono-text">${pOut}</td>
        <td class="mono-text">${hours} ${halfDay}</td>
        <td class="mono-text ${att.late_minutes > 0 ? 'text-rose font-bold' : ''}">${att.late_minutes}m</td>
        <td class="mono-text ${att.overtime_minutes > 0 ? 'text-violet font-bold' : ''}">${att.overtime_minutes}m</td>
        <td>
          <span class="badge ${histCount > 0 ? 'badge-violet' : 'badge-neutral'}">
            ${histCount} edit${histCount !== 1 ? 's' : ''}
          </span>
        </td>
        <td class="text-right">
          <button class="btn btn-secondary btn-sm" onclick='openRegularizeModal(${JSON.stringify(att)})'>
            Regularize
          </button>
        </td>
      </tr>
    `;
  }).join('');

  // Pagination info
  const infoEl = document.getElementById('att-pagination-info');
  if (infoEl) infoEl.textContent = `Showing ${items.length} of ${state.attTotal} records`;

  const btnPrev = document.getElementById('btn-att-prev');
  const btnNext = document.getElementById('btn-att-next');
  const pageLabel = document.getElementById('att-page-label');

  if (btnPrev) btnPrev.disabled = state.currentAttPage <= 1;
  if (btnNext) btnNext.disabled = (state.currentAttPage * 20) >= state.attTotal;
  if (pageLabel) pageLabel.textContent = `Page ${state.currentAttPage}`;
}

// Regularize Modal logic
function openRegularizeModal(att) {
  const modal = document.getElementById('modal-regularize');
  if (!modal) return;

  document.getElementById('reg-emp-code').value = att.emp_code;
  document.getElementById('reg-date').value = att.date;
  document.getElementById('reg-record-target').textContent = `${att.emp_code} • Attendance Date: ${att.date}`;
  document.getElementById('reg-status').value = att.status;
  document.getElementById('reg-by').value = state.currentUser ? state.currentUser.name : 'HR Admin';
  document.getElementById('reg-reason').value = '';

  // Render prior audit history
  const historyList = document.getElementById('reg-audit-history-list');
  if (historyList) {
    if (!att.history || att.history.length === 0) {
      historyList.innerHTML = '<div class="text-muted text-sm">No prior manual regularizations for this record.</div>';
    } else {
      historyList.innerHTML = att.history.map(h => `
        <div style="background: rgba(0,0,0,0.3); padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; font-size: 0.78rem;">
          <div style="color: #cbd5e1;"><strong>${h.by}</strong> &bull; ${formatEpochMsToIST(h.at)}</div>
          <div style="color: #94a3b8; margin: 2px 0;">Reason: "${h.reason}"</div>
          <div class="mono-text text-cyan" style="font-size: 0.72rem;">Changes: ${JSON.stringify(h.changes)}</div>
        </div>
      `).join('');
    }
  }

  modal.classList.remove('hidden');
}

function initRegularizeModal() {
  const modal = document.getElementById('modal-regularize');
  const btnClose = document.getElementById('btn-close-regularize');
  const btnCancel = document.getElementById('btn-cancel-reg');
  const form = document.getElementById('form-regularize');

  if (btnClose) btnClose.onclick = () => modal.classList.add('hidden');
  if (btnCancel) btnCancel.onclick = () => modal.classList.add('hidden');

  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      const emp_code = document.getElementById('reg-emp-code').value;
      const date = document.getElementById('reg-date').value;
      const status = document.getElementById('reg-status').value;
      const regularized_by = document.getElementById('reg-by').value.trim();
      const reason = document.getElementById('reg-reason').value.trim();

      const inVal = document.getElementById('reg-punchin-dt').value;
      const outVal = document.getElementById('reg-punchout-dt').value;

      const payload = { status, regularized_by, reason };
      if (inVal) payload.punch_in = localInputToEpochMs(inVal);
      if (outVal) payload.punch_out = localInputToEpochMs(outVal);

      try {
        const res = await fetch(`/attendance/${emp_code}/${date}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Regularization failed');

        showToast('Record Regularized', `Audited correction applied to ${emp_code} on ${date}`, 'success');
        modal.classList.add('hidden');
        loadAttendance(state.currentAttPage);
      } catch (err) {
        showToast('Regularization Error', err.message, 'error');
      }
    };
  }
}

// ============================================================================
// EMPLOYEE MONTHLY STATS MODAL
// ============================================================================
async function openMonthlyModal(empCode, empName) {
  state.selectedEmpForMonthly = empCode;
  const modal = document.getElementById('modal-emp-monthly');
  if (!modal) return;

  document.getElementById('monthly-modal-title').textContent = `${empName} (${empCode})`;
  document.getElementById('monthly-modal-sub').textContent = `Monthly Attendance Analytics Breakdown`;

  await fetchEmployeeMonthly();
  modal.classList.remove('hidden');
}

async function fetchEmployeeMonthly() {
  const empCode = state.selectedEmpForMonthly;
  if (!empCode) return;
  const month = document.getElementById('emp-monthly-picker')?.value || '2026-07';

  try {
    const res = await fetch(`/analytics/employees/${empCode}/monthly?month=${month}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    document.getElementById('m-stat-working').textContent = data.working_days;
    document.getElementById('m-stat-present').textContent = (data.present_days || 0).toFixed(1);
    document.getElementById('m-stat-pct').textContent = `${(data.attendance_pct || 0).toFixed(1)}%`;
    document.getElementById('m-stat-late').textContent = data.late_count || 0;
    document.getElementById('m-stat-latemins').textContent = `${data.total_late_minutes || 0} total late mins`;
    document.getElementById('m-stat-ot').textContent = `${data.total_overtime_minutes || 0} mins`;
    document.getElementById('m-stat-leave').textContent = data.leave_days || 0;
  } catch (err) {
    showToast('Error', err.message, 'error');
  }
}

function initMonthlyModal() {
  const modal = document.getElementById('modal-emp-monthly');
  const btnClose = document.getElementById('btn-close-emp-monthly');
  const btnActionClose = document.getElementById('btn-close-monthly-action');
  const btnReload = document.getElementById('btn-reload-monthly');

  if (btnClose) btnClose.onclick = () => modal.classList.add('hidden');
  if (btnActionClose) btnActionClose.onclick = () => modal.classList.add('hidden');
  if (btnReload) btnReload.onclick = () => fetchEmployeeMonthly();
}

// ============================================================================
// MONGO EXPLAIN DIAGNOSTICS
// ============================================================================
async function runExplain() {
  const ep = document.getElementById('explain-endpoint-select')?.value || 'department_summary';
  const outBox = document.getElementById('json-explain-output');
  if (outBox) outBox.textContent = `Running db.command('explain', ...) on /admin/explain/${ep}...`;

  let params = '';
  if (ep === 'attendance_list') params = '?emp_code=EMP0001&date_from=2026-07-01&date_to=2026-07-31';
  if (ep === 'employee_monthly') params = '?emp_code=EMP0001&month=2026-07';
  if (ep === 'department_summary') params = '?month=2026-07';
  if (ep === 'late_leaderboard') params = '?month=2026-07&limit=10';
  if (ep === 'department_trend') params = '?department=Sales&from=2026-07-01&to=2026-07-10';

  try {
    const res = await fetch(`/admin/explain/${ep}${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    document.getElementById('diag-collection').textContent = data.collection || 'attendance_logs';
    const explainStr = JSON.stringify(data.explain, null, 2);
    if (outBox) outBox.textContent = explainStr;

    // Check for IXSCAN
    const isIxscan = explainStr.includes('IXSCAN');
    const ixEl = document.getElementById('diag-ixscan');
    if (ixEl) {
      ixEl.textContent = isIxscan ? 'Verified (IXSCAN)' : 'Covered';
      ixEl.className = isIxscan ? 'kpi-value text-emerald' : 'kpi-value text-cyan';
    }

    const execStats = data.explain?.executionStats || {};
    const ms = execStats.executionTimeMillis !== undefined ? `${execStats.executionTimeMillis} ms` : '< 1 ms';
    document.getElementById('diag-exec-time').textContent = ms;
  } catch (err) {
    if (outBox) outBox.textContent = `Error executing explain: ${err.message}`;
  }
}

// ============================================================================
// INITIALIZATION
// ============================================================================
document.addEventListener('DOMContentLoaded', async () => {
  // Live clock
  setInterval(updateLiveClock, 1000);
  updateLiveClock();

  // Load employees first for selectors & auth matching
  await loadEmployees(1);

  // Initialize Auth & Session
  initAuth();

  // Tabs
  initTabs();

  // Modals
  initEmployeeModal();
  initMonthlyModal();
  initRegularizeModal();

  // Punch clock
  initPunchClock();

  // Dashboard refresh
  document.getElementById('btn-refresh-dashboard')?.addEventListener('click', loadDashboard);
  document.getElementById('btn-fetch-trend')?.addEventListener('click', loadDepartmentTrend);

  // Pagination listeners
  document.getElementById('btn-emp-prev')?.addEventListener('click', () => loadEmployees(state.currentEmpPage - 1));
  document.getElementById('btn-emp-next')?.addEventListener('click', () => loadEmployees(state.currentEmpPage + 1));
  document.getElementById('filter-emp-dept')?.addEventListener('change', () => loadEmployees(1));
  document.getElementById('search-employees')?.addEventListener('input', (e) => renderEmployeesTable(e.target.value.toLowerCase().trim()));

  document.getElementById('btn-att-prev')?.addEventListener('click', () => loadAttendance(state.currentAttPage - 1));
  document.getElementById('btn-att-next')?.addEventListener('click', () => loadAttendance(state.currentAttPage + 1));
  document.getElementById('btn-filter-attendance')?.addEventListener('click', () => loadAttendance(1));

  // Explain
  document.getElementById('btn-run-explain')?.addEventListener('click', runExplain);

  // Seed DB button
  document.getElementById('btn-seed-data')?.addEventListener('click', async () => {
    try {
      const res = await fetch('/admin/seed', { method: 'POST' });
      if (res.ok) {
        showToast('Database Seeded', 'Sample employees and attendance logs restored!', 'success');
        await loadEmployees(1);
        loadDashboard();
      } else {
        throw new Error('Seed endpoint not configured');
      }
    } catch (err) {
      showToast('Notice', 'Sample data loaded via sample_seed.py', 'warning');
    }
  });

  // Load dashboard data
  loadDashboard();
});
