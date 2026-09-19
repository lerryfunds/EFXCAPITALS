/* =========================================================
   EFXCAPITALS — Admin console (demo, localStorage-backed)
   Data: users, packages, withdrawals, audit logs
   ========================================================= */

const ADMIN_NAME = 'Admin';
const KEYS = { users:'efx_users', packages:'efx_packages', withdrawals:'efx_withdrawals', logs:'efx_logs' };

const fmt = n => '$' + Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const now  = () => new Date().toLocaleString('en-US',{month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'});

/* ---------- Storage ---------- */
function load(key, seed){
  try{
    const raw = localStorage.getItem(key);
    if(raw !== null) return JSON.parse(raw);
  }catch(e){}
  localStorage.setItem(key, JSON.stringify(seed));
  return JSON.parse(JSON.stringify(seed));
}
function save(key, val){ localStorage.setItem(key, JSON.stringify(val)); }
const nextId = arr => arr.reduce((m,a) => Math.max(m, +a.id||0), 0) + 1;

/* ---------- Seed data ---------- */
const SEED_USERS = [
  {id:1,name:'John Carter',  username:'johncarter', email:'john@example.com',   balance:2847.50, status:'active',   role:'user',   createdAt:'Aug 01 2026'   },
  {id:2,name:'Lisa Morgan',  username:'j.morgan',   email:'lisa@example.com',   balance:1200.00, status:'active',   role:'user',   createdAt:'Aug 12 2026'   },
  {id:3,name:'Kevin Trader', username:'k.trader',   email:'kevin@example.com',  balance:3100.00, status:'active',   role:'user',   createdAt:'Aug 20 2026'   },
  {id:4,name:'Sam Wilson',   username:'samwilson',  email:'sam@example.com',    balance:85.00,   status:'disabled', role:'user',   createdAt:'Sep 01 2026'   },
  {id:5,name:'Eva Chen',     username:'evachen',    email:'eva@example.com',    balance:0.00,    status:'active',   role:'user',   createdAt:'Sep 05 2026'   }
];

const SEED_PACKAGES = [
  {id:1,name:'Oil',      subtype:'Crude oil',      roi:6.7, min:20,   max:500,    cycles:30, durDays:30, interval:24, active:true,  featured:true},
  {id:2,name:'Gas',      subtype:'LPG GAS',        roi:6.7, min:500,  max:1000,   cycles:30, durDays:30, interval:24, active:true,  featured:false},
  {id:3,name:'Gold',     subtype:'Gold',           roi:4.0, min:800,  max:5000,   cycles:50, durDays:50, interval:24, active:true,  featured:false},
  {id:4,name:'Crypto',   subtype:'Cryptocurrency', roi:6.7, min:5000, max:10000,  cycles:30, durDays:30, interval:24, active:true,  featured:false},
  {id:5,name:'Premium',  subtype:'Investor',       roi:6.7, min:10000,max:100000, cycles:30, durDays:30, interval:24, active:true,  featured:false}
];

const SEED_WITHDRAWALS = [
  {id:1,userId:1,user:'John Carter', amount:120.00, network:'TRC20', address:'TWVopKQ96Ffp9w1c2UEzqhZ4pi3JkM8Yc', status:'pending',  date:'Sep 06 2026'},
  {id:2,userId:3,user:'Kevin Trader', amount:250.00, network:'TRC20', address:'TKv2mQ84Gfp8xXh4aCdZEtpH3jRkS9AwBd', status:'pending',  date:'Sep 08 2026'},
  {id:3,userId:2,user:'Lisa Morgan', amount:80.00, network:'BEP20',  address:'0x5aB3f2EaC78d94Bb21C9Ff6Aa8B23D1eF0c90A2e', status:'approved', date:'Aug 28 2026'}
];

const SEED_LOGS = [
  {id:3, time:'Sep 08 · 14:02', level:'success', actor:'System',    action:'Cycle payout credited', detail:'Oil payout +$1.34 to johncarter'},
  {id:2, time:'Sep 08 · 09:41', level:'info',    actor:'Admin',     action:'Package edited',        detail:'Updated max range of Oil package'},
  {id:1, time:'Sep 07 · 18:15', level:'warn',    actor:'system',    action:'Withdrawal requested',  detail:'WDR-12008 · $120.00 pending review'}
];

/* ---------- API ---------- */
const DB = {
  users:       () => load(KEYS.users, SEED_USERS),
  packages:    () => load(KEYS.packages, SEED_PACKAGES),
  withdrawals: () => load(KEYS.withdrawals, SEED_WITHDRAWALS),
  logs:        () => load(KEYS.logs, SEED_LOGS),
  saveUsers:       v => save(KEYS.users, v),
  savePackages:    v => save(KEYS.packages, v),
  saveWithdrawals: v => save(KEYS.withdrawals, v),
  saveLogs:        v => save(KEYS.logs, v),
  reset: () => { Object.values(KEYS).forEach(k=>localStorage.removeItem(k)); }
};

function addLog(level, action, detail){
  const logs = DB.logs();
  logs.unshift({id:nextId(logs), time:now(), level, actor:ADMIN_NAME, action, detail});
  DB.saveLogs(logs.slice(0,200));
}

function findUser(id){ return DB.users().find(u => String(u.id) === String(id)); }
function findPkg(id){ return DB.packages().find(p => String(p.id) === String(id)); }

/* ---------- Shared shell init: active nav + admin count ---------- */
document.addEventListener('DOMContentLoaded', () => {
  const nav = document.querySelector('[data-active]');
  if(nav){
    document.querySelectorAll('.side-link[href]').forEach(a => {
      if(a.getAttribute('href').split('?')[0] === nav.getAttribute('data-active')){
        a.classList.add('active');
      }
    });
  }
  const pending = DB.withdrawals().filter(w => w.status === 'pending').length;
  document.querySelectorAll('[id="pendingWCount"]').forEach(el => el.textContent = pending);
});

/* ---------- Modal helper ---------- */
function openModal(id){ document.getElementById(id).classList.add('open'); }
function closeModal(id){ document.getElementById(id).classList.remove('open'); }
const esc = s => String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
window.addEventListener('keydown', e => { if(e.key==='Escape') document.querySelectorAll('.modal-bg.open').forEach(m=>m.classList.remove('open')); });

/* =========================================================
   ADMIN OVERVIEW (admin.html)
   ========================================================= */
function initAdminOverview(){
  const users = DB.users(), pkgs = DB.packages(), wd = DB.withdrawals(), logs = DB.logs();
  const pendWd = wd.filter(w => w.status === 'pending');

  const set = (id,v) => { const el = document.getElementById(id); if(el) el.textContent = v; };
  set('stUsers', users.length);
  set('stActive', users.filter(u=>u.status==='active').length);
  set('stPackages', pkgs.filter(p=>p.active).length);
  set('stPending', pendWd.length);

  const sum = arr => arr.reduce((a,b)=>a+(+b.amount||0),0);
  set('stWdAmt', fmt(sum(pendWd)));
  set('stLogs', logs.length);

  const wdBody = document.getElementById('recentWd');
  if(wdBody){
    wdBody.innerHTML = pendWd.slice(0,4).map(w => `
      <tr>
        <td><b>${esc(w.user)}</b></td>
        <td class="mono">WDR-${w.id}</td>
        <td>${fmt(w.amount)}</td>
        <td><span class="tag gold">Pending</span></td>
      </tr>`).join('') || `<tr><td colspan="4"><div class="empty">No pending withdrawals</div></td></tr>`;
  }

  const userBody = document.getElementById('recentUsers');
  if(userBody){
    userBody.innerHTML = users.slice(0,4).map(u => `
      <tr>
        <td><div class="user-cell"><span class="avatar">${esc(initials(u.name))}</span><div><b>${esc(u.name)}</b><span class="user-email">@${esc(u.username)}</span></div></div></td>
        <td>${fmt(u.balance)}</td>
        <td><span class="tag ${u.status==='active'?'green':u.status==='disabled'?'red':'grey'}">${u.status==='disabled'?'Disabled':u.status==='active'?'Active':u.status}</span></td>
      </tr>`).join('') || `<tr><td colspan="3"><div class="empty">No users yet</div></td></tr>`;
  }

  const logBody = document.getElementById('recentLogs');
  if(logBody){
    logBody.innerHTML = logs.slice(0,4).map(l => logRow(l)).join('') || `<div class="empty">No activity yet</div>`;
  }
}
function initials(name){
  return String(name||'?').trim().split(/\s+/).map(w=>w[0]).slice(0,2).join('').toUpperCase() || '?';
}

/* =========================================================
   ADMIN USERS (admin-users.html)
   ========================================================= */
function initAdminUsers(){
  const tbody = document.getElementById('usersBody');
  const render = (list) => {
    if(!tbody) return;
    tbody.innerHTML = list.map(u => `
      <tr>
        <td><div class="user-cell"><span class="avatar">${esc(initials(u.name))}</span><div><b>${esc(u.name)}</b><span class="user-email">${esc(u.email)}</span></div></div></td>
        <td>@${esc(u.username)}</td>
        <td>${fmt(u.balance)}</td>
        <td>${u.status==='disabled'?'<span class="tag red">Disabled</span>':'<span class="tag green">Active</span>'}</td>
        <td>${u.createdAt}</td>
        <td>
          <div class="act-row">
            <a href="admin-user-form.html?id=${u.id}" class="act-btn" title="Edit">✎</a>
            <button class="act-btn ${u.status==='disabled'?'green':'warn'}" title="${u.status==='disabled'?'Enable':'Disable'}" onclick="toggleUser(${u.id})">${u.status==='disabled'?'✓':'⊘'}</button>
            <button class="act-btn danger" title="Delete" onclick="askDeleteUser(${u.id})">🗑</button>
          </div>
        </td>
      </tr>`).join('') || `<tr><td colspan="6"><div class="empty">No users match your search</div></td></tr>`;
  };
  render(DB.users());

  const q = document.getElementById('userSearch');
  if(q) q.addEventListener('input', () => {
    const t = q.value.toLowerCase();
    render(DB.users().filter(u =>
      u.name.toLowerCase().includes(t) || u.username.toLowerCase().includes(t) || (u.email||'').toLowerCase().includes(t)));
  });

  let targetId = null;
  window.askDeleteUser = id => {
    targetId = id;
    const u = findUser(id);
    document.getElementById('delName').textContent = u ? u.name : 'this user';
    openModal('confirmDelUser');
  };
  document.getElementById('confirmDelUser')?.addEventListener('click', e => {
    if(e.target.id === 'doDeleteUser'){
      const u = findUser(targetId);
      DB.saveUsers(DB.users().filter(x => x.id !== targetId));
      addLog('danger', 'User deleted', (u?u.name+' (@'+u.username+')':'User #'+targetId));
      closeModal('confirmDelUser');
      render(DB.users());
      toast('User deleted');
    } else if(e.target.id === 'closeDelUser'){
      closeModal('confirmDelUser');
    }
  });

  window.toggleUser = id => {
    const users = DB.users();
    const u = users.find(x => x.id === id);
    if(!u) return;
    const wasDisabled = u.status === 'disabled';
    u.status = wasDisabled ? 'active' : 'disabled';
    DB.saveUsers(users);
    addLog(wasDisabled?'success':'warn', (wasDisabled?'User enabled':'User disabled'), u.name+' (@'+u.username+')');
    render(DB.users());
    toast(wasDisabled ? u.name+' enabled' : u.name+' disabled');
  };
}

/* =========================================================
   ADMIN USER FORM (admin-user-form.html?mode=new|id=)
   ========================================================= */
function initAdminUserForm(){
  const qp = new URLSearchParams(location.search);
  const isEdit = qp.has('id');
  const u = isEdit ? findUser(qp.get('id')) : null;

  document.getElementById('formTitle').textContent = isEdit ? 'Edit User' : 'Create User';
  document.getElementById('pageTitle').textContent = isEdit ? 'Edit ' + (u?u.name:'User') : 'Create User';
  document.getElementById('cancelLink').href = 'admin-users.html';

  const btn = document.getElementById('submitBtn');
  const dirtyIcon = document.getElementById('savedTag');
  if(dirtyIcon) dirtyIcon.style.display = 'none';

  if(u){
    document.getElementById('id').value = u.id;
    document.getElementById('name').value = u.name;
    document.getElementById('username').value = u.username;
    document.getElementById('email').value = u.email;
    document.getElementById('balance').value = u.balance;
    document.getElementById('role').value = u.role;
    document.getElementById('status').value = u.status;
    btn.textContent = 'Save Changes';
  } else {
    btn.textContent = 'Create User';
  }

  document.getElementById('userForm').addEventListener('submit', e => {
    e.preventDefault();
    const users = DB.users();
    const data = {
      name: document.getElementById('name').value.trim(),
      username: document.getElementById('username').value.trim().replace(/^@/,''),
      email: document.getElementById('email').value.trim(),
      balance: parseFloat(document.getElementById('balance').value) || 0,
      role: document.getElementById('role').value,
      status: document.getElementById('status').value
    };
    if(!data.name || !data.username || !data.email){ toast('Name, username and email are required','red'); return; }
    if(users.some(x => x.username.toLowerCase() === data.username.toLowerCase() && String(x.id) !== document.getElementById('id').value)){
      toast('Username already in use','red'); return;
    }
    if(isEdit){
      const target = findUser(document.getElementById('id').value);
      Object.assign(target, data);
      DB.saveUsers(users);
      addLog('info','User updated', data.name+' (@'+data.username+') · balance '+fmt(data.balance)+' · status '+data.status);
    } else {
      const created = Object.assign({id:nextId(users), createdAt:new Date().toLocaleDateString('en-US',{month:'short',day:'2-digit',year:'numeric'})}, data);
      users.push(created);
      DB.saveUsers(users);
      addLog('success', (data.status==='disabled'?'User created (disabled)':'User created'), data.name+' (@'+data.username+') · +'+fmt(data.balance));
    }
    showSaved();
    setTimeout(() => location.href = 'admin-users.html', 900);
  });
}

/* =========================================================
   ADMIN PACKAGES (admin-packages.html)
   ========================================================= */
function initAdminPackages(){
  const tbody = document.getElementById('pkgBody');
  const render = list => {
    if(!tbody) return;
    tbody.innerHTML = list.map(p => `
      <tr>
        <td><div style="display:flex;align-items:center;gap:11px"><span class="pkg-token">${esc(p.name.slice(0,2).toUpperCase())}</span><b>${esc(p.name)}${p.featured?' <span class="tag gold">Featured</span>':''}</b></div></td>
        <td>${p.roi}% /cycle</td>
        <td class="mono">$${p.min.toLocaleString()} · $${p.max.toLocaleString()}</td>
        <td>${p.cycles} · ${p.durDays}d</td>
        <td><button class="toggle ${p.active?'on':''}" title="${p.active?'Deactivate':'Activate'}" onclick="togglePkg(${p.id})"></button></td>
        <td>
          <div class="act-row">
            <a href="admin-package-form.html?id=${p.id}" class="act-btn" title="Edit">✎</a>
            <button class="act-btn danger" title="Delete" onclick="askDeletePkg(${p.id})">🗑</button>
          </div>
        </td>
      </tr>`).join('') || `<tr><td colspan="6"><div class="empty">No packages yet — create one</div></td></tr>`;
  };
  render(DB.packages());

  const q = document.getElementById('pkgSearch');
  if(q) q.addEventListener('input', () => {
    const t = q.value.toLowerCase();
    render(DB.packages().filter(p => p.name.toLowerCase().includes(t) || (p.subtype||'').toLowerCase().includes(t)));
  });

  let targetId = null;
  window.askDeletePkg = id => {
    targetId = id;
    const p = findPkg(id);
    document.getElementById('delPkgName').textContent = p ? p.name + ' Package' : 'this package';
    openModal('confirmDelPkg');
  };
  document.getElementById('confirmDelPkg')?.addEventListener('click', e => {
    if(e.target.id === 'doDeletePkg'){
      const p = findPkg(targetId);
      DB.savePackages(DB.packages().filter(x => x.id !== targetId));
      addLog('danger', 'Package deleted', p?p.name+' package':'#'+targetId);
      closeModal('confirmDelPkg');
      render(DB.packages());
      toast('Package deleted');
    } else if(e.target.id === 'closeDelPkg'){
      closeModal('confirmDelPkg');
    }
  });

  window.togglePkg = id => {
    const list = DB.packages();
    const p = list.find(x => x.id === id);
    if(!p) return;
    p.active = !p.active;
    DB.savePackages(list);
    addLog(p.active?'success':'warn', (p.active?'Package activated':'Package deactivated'), p.name+' package');
    render(list);
    toast(p.name+' package '+(p.active?'activated':'deactivated'));
  };
}

/* =========================================================
   ADMIN PACKAGE FORM (admin-package-form.html?mode=new|id=)
   ========================================================= */
function initAdminPackageForm(){
  const qp = new URLSearchParams(location.search);
  const isEdit = qp.has('id');
  const p = isEdit ? findPkg(qp.get('id')) : null;

  document.getElementById('formTitle').textContent = isEdit ? 'Edit Package' : 'Create Package';
  document.getElementById('pageTitle').textContent = isEdit ? 'Edit ' + (p?p.name:'Package') : 'Create Package';
  document.getElementById('cancelLink').href = 'admin-packages.html';
  const btn = document.getElementById('submitBtn');

  if(p){
    document.getElementById('id').value = p.id;
    document.getElementById('name').value = p.name;
    document.getElementById('subtype').value = p.subtype;
    document.getElementById('roi').value = p.roi;
    document.getElementById('min').value = p.min;
    document.getElementById('max').value = p.max;
    document.getElementById('cycles').value = p.cycles;
    document.getElementById('dur').value = p.durDays;
    document.getElementById('interval').value = p.interval;
    document.getElementById('featured').checked = !!p.featured;
    btn.textContent = 'Save Changes';
  } else {
    btn.textContent = 'Create Package';
  }

  document.getElementById('pkgForm').addEventListener('submit', e => {
    e.preventDefault();
    const roi = parseFloat(document.getElementById('roi').value);
    const min = parseFloat(document.getElementById('min').value);
    const max = parseFloat(document.getElementById('max').value);
    const cycles = parseInt(document.getElementById('cycles').value, 10);
    if(!document.getElementById('name').value.trim() || isNaN(roi) || isNaN(min) || isNaN(max) || isNaN(cycles)){
      toast('Fill in all required numeric fields','red'); return;
    }
    if(max <= min){ toast('Maximum must be larger than minimum','red'); return; }
    const data = {
      name: document.getElementById('name').value.trim(),
      subtype: document.getElementById('subtype').value.trim(),
      roi, min, max,
      cycles,
      durDays: parseInt(document.getElementById('dur').value,10) || cycles,
      interval: parseInt(document.getElementById('interval').value,10) || 24,
      featured: document.getElementById('featured').checked
    };
    if(isEdit){
      Object.assign(findPkg(document.getElementById('id').value), data);
      DB.savePackages(DB.packages());
      addLog('info','Package updated', data.name+' package · '+data.roi+'% · $'+min+'–$'+max);
    } else {
      const list = DB.packages();
      list.push(Object.assign({id:nextId(list), active:true}, data));
      DB.savePackages(list);
      addLog('success','Package created', data.name+' package · '+data.roi+'% · $'+min+'–$'+max);
    }
    toast('Package saved');
    setTimeout(() => location.href = 'admin-packages.html', 900);
  });
}

/* =========================================================
   ADMIN WITHDRAWALS (admin-withdrawals.html)
   ========================================================= */
function initAdminWithdrawals(){
  const tbody = document.getElementById('wdBody');
  const statusFilter = document.getElementById('wdFilter');

  const render = () => {
    let list = DB.withdrawals();
    const f = statusFilter ? statusFilter.value : 'all';
    if(f !== 'all') list = list.filter(w => w.status === f);
    if(!tbody) return;
    tbody.innerHTML = list.map(w => `
      <tr>
        <td class="mono">WDR-${w.id}</td>
        <td><b>${esc(w.user)}</b></td>
        <td>${fmt(w.amount)}</td>
        <td>${w.network}</td>
        <td><span class="mono" style="font-size:11.5px">${esc(w.address.slice(0,14))}…</span></td>
        <td>${w.date}</td>
        <td>
          ${w.status==='pending'
            ? `<div class="act-row">
                <button class="act-btn green" title="Approve" onclick="approveWd(${w.id})">✓ Approve</button>
                <button class="act-btn danger" title="Reject" onclick="rejectWd(${w.id})">✕</button>
              </div>`
            : `<span class="tag ${w.status==='approved'?'green':'red'}">${w.status==='approved'?'Approved':'Rejected'}</span>`}
        </td>
      </tr>`).join('') || `<tr><td colspan="7"><div class="empty">No withdrawals in this view</div></td></tr>`;
  };
  render();
  if(statusFilter) statusFilter.addEventListener('change', render);

  window.approveWd = id => {
    const list = DB.withdrawals();
    const w = list.find(x => x.id === id);
    if(!w) return;
    w.status = 'approved';
    const users = DB.users();
    const u = users.find(x => x.id === w.userId);
    if(u) u.balance = (+u.balance||0) - (+w.amount||0);
    DB.saveWithdrawals(list); DB.saveUsers(users);
    addLog('success','Withdrawal approved','WDR-'+id+' · '+fmt(w.amount)+' to '+w.user+' ('+w.network+')');
    render();
    toast('Withdrawal approved — balance debited');
  };

  window.rejectWd = id => {
    const list = DB.withdrawals();
    const w = list.find(x => x.id === id);
    if(!w) return;
    w.status = 'rejected';
    DB.saveWithdrawals(list);
    addLog('warn','Withdrawal rejected','WDR-'+id+' · '+fmt(w.amount)+' · '+w.user);
    render();
    toast('Withdrawal rejected');
  };
}

/* =========================================================
   ADMIN LOGS (admin-logs.html)
   ========================================================= */
function initAdminLogs(){
  const box = document.getElementById('logsBox');
  const f = document.getElementById('logFilter');
  const render = () => {
    let list = DB.logs();
    const lv = f ? f.value : 'all';
    if(lv !== 'all') list = list.filter(l => l.level === lv);
    if(!box) return;
    box.innerHTML = list.map(logRow).join('') || `<div class="empty">No log entries</div>`;
  };
  render();
  if(f) f.addEventListener('change', render);

  document.getElementById('clearLogs')?.addEventListener('click', () => {
    DB.saveLogs([]);
    addLog('info','Logs cleared','Audit log was reset by admin');
    render();
    toast('Logs cleared');
  });

  document.getElementById('resetDemo')?.addEventListener('click', () => {
    DB.reset();
    location.reload();
  });
}

/* ---------- Shared render helpers ---------- */
function logRow(l){
  return `<div class="log-item">
    <span class="l-dot ${esc(l.level)}"></span>
    <div>
      <div><span class="l-who">${esc(l.actor)}</span> · ${esc(l.action)}</div>
      <div class="l-action">${esc(l.detail)}</div>
    </div>
    <span class="l-time">${esc(l.time)}</span>
  </div>`;
}

function showSaved(){
  const t = document.getElementById('savedTag');
  if(t) t.style.display = 'inline-flex';
}
let toastTimer = null;
function toast(msg, level){
  const el = document.getElementById('toast');
  if(!el) return;
  el.textContent = msg;
  el.className = 'toast show' + (level === 'red' ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2400);
}

/* ---------- Per-page bootstrap ---------- */
(function boot(){
  const AUTH_KEY = 'efx_admin_auth';
  const file = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  const authed = localStorage.getItem(AUTH_KEY) === '1';
  const isAdminPage = file.indexOf('admin') === 0;

  /* Admin session gate */
  if(isAdminPage && file !== 'admin-login.html'){
    if(!authed){
      location.replace('admin-login.html');
      return;
    }
    const cta = document.querySelector('.side-cta');
    if(cta){
      const lo = document.createElement('a');
      lo.href = '#';
      lo.className = 'btn btn-ghost btn-block';
      lo.style.marginTop = '8px';
      lo.textContent = 'Log Out';
      lo.addEventListener('click', e => { e.preventDefault(); adminLogout(); });
      cta.appendChild(lo);
    }
  }
  if(file === 'admin-login.html' && authed){
    location.replace('admin.html');
    return;
  }

  const page = document.body.getAttribute('data-page');
  if(page === 'overview') initAdminOverview();
  if(page === 'users')     initAdminUsers();
  if(page === 'userForm')  initAdminUserForm();
  if(page === 'packages')  initAdminPackages();
  if(page === 'pkgForm')   initAdminPackageForm();
  if(page === 'withdrawals') initAdminWithdrawals();
  if(page === 'logs')      initAdminLogs();
})();

function adminLogout(){
  localStorage.removeItem('efx_admin_auth');
  location.href = 'index.html';
}
window.adminLogout = adminLogout;