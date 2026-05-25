const state = {
  authToken: sessionStorage.getItem("authToken") || "",
  currentUser: null,
  savedUnitIds: new Set(),
  activeTab: "category",
  ncsTree: [],
  selectedSubcategoryCode: "",
  selectedSubcategoryName: "",
  resultTab: "full",
  lastSearchResult: null,
  isSearching: false,
  selectedResultKey: "",
  selectedUnitCategoryId: "",
  lastJobDescriptionUnitId: "",
  lastMatrixUnitId: "",
};

function isLoggedIn() {
  return Boolean(state.authToken);
}

function apiHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (state.authToken) headers.Authorization = `Bearer ${state.authToken}`;
  return headers;
}

async function safeJson(res) {
  try {
    return await res.json();
  } catch {
    return {};
  }
}

async function apiGet(url) {
  const res = await fetch(url, {
    headers: apiHeaders(),
    cache: "no-store",
  });
  if (!res.ok) throw new Error((await safeJson(res)).detail || `GET failed: ${res.status}`);
  return res.json();
}

async function apiPost(url, payload) {
  const res = await fetch(url, { method: "POST", headers: apiHeaders(), body: JSON.stringify(payload) });
  if (!res.ok) throw new Error((await safeJson(res)).detail || `POST failed: ${res.status}`);
  return res.json();
}

function updateAuthUi() {
  const badge = document.getElementById("authStatusBadge");
  const loginBtn = document.getElementById("loginBtn");
  const logoutBtn = document.getElementById("logoutBtn");
  const myUnitsBtn = document.getElementById("myUnitsBtn");
  const unitMatrixBtn = document.getElementById("unitMatrixBtn");
  if (!badge) return;

  if (isLoggedIn() && state.currentUser) {
    const u = state.currentUser;
    badge.textContent = `${u.full_name} · ${u.company_name}`;
    badge.title = `${u.email} / ${u.department_name}`;
    loginBtn.classList.add("hidden");
    logoutBtn.classList.remove("hidden");
    myUnitsBtn.classList.remove("hidden");
    unitMatrixBtn?.classList.remove("hidden");
  } else {
    badge.textContent = "게스트";
    badge.title = "";
    loginBtn.classList.remove("hidden");
    logoutBtn.classList.add("hidden");
    myUnitsBtn.classList.add("hidden");
    unitMatrixBtn?.classList.add("hidden");
  }
}

function logout() {
  state.authToken = "";
  state.currentUser = null;
  state.savedUnitIds = new Set();
  sessionStorage.removeItem("authToken");
  updateAuthUi();
}

async function loadCurrentUser() {
  if (!state.authToken) {
    state.currentUser = null;
    return null;
  }
  const user = await apiGet("/api/auth/me");
  state.currentUser = user;
  updateAuthUi();
  await refreshSavedUnitIds();
  return user;
}

async function refreshSavedUnitIds() {
  if (!isLoggedIn()) {
    state.savedUnitIds = new Set();
    return;
  }
  try {
    const data = await apiGet("/api/me/units");
    state.savedUnitIds = new Set((data.items || []).map((item) => String(item.unit_category_id)));
  } catch {
    state.savedUnitIds = new Set();
  }
}

function showAuthError(el, message) {
  if (!el) return;
  if (!message) {
    el.textContent = "";
    el.classList.add("hidden");
    return;
  }
  el.textContent = message;
  el.classList.remove("hidden");
}

function openAuthModal(view = "login", presetEmail = "") {
  document.getElementById("authModal")?.classList.remove("hidden");
  showAuthError(document.getElementById("loginError"), "");
  showAuthError(document.getElementById("signupError"), "");
  if (view === "signup") {
    document.getElementById("loginView")?.classList.add("hidden");
    document.getElementById("signupView")?.classList.remove("hidden");
    if (presetEmail) document.getElementById("signupEmail").value = presetEmail;
  } else {
    document.getElementById("signupView")?.classList.add("hidden");
    document.getElementById("loginView")?.classList.remove("hidden");
    if (presetEmail) document.getElementById("loginEmail").value = presetEmail;
  }
}

function closeAuthModal() {
  document.getElementById("authModal")?.classList.add("hidden");
}

function openGuestFeatureModal(message) {
  const el = document.getElementById("guestFeatureMessage");
  if (el) el.textContent = message || "로그인 후 이용할 수 있습니다.";
  document.getElementById("guestFeatureModal")?.classList.remove("hidden");
}

function closeGuestFeatureModal() {
  document.getElementById("guestFeatureModal")?.classList.add("hidden");
}

async function submitLogin() {
  const email = document.getElementById("loginEmail")?.value.trim().toLowerCase();
  const password = document.getElementById("loginPassword")?.value || "";
  const errEl = document.getElementById("loginError");
  showAuthError(errEl, "");
  if (!email || !password) {
    showAuthError(errEl, "이메일과 비밀번호를 입력하세요.");
    return;
  }
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await safeJson(res);
    if (!res.ok) {
      if (res.status === 404) {
        showAuthError(errEl, data.detail || "가입 이력이 없습니다.");
        openAuthModal("signup", email);
        return;
      }
      throw new Error(data.detail || "로그인에 실패했습니다.");
    }
    state.authToken = data.access_token;
    sessionStorage.setItem("authToken", state.authToken);
    state.currentUser = data.user;
    updateAuthUi();
    await refreshSavedUnitIds();
    closeAuthModal();
    closeGuestFeatureModal();
    if (state.selectedUnitCategoryId) {
      const panels = getWorkspacePanels();
      await renderUnitStructure(state.selectedUnitCategoryId, null, panels.structureEl);
    }
  } catch (err) {
    showAuthError(errEl, err.message);
  }
}

async function submitSignup() {
  const payload = {
    email: document.getElementById("signupEmail")?.value.trim().toLowerCase(),
    password: document.getElementById("signupPassword")?.value || "",
    full_name: document.getElementById("signupFullName")?.value.trim(),
    phone: document.getElementById("signupPhone")?.value.trim() || null,
    company_name: document.getElementById("signupCompany")?.value.trim(),
    department_name: document.getElementById("signupDepartment")?.value.trim(),
  };
  const errEl = document.getElementById("signupError");
  showAuthError(errEl, "");
  if (!payload.email || !payload.password || !payload.full_name || !payload.company_name || !payload.department_name) {
    showAuthError(errEl, "필수 항목을 모두 입력하세요.");
    return;
  }
  if (payload.password.length < 8) {
    showAuthError(errEl, "비밀번호는 8자 이상이어야 합니다.");
    return;
  }
  try {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await safeJson(res);
    if (!res.ok) throw new Error(data.detail || "회원가입에 실패했습니다.");
    state.authToken = data.access_token;
    sessionStorage.setItem("authToken", state.authToken);
    state.currentUser = data.user;
    updateAuthUi();
    await refreshSavedUnitIds();
    closeAuthModal();
    alert("회원가입이 완료되었습니다.");
  } catch (err) {
    showAuthError(errEl, err.message);
  }
}

async function resolveUnitNcsMeta(unitCategoryId) {
  const uid = String(unitCategoryId || "").trim();
  if (!uid) return null;
  return apiGet(`/api/ncs/unit-meta/${encodeURIComponent(uid)}`);
}

async function enrichUnitSelectionsForDisplay(items) {
  if (!items.length) return [];
  return Promise.all(
    items.map(async (item) => {
      const uid = String(item.unit_category_id || "").trim();
      if (!uid) return item;
      try {
        const meta = await resolveUnitNcsMeta(uid);
        if (!meta?.subcategory_code) return item;
        return {
          ...item,
          unit_name: item.unit_name || meta.unit_name,
          subcategory_code: meta.subcategory_code,
          subcategory_name: meta.subcategory_name || item.subcategory_name,
        };
      } catch {
        return item;
      }
    })
  );
}

