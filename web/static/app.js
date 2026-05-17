const state = {
  userMode: localStorage.getItem("userMode") || "guest",
  activeTab: "category",
  ncsTree: [],
  selectedSubcategoryCode: "",
  selectedSubcategoryName: "",
  selectedSubcategoryUnits: [],
  resultTab: "full",
  lastSearchResult: null,
};

function apiHeaders() {
  return { "Content-Type": "application/json", "X-User-Mode": state.userMode };
}

async function safeJson(res) {
  try {
    return await res.json();
  } catch {
    return {};
  }
}

async function apiGet(url) {
  const res = await fetch(url, { headers: { "X-User-Mode": state.userMode } });
  if (!res.ok) throw new Error((await safeJson(res)).detail || `GET failed: ${res.status}`);
  return res.json();
}

async function apiPost(url, payload) {
  const res = await fetch(url, { method: "POST", headers: apiHeaders(), body: JSON.stringify(payload) });
  if (!res.ok) throw new Error((await safeJson(res)).detail || `POST failed: ${res.status}`);
  return res.json();
}

function setMode(mode) {
  state.userMode = mode;
  localStorage.setItem("userMode", mode);
  document.getElementById("modeBadge").textContent = mode === "member" ? "회원 모드" : "게스트 모드";
  document.getElementById("modeToggleBtn").textContent = mode === "member" ? "게스트 모드 전환" : "회원 모드 전환";
}

function setActiveTab(tab) {
  state.activeTab = tab;
  document.getElementById("categoryTab").classList.toggle("active", tab === "category");
  document.getElementById("naturalTab").classList.toggle("active", tab === "natural");
  document.getElementById("tabCategoryBtn").classList.toggle("active", tab === "category");
  document.getElementById("tabNaturalBtn").classList.toggle("active", tab === "natural");
}

function filterTree(nodes, keyword) {
  const out = [];
  nodes.forEach((node) => {
    const hit = (node.name || "").toLowerCase().includes(keyword);
    const children = node.children ? filterTree(node.children, keyword) : [];
    if (hit || children.length > 0) out.push({ ...node, children });
  });
  return out;
}