async function saveUnitToMyList(unit, hierarchyItem) {
  if (!isLoggedIn()) {
    openGuestFeatureModal("로그인 후 능력단위를 저장할 수 있습니다.");
    return;
  }
  const unitId = String(unit.unit_category_id || "").trim();
  if (!unitId) return;

  let meta = null;
  try {
    meta = await resolveUnitNcsMeta(unitId);
  } catch {
    meta = null;
  }

  const payload = {
    unit_category_id: unitId,
    unit_name: meta?.unit_name || unit.unit_name || null,
    subcategory_code: meta?.subcategory_code || unit.subcategory_code || hierarchyItem?.subcategory_code || null,
    subcategory_name: meta?.subcategory_name || unit.subcategory_name || hierarchyItem?.subcategory_name || null,
  };
  const saved = await apiPost("/api/me/units", payload);
  state.savedUnitIds.add(unitId);
  return saved;
}

function parseFilenameFromDisposition(headerValue) {
  if (!headerValue) return null;
  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) return decodeURIComponent(utf8Match[1]);
  const plainMatch = headerValue.match(/filename="?([^";]+)"?/i);
  return plainMatch ? plainMatch[1] : null;
}

async function downloadMyUnitsExcel() {
  if (!isLoggedIn()) {
    openGuestFeatureModal("엑셀 다운로드는 로그인 후 이용할 수 있습니다.");
    return;
  }
  const res = await fetch("/api/me/units/export", { headers: apiHeaders() });
  if (!res.ok) {
    const err = await safeJson(res);
    throw new Error(err.detail || "엑셀 다운로드에 실패했습니다.");
  }
  const blob = await res.blob();
  const filename =
    parseFilenameFromDisposition(res.headers.get("Content-Disposition")) ||
    `ncs_units_export_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}.xlsx`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function removeUnitFromMyList(unitCategoryId) {
  await fetch(`/api/me/units/${encodeURIComponent(unitCategoryId)}`, {
    method: "DELETE",
    headers: apiHeaders(),
  }).then(async (res) => {
    if (!res.ok) throw new Error((await safeJson(res)).detail || "삭제 실패");
  });
  state.savedUnitIds.delete(String(unitCategoryId));
}

async function openMyUnitsModal() {
  if (!isLoggedIn()) {
    openAuthModal("login");
    return;
  }
  const modal = document.getElementById("myUnitsModal");
  const listEl = document.getElementById("myUnitsList");
  modal?.classList.remove("hidden");
  listEl.className = "my-units-list detail-empty";
  listEl.textContent = "불러오는 중...";
  try {
    const data = await apiGet("/api/me/units");
    const items = await enrichUnitSelectionsForDisplay(data.items || []);
    if (!items.length) {
      listEl.className = "my-units-list detail-empty";
      listEl.textContent = "저장한 능력단위가 없습니다.";
      document.getElementById("myUnitsPrintAllJdsBtn")?.classList.add("hidden");
      document.getElementById("myUnitsExportBtn")?.classList.add("hidden");
      return;
    }
    listEl.className = "my-units-list";
    listEl.innerHTML = items
      .map(
        (item) => `
        <div class="my-unit-row" data-unit-id="${escapeHtml(item.unit_category_id)}">
          <div>
            <div class="unit-name"><b>${escapeHtml(item.unit_name || item.unit_category_id)}</b></div>
            <div class="meta">코드: ${escapeHtml(item.unit_category_id)}</div>
            <div class="meta">세분류: ${escapeHtml(item.subcategory_code || "-")} ${escapeHtml(item.subcategory_name || "")}</div>
          </div>
          <div class="my-unit-actions">
            <button type="button" class="small-btn my-unit-jds" data-unit-id="${escapeHtml(item.unit_category_id)}">직무기술서</button>
            <button type="button" class="small-btn my-unit-delete" data-unit-id="${escapeHtml(item.unit_category_id)}">삭제</button>
          </div>
        </div>
      `
      )
      .join("");
    document.getElementById("myUnitsPrintAllJdsBtn")?.classList.remove("hidden");
    document.getElementById("myUnitsExportBtn")?.classList.remove("hidden");
    listEl.querySelectorAll(".my-unit-jds").forEach((btn) => {
      btn.onclick = () => {
        const id = btn.dataset.unitId;
        if (!id) return;
        closeMyUnitsModal();
        openJobDescriptionModal(id).catch((err) => alert(err.message));
      };
    });
    listEl.querySelectorAll(".my-unit-delete").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.unitId;
        if (!id || !confirm("저장 목록에서 삭제할까요?")) return;
        await removeUnitFromMyList(id);
        await openMyUnitsModal();
        document.querySelectorAll(".unit-save-btn").forEach((saveBtn) => {
          if (saveBtn.dataset.unitId === id) saveBtn.textContent = "저장";
        });
      };
    });
  } catch (err) {
    listEl.className = "my-units-list detail-empty";
    listEl.textContent = `불러오기 실패: ${err.message}`;
  }
}

function closeMyUnitsModal() {
  document.getElementById("myUnitsModal")?.classList.add("hidden");
}

function buildJdsBulletList(items) {
  if (!items?.length) {
    return '<p class="jds-empty">등록된 내용이 없습니다.</p>';
  }
  return `<ul class="jds-bullet-list">${items.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
}

function buildJobDescriptionHtml(data) {
  const devDate = data.development_date || "-";
  const devOrg = data.development_org || "-";
  const jobPurpose = data.job_purpose || "등록된 직무 목적이 없습니다.";

  const responsibilityRows = (data.elements || [])
    .map((element) => {
      const items = (element.responsibilities || [])
        .map((row) => {
          const no = row.criteria_no ? `${escapeHtml(row.criteria_no)}. ` : "";
          return `<li>${no}${escapeHtml(row.text)}</li>`;
        })
        .join("");
      return `
        <tr>
          <td class="jds-label-cell">${escapeHtml(element.unit_element_name || "-")}</td>
          <td class="jds-content-cell">
            ${items ? `<ol class="jds-numbered-list">${items}</ol>` : '<span class="jds-empty">-</span>'}
          </td>
        </tr>
      `;
    })
    .join("");

  const evalSectionsHtml = Array.isArray(data.evaluation_sections)
    ? data.evaluation_sections
        .filter((sec) => sec?.items?.length)
        .map(
          (sec) => `
      <p class="jds-section-title">□ ${escapeHtml(sec.title)}</p>
      ${buildJdsBulletList(sec.items)}`
        )
        .join("")
    : "";

  return `
    <article class="jds-print-sheet" data-unit-id="${escapeHtml(data.unit_category_id)}">
      <h2 class="jds-title">직무기술서</h2>
      <table class="jds-table jds-info-table">
        <tbody>
          <tr>
            <th>직무</th>
            <td class="jds-value">${escapeHtml(data.job_title || data.subcategory_name || "-")}</td>
            <th>능력단위분류번호</th>
            <td class="jds-value">${escapeHtml(data.unit_category_id)}</td>
            <th>능력단위</th>
            <td class="jds-value">${escapeHtml(data.unit_name)}</td>
          </tr>
          <tr>
            <th>직무 목적</th>
            <td class="jds-value" colspan="5">${escapeHtml(jobPurpose)}</td>
          </tr>
          <tr>
            <th>개발날짜<br>(개선날짜)</th>
            <td class="jds-value">${escapeHtml(devDate)}</td>
            <th>개발기관<br>(개선기관)</th>
            <td class="jds-value" colspan="3">${escapeHtml(devOrg)}</td>
          </tr>
        </tbody>
      </table>

      <p class="jds-section-title">□ 직무 책임 및 역할</p>
      <table class="jds-table">
        <thead>
          <tr>
            <th>주요업무</th>
            <th>책임 및 역할</th>
          </tr>
        </thead>
        <tbody>
          ${responsibilityRows || '<tr><td colspan="2" class="jds-empty">등록된 수행준거가 없습니다.</td></tr>'}
        </tbody>
      </table>

      <p class="jds-section-title">□ 직무 수행 요건</p>
      <table class="jds-table">
        <tbody>
          <tr>
            <th>지식</th>
            <td class="jds-content-cell">${buildJdsBulletList(data.knowledge)}</td>
          </tr>
          <tr>
            <th>기술</th>
            <td class="jds-content-cell">${buildJdsBulletList(data.skills)}</td>
          </tr>
          <tr>
            <th>태도</th>
            <td class="jds-content-cell">${buildJdsBulletList(data.attitudes)}</td>
          </tr>
        </tbody>
      </table>
      ${evalSectionsHtml}
    </article>
  `;
}

async function fetchJobDescription(unitCategoryId) {
  const uid = String(unitCategoryId || "").trim();
  if (!uid) throw new Error("능력단위 코드가 없습니다.");
  return apiGet(`/api/units/${encodeURIComponent(uid)}/job-description`);
}

async function openJobDescriptionModal(unitCategoryId, options = {}) {
  if (!isLoggedIn()) {
    openGuestFeatureModal("직무기술서는 로그인 후 이용할 수 있습니다.");
    return;
  }
  const uid = String(unitCategoryId || "").trim();
  if (!uid) return;

  const modal = document.getElementById("jobDescriptionModal");
  const body = document.getElementById("jobDescriptionBody");
  const printAllBtn = document.getElementById("jdsPrintAllBtn");
  modal?.classList.remove("hidden");
  document.body.classList.add("jds-modal-open");
  body.className = "jds-body detail-empty";
  body.textContent = "직무기술서를 불러오는 중입니다...";
  state.lastJobDescriptionUnitId = uid;

  if (printAllBtn) {
    printAllBtn.classList.toggle("hidden", !options.showPrintAll);
  }

  try {
    const data = await fetchJobDescription(uid);
    body.className = "jds-body";
    body.innerHTML = buildJobDescriptionHtml(data);
  } catch (err) {
    body.className = "jds-body detail-empty";
    body.textContent = `직무기술서 로딩 실패: ${err.message}`;
  }
}

function closeJobDescriptionModal() {
  document.getElementById("jobDescriptionModal")?.classList.add("hidden");
  document.body.classList.remove("printing-jds", "jds-modal-open");
}

function printJobDescriptionModal() {
  const body = document.getElementById("jobDescriptionBody");
  if (!body?.querySelector(".jds-print-sheet")) {
    alert("인쇄할 직무기술서가 없습니다.");
    return;
  }
  document.body.classList.add("printing-jds");
  window.print();
  window.setTimeout(() => document.body.classList.remove("printing-jds"), 500);
}

async function printAllJobDescriptions() {
  if (!isLoggedIn()) {
    openGuestFeatureModal("로그인 후 이용할 수 있습니다.");
    return;
  }
  const modal = document.getElementById("jobDescriptionModal");
  const body = document.getElementById("jobDescriptionBody");
  modal?.classList.remove("hidden");
  document.body.classList.add("jds-modal-open");
  body.className = "jds-body detail-empty";
  body.textContent = "저장한 능력단위 직무기술서를 불러오는 중입니다...";

  try {
    const listData = await apiGet("/api/me/units");
    const items = listData.items || [];
    if (!items.length) {
      alert("저장한 능력단위가 없습니다.");
      closeJobDescriptionModal();
      return;
    }

    const sheets = [];
    for (const item of items) {
      const uid = String(item.unit_category_id || "").trim();
      if (!uid) continue;
      try {
        const data = await fetchJobDescription(uid);
        sheets.push(buildJobDescriptionHtml(data));
      } catch (err) {
        sheets.push(
          `<article class="jds-print-sheet"><p class="jds-empty">${escapeHtml(uid)}: ${escapeHtml(err.message)}</p></article>`
        );
      }
    }

    body.className = "jds-body";
    body.innerHTML = sheets.join("");
    document.getElementById("jdsPrintAllBtn")?.classList.remove("hidden");
    printJobDescriptionModal();
  } catch (err) {
    body.className = "jds-body detail-empty";
    body.textContent = `일괄 로딩 실패: ${err.message}`;
  }
}

function setActiveTab(tab) {
  state.activeTab = tab;
  document.getElementById("categoryTab").classList.toggle("active", tab === "category");
  document.getElementById("naturalTab").classList.toggle("active", tab === "natural");
  document.getElementById("unitMatrixTab")?.classList.toggle("active", tab === "matrix");
  document.getElementById("tabCategoryBtn").classList.toggle("active", tab === "category");
  document.getElementById("tabNaturalBtn").classList.toggle("active", tab === "natural");
}

const MATRIX_PRINT_ICON = `<svg class="matrix-jds-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M19 8H5a3 3 0 0 0-3 3v6h4v4h12v-4h4v-6a3 3 0 0 0-3-3zm-3 11H8v-5h8v5zm3-7a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm-1-9H6v4h12V3z"/></svg>`;

function buildMatrixUnitRow(unit, selected) {
  const unitId = String(unit.unit_category_id || "");
  const attrs = ` data-unit-id="${escapeHtml(unitId)}" data-sub-code="${escapeHtml(unit.subcategory_code)}" data-sub-name="${escapeHtml(unit.subcategory_name)}" data-unit-name="${escapeHtml(unit.unit_name)}"`;
  const unitCls = selected ? "selected" : "unselected";
  const namePart = selected
    ? `<span class="matrix-unit-name">${escapeHtml(unit.unit_name)}</span><button type="button" class="small-btn matrix-unit-delete no-print" data-unit-id="${escapeHtml(unitId)}">삭제</button>`
    : `<button type="button" class="matrix-unit-save clickable"${attrs}>${escapeHtml(unit.unit_name)}</button>`;
  return `
    <div class="matrix-unit-row">
      <div class="matrix-unit ${unitCls}">
        <div class="matrix-unit-head">
          ${namePart}
          <button type="button" class="matrix-jds-btn" data-unit-id="${escapeHtml(unitId)}" aria-label="${escapeHtml(unit.unit_name)} 직무기술서" title="직무기술서">${MATRIX_PRINT_ICON}</button>
        </div>
        <span class="matrix-unit-code">${escapeHtml(unitId)}</span>
      </div>
    </div>
  `;
}

function buildMatrixGrid(data) {
  const byCell = new Map();
  (data.units || []).forEach((unit) => {
    const levelKey =
      unit.level_num != null && unit.level_num !== ""
        ? String(unit.level_num)
        : String(unit.level ?? "").replace(/\D/g, "") || String(unit.level ?? "");
    const key = `${unit.subcategory_code}::${levelKey}`;
    if (!byCell.has(key)) byCell.set(key, []);
    byCell.get(key).push(unit);
  });

  const subHeaders = (data.subcategories || [])
    .map(
      (sub) =>
        `<th class="matrix-subcategory-header clickable" data-sub-code="${escapeHtml(sub.subcategory_code)}" data-sub-name="${escapeHtml(sub.subcategory_name)}" title="분류로 찾기: ${escapeHtml(sub.subcategory_name)} (${escapeHtml(sub.subcategory_code)})">${escapeHtml(sub.subcategory_name)}<br><span class="matrix-unit-code">${escapeHtml(sub.subcategory_code)}</span></th>`
    )
    .join("");

  const levelRows = (data.levels || [])
    .map((level) => {
      const cells = (data.subcategories || [])
        .map((sub) => {
          const key = `${sub.subcategory_code}::${level}`;
          const items = byCell.get(key) || byCell.get(`${sub.subcategory_code}::${parseInt(level, 10)}`) || [];
          if (!items.length) {
            return '<td class="unit-matrix-cell"></td>';
          }
          const blocks = items
            .map((unit) => {
              const unitId = String(unit.unit_category_id || "");
              const selected = unit.selected || state.savedUnitIds.has(unitId);
              return buildMatrixUnitRow(unit, selected);
            })
            .join("");
          return `<td class="unit-matrix-cell">${blocks}</td>`;
        })
        .join("");
      return `<tr><th class="matrix-level-header">${escapeHtml(level)}</th>${cells}</tr>`;
    })
    .join("");

  return `
    <table class="unit-matrix-table">
      <thead>
        <tr>
          <th class="matrix-corner matrix-level-header">수준</th>
          ${subHeaders}
        </tr>
      </thead>
      <tbody>${levelRows}</tbody>
    </table>
  `;
}

async function renderUnitMatrix() {
  const container = document.getElementById("unitMatrixContainer");
  const scopeHint = document.getElementById("matrixScopeHint");
  if (!container) return;

  container.className = "unit-matrix-container detail-empty";
  container.textContent = "구조도를 불러오는 중입니다...";

  try {
    if (isLoggedIn()) await refreshSavedUnitIds();
    const data = await apiGet("/api/me/units/matrix");
    const subcategories = data.subcategories || [];
    if (!subcategories.length) {
      container.className = "unit-matrix-container detail-empty";
      container.textContent =
        "저장한 능력단위가 없습니다. 검색·분류 화면에서 능력단위를 저장한 뒤 새로고침하세요.";
      if (scopeHint) scopeHint.textContent = "표시할 세분류가 없습니다.";
      return;
    }

    const names = subcategories.map((s) => `${s.subcategory_name} (${s.subcategory_code})`).join(" · ");
    if (scopeHint) {
      scopeHint.textContent = `표시 세분류: ${names}`;
    }

    container.className = "unit-matrix-container";
    container.innerHTML = buildMatrixGrid(data);

    container.querySelectorAll(".matrix-subcategory-header.clickable").forEach((th) => {
      th.onclick = () => {
        const code = th.dataset.subCode;
        if (!code) return;
        jumpToCategory(code, { name: th.dataset.subName || "" });
      };
    });

    container.querySelectorAll(".matrix-unit-save.clickable").forEach((btn) => {
      btn.onclick = async () => {
        const payload = {
          unit_category_id: btn.dataset.unitId,
          unit_name: btn.dataset.unitName,
          subcategory_code: btn.dataset.subCode,
          subcategory_name: btn.dataset.subName,
        };
        try {
          btn.disabled = true;
          await apiPost("/api/me/units", payload);
          state.savedUnitIds.add(String(payload.unit_category_id));
          state.lastMatrixUnitId = String(payload.unit_category_id);
          await renderUnitMatrix();
        } catch (err) {
          alert(err.message);
          btn.disabled = false;
        }
      };
    });

    container.querySelectorAll(".matrix-unit-delete").forEach((btn) => {
      btn.onclick = async (event) => {
        event.stopPropagation();
        const id = btn.dataset.unitId;
        if (!id || !confirm("저장 목록에서 이 능력단위를 삭제할까요?")) return;
        try {
          btn.disabled = true;
          await removeUnitFromMyList(id);
          await renderUnitMatrix();
        } catch (err) {
          alert(err.message);
          btn.disabled = false;
        }
      };
    });

    container.querySelectorAll(".matrix-jds-btn").forEach((btn) => {
      btn.onclick = (event) => {
        event.stopPropagation();
        const unitId = btn.dataset.unitId;
        if (!unitId) return;
        state.lastMatrixUnitId = unitId;
        openJobDescriptionModal(unitId, { showPrintAll: true }).catch((err) => alert(err.message));
      };
    });
  } catch (err) {
    container.className = "unit-matrix-container detail-empty";
    const hint =
      /not found/i.test(err.message) || err.message.includes("404")
        ? " API 서버를 재시작하세요: python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
        : "";
    container.textContent = `구조도 로딩 실패: ${err.message}${hint}`;
  }
}

async function openUnitMatrixPage() {
  if (!isLoggedIn()) {
    openGuestFeatureModal("능력단위구조도는 로그인 후 이용할 수 있습니다.");
    return;
  }
  setActiveTab("matrix");
  await renderUnitMatrix();
}

function isSubcategoryLeaf(node) {
  return !node.children?.length && /^\d{8}$/.test(String(node.code || "").trim());
}

function getTreeLevelLabel(depth, node) {
  if (isSubcategoryLeaf(node)) return "세분류";
  if (depth === 0) return "대분류";
  if (depth === 1) return "중분류";
  return "소분류";
}

function ncsTreeSortKey(node) {
  const code = String(node.code || "").trim();
  if (/^\d+$/.test(code)) return code.padStart(8, "0");
  if (node.children?.length) return ncsTreeSortKey(node.children[0]);
  return code;
}

function sortNcsTree(nodes) {
  nodes.sort((a, b) => ncsTreeSortKey(a).localeCompare(ncsTreeSortKey(b), undefined, { numeric: true }));
  nodes.forEach((node) => {
    if (node.children?.length) sortNcsTree(node.children);
  });
}

function filterTree(nodes, keyword) {
  const out = [];
  nodes.forEach((node) => {
    const label = `${node.code || ""} ${node.name || ""}`.toLowerCase();
    const hit = label.includes(keyword);
    const children = node.children ? filterTree(node.children, keyword) : [];
    if (hit || children.length > 0) out.push({ ...node, children });
  });
  return out;
}

function createTreeNode(node, depth) {
  const wrap = document.createElement("div");
  wrap.className = "tree-item";
  const pad = `${8 + depth * 14}px`;

  if (isSubcategoryLeaf(node)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tree-node tree-node-selectable";
    if (state.selectedSubcategoryCode === node.code) btn.classList.add("selected");
    btn.style.paddingLeft = pad;
    btn.title = "세분류 선택 — 능력단위 목록이 표시됩니다";
    btn.innerHTML = `
      <span class="tree-badge tree-badge-sub">선택</span>
      <span class="tree-code">${node.code}</span>
      <span class="tree-name">${node.name || ""}</span>
    `;
    btn.onclick = () => onTreeSubcategoryClick(node);
    wrap.appendChild(btn);
    return wrap;
  }

  const label = document.createElement("div");
  label.className = `tree-node-label tree-level-${depth}`;
  label.style.paddingLeft = pad;
  const level = getTreeLevelLabel(depth, node);
  label.innerHTML = `
    <span class="tree-badge tree-badge-group">${level}</span>
    <span class="tree-name">${node.name || node.code || ""}</span>
  `;
  wrap.appendChild(label);

  if (node.children?.length) {
    const childWrap = document.createElement("div");
    childWrap.className = "tree-children";
    node.children.forEach((child) => childWrap.appendChild(createTreeNode(child, depth + 1)));
    wrap.appendChild(childWrap);
  }
  return wrap;
}

function renderTree() {
  const target = document.getElementById("categoryTree");
  target.innerHTML = "";
  const keyword = document.getElementById("treeFilterInput").value.trim().toLowerCase();
  const tree = keyword ? filterTree(state.ncsTree, keyword) : state.ncsTree;
  tree.forEach((major) => target.appendChild(createTreeNode(major, 0)));
}

function getWorkspacePanels() {
  if (state.activeTab === "category") {
    return {
      detailEl: document.getElementById("categoryUnitDetail"),
      structureEl: document.getElementById("categoryUnitStructure"),
      hierarchyId: "categoryDetailHierarchy",
    };
  }
  return {
    detailEl: document.getElementById("naturalUnitDetail"),
    structureEl: document.getElementById("naturalUnitStructure"),
    hierarchyId: "resultDetailHierarchy",
  };
}

function findSubcategoryNode(nodes, subcategoryCode) {
  for (const node of nodes || []) {
    if (isSubcategoryLeaf(node) && node.code === subcategoryCode) return node;
    const found = findSubcategoryNode(node.children, subcategoryCode);
    if (found) return found;
  }
  return null;
}

function findHierarchyInTree(nodes, subcategoryCode, ancestors = []) {
  for (const node of nodes || []) {
    const path = [...ancestors, node];
    const children = node.children || [];
    if (!children.length && node.code === subcategoryCode) {
      return {
        major_category_name: path[0]?.name || path[0]?.code || "",
        middle_category_name: path[1]?.name || path[1]?.code || "",
        minor_category_name: path[2]?.name || path[2]?.code || "",
        subcategory_name: node.name || "",
        subcategory_code: node.code || subcategoryCode,
      };
    }
    const found = findHierarchyInTree(children, subcategoryCode, path);
    if (found) return found;
  }
  return null;
}

function resolveNcsHierarchy(item) {
  if (!item) return null;
  const hasNames = item.major_category_name && item.middle_category_name && item.minor_category_name;
  if (hasNames && item.subcategory_code) return item;
  if (!item.subcategory_code) return item;
  const fromTree = findHierarchyInTree(state.ncsTree, item.subcategory_code);
  if (!fromTree) return item;
  return {
    ...item,
    major_category_name: item.major_category_name || fromTree.major_category_name,
    middle_category_name: item.middle_category_name || fromTree.middle_category_name,
    minor_category_name: item.minor_category_name || fromTree.minor_category_name,
    subcategory_name: item.subcategory_name || fromTree.subcategory_name,
  };
}

function formatNcsHierarchyInline(item) {
  const resolved = resolveNcsHierarchy(item);
  const code = resolved?.subcategory_code;
  if (!code) return "";
  const segments = [
    resolved.major_category_name,
    resolved.middle_category_name,
    resolved.minor_category_name,
    resolved.subcategory_name,
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  if (!segments.length) return String(code);
  return `${code}  ${segments.join("/")}`;
}

function setDetailHierarchy(item, hierarchyId) {
  const id = hierarchyId || getWorkspacePanels().hierarchyId;
  const el = document.getElementById(id);
  if (!el) return;
  const text = formatNcsHierarchyInline(item);
  if (!text) {
    el.textContent = "";
    el.classList.add("hidden");
    return;
  }
  el.textContent = text;
  el.classList.remove("hidden");
}

function clearDetailHierarchy(hierarchyId) {
  setDetailHierarchy(null, hierarchyId);
}

function clearStructurePanel(structureEl) {
  if (!structureEl) return;
  structureEl.className = "detail-body detail-empty";
  structureEl.textContent = "능력단위를 선택하면 구조가 표시됩니다.";
}

function formatNcsHierarchy(item) {
  const major = item.major_category_name || "-";
  const middle = item.middle_category_name || "-";
  const minor = item.minor_category_name || "-";
  const subName = item.subcategory_name || "-";
  const subCode = item.subcategory_code || "-";
  return `대: ${major} / 중: ${middle} / 소: ${minor} / 세: ${subName} (${subCode})`;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseDescriptionCodes(description) {
  const raw = String(description || "").trim();
  if (!raw) return null;
  const parts = [...new Set(raw.match(/\d{6,8}/g) || [])];
  return parts.length ? parts : null;
}

function setExampleBrowseHierarchy(bulkData) {
  const el = document.getElementById("resultDetailHierarchy");
  if (!el) return;
  const patterns = (bulkData.requested_patterns || []).join(", ");
  const resolved = bulkData.resolved_subcategory_codes || [];
  if (!patterns && !resolved.length) {
    el.classList.add("hidden");
    return;
  }
  const resolvedText = resolved.length ? resolved.join(" · ") : "-";
  el.textContent = `${patterns}  →  ${resolvedText}`;
  el.classList.remove("hidden");
}

function buildUnitListHtml(units, selectedUnitId) {
  return units
    .map((unit) => {
      const unitId = String(unit.unit_category_id || "");
      const isSelected = unitId && unitId === selectedUnitId;
      const unitDefinition = (unit.unit_definition || "").trim();
      const saved = state.savedUnitIds.has(unitId);
      let actionsHtml = "";
      if (isLoggedIn()) {
        if (saved) {
          actionsHtml = `<span class="unit-saved-label">저장됨</span><button type="button" class="small-btn danger-outline unit-remove-btn" data-unit-id="${escapeHtml(unitId)}">삭제</button>`;
        } else {
          actionsHtml = `<button type="button" class="small-btn unit-save-btn" data-unit-id="${escapeHtml(unitId)}">저장</button>`;
        }
      }
      return `
        <li class="unit-list-item ${isSelected ? "selected" : ""}" data-unit-id="${escapeHtml(unitId)}" role="button" tabindex="0">
          <div class="unit-list-item-head">
            <div class="unit-name ${isSelected ? "selected-name" : ""}"><b>${escapeHtml(unit.unit_name)}</b></div>
            ${actionsHtml}
          </div>
          <div class="meta">unit_category_id: ${escapeHtml(unitId)}</div>
          <div class="unit-definition-inline">
            ${escapeHtml(unitDefinition || "정의 정보가 등록되어 있지 않습니다.")}
          </div>
        </li>
      `;
    })
    .join("");
}

function attachUnitListHandlers(detailEl, units, hierarchyItem, structureEl, meta = {}) {
  const { refreshAfterListChange } = meta;
  detailEl.querySelectorAll(".unit-list-item").forEach((li) => {
    const activate = () => {
      const unitId = li.dataset.unitId;
      if (!unitId) return;
      state.selectedUnitCategoryId = unitId;
      detailEl.querySelectorAll(".unit-list-item").forEach((row) => row.classList.remove("selected"));
      detailEl.querySelectorAll(".unit-name").forEach((name) => name.classList.remove("selected-name"));
      li.classList.add("selected");
      li.querySelector(".unit-name")?.classList.add("selected-name");
      renderUnitStructure(unitId, hierarchyItem, structureEl);
    };
    li.onclick = (event) => {
      if (event.target.closest(".unit-save-btn")) return;
      if (event.target.closest(".unit-remove-btn")) return;
      activate();
    };
    li.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    };
  });

  detailEl.querySelectorAll(".unit-save-btn").forEach((btn) => {
    btn.onclick = async (event) => {
      event.stopPropagation();
      const unitId = btn.dataset.unitId;
      const unit = units.find((row) => String(row.unit_category_id) === unitId);
      if (!unit) return;
      try {
        btn.disabled = true;
        await saveUnitToMyList(unit, hierarchyItem);
        await refreshSavedUnitIds();
        if (typeof refreshAfterListChange === "function") {
          await refreshAfterListChange();
        }
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
      }
    };
  });

  detailEl.querySelectorAll(".unit-remove-btn").forEach((btn) => {
    btn.onclick = async (event) => {
      event.stopPropagation();
      const unitId = btn.dataset.unitId;
      if (!unitId || !confirm("저장 목록에서 이 능력단위를 삭제할까요?")) return;
      try {
        btn.disabled = true;
        await removeUnitFromMyList(unitId);
        await refreshSavedUnitIds();
        if (typeof refreshAfterListChange === "function") {
          await refreshAfterListChange();
        }
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    };
  });
}

async function renderUnitStructure(unitCategoryId, hierarchyContext, structureEl) {
  const panel = structureEl || getWorkspacePanels().structureEl;
  if (!panel) return;

  if (!isLoggedIn()) {
    panel.className = "detail-body detail-empty structure-guest";
    panel.innerHTML = `
      <p>능력단위 구조도는 <strong>로그인한 회원</strong>만 볼 수 있습니다.</p>
      <button type="button" class="small-btn" id="structureLoginBtn">로그인</button>
      <button type="button" class="small-btn" id="structureSignupBtn">회원가입</button>
    `;
    panel.querySelector("#structureLoginBtn")?.addEventListener("click", () => openAuthModal("login"));
    panel.querySelector("#structureSignupBtn")?.addEventListener("click", () => openAuthModal("signup"));
    return;
  }

  panel.className = "detail-body";
  panel.innerHTML = '<div class="detail-empty">구조를 불러오는 중입니다...</div>';

  try {
    const data = await apiGet(`/api/units/${encodeURIComponent(unitCategoryId)}/structure`);
    setDetailHierarchy(
      hierarchyContext || {
        subcategory_code: data.subcategory_code,
        subcategory_name: data.subcategory_name,
      },
      getWorkspacePanels().hierarchyId
    );

    const elementsHtml = (data.elements || [])
      .map((element) => {
        const criteria = (element.performance_criteria || [])
          .map((line) => `<li>${escapeHtml(line)}</li>`)
          .join("");
        return `
          <li class="structure-element">
            <div class="structure-element-title">
              <b>${escapeHtml(element.unit_element_name)}</b>
              <span class="meta">(${escapeHtml(element.unit_element_id)})</span>
            </div>
            ${criteria ? `<ul class="structure-criteria">${criteria}</ul>` : ""}
          </li>
        `;
      })
      .join("");

    panel.innerHTML = `
      <div class="structure-actions no-print">
        <button type="button" class="small-btn" id="structureJdsBtn">직무기술서</button>
        <button type="button" class="small-btn" id="structureMatrixBtn">능력단위구조도</button>
      </div>
      <h4 class="structure-unit-title">${escapeHtml(data.unit_name)}</h4>
      <ul class="structure-list">${elementsHtml || "<li>구조 정보가 없습니다.</li>"}</ul>
    `;
    panel.querySelector("#structureJdsBtn")?.addEventListener("click", () => {
      openJobDescriptionModal(unitCategoryId).catch((err) => alert(err.message));
    });
    panel.querySelector("#structureMatrixBtn")?.addEventListener("click", () => {
      state.lastMatrixUnitId = String(unitCategoryId);
      openUnitMatrixPage().catch((err) => alert(err.message));
    });
  } catch (err) {
    panel.className = "detail-body detail-empty";
    panel.textContent = `구조 로딩 실패: ${err.message}`;
  }
}

function buildGroupedUnitListHtml(subcategories, selectedUnitId) {
  return subcategories
    .map((group) => {
      const code = group.subcategory_code || "";
      const name = group.subcategory_name || "";
      const units = group.units || [];
      const items = buildUnitListHtml(units, selectedUnitId);
      return `
        <section class="subcategory-group" data-subcategory-code="${escapeHtml(code)}">
          <h6 class="subcategory-group-title">${escapeHtml(code)} ${escapeHtml(name)}</h6>
          <ul class="unit-list unit-list-clickable">${items}</ul>
        </section>
      `;
    })
    .join("");
}

async function renderMultiSubcategoryUnitsPanel(bulkData, panels, options = {}) {
  const { detailEl, structureEl, hierarchyId } = panels;
  const subcategories = bulkData.subcategories || [];
  const allUnits = bulkData.units || [];

  detailEl.className = "detail-body";
  clearStructurePanel(structureEl);

  if (!subcategories.length) {
    detailEl.className = "detail-body detail-empty";
    detailEl.textContent = "해당 분류 코드에 능력단위가 없습니다.";
    return;
  }

  const firstGroup = subcategories[0];
  const firstUnit = allUnits[0];
  const hierarchyItem = {
    subcategory_code: firstGroup.subcategory_code,
    subcategory_name: firstGroup.subcategory_name,
    major_category_name: firstGroup.major_category_name || firstUnit?.major_category_name,
    middle_category_name: firstGroup.middle_category_name || firstUnit?.middle_category_name,
    minor_category_name: firstGroup.minor_category_name || firstUnit?.minor_category_name,
  };

  const selectedUnitId = String(
    options.preferredUnitId || state.selectedUnitCategoryId || firstUnit?.unit_category_id || ""
  );

  detailEl.innerHTML = `
    <div class="example-browse-detail-banner">
      <strong>예시 분류 조회</strong>
      입력 코드: ${escapeHtml((bulkData.requested_patterns || []).join(", "))}
      · 세분류 ${subcategories.length}개 · 능력단위 ${allUnits.length}개
    </div>
    <p class="unit-list-guide">아래 목록은 선택한 분류의 <strong>전체 능력단위</strong>입니다. 항목을 클릭하면 오른쪽에 구조가 표시됩니다.</p>
    ${buildGroupedUnitListHtml(subcategories, selectedUnitId)}
  `;

  attachUnitListHandlers(detailEl, allUnits, hierarchyItem, structureEl, {
    async refreshAfterListChange() {
      await refreshSavedUnitIds();
      await renderMultiSubcategoryUnitsPanel(bulkData, panels, {
        ...options,
        preferredUnitId: state.selectedUnitCategoryId || options.preferredUnitId,
      });
    },
  });

  if (selectedUnitId) {
    state.selectedUnitCategoryId = selectedUnitId;
    await renderUnitStructure(selectedUnitId, hierarchyItem, structureEl);
  }
}

function renderExampleBrowseResults(bulkData, exampleText) {
  const target = document.getElementById("resultList");
  target.innerHTML = "";
  const subcategories = bulkData.subcategories || [];
  if (!subcategories.length) {
    target.innerHTML = '<div class="detail-empty">분류 코드에 해당하는 세분류가 없습니다.</div>';
    return;
  }

  const summary = document.createElement("div");
  summary.className = "card example-browse-summary";
  const resolvedCodes = bulkData.resolved_subcategory_codes || [];
  summary.innerHTML = `
    <h4>${escapeHtml(exampleText)}</h4>
    <div class="meta">예시 분류 조회 · 입력: ${escapeHtml((bulkData.requested_patterns || []).join(", "))}</div>
    <div class="meta">세분류 ${subcategories.length}개 · 능력단위 ${(bulkData.units || []).length}개</div>
    <div class="meta example-browse-resolved">포함 세분류: ${escapeHtml(resolvedCodes.join(", "))}</div>
  `;
  target.appendChild(summary);

  const detailEl = document.getElementById("naturalUnitDetail");

  subcategories.forEach((group) => {
    const card = document.createElement("div");
    card.className = "card example-browse-subcard";
    const unitCount = (group.units || []).length;
    card.innerHTML = `
      <h4>${escapeHtml(group.subcategory_name || group.subcategory_code)} (${escapeHtml(group.subcategory_code)})</h4>
      <div class="meta">${escapeHtml(formatNcsHierarchy(group))}</div>
      <div class="meta">능력단위 ${unitCount}개 · 클릭 시 가운데 목록으로 이동</div>
    `;
    card.onclick = () => {
      target.querySelectorAll(".card").forEach((el) => el.classList.remove("selected-result"));
      card.classList.add("selected-result");
      const code = String(group.subcategory_code || "");
      const section = detailEl?.querySelector(`.subcategory-group[data-subcategory-code="${code}"]`);
      if (section) {
        section.scrollIntoView({ behavior: "smooth", block: "start" });
        section.classList.add("subcategory-group-highlight");
        window.setTimeout(() => section.classList.remove("subcategory-group-highlight"), 1500);
      }
    };
    target.appendChild(card);
  });
}

async function runExampleCategoryBrowse(example) {
  const exampleText = String(example.example_text || "").trim();
  const codes = parseDescriptionCodes(example.description);
  if (!codes?.length) {
    document.getElementById("queryInput").value = exampleText;
    runNaturalSearch().catch((err) => alert(err.message));
    return;
  }

  if (state.isSearching) return;
  state.isSearching = true;
  state.selectedResultKey = "";
  state.selectedUnitCategoryId = "";
  document.getElementById("queryInput").value = exampleText;

  const searchBtn = document.getElementById("searchBtn");
  const resultList = document.getElementById("resultList");
  const naturalDetail = document.getElementById("naturalUnitDetail");
  const naturalStructure = document.getElementById("naturalUnitStructure");
  const panels = getWorkspacePanels();

  searchBtn.disabled = true;
  searchBtn.textContent = "불러오는 중...";
  resultList.innerHTML = '<div class="detail-empty">분류 코드로 능력단위를 불러오는 중입니다...</div>';
  naturalDetail.className = "detail-body detail-empty";
  naturalDetail.textContent = "불러오는 중...";
  clearStructurePanel(naturalStructure);
  clearDetailHierarchy("resultDetailHierarchy");

  try {
    const bulkData = await apiGet(
      `/api/subcategories/units-by-patterns?codes=${encodeURIComponent(codes.join(","))}`
    );
    state.lastSearchResult = { exampleBrowse: true, bulkData, exampleText };
    setExampleBrowseHierarchy(bulkData);
    renderExampleBrowseResults(bulkData, exampleText);
    await renderMultiSubcategoryUnitsPanel(bulkData, panels, { highlightSelected: true });
  } catch (err) {
    resultList.innerHTML = `<div class="detail-empty">예시 분류 조회 실패: ${escapeHtml(err.message)}</div>`;
    naturalDetail.className = "detail-body detail-empty";
    naturalDetail.textContent = `조회 실패: ${err.message}`;
  } finally {
    state.isSearching = false;
    searchBtn.disabled = false;
    searchBtn.textContent = "검색";
  }
}

async function renderSubcategoryUnitsPanel(item, panels, options = {}) {
  const { detailEl, structureEl, hierarchyId } = panels;
  const highlightSelected = options.highlightSelected ?? true;

  detailEl.className = "detail-body";
  detailEl.innerHTML = '<div class="detail-empty">세분류 능력단위 목록을 불러오는 중입니다...</div>';
  clearStructurePanel(structureEl);

  let context = { ...item };
  if (context.unit_category_id) {
    try {
      const meta = await resolveUnitNcsMeta(context.unit_category_id);
      context = { ...context, ...meta };
    } catch {
      /* 메타 조회 실패 시 기존 item 값 사용 */
    }
  }
  if (!context.subcategory_code) {
    detailEl.className = "detail-body detail-empty";
    detailEl.textContent = "세분류 코드를 확인할 수 없습니다.";
    return;
  }

  const data = await apiGet(`/api/subcategories/${encodeURIComponent(context.subcategory_code)}/units`);
  const units = [];
  const seenUnitIds = new Set();
  (data.units || []).forEach((unit) => {
    const unitId = String(unit.unit_category_id || "");
    if (!unitId || seenUnitIds.has(unitId)) return;
    seenUnitIds.add(unitId);
    units.push(unit);
  });

  if (!units.length) {
    detailEl.className = "detail-body detail-empty";
    detailEl.textContent = "능력단위가 없습니다.";
    return;
  }

  const preferredId = String(
    options.preferredUnitId ?? context.unit_category_id ?? state.selectedUnitCategoryId ?? ""
  );
  const selectedUnitById = units.find((unit) => String(unit.unit_category_id) === preferredId);
  const selectedUnitByName = units.find(
    (unit) => String(unit.unit_name || "") === String(context.job_name || context.unit_name || "")
  );
  const selectedUnit = selectedUnitById || selectedUnitByName || units[0];
  const selectedUnitId = String(selectedUnit?.unit_category_id || "");

  const hierarchySource = selectedUnit || units[0] || context;
  const hierarchyItem = {
    ...context,
    subcategory_code: context.subcategory_code || data.subcategory_code,
    subcategory_name: context.subcategory_name || data.subcategory_name,
    major_category_name: context.major_category_name || hierarchySource?.major_category_name,
    middle_category_name: context.middle_category_name || hierarchySource?.middle_category_name,
    minor_category_name: context.minor_category_name || hierarchySource?.minor_category_name,
  };
  setDetailHierarchy(hierarchyItem, hierarchyId);

  detailEl.className = "detail-body";
  const saveGuide = isLoggedIn()
    ? " <strong>저장</strong> 버튼으로 내 능력단위 목록에 추가할 수 있습니다."
    : "";
  detailEl.innerHTML = `
    <p class="unit-list-guide">아래 능력단위를 클릭하면 오른쪽에 <strong>능력단위구조</strong>가 표시됩니다.${saveGuide}</p>
    <ul class="unit-list unit-list-clickable">${buildUnitListHtml(units, highlightSelected ? selectedUnitId : "")}</ul>
  `;

  attachUnitListHandlers(detailEl, units, hierarchyItem, structureEl, {
    async refreshAfterListChange() {
      await refreshSavedUnitIds();
      await renderSubcategoryUnitsPanel(hierarchyItem, getWorkspacePanels(), {
        highlightSelected,
        preferredUnitId: state.selectedUnitCategoryId,
      });
    },
  });

  if (selectedUnitId) {
    state.selectedUnitCategoryId = selectedUnitId;
    await renderUnitStructure(selectedUnitId, hierarchyItem, structureEl);
  }
}

async function onTreeSubcategoryClick(node) {
  state.selectedSubcategoryCode = node.code;
  state.selectedSubcategoryName = node.name;
  state.selectedUnitCategoryId = "";
  renderTree();

  const hierarchyItem = findHierarchyInTree(state.ncsTree, node.code) || {
    subcategory_code: node.code,
    subcategory_name: node.name,
  };

  const panels = getWorkspacePanels();
  await renderSubcategoryUnitsPanel(hierarchyItem, panels, { highlightSelected: true });
}

async function runNaturalSearch() {
  if (state.isSearching) return;
  const query = document.getElementById("queryInput").value.trim();
  if (!query) return alert("검색어를 입력하세요.");

  state.isSearching = true;
  state.selectedResultKey = "";
  state.selectedUnitCategoryId = "";
  clearDetailHierarchy("resultDetailHierarchy");
  clearStructurePanel(document.getElementById("naturalUnitStructure"));

  const searchBtn = document.getElementById("searchBtn");
  const resultList = document.getElementById("resultList");
  const naturalDetail = document.getElementById("naturalUnitDetail");
  searchBtn.disabled = true;
  searchBtn.textContent = "검색 중...";
  resultList.innerHTML = '<div class="detail-empty">검색 중입니다...</div>';
  naturalDetail.className = "detail-body detail-empty";
  naturalDetail.textContent = "검색 결과에서 항목을 선택하세요.";

  try {
    const full = await apiPost("/api/search/full", { query, top_k: 10 });
    state.lastSearchResult = {
      full,
      jobs: full.recommended_jobs || [],
      units: full.recommended_units || [],
      subcategories: full.recommended_subcategories || [],
    };
    renderResults();
  } finally {
    state.isSearching = false;
    searchBtn.disabled = false;
    searchBtn.textContent = "검색";
  }
}

function jumpToCategory(code, options = {}) {
  const subCode = String(code || "").trim();
  if (!subCode) return;

  setActiveTab("category");
  const filterInput = document.getElementById("treeFilterInput");
  if (filterInput) {
    const label = String(options.name || "").trim();
    filterInput.value = label;
    renderTree();
  }

  const node =
    findSubcategoryNode(state.ncsTree, subCode) || {
      code: subCode,
      name: String(options.name || "").trim(),
      children: [],
    };
  onTreeSubcategoryClick(node).catch((err) => alert(err.message));
}

function getResultKey(item) {
  if (item.unit_category_id) return `unit:${item.unit_category_id}`;
  if (item.job_name) return `job:${item.job_name}`;
  if (item.subcategory_code) return `sub:${item.subcategory_code}`;
  return `raw:${JSON.stringify(item)}`;
}

function renderCard(item) {
  const card = document.createElement("div");
  card.className = "card";
  const resultKey = getResultKey(item);
  if (state.selectedResultKey === resultKey) card.classList.add("selected-result");

  const title = item.job_name || item.unit_name || item.subcategory_name || "결과";
  const subCode = item.subcategory_code ? ` (${item.subcategory_code})` : "";
  card.innerHTML = `
    <h4>${escapeHtml(title)}${escapeHtml(subCode)}</h4>
    <div class="meta">${escapeHtml(formatNcsHierarchy(item))}</div>
    <div class="meta">점수: ${Number(item.final_score || 0).toFixed(4)}</div>
    <div class="meta">${escapeHtml(item.reason || "")}</div>
  `;

  card.onclick = async () => {
    state.selectedResultKey = resultKey;
    state.selectedUnitCategoryId = String(item.unit_category_id || "");
    renderResults();

    const panels = getWorkspacePanels();
    setDetailHierarchy(item, panels.hierarchyId);

    if (item.subcategory_code) {
      try {
        await renderSubcategoryUnitsPanel(item, panels, {
          highlightSelected: state.resultTab !== "subcategories",
        });
      } catch (err) {
        panels.detailEl.className = "detail-body detail-empty";
        panels.detailEl.textContent = `상세 로딩 실패: ${err.message}`;
      }
      return;
    }

    panels.detailEl.className = "detail-body detail-empty";
    panels.detailEl.innerHTML = `<h4>${escapeHtml(title)}</h4><p class="meta">세분류 코드가 없어 목록을 표시할 수 없습니다.</p>`;
    clearStructurePanel(panels.structureEl);
  };
  return card;
}

function renderResults() {
  const target = document.getElementById("resultList");
  target.innerHTML = "";
  if (!state.lastSearchResult) {
    target.innerHTML = '<div class="detail-empty">검색 결과가 없습니다.</div>';
    return;
  }
  if (state.lastSearchResult.exampleBrowse && state.lastSearchResult.bulkData) {
    renderExampleBrowseResults(state.lastSearchResult.bulkData, state.lastSearchResult.exampleText || "");
    return;
  }
  let items = [];
  if (state.resultTab === "full") items = state.lastSearchResult.jobs || [];
  else items = state.lastSearchResult[state.resultTab] || [];
  if (!items.length) {
    target.innerHTML = '<div class="detail-empty">결과가 없습니다.</div>';
    return;
  }
  items.forEach((item) => target.appendChild(renderCard(item)));
}

async function loadTree() {
  state.ncsTree = await apiGet("/api/ncs/tree");
  sortNcsTree(state.ncsTree);
  renderTree();
}

function renderExampleChips(examples) {
  const container = document.getElementById("exampleChips");
  if (!container) return;
  container.innerHTML = "";
  if (!examples?.length) {
    container.innerHTML = '<span class="chips-empty">등록된 예시 질문이 없습니다.</span>';
    return;
  }
  examples.forEach((item) => {
    const text = String(item.example_text || "").trim();
    if (!text) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.textContent = text;
    const codes = parseDescriptionCodes(item.description);
    if (codes) {
      btn.title = `분류 코드: ${codes.join(", ")}`;
      btn.classList.add("chip-coded");
    } else if (item.description) {
      btn.title = String(item.description);
    }
    btn.onclick = () => {
      runExampleCategoryBrowse(item).catch((err) => alert(err.message));
    };
    container.appendChild(btn);
  });
}

async function loadExampleQueries() {
  const container = document.getElementById("exampleChips");
  if (!container) return;
  container.innerHTML = '<span class="chips-loading">예시 질문 불러오는 중...</span>';
  const ts = Date.now();
  const urls = [
    `/api/search/examples?limit=12&_=${ts}`,
    `/api/example-queries?limit=12&_=${ts}`,
  ];
  let lastError = null;
  for (const url of urls) {
    try {
      const examples = await apiGet(url);
      renderExampleChips(examples);
      return;
    } catch (err) {
      lastError = err;
    }
  }
  const hint =
    lastError?.message === "Not Found" || String(lastError?.message || "").includes("404")
      ? " API 서버를 재시작하세요: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
      : "";
  container.innerHTML = `<span class="chips-empty">예시 질문 로딩 실패: ${escapeHtml(
    lastError?.message || "unknown"
  )}.${escapeHtml(hint)}</span>`;
}

function bindEvents() {
  document.getElementById("tabCategoryBtn").onclick = () => setActiveTab("category");
  document.getElementById("tabNaturalBtn").onclick = () => {
    setActiveTab("natural");
    loadExampleQueries().catch((err) => console.error(err));
  };
  document.getElementById("loginBtn").onclick = () => openAuthModal("login");
  document.getElementById("logoutBtn").onclick = () => {
    logout();
    alert("로그아웃되었습니다.");
  };
  document.getElementById("myUnitsBtn").onclick = () => openMyUnitsModal().catch((err) => alert(err.message));
  document.getElementById("unitMatrixBtn").onclick = () => openUnitMatrixPage().catch((err) => alert(err.message));
  document.getElementById("matrixRefreshBtn").onclick = () => renderUnitMatrix().catch((err) => alert(err.message));
  document.getElementById("matrixExportBtn").onclick = () =>
    downloadMyUnitsExcel().catch((err) => alert(err.message));
  document.getElementById("myUnitsExportBtn").onclick = () => {
    downloadMyUnitsExcel().catch((err) => alert(err.message));
  };
  document.getElementById("loginSubmitBtn").onclick = () => submitLogin();
  document.getElementById("signupSubmitBtn").onclick = () => submitSignup();
  document.getElementById("goSignupBtn").onclick = () => openAuthModal("signup", document.getElementById("loginEmail")?.value.trim());
  document.getElementById("goLoginBtn").onclick = () => openAuthModal("login", document.getElementById("signupEmail")?.value.trim());
  document.getElementById("authCloseBtn").onclick = closeAuthModal;
  document.getElementById("signupCloseBtn").onclick = closeAuthModal;
  document.getElementById("guestFeatureLoginBtn").onclick = () => {
    closeGuestFeatureModal();
    openAuthModal("login");
  };
  document.getElementById("guestFeatureSignupBtn").onclick = () => {
    closeGuestFeatureModal();
    openAuthModal("signup");
  };
  document.getElementById("guestFeatureCloseBtn").onclick = closeGuestFeatureModal;
  document.getElementById("myUnitsCloseBtn").onclick = closeMyUnitsModal;
  document.getElementById("myUnitsPrintAllJdsBtn").onclick = () => {
    closeMyUnitsModal();
    printAllJobDescriptions().catch((err) => alert(err.message));
  };
  document.getElementById("jdsCloseBtn").onclick = closeJobDescriptionModal;
  document.getElementById("jdsPrintBtn").onclick = printJobDescriptionModal;
  document.getElementById("jdsPrintAllBtn").onclick = () => printAllJobDescriptions().catch((err) => alert(err.message));
  document.getElementById("jdsMatrixBtn").onclick = () => {
    closeJobDescriptionModal();
    openUnitMatrixPage().catch((err) => alert(err.message));
  };
  document.getElementById("loginPassword").onkeydown = (e) => {
    if (e.key === "Enter") submitLogin();
  };
  document.getElementById("loginEmail")?.addEventListener("blur", async () => {
    const email = document.getElementById("loginEmail")?.value.trim().toLowerCase();
    if (!email || !email.includes("@")) return;
    try {
      const data = await apiGet(`/api/auth/email-exists?email=${encodeURIComponent(email)}`);
      if (!data.exists) {
        showAuthError(document.getElementById("loginError"), "가입 이력이 없습니다. 아래 회원가입 버튼을 눌러 주세요.");
      }
    } catch {
      /* ignore */
    }
  });
  document.getElementById("treeFilterInput").oninput = renderTree;
  document.getElementById("searchBtn").onclick = () => runNaturalSearch().catch((err) => alert(err.message));
  document.getElementById("queryInput").onkeydown = (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      runNaturalSearch().catch((err) => alert(err.message));
    }
  };
  document.getElementById("downloadBtn").onclick = () => window.open("/api/download/basic-ncs", "_blank");
  document.querySelectorAll(".result-tab").forEach((btn) => {
    btn.onclick = () => {
      state.resultTab = btn.dataset.resultTab;
      document.querySelectorAll(".result-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderResults();
    };
  });
}

async function bootstrap() {
  const legacy = localStorage.getItem("authToken");
  if (legacy && !sessionStorage.getItem("authToken")) {
    sessionStorage.setItem("authToken", legacy);
    localStorage.removeItem("authToken");
    state.authToken = legacy;
  }
  localStorage.removeItem("userMode");
  updateAuthUi();
  bindEvents();
  if (state.authToken) {
    try {
      await loadCurrentUser();
    } catch {
      logout();
    }
  }
  await Promise.all([loadTree(), loadExampleQueries()]);
}

bootstrap().catch((err) => {
  alert(`초기 로딩 실패: ${err.message}`);
});