function createTreeNode(node, depth) {
  const wrap = document.createElement("div");
  wrap.className = "tree-item";
  const btn = document.createElement("button");
  btn.className = "tree-node";
  if (state.selectedSubcategoryCode && node.code === state.selectedSubcategoryCode) btn.classList.add("selected");
  btn.style.paddingLeft = `${8 + depth * 12}px`;
  btn.textContent = `${node.code || ""} ${node.name || ""}`.trim();
  btn.onclick = () => onTreeNodeClick(node);
  wrap.appendChild(btn);
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

async function onTreeNodeClick(node) {
  if (node.children?.length) return;
  state.selectedSubcategoryCode = node.code;
  state.selectedSubcategoryName = node.name;
  document.getElementById("categoryDetail").innerHTML = `<h4>${node.name}</h4><div class="meta">세분류 코드: ${node.code}</div>`;
  document.getElementById("jumpToNaturalBtn").disabled = false;
  renderTree();
  await loadSubcategoryUnits(node.code);
}

async function loadSubcategoryUnits(code) {
  const data = await apiGet(`/api/subcategories/${encodeURIComponent(code)}/units`);
  state.selectedSubcategoryUnits = data.units || [];
  const target = document.getElementById("subcategoryUnits");
  target.innerHTML = "";
  if (!state.selectedSubcategoryUnits.length) {
    target.innerHTML = '<div class="detail-empty">능력단위가 없습니다.</div>';
    return;
  }
  state.selectedSubcategoryUnits.forEach((unit) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h4>${unit.unit_name}</h4><div class="meta">${unit.unit_element_name}</div><div class="meta">unit_category_id: ${unit.unit_category_id}</div>`;
    const btn = document.createElement("button");
    btn.className = "small-btn";
    btn.textContent = "구조도 보기";
    btn.onclick = () => showUnitStructure(unit.unit_category_id);
    card.appendChild(btn);
    target.appendChild(card);
  });
}

function openMemberModal() {
  document.getElementById("memberModal").classList.remove("hidden");
}

function closeMemberModal() {
  document.getElementById("memberModal").classList.add("hidden");
}

async function showUnitStructure(unitCategoryId) {
  if (state.userMode !== "member") return openMemberModal();
  try {
    const data = await apiGet(`/api/units/${encodeURIComponent(unitCategoryId)}/structure`);
    const items = (data.elements || [])
      .map((e) => `<li><b>${e.unit_element_name}</b> (${e.unit_element_id})<br/>${(e.performance_criteria || []).join("<br/>")}</li>`)
      .join("");
    document.getElementById("resultDetail").innerHTML = `<h4>${data.unit_name}</h4><div class="meta">세분류: ${data.subcategory_name} (${data.subcategory_code})</div><ul>${items}</ul>`;
  } catch (err) {
    alert(err.message);
  }
}

async function runNaturalSearch() {
  const query = document.getElementById("queryInput").value.trim();
  if (!query) return alert("검색어를 입력하세요.");
  const full = await apiPost("/api/search/full", { query, top_k: 5 });
  const jobs = await apiPost("/api/search/jobs", { query, top_k: 5 });
  const units = await apiPost("/api/search/units", { query, top_k: 5 });
  const subcategories = await apiPost("/api/search/subcategories", { query, top_k: 5 });
  state.lastSearchResult = { full, jobs, units, subcategories };
  renderResults();
}

function jumpToCategory(code) {
  state.selectedSubcategoryCode = code;
  setActiveTab("category");
  renderTree();
  loadSubcategoryUnits(code).catch((err) => alert(err.message));
}

function renderCard(item) {
  const card = document.createElement("div");
  card.className = "card";
  const title = item.job_name || item.unit_name || item.subcategory_name || "결과";
  const subCode = item.subcategory_code ? ` (${item.subcategory_code})` : "";
  card.innerHTML = `<h4>${title}${subCode}</h4><div class="meta">점수: ${Number(item.final_score || 0).toFixed(4)}</div><div class="meta">${item.reason || ""}</div>`;
  card.onclick = () => {
    const detail = document.getElementById("resultDetail");
    detail.innerHTML = `<h4>${title}</h4><pre>${JSON.stringify(item, null, 2)}</pre>`;
    if (item.subcategory_code) {
      const link = document.createElement("div");
      link.className = "code-link";
      link.textContent = "분류 탭으로 이동";
      link.onclick = () => jumpToCategory(item.subcategory_code);
      detail.appendChild(link);
    }
    if (item.unit_category_id) {
      const btn = document.createElement("button");
      btn.className = "small-btn";
      btn.textContent = "구조도 보기";
      btn.onclick = () => showUnitStructure(item.unit_category_id);
      detail.appendChild(btn);
    }
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
  let items = [];
  if (state.resultTab === "full") items = state.lastSearchResult.full.recommended_jobs || [];
  else items = state.lastSearchResult[state.resultTab] || [];
  if (!items.length) {
    target.innerHTML = '<div class="detail-empty">결과가 없습니다.</div>';
    return;
  }
  items.forEach((item) => target.appendChild(renderCard(item)));
}

async function loadTree() {
  state.ncsTree = await apiGet("/api/ncs/tree");
  renderTree();
}

function bindEvents() {
  document.getElementById("tabCategoryBtn").onclick = () => setActiveTab("category");
  document.getElementById("tabNaturalBtn").onclick = () => setActiveTab("natural");
  document.getElementById("modeToggleBtn").onclick = () => setMode(state.userMode === "member" ? "guest" : "member");
  document.getElementById("treeFilterInput").oninput = renderTree;
  document.getElementById("searchBtn").onclick = () => runNaturalSearch().catch((err) => alert(err.message));
  document.getElementById("downloadBtn").onclick = () => window.open("/api/download/basic-ncs", "_blank");
  document.getElementById("jumpToNaturalBtn").onclick = () => {
    const query = `${state.selectedSubcategoryName} 관련 직무`;
    document.getElementById("queryInput").value = query;
    setActiveTab("natural");
    runNaturalSearch().catch((err) => alert(err.message));
  };
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.onclick = () => {
      document.getElementById("queryInput").value = chip.textContent;
      runNaturalSearch().catch((err) => alert(err.message));
    };
  });
  document.querySelectorAll(".result-tab").forEach((btn) => {
    btn.onclick = () => {
      state.resultTab = btn.dataset.resultTab;
      document.querySelectorAll(".result-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderResults();
    };
  });
  document.getElementById("memberSwitchBtn").onclick = () => {
    setMode("member");
    closeMemberModal();
  };
  document.getElementById("memberCloseBtn").onclick = closeMemberModal;
}

async function bootstrap() {
  setMode(state.userMode);
  bindEvents();
  await loadTree();
}

bootstrap().catch((err) => {
  alert(`초기 로딩 실패: ${err.message}`);
});
