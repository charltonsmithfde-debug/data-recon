/**
 * app.js
 * Sanlam Online Analytics Portal Frontend Application
 * Scoped exclusively to the two flagship Power BI replicas:
 *  1. Member Analysis Summary (PBI Replica)
 *  2. Fund Analytics - Investment Analysis (PBI Replica)
 */

let currentDashboard = "member_analysis";
let currentRole = "ROLE_FINANCE_MEMBER";
let isPiiMasked = true;
let currentPbiTab = "overview";
let currentInvTab = "overview";
let currentAnnuityTab = "acceptances_over_time";
const pbiChartInstances = {};

// ── Dashboard Loading State & Telemetry ────────────────────────────────────
function setDashboardLoading(viewId, isLoading) {
  const container = document.getElementById(viewId);
  if (!container) return;
  const overlayMap = {
    memberAnalysisView: "memberAnalysisLoadingOverlay",
    investmentAnalysisView: "investmentAnalysisLoadingOverlay",
    annuityReportingView: "annuityLoadingOverlay"
  };
  const overlay = document.getElementById(overlayMap[viewId]);
  if (isLoading) {
    container.classList.add("dashboard-loading");
    if (overlay) overlay.style.display = "flex";
  } else {
    container.classList.remove("dashboard-loading");
    if (overlay) overlay.style.display = "none";
  }
}

function updateFetchTelemetry(durationMs) {
  const timeEl = document.getElementById("telemetryLastFetchTime");
  const durEl = document.getElementById("telemetryDuration");
  if (timeEl) {
    const now = new Date();
    timeEl.textContent = now.toLocaleTimeString();
  }
  if (durEl && durationMs !== undefined && durationMs !== null) {
    durEl.textContent = `${durationMs} ms`;
  }
}

function debounce(fn, delay = 250) {
  let timer = null;
  return function (...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

document.addEventListener("DOMContentLoaded", () => {
  initDashboardSwitcher();
  initIdentity();
  initDrawer();
  initMemberAnalysis();
  initInvestmentAnalysis();
  initAnnuityReporting();
  initSysAdminCockpit();
  fetchLakehouseStatus();
  
  // Activate initial view (Member Analysis Summary)
  switchDashboard("member_analysis");
});

function initDashboardSwitcher() {
  const tabMember = document.getElementById("tabNavMemberAnalysis");
  const tabInv = document.getElementById("tabNavInvestmentAnalysis");
  const tabAnnuity = document.getElementById("tabNavAnnuityReporting");
  const tabSysAdmin = document.getElementById("tabNavSysAdmin");

  if (tabMember) {
    tabMember.addEventListener("click", () => switchDashboard("member_analysis"));
  }
  if (tabInv) {
    tabInv.addEventListener("click", () => switchDashboard("investment_analysis"));
  }
  if (tabAnnuity) {
    tabAnnuity.addEventListener("click", () => switchDashboard("annuity_reporting"));
  }
  if (tabSysAdmin) {
    tabSysAdmin.addEventListener("click", () => switchDashboard("sysadmin_cockpit"));
  }
}

function syncFiltersCrossDashboard(sourceDashboard) {
  let dateVal = "", fundVal = "", buVal = "", clientVal = "", empVal = "", brokVal = "", assocVal = "";

  if (sourceDashboard === "member_analysis") {
    dateVal = document.getElementById("pbiSlicerDate")?.value || "";
    fundVal = document.getElementById("pbiSlicerFund")?.value || "";
    buVal = document.getElementById("pbiSlicerBU")?.value || "";
    clientVal = document.getElementById("pbiSlicerClient")?.value || "";
    empVal = document.getElementById("pbiSlicerEmployer")?.value || "";
    brokVal = document.getElementById("pbiSlicerBrokerage")?.value || "";
    assocVal = document.getElementById("pbiSlicerAssociation")?.value || "";
  } else if (sourceDashboard === "investment_analysis") {
    dateVal = document.getElementById("pbiInvSlicerDate")?.value || "";
    fundVal = document.getElementById("pbiInvSlicerFund")?.value || "";
    buVal = document.getElementById("pbiInvSlicerBU")?.value || "";
    clientVal = document.getElementById("pbiInvSlicerClient")?.value || "";
    empVal = document.getElementById("pbiInvSlicerEmployer")?.value || "";
    brokVal = document.getElementById("pbiInvSlicerBrokerage")?.value || "";
    assocVal = document.getElementById("pbiInvSlicerAssociation")?.value || "";
  } else if (sourceDashboard === "annuity_reporting") {
    dateVal = document.getElementById("annuitySlicerDate")?.value || "";
    fundVal = document.getElementById("annuitySlicerFund")?.value || "";
    buVal = document.getElementById("annuitySlicerBusiness")?.value || "";
  }

  const applyVal = (selId, val) => {
    if (!val || val === "All" || val === "All Dates" || val === "All Funds" || val === "All Funds (SUS)" || val === "All Businesses") return;
    const sel = document.getElementById(selId);
    if (!sel) return;
    let found = false;
    for (let i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === val) {
        sel.selectedIndex = i;
        found = true;
        break;
      }
    }
    if (!found && val) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = val;
      sel.appendChild(opt);
      sel.value = val;
    }
  };

  if (sourceDashboard !== "member_analysis") {
    if (dateVal) applyVal("pbiSlicerDate", dateVal);
    if (fundVal) applyVal("pbiSlicerFund", fundVal);
    if (buVal) applyVal("pbiSlicerBU", buVal);
    if (clientVal) applyVal("pbiSlicerClient", clientVal);
    if (empVal) applyVal("pbiSlicerEmployer", empVal);
    if (brokVal) applyVal("pbiSlicerBrokerage", brokVal);
    if (assocVal) applyVal("pbiSlicerAssociation", assocVal);
  }

  if (sourceDashboard !== "investment_analysis") {
    if (dateVal) applyVal("pbiInvSlicerDate", dateVal);
    if (fundVal) applyVal("pbiInvSlicerFund", fundVal);
    if (buVal) applyVal("pbiInvSlicerBU", buVal);
    if (clientVal) applyVal("pbiInvSlicerClient", clientVal);
    if (empVal) applyVal("pbiInvSlicerEmployer", empVal);
    if (brokVal) applyVal("pbiInvSlicerBrokerage", brokVal);
    if (assocVal) applyVal("pbiInvSlicerAssociation", assocVal);
  }

  if (sourceDashboard !== "annuity_reporting") {
    if (dateVal) applyVal("annuitySlicerDate", dateVal);
    if (fundVal) applyVal("annuitySlicerFund", fundVal);
    if (buVal) applyVal("annuitySlicerBusiness", buVal);
  }
}

function switchDashboard(slug) {
  const previousDashboard = currentDashboard;
  currentDashboard = slug;
  syncFiltersCrossDashboard(previousDashboard);

  const tabMember = document.getElementById("tabNavMemberAnalysis");
  const tabInv = document.getElementById("tabNavInvestmentAnalysis");
  const tabAnnuity = document.getElementById("tabNavAnnuityReporting");
  const tabSysAdmin = document.getElementById("tabNavSysAdmin");
  const memberAnalysisView = document.getElementById("memberAnalysisView");
  const investmentAnalysisView = document.getElementById("investmentAnalysisView");
  const annuityReportingView = document.getElementById("annuityReportingView");
  const sysadminCockpitView = document.getElementById("sysadminCockpitView");

  if (slug === "member_analysis") {
    if (tabMember) tabMember.classList.add("active");
    if (tabInv) tabInv.classList.remove("active");
    if (tabAnnuity) tabAnnuity.classList.remove("active");
    if (tabSysAdmin) tabSysAdmin.classList.remove("active");
    if (investmentAnalysisView) investmentAnalysisView.style.display = "none";
    if (annuityReportingView) annuityReportingView.style.display = "none";
    if (sysadminCockpitView) sysadminCockpitView.style.display = "none";
    if (memberAnalysisView) memberAnalysisView.style.display = "block";
    stopSysAdminPolling();
    updateDrawerSchema("member_analysis");
    refreshMemberSlicersCascading(false);
    fetchMemberAnalysisData(currentPbiTab);
  } else if (slug === "investment_analysis") {
    if (tabMember) tabMember.classList.remove("active");
    if (tabInv) tabInv.classList.add("active");
    if (tabAnnuity) tabAnnuity.classList.remove("active");
    if (tabSysAdmin) tabSysAdmin.classList.remove("active");
    if (memberAnalysisView) memberAnalysisView.style.display = "none";
    if (annuityReportingView) annuityReportingView.style.display = "none";
    if (sysadminCockpitView) sysadminCockpitView.style.display = "none";
    if (investmentAnalysisView) investmentAnalysisView.style.display = "block";
    stopSysAdminPolling();
    updateDrawerSchema("investment_analysis");
    refreshInvestmentSlicersCascading(false);
    fetchInvestmentAnalysisData(currentInvTab);
  } else if (slug === "annuity_reporting") {
    if (tabMember) tabMember.classList.remove("active");
    if (tabInv) tabInv.classList.remove("active");
    if (tabAnnuity) tabAnnuity.classList.add("active");
    if (tabSysAdmin) tabSysAdmin.classList.remove("active");
    if (memberAnalysisView) memberAnalysisView.style.display = "none";
    if (investmentAnalysisView) investmentAnalysisView.style.display = "none";
    if (sysadminCockpitView) sysadminCockpitView.style.display = "none";
    if (annuityReportingView) annuityReportingView.style.display = "block";
    stopSysAdminPolling();
    updateDrawerSchema("annuity_reporting");
    refreshAnnuitySlicersCascading(false);
    fetchAnnuityData(currentAnnuityTab);
  } else if (slug === "sysadmin_cockpit") {
    if (tabMember) tabMember.classList.remove("active");
    if (tabInv) tabInv.classList.remove("active");
    if (tabAnnuity) tabAnnuity.classList.remove("active");
    if (tabSysAdmin) tabSysAdmin.classList.add("active");
    if (memberAnalysisView) memberAnalysisView.style.display = "none";
    if (investmentAnalysisView) investmentAnalysisView.style.display = "none";
    if (annuityReportingView) annuityReportingView.style.display = "none";
    if (sysadminCockpitView) sysadminCockpitView.style.display = "block";
    updateDrawerSchema("sysadmin_cockpit");
    startSysAdminPolling();
  }
}

/**
 * US-1.2 (cycle 5): the POPIA pill reports the entitlement the server resolved.
 * It is an indicator, never a control -- the client has no say in masking, so it
 * must not render anything that suggests it does.
 */
function renderPiiIndicator(canViewPii) {
  isPiiMasked = !canViewPii;
  const pill = document.getElementById("popiaIndicator");
  if (!pill) return;
  pill.className = `popia-pill ${isPiiMasked ? "active" : "inactive"}`;
  const text = document.getElementById("popiaText");
  if (text) {
    text.textContent = isPiiMasked ? "POPIA Masked" : "PII Visible";
  }
  pill.title = isPiiMasked
    ? "Personal information is masked for your role"
    : "Your role is entitled to view personal information";
}

const ROLE_LABELS = {
  ROLE_EXECUTIVE_ALL: "Executive (Full Access)",
  ROLE_FINANCE_MEMBER: "Finance & Member Analytics",
  ROLE_DIGITAL_OPERATIONS: "Digital Operations",
  ROLE_INVESTMENTS: "Investment Consultants",
  ROLE_ANNUITY: "Annuity & Preservation",
};

/**
 * US-1.2: the role is resolved server-side from the caller's identity.
 * The UI asks who it is, displays the answer, and offers no way to change it.
 */
async function initIdentity() {
  const el = document.getElementById("roleDisplay");
  try {
    const res = await fetch("/api/identity");
    const identity = await res.json();
    currentRole = identity.role;
    isPiiMasked = !identity.can_view_pii;
    if (el) {
      el.textContent = ROLE_LABELS[identity.role] || identity.role;
      el.dataset.role = identity.role;
      el.title = identity.authenticated
        ? `Signed in as ${identity.email}`
        : "Not signed in - least-privilege access";
    }
    renderPiiIndicator(identity.can_view_pii);
  } catch (err) {
    // Identity is unknown, so assume nothing. The server is the authority and
    // will apply least privilege regardless of what is shown here.
    if (el) {
      el.textContent = "Role unavailable";
      el.dataset.role = "";
      el.title = "Could not resolve identity";
    }
    // Identity is unknown, so report the safe assumption, not a guess.
    renderPiiIndicator(false);
  }
  refreshActiveDashboard();
}

function refreshActiveDashboard() {
  if (currentDashboard === "member_analysis") {
    fetchMemberAnalysisData(currentPbiTab);
  } else if (currentDashboard === "investment_analysis") {
    fetchInvestmentAnalysisData(currentInvTab);
  } else if (currentDashboard === "annuity_reporting") {
    fetchAnnuityData(currentAnnuityTab);
  }
}

function initDrawer() {
  const drawer = document.getElementById("schemaDrawer");
  const overlay = document.getElementById("drawerOverlay");
  const btnOpen = document.getElementById("btnSchemaInspector");
  const btnClose = document.getElementById("btnCloseDrawer");

  const openDrawer = () => {
    if (drawer) drawer.classList.add("open");
    if (overlay) overlay.style.display = "block";
  };

  const closeDrawer = () => {
    if (drawer) drawer.classList.remove("open");
    if (overlay) overlay.style.display = "none";
  };

  if (btnOpen) btnOpen.addEventListener("click", openDrawer);
  if (btnClose) btnClose.addEventListener("click", closeDrawer);
  if (overlay) overlay.addEventListener("click", closeDrawer);
}

function updateDrawerSchema(slug) {
  const sqlEl = document.getElementById("drawerDuckDbSql");
  const cubeEl = document.getElementById("drawerCubeJs");
  const gcsEl = document.getElementById("drawerGcsPath");

  if (slug === "member_analysis") {
    if (sqlEl) {
      sqlEl.textContent = `-- Member Analysis Summary Semantic View
CREATE OR REPLACE VIEW scbi_cdp_mart.v_member_analysis AS
SELECT 
    m.MEMBER_HK, m.GENDER, m.BIRTH_DATE, m.CURRENT_AGE,
    fm.DATE_SK, fm.TOTAL_AUA, fm.MONTHLY_SALARY, fm.PENSIONABLE_SALARY
FROM scbi_cdp_mart.cnf__dim_member m
JOIN scbi_cdp_mart.cnf__fact_member_monthly fm ON m.MEMBER_HK = fm.MEMBER_HK
WHERE fm.DATE_SK >= 20240101;`;
    }
    if (cubeEl) {
      cubeEl.textContent = `cube(\`MemberGalaxy\`, {
  sql: \`SELECT * FROM scbi_cdp_mart.cnf__fact_member_monthly\`,
  joins: {
    DimMember: { sql: \`\${CUBE}.MEMBER_HK = \${DimMember}.MEMBER_HK\`, relationship: \`manyToOne\` },
    DimDate: { sql: \`\${CUBE}.DATE_SK = \${DimDate}.DATE_SK\`, relationship: \`manyToOne\` }
  },
  measures: {
    totalMembers: { type: \`countDistinct\`, sql: \`\${DimMember.memberHk}\` },
    totalAua: { type: \`sum\`, sql: \`\${CUBE}.AUA_AMOUNT\` },
    avgSalary: { type: \`avg\`, sql: \`\${CUBE}.MONTHLY_SALARY\` }
  }
});`;
    }
    if (gcsEl) {
      gcsEl.textContent = `gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_member/*.parquet
gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_member_monthly/*.parquet`;
    }
  } else if (slug === "investment_analysis") {
    if (sqlEl) {
      sqlEl.textContent = `-- Fund Analytics - Investment Analysis Semantic View
CREATE OR REPLACE VIEW scbi_cdp_mart.v_investment_analysis AS
SELECT 
    f.PORTFOLIO_HK, f.DATE_SK, f.MARKET_VALUE, f.SMOOTHED_BONUS_FLAG,
    p.PORTFOLIO_CODE, p.PORTFOLIO_NAME, p.RISK_PROFILE
FROM scbi_cdp_mart.cnf__fact_investments_fundamental f
JOIN scbi_cdp_mart.cnf__dim_portfolio p ON f.PORTFOLIO_HK = p.PORTFOLIO_HK
WHERE f.DATE_SK >= 20240101;`;
    }
    if (cubeEl) {
      cubeEl.textContent = `cube(\`InvestmentsFundamental\`, {
  sql: \`SELECT * FROM scbi_cdp_mart.cnf__fact_investments_fundamental\`,
  joins: {
    DimPortfolio: { sql: \`\${CUBE}.PORTFOLIO_HK = \${DimPortfolio}.PORTFOLIO_HK\`, relationship: \`manyToOne\` }
  },
  measures: {
    totalMarketValue: { type: \`sum\`, sql: \`\${CUBE}.MARKET_VALUE\` },
    portfolioCount: { type: \`countDistinct\`, sql: \`\${DimPortfolio.portfolioHk}\` }
  }
});`;
    }
    if (gcsEl) {
      gcsEl.textContent = `gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_investments_fundamental/*.parquet
gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_portfolio/*.parquet`;
    }
  } else if (slug === "annuity_reporting") {
    if (sqlEl) {
      sqlEl.textContent = `-- Life Annuity Quotes & Acceptances Semantic View
CREATE OR REPLACE VIEW scbi_cdp_mart.v_annuity_quotations AS
SELECT 
    f.QUOTATION_NUMBER, f.QUOTATION_DATE_SK, f.DERIVED_QUOTATION_STATUS,
    f.QUOTATION_PURCHASE_PRICE, f.QUOTATION_ANNUITY_PAYMENT, f.SOURCE,
    f.MEMBER_ID, b.BROKER_CONSULTANT_NAME, b.BROKER_CONSULTANT_BUSINESS,
    p.PRODUCT_DESCRIPTION, p.PRODUCT_GROUP
FROM scbi_cdp_mart.cnf__fact_annuity_quotations f
LEFT JOIN scbi_cdp_mart.cnf__dim_broker_consultant b ON f.BROKER_CONSULTANT_HK = b.BROKER_CONSULTANT_HK
LEFT JOIN scbi_cdp_mart.cnf__dim_annuity_product p ON f.PRODUCT_HK = p.PRODUCT_HK
WHERE f.DERIVED_QUOTATION_STATUS <> 'Accepted' 
  AND NOT (f.DERIVED_QUOTATION_TYPE = 'Bulk' AND LOWER(f.SOURCE) = 'online');`;
    }
    if (cubeEl) {
      cubeEl.textContent = `cube(\`AnnuityQuotation\`, {
  sql: \`SELECT * FROM scbi_cdp_mart.cnf__fact_annuity_quotations\`,
  joins: {
    DimBrokerConsultant: { sql: \`\${CUBE}.BROKER_CONSULTANT_HK = \${DimBrokerConsultant}.BROKER_CONSULTANT_HK\`, relationship: \`manyToOne\` },
    DimAnnuityProduct: { sql: \`\${CUBE}.PRODUCT_HK = \${DimAnnuityProduct}.PRODUCT_HK\`, relationship: \`manyToOne\` }
  },
  measures: {
    distinctQuotedMembers: { type: \`countDistinct\`, sql: \`\${CUBE}.MEMBER_ID\` },
    distinctAcceptedMembers: { type: \`countDistinct\`, sql: \`\${CUBE}.MEMBER_ID\`, filters: [{ sql: \`\${CUBE}.DERIVED_QUOTATION_STATUS = 'Accepted'\` }] },
    acceptedPurchasePrice: { type: \`sum\`, sql: \`\${CUBE}.QUOTATION_PURCHASE_PRICE\`, filters: [{ sql: \`\${CUBE}.DERIVED_QUOTATION_STATUS = 'Accepted'\` }] }
  }
});`;
    }
    if (gcsEl) {
      gcsEl.textContent = `gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__fact_annuity_quotations/*.parquet
gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_broker_consultant/*.parquet
gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_fund/*.parquet
gs://scbi-ducklake-myanalyticsproduct/scbi_cdp_mart/cnf__dim_annuity_product/*.parquet`;
    }
  }
}

async function fetchLakehouseStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.status === "HEALTHY") {
      const el = document.getElementById("lakehouseStatusText");
      if (el) {
        el.textContent = `DuckLake Active (${data.migrated_tables}/${data.total_tables} Tables)`;
      }
    }
  } catch (err) {
    console.warn("Status fetch failed:", err);
  }
}

function slugToPascal(slug) {
  return slug
    .split("_")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join("");
}

/* ── 8. Power BI Replica: Member Analysis Summary Module (Option A) ─────── */

let memberAnalysisAbortController = null;

async function initMemberAnalysis() {
  // 1. Sub-Tab Switching
  const subtabs = document.querySelectorAll(".pbi-subtab-btn");
  subtabs.forEach(btn => {
    btn.addEventListener("click", () => {
      subtabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentPbiTab = btn.dataset.tab;

      // Hide all panes
      document.querySelectorAll(".pbi-tab-pane").forEach(pane => pane.style.display = "none");

      // Show selected pane
      const paneMap = {
        overview: "pbiTabOverview",
        retirement: "pbiTabRetirement",
        age_salary: "pbiTabAgeSalary",
        contributions: "pbiTabContributions",
        products_risk: "pbiTabProductsRisk"
      };
      const targetPane = document.getElementById(paneMap[currentPbiTab]);
      if (targetPane) targetPane.style.display = "block";

      fetchMemberAnalysisData(currentPbiTab);
    });
  });

  // 2. Initial load of cascading slicers
  await refreshMemberSlicersCascading(true);

  // 3. Slicer Change Listeners with 250ms debouncing and cascading dependency
  const slicerIds = [
    "pbiSlicerDate", "pbiSlicerFund", "pbiSlicerBU", "pbiSlicerClient",
    "pbiSlicerEmployer", "pbiSlicerBrokerage", "pbiSlicerAssociation", "pbiSlicerPaypoint"
  ];

  const handleMemberSlicerChange = debounce(async (changedId) => {
    await refreshMemberSlicersCascading(false, changedId);
    syncFiltersCrossDashboard("member_analysis");
    fetchMemberAnalysisData(currentPbiTab);
  }, 250);

  slicerIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("change", () => handleMemberSlicerChange(id));
    }
  });
}

function getMemberCurrentFilters() {
  return {
    date: document.getElementById("pbiSlicerDate")?.value || "",
    fund: document.getElementById("pbiSlicerFund")?.value || "",
    business_unit: document.getElementById("pbiSlicerBU")?.value || "",
    client: document.getElementById("pbiSlicerClient")?.value || "",
    employer: document.getElementById("pbiSlicerEmployer")?.value || "",
    brokerage: document.getElementById("pbiSlicerBrokerage")?.value || "",
    association: document.getElementById("pbiSlicerAssociation")?.value || "",
    paypoint: document.getElementById("pbiSlicerPaypoint")?.value || ""
  };
}

async function refreshMemberSlicersCascading(isInitial = false, triggeringId = null) {
  try {
    const filters = getMemberCurrentFilters();
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v && v !== "All" && v !== "All Dates" && v !== "All Funds" && v !== "All Funds (SUS)") {
        params.append(k, v);
      }
    });

    const res = await fetch(`/api/member_analysis/slicers?${params.toString()}`);
    if (!res.ok) return;
    const slicers = await res.json();

    if (isInitial || triggeringId !== "pbiSlicerDate") populatePbiSelect("pbiSlicerDate", slicers.date || slicers.dates);
    if (isInitial || triggeringId !== "pbiSlicerFund") {
      const fundOpts = filters.business_unit === "SUS" && slicers.sus_funds ? slicers.sus_funds : slicers.fund;
      populatePbiSelect("pbiSlicerFund", fundOpts);
    }
    if (isInitial || triggeringId !== "pbiSlicerBU") populatePbiSelect("pbiSlicerBU", slicers.business_unit);
    if (isInitial || triggeringId !== "pbiSlicerClient") populatePbiSelect("pbiSlicerClient", slicers.client);
    if (isInitial || triggeringId !== "pbiSlicerEmployer") populatePbiSelect("pbiSlicerEmployer", slicers.employer);
    if (isInitial || triggeringId !== "pbiSlicerBrokerage") populatePbiSelect("pbiSlicerBrokerage", slicers.brokerage);
    if (isInitial || triggeringId !== "pbiSlicerAssociation") populatePbiSelect("pbiSlicerAssociation", slicers.association);
    if (isInitial || triggeringId !== "pbiSlicerPaypoint") populatePbiSelect("pbiSlicerPaypoint", slicers.paypoint_classification);
  } catch (err) {
    console.warn("Could not load Member Analysis slicers:", err);
  }
}

function populatePbiSelect(id, options) {
  const sel = document.getElementById(id);
  if (!sel || !options) return;
  const currentVal = sel.value;
  sel.innerHTML = "";
  options.forEach(optVal => {
    const opt = document.createElement("option");
    opt.value = optVal;
    opt.textContent = optVal;
    sel.appendChild(opt);
  });
  if (currentVal && options.includes(currentVal)) {
    sel.value = currentVal;
  } else if (id.toLowerCase().includes("date") && options.length > 1) {
    sel.value = options.includes("31-DEC-2025") ? "31-DEC-2025" : options[1];
  }
}

async function fetchMemberAnalysisData(tab) {
  if (memberAnalysisAbortController) {
    memberAnalysisAbortController.abort();
  }
  memberAnalysisAbortController = new AbortController();

  setDashboardLoading("memberAnalysisView", true);
  const t0 = performance.now();

  try {
    const filters = getMemberCurrentFilters();
    const params = new URLSearchParams({
      tab: tab || "overview",
      role: currentRole
    });

    Object.entries(filters).forEach(([k, v]) => {
      if (v && v !== "All" && v !== "All Dates" && v !== "All Funds" && v !== "All Funds (SUS)") {
        params.append(k, v);
      }
    });

    const res = await fetch(`/api/member_analysis/query?${params.toString()}`, {
      signal: memberAnalysisAbortController.signal
    });
    if (!res.ok) return;
    const data = await res.json();

    const elapsed = data.execution_time_ms !== undefined ? data.execution_time_ms : Math.round(performance.now() - t0);
    updateFetchTelemetry(elapsed);

    if (tab === "overview") {
      renderOverviewTab(data);
    } else if (tab === "retirement") {
      renderRetirementTab(data);
    } else if (tab === "age_salary") {
      renderAgeSalaryTab(data);
    } else if (tab === "contributions") {
      renderContributionsTab(data);
    } else if (tab === "products_risk") {
      renderProductsRiskTab(data);
    }

    if (data.cube_status) {
      const tag = document.querySelector("#memberAnalysisView .pbi-cloud-tag span:last-child");
      if (tag) tag.textContent = data.cube_status;
    }

    // US-6.0: surface fabricated data. Removed when US-6.1..6.4 make the
    // handler query Cube and demo_data stops being set.
    const demoBanner = document.getElementById("memberDemoBanner");
    if (demoBanner) {
      if (data.demo_data) {
        demoBanner.textContent = data.demo_banner || "DEMO DATA — NOT FROM SOURCE";
        demoBanner.style.display = "block";
      } else {
        demoBanner.style.display = "none";
      }
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      console.error("Failed to load member analysis data:", err);
    }
  } finally {
    setDashboardLoading("memberAnalysisView", false);
  }
}

function createOrUpdateChart(chartKey, canvasId, config) {
  if (pbiChartInstances[chartKey]) {
    pbiChartInstances[chartKey].destroy();
  }
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  pbiChartInstances[chartKey] = new Chart(ctx, config);
}

// ── Tab 1: Overview & Demographics ──────────────────────────────────────────
function renderOverviewTab(data) {
  const d = data.demographics;
  if (d) {
    document.getElementById("pbiAllTotalMembers").textContent = d.all?.total_members || "-";
    document.getElementById("pbiAllAvgAge").textContent = d.all?.avg_age || "-";
    document.getElementById("pbiAllAvgSalary").textContent = d.all?.avg_monthly_salary || "-";

    document.getElementById("pbiMaleTotalMembers").textContent = d.male?.total_members || "-";
    document.getElementById("pbiMaleAvgAge").textContent = d.male?.avg_age || "-";
    document.getElementById("pbiMaleAvgSalary").textContent = d.male?.avg_monthly_salary || "-";

    document.getElementById("pbiFemaleTotalMembers").textContent = d.female?.total_members || "-";
    document.getElementById("pbiFemaleAvgAge").textContent = d.female?.avg_age || "-";
    document.getElementById("pbiFemaleAvgSalary").textContent = d.female?.avg_monthly_salary || "-";
  }

  const kpis = data.financial_kpis;
  if (kpis) {
    document.getElementById("pbiKpiTotalAua").textContent = kpis.total_aua || "-";
    document.getElementById("pbiKpiAvgAua").textContent = kpis.avg_aua || "-";
    document.getElementById("pbiKpiTotalSalary").textContent = kpis.total_monthly_salary || "-";
  }

  if (data.age_band_chart) {
    createOrUpdateChart("ageBand", "pbiChartAgeBand", {
      type: "bar",
      data: {
        labels: data.age_band_chart.labels,
        datasets: [{
          label: "Member Count",
          data: data.age_band_chart.values,
          backgroundColor: "#0078D4",
          borderRadius: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `Member Count: ${ctx.raw.toLocaleString()}`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: "#475569", font: { size: 11 } }
          },
          y: {
            grid: { color: "#F1F5F9" },
            ticks: {
              color: "#475569",
              callback: (v) => (v >= 1000 ? `${v / 1000}K` : v)
            }
          }
        }
      }
    });
  }
}

// ── Tab 2: Retirement Age Analysis ──────────────────────────────────────────
function renderRetirementTab(data) {
  if (data.near_normal) {
    createOrUpdateChart("nearRetirement", "pbiChartNearRetirement", {
      type: "bar",
      data: {
        labels: data.near_normal.categories,
        datasets: [
          { label: "Female", data: data.near_normal.female, backgroundColor: "#0078D4" },
          { label: "Male", data: data.near_normal.male, backgroundColor: "#00B7C3" }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12 } },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw.toLocaleString()}` } }
        },
        scales: {
          x: {
            grid: { color: "#F1F5F9" },
            ticks: { callback: v => (v >= 1000 ? `${v / 1000}K` : v) }
          },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } }
        }
      }
    });
  }

  if (data.past_early) {
    createOrUpdateChart("pastRetirement", "pbiChartPastRetirement", {
      type: "bar",
      data: {
        labels: data.past_early.categories,
        datasets: [
          { label: "Female", data: data.past_early.female, backgroundColor: "#0078D4" },
          { label: "Male", data: data.past_early.male, backgroundColor: "#00B7C3" }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12 } },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw.toLocaleString()}` } }
        },
        scales: {
          x: {
            grid: { color: "#F1F5F9" },
            ticks: { callback: v => (v >= 1000 ? `${v / 1000}K` : v) }
          },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } }
        }
      }
    });
  }
}

// ── Tab 3: Member Distribution by Age Band & Salary Band ────────────────────
function renderAgeSalaryTab(data) {
  if (data.age_band_gender) {
    createOrUpdateChart("ageBandGender", "pbiChartAgeBandGender", {
      type: "bar",
      data: {
        labels: data.age_band_gender.categories,
        datasets: [
          { label: "Female", data: data.age_band_gender.female, backgroundColor: "#0078D4" },
          { label: "Male", data: data.age_band_gender.male, backgroundColor: "#00B7C3" }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12 } },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw.toLocaleString()}` } }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 11 } } },
          y: { grid: { color: "#F1F5F9" }, ticks: { callback: v => (v >= 1000 ? `${v / 1000}K` : v) } }
        }
      }
    });
  }

  if (data.salary_band_gender) {
    createOrUpdateChart("salaryBandGender", "pbiChartSalaryBandGender", {
      type: "bar",
      data: {
        labels: data.salary_band_gender.categories,
        datasets: [
          { label: "Female", data: data.salary_band_gender.female, backgroundColor: "#0078D4" },
          { label: "Male", data: data.salary_band_gender.male, backgroundColor: "#00B7C3" }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12 } },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw.toLocaleString()}` } }
        },
        scales: {
          x: { grid: { color: "#F1F5F9" }, ticks: { callback: v => (v >= 1000 ? `${v / 1000}K` : v) } },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } }
        }
      }
    });
  }
}

// ── Tab 4: Contribution Rates ───────────────────────────────────────────────
function renderContributionsTab(data) {
  if (data.gross_age_band) {
    createOrUpdateChart("grossAge", "pbiChartGrossAge", {
      type: "bar",
      data: {
        labels: data.gross_age_band.categories,
        datasets: [{
          label: "Avg Gross Contribution",
          data: data.gross_age_band.values,
          backgroundColor: "#0078D4"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.raw}%` } }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 10 } } },
          y: { grid: { color: "#F1F5F9" }, ticks: { callback: v => `${v}%` } }
        }
      }
    });
  }

  if (data.net_age_band) {
    createOrUpdateChart("netAge", "pbiChartNetAge", {
      type: "bar",
      data: {
        labels: data.net_age_band.categories,
        datasets: [{
          label: "Avg Net Contribution",
          data: data.net_age_band.values,
          backgroundColor: "#0078D4"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.raw}%` } }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 10 } } },
          y: { grid: { color: "#F1F5F9" }, ticks: { callback: v => `${v}%` } }
        }
      }
    });
  }

  if (data.gross_salary_band) {
    createOrUpdateChart("grossSalary", "pbiChartGrossSalary", {
      type: "bar",
      data: {
        labels: data.gross_salary_band.categories,
        datasets: [{
          label: "Avg Gross Contribution",
          data: data.gross_salary_band.values,
          backgroundColor: "#0078D4"
        }]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.raw}%` } }
        },
        scales: {
          x: { grid: { color: "#F1F5F9" }, ticks: { callback: v => `${v}%` } },
          y: { grid: { display: false }, ticks: { font: { size: 10 } } }
        }
      }
    });
  }

  if (data.net_salary_band) {
    createOrUpdateChart("netSalary", "pbiChartNetSalary", {
      type: "bar",
      data: {
        labels: data.net_salary_band.categories,
        datasets: [{
          label: "Avg Net Contribution",
          data: data.net_salary_band.values,
          backgroundColor: "#0078D4"
        }]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.raw}%` } }
        },
        scales: {
          x: { grid: { color: "#F1F5F9" }, ticks: { callback: v => `${v}%` } },
          y: { grid: { display: false }, ticks: { font: { size: 10 } } }
        }
      }
    });
  }
}

// ── Tab 5: Products & Risk ──────────────────────────────────────────────────
function renderProductsRiskTab(data) {
  if (data.product_group_aua) {
    const pg = data.product_group_aua;
    const formattedLabels = pg.labels.map((l, i) => `${l}: R ${pg.amounts[i]}bn (${pg.percentages[i]}%)`);
    createOrUpdateChart("productDonut", "pbiChartProductDonut", {
      type: "doughnut",
      data: {
        labels: formattedLabels,
        datasets: [{
          data: pg.amounts,
          backgroundColor: ["#0078D4", "#50E6FF", "#E3008C", "#FFB900"],
          borderWidth: 2,
          borderColor: "#FFFFFF"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "right",
            labels: { font: { size: 12 }, boxWidth: 14 }
          }
        }
      }
    });
  }

  if (data.top_risk_products) {
    createOrUpdateChart("topRisk", "pbiChartTopRisk", {
      type: "bar",
      data: {
        labels: data.top_risk_products.categories,
        datasets: [
          { label: "Female", data: data.top_risk_products.female, backgroundColor: "#0078D4" },
          { label: "Male", data: data.top_risk_products.male, backgroundColor: "#00B7C3" }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12 } },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw.toLocaleString()}` } }
        },
        scales: {
          x: {
            grid: { color: "#F1F5F9" },
            ticks: { callback: v => (v >= 1000 ? `${v / 1000}K` : v) }
          },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } }
        }
      }
    });
  }
}

/* ── 9. Power BI Replica: Fund Analytics - Investment Analysis (Option A) ── */

let investmentAnalysisAbortController = null;

async function initInvestmentAnalysis() {
  // 1. Sub-Tab Switching
  const subtabs = document.querySelectorAll(".pbi-inv-subtab-btn");
  subtabs.forEach(btn => {
    btn.addEventListener("click", () => {
      subtabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentInvTab = btn.dataset.tab;

      // Hide all panes
      document.querySelectorAll(".pbi-inv-tab-pane").forEach(pane => pane.style.display = "none");

      // Show selected pane
      const paneMap = {
        overview: "pbiInvTabOverview",
        distribution: "pbiInvTabDistribution",
        risk_matrix: "pbiInvTabRiskMatrix",
        holdings: "pbiInvTabHoldings",
        pensionable_service: "pbiInvTabPensionableService"
      };
      const targetPane = document.getElementById(paneMap[currentInvTab]);
      if (targetPane) targetPane.style.display = "block";

      fetchInvestmentAnalysisData(currentInvTab);
    });
  });

  // 2. Initial load of cascading slicers
  await refreshInvestmentSlicersCascading(true);

  // 3. Slicer Change Listeners with 250ms debouncing and cascading dependency
  const slicerIds = [
    "pbiInvSlicerDate", "pbiInvSlicerBU", "pbiInvSlicerClient", "pbiInvSlicerFund",
    "pbiInvSlicerEmployer", "pbiInvSlicerAssociation", "pbiInvSlicerBrokerage"
  ];

  const handleInvSlicerChange = debounce(async (changedId) => {
    await refreshInvestmentSlicersCascading(false, changedId);
    syncFiltersCrossDashboard("investment_analysis");
    fetchInvestmentAnalysisData(currentInvTab);
  }, 250);

  slicerIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("change", () => handleInvSlicerChange(id));
    }
  });
}

function getInvestmentCurrentFilters() {
  return {
    date: document.getElementById("pbiInvSlicerDate")?.value || "",
    business_unit: document.getElementById("pbiInvSlicerBU")?.value || "",
    client_name: document.getElementById("pbiInvSlicerClient")?.value || "",
    fund_name: document.getElementById("pbiInvSlicerFund")?.value || "",
    employer_name: document.getElementById("pbiInvSlicerEmployer")?.value || "",
    association_name: document.getElementById("pbiInvSlicerAssociation")?.value || "",
    brokerage_name: document.getElementById("pbiInvSlicerBrokerage")?.value || ""
  };
}

async function refreshInvestmentSlicersCascading(isInitial = false, triggeringId = null) {
  try {
    const filters = getInvestmentCurrentFilters();
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v && v !== "All" && v !== "All Dates" && v !== "All Funds" && v !== "All Funds (SUS)") {
        params.append(k, v);
      }
    });

    const res = await fetch(`/api/investment_analysis/slicers?${params.toString()}`);
    if (!res.ok) return;
    const slicers = await res.json();

    if (isInitial || triggeringId !== "pbiInvSlicerDate") populatePbiSelect("pbiInvSlicerDate", slicers.date || slicers.dates);
    if (isInitial || triggeringId !== "pbiInvSlicerBU") populatePbiSelect("pbiInvSlicerBU", slicers.business_unit);
    if (isInitial || triggeringId !== "pbiInvSlicerClient") populatePbiSelect("pbiInvSlicerClient", slicers.client_name || slicers.clients);
    if (isInitial || triggeringId !== "pbiInvSlicerFund") {
      const fundOpts = filters.business_unit === "SUS" && slicers.sus_funds ? slicers.sus_funds : (slicers.fund_name || slicers.funds);
      populatePbiSelect("pbiInvSlicerFund", fundOpts);
    }
    if (isInitial || triggeringId !== "pbiInvSlicerEmployer") populatePbiSelect("pbiInvSlicerEmployer", slicers.employer_name || slicers.employers);
    if (isInitial || triggeringId !== "pbiInvSlicerAssociation") populatePbiSelect("pbiInvSlicerAssociation", slicers.association_name || slicers.associations);
    if (isInitial || triggeringId !== "pbiInvSlicerBrokerage") populatePbiSelect("pbiInvSlicerBrokerage", slicers.brokerage_name || slicers.brokerages);
  } catch (err) {
    console.warn("Could not load Investment Analysis slicers:", err);
  }
}

async function fetchInvestmentAnalysisData(tab) {
  if (investmentAnalysisAbortController) {
    investmentAnalysisAbortController.abort();
  }
  investmentAnalysisAbortController = new AbortController();

  setDashboardLoading("investmentAnalysisView", true);
  const t0 = performance.now();

  try {
    const filters = getInvestmentCurrentFilters();
    const params = new URLSearchParams({
      tab: tab || "overview",
      role: currentRole
    });

    Object.entries(filters).forEach(([k, v]) => {
      if (v && v !== "All" && v !== "All Dates" && v !== "All Funds" && v !== "All Funds (SUS)") {
        params.append(k, v);
      }
    });

    const res = await fetch(`/api/investment_analysis/query?${params.toString()}`, {
      signal: investmentAnalysisAbortController.signal
    });
    if (!res.ok) return;
    const data = await res.json();

    const elapsed = data.execution_time_ms !== undefined ? data.execution_time_ms : Math.round(performance.now() - t0);
    updateFetchTelemetry(elapsed);

    if (tab === "overview") {
      renderInvOverviewTab(data);
    } else if (tab === "distribution") {
      renderInvDistributionTab(data);
    } else if (tab === "risk_matrix") {
      renderInvRiskMatrixTab(data);
    } else if (tab === "holdings") {
      renderInvHoldingsTab(data);
    } else if (tab === "pensionable_service") {
      renderInvPensionableServiceTab(data);
    }

    if (data.cube_status) {
      const tag = document.querySelector("#investmentAnalysisView .pbi-cloud-tag span:last-child");
      if (tag) tag.textContent = data.live_feed ? "scbi-cube live feed active" : data.cube_status;
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      console.error("Failed to load investment analysis data:", err);
    }
  } finally {
    setDashboardLoading("investmentAnalysisView", false);
  }
}

// ── Tab 1: Overview & Portfolio Allocation ──────────────────────────────────
function renderInvOverviewTab(data) {
  const kpis = data.kpis;
  if (kpis) {
    document.getElementById("pbiInvKpiAua").textContent = kpis.total_aua || "-";
    document.getElementById("pbiInvKpiClients").textContent = kpis.distinct_clients || "-";
    document.getElementById("pbiInvKpiPortfolios").textContent = kpis.investment_portfolios || "-";
    document.getElementById("pbiInvKpiPaypoints").textContent = kpis.distinct_paypoints || "-";
  }

  // Top 10 Portfolios
  if (data.top_portfolios) {
    createOrUpdateChart("topPortfolios", "pbiChartTopPortfolios", {
      type: "bar",
      data: {
        labels: data.top_portfolios.categories,
        datasets: [
          { label: "Default", data: data.top_portfolios.default, backgroundColor: "#0078D4" },
          { label: "Member Choice", data: data.top_portfolios.member_choice, backgroundColor: "#00B7C3" }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
            grid: { color: "#F1F5F9" },
            ticks: { callback: v => `${v}bn` }
          },
          y: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 } } }
        },
        plugins: {
          legend: { position: "top", labels: { boxWidth: 12 } }
        }
      }
    });
  }

  // AUA by Member Choice Donut
  if (data.member_choice_donut) {
    const mc = data.member_choice_donut;
    createOrUpdateChart("memberChoiceDonut", "pbiChartMemberChoiceDonut", {
      type: "doughnut",
      data: {
        labels: mc.labels.map((l, i) => `${l}: R ${mc.values[i]}bn (${mc.percentages[i]}%)`),
        datasets: [{
          data: mc.values,
          backgroundColor: ["#0078D4", "#00B7C3"],
          borderWidth: 2,
          borderColor: "#FFFFFF"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12, font: { size: 11 } } }
        }
      }
    });
  }

  // AUA by Age Band
  if (data.age_band_aua) {
    createOrUpdateChart("ageBandAua", "pbiChartAgeBandAua", {
      type: "bar",
      data: {
        labels: data.age_band_aua.labels,
        datasets: [{
          label: "AUA Amount",
          data: data.age_band_aua.values,
          backgroundColor: "#0078D4",
          borderRadius: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `AUA: ${ctx.raw}T (R ${(ctx.raw * 1000).toFixed(1)}B)`
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 10 } } },
          y: {
            grid: { color: "#F1F5F9" },
            ticks: { callback: v => `${v}T` }
          }
        }
      }
    });
  }

  // AUA by Gender Donut
  if (data.gender_donut) {
    const gd = data.gender_donut;
    createOrUpdateChart("genderDonut", "pbiChartGenderDonut", {
      type: "doughnut",
      data: {
        labels: gd.labels.map((l, i) => `${l}: R ${gd.values[i]}bn (${gd.percentages[i]}%)`),
        datasets: [{
          data: gd.values,
          backgroundColor: ["#0078D4", "#00B7C3"],
          borderWidth: 2,
          borderColor: "#FFFFFF"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12, font: { size: 11 } } }
        }
      }
    });
  }
}

// ── Tab 2: Member Choice vs Default Risk Distribution ───────────────────────
function renderInvDistributionTab(data) {
  const kpis = data.kpis;
  if (kpis) {
    document.getElementById("pbiInvKpiTotalMembers").textContent = kpis.total_membership_count || "-";
    document.getElementById("pbiInvKpiChoiceExercised").textContent = kpis.member_choice_exercised || "-";
    document.getElementById("pbiInvKpiDefaultCount").textContent = kpis.default_count || "-";
  }

  if (data.member_choice_chart) {
    const mc = data.member_choice_chart;
    createOrUpdateChart("memberChoiceDist", "pbiChartMemberChoiceDist", {
      type: "bar",
      data: {
        labels: mc.categories,
        datasets: mc.series.map(s => ({
          label: s.name,
          data: s.data,
          backgroundColor: s.color
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 } } },
          y: { stacked: true, max: 100, ticks: { callback: v => `${v}%` } }
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } }
        }
      }
    });
  }

  if (data.default_choice_chart) {
    const dc = data.default_choice_chart;
    createOrUpdateChart("defaultDist", "pbiChartDefaultDist", {
      type: "bar",
      data: {
        labels: dc.categories,
        datasets: dc.series.map(s => ({
          label: s.name,
          data: s.data,
          backgroundColor: s.color
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 } } },
          y: { stacked: true, max: 100, ticks: { callback: v => `${v}%` } }
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } }
        }
      }
    });
  }
}

// ── Tab 3: Risk Rating Asset Distribution Matrix ────────────────────────────
function renderInvRiskMatrixTab(data) {
  const container = document.getElementById("pbiMatrixCardsContainer");
  if (!container || !data.matrix_data) return;
  container.innerHTML = "";

  const titleMap = {
    age_18_to_24: "18 to 24",
    age_25_to_34: "25 to 34",
    age_35_to_44: "35 to 44",
    age_45_to_54: "45 to 54",
    age_55_to_64: "55 to 64",
    age_65_plus: "65+"
  };

  Object.entries(data.matrix_data).forEach(([key, rows]) => {
    const card = document.createElement("div");
    card.className = "pbi-matrix-card";

    let rowsHtml = rows.map(r => `
      <tr>
        <td>${r.risk}</td>
        <td>${r.pct}</td>
      </tr>
    `).join("");

    card.innerHTML = `
      <div class="pbi-matrix-card-header">
        <span>Risk Rating</span>
        <span>${titleMap[key] || key}</span>
      </div>
      <table class="pbi-matrix-table">
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    `;
    container.appendChild(card);
  });
}

// ── Tab 4: Holdings Detail ──────────────────────────────────────────────────
function renderInvHoldingsTab(data) {
  const tbody = document.getElementById("pbiInvHoldingsBody");
  if (!tbody || !data.holdings_table) return;
  tbody.innerHTML = "";

  data.holdings_table.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${row.code}</strong></td>
      <td>${row.name}</td>
      <td><span class="status-pill status-active">${row.risk_meter}</span></td>
      <td>${row.category}</td>
      <td style="font-family: 'Roboto Mono', monospace; font-weight: 600;">${row.aua}</td>
      <td>${row.members}</td>
      <td><span class="status-pill status-completed">${row.status}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// ── Tab 5: Pensionable Service Cross-Tab ─────────────────────────────────────
function renderInvPensionableServiceTab(data) {
  const tbody = document.getElementById("pbiInvCrosstabBody");
  if (!tbody || !data.rows) return;
  tbody.innerHTML = "";

  data.rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.service_band}</td>
      <td>${r.c_u18}</td>
      <td>${r.c_18_24}</td>
      <td>${r.c_25_34}</td>
      <td>${r.c_35_44}</td>
      <td>${r.c_45_54 || r.c_21_54 || "-"}</td>
      <td>${r.c_55_64}</td>
      <td>${r.c_65p}</td>
      <td style="font-weight: 700; color: #0078D4;">${r.total}</td>
    `;
    tbody.appendChild(tr);
  });
}


// ============================================================================
// LIFE ANNUITY: QUOTES & ACCEPTANCES (10-PAGE LIVE REPORTING ENGINE)
// ============================================================================

let annuityCachedSlicers = null;
let annuityConsultantsMasterList = [];
let annuityConsultantsPage = 1;
const ANNUITY_CONSULTANTS_PAGE_SIZE = 15;

let annuityLedgerMasterList = [];
let annuityLedgerPage = 1;
const ANNUITY_LEDGER_PAGE_SIZE = 25;

let annuityActiveData = null;

function initAnnuityReporting() {
  initAnnuitySubtabs();
  initAnnuitySlicers();
  initAnnuityControls();
}

// ── 1. Subtab Switching (10 Pages with Text Wrapping) ───────────────────────
function initAnnuitySubtabs() {
  const subtabButtons = document.querySelectorAll(".pbi-subtab-btn-wrap");
  const panes = {
    acceptances_over_time: { id: "annuityPaneOverview", title: "Acceptances over time" },
    ytd_figures: { id: "annuityPaneYtd", title: "YTD Quotes & Acceptances" },
    business_summary: { id: "annuityPaneBusinessSummary", title: "Business Summary" },
    top_consultants: { id: "annuityPaneTopConsultants", title: "Top Consultants: What do they sell?" },
    purchase_price_distribution: { id: "annuityPanePriceDistribution", title: "Purchase Price Distribution" },
    consultant_details: { id: "annuityPaneConsultantDetails", title: "Consultant Details" },
    detailed_ledger: { id: "annuityPaneDetailedLedger", title: "Transaction Ledger & Drillthrough Audit" },
    alexforbes: { id: "annuityPaneAlexforbes", title: "Alexforbes Summary" },
    graviton: { id: "annuityPaneGraviton", title: "Graviton Summary" },
    new_business_dc: { id: "annuityPaneDcNewBusiness", title: "SCInvest DC New Business" }
  };

  subtabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      subtabButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");

      const tabKey = btn.getAttribute("data-tab");
      currentAnnuityTab = tabKey;

      // Toggle display of panes
      Object.keys(panes).forEach(k => {
        const paneEl = document.getElementById(panes[k].id);
        if (paneEl) {
          paneEl.style.display = k === tabKey ? "block" : "none";
        }
      });

      // Update header title
      const headingEl = document.getElementById("annuityReportHeading");
      if (headingEl && panes[tabKey]) {
        headingEl.textContent = panes[tabKey].title;
      }

      fetchAnnuityData(tabKey);
    });
  });
}

// ── 2. Dynamic Cascading Slicers ────────────────────────────────────────────
function initAnnuitySlicers() {
  const slicerIds = [
    "annuitySlicerYear",
    "annuitySlicerDate",
    "annuitySlicerFund",
    "annuitySlicerBusiness",
    "annuitySlicerBusinessType",
    "annuitySlicerStatus"
  ];

  const handleAnnuitySlicerChange = debounce(async () => {
    // Trigger cascading update of options
    await refreshAnnuitySlicersCascading();
    syncFiltersCrossDashboard("annuity_reporting");
    // Refresh current active view
    fetchAnnuityData(currentAnnuityTab);
  }, 250);

  slicerIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("change", handleAnnuitySlicerChange);
    }
  });

  // Initial load of slicers from live DuckDB Parquet data
  refreshAnnuitySlicersCascading(true);
}

function getAnnuityCurrentFilters() {
  return {
    year: document.getElementById("annuitySlicerYear")?.value || "",
    date: document.getElementById("annuitySlicerDate")?.value || "",
    fund: document.getElementById("annuitySlicerFund")?.value || "",
    business: document.getElementById("annuitySlicerBusiness")?.value || "",
    business_type: document.getElementById("annuitySlicerBusinessType")?.value || "",
    status: document.getElementById("annuitySlicerStatus")?.value || ""
  };
}

async function refreshAnnuitySlicersCascading(isInitial = false) {
  try {
    const currentFilters = getAnnuityCurrentFilters();
    const params = new URLSearchParams();
    Object.entries(currentFilters).forEach(([k, v]) => {
      if (v && v !== "All" && v !== "All Years" && v !== "All Dates" && v !== "All Funds" && v !== "All Businesses" && v !== "All Types" && v !== "All Statuses") {
        params.append(k, v);
      }
    });

    const res = await fetch(`/api/annuity/slicers?${params.toString()}`);
    if (!res.ok) return;
    const slicers = await res.json();
    annuityCachedSlicers = slicers;

    populateSelect("annuitySlicerYear", slicers.years || [], currentFilters.year);
    populateSelect("annuitySlicerDate", slicers.dates || [], currentFilters.date);
    populateSelect("annuitySlicerFund", slicers.funds || [], currentFilters.fund);
    populateSelect("annuitySlicerBusiness", slicers.businesses || [], currentFilters.business);
    populateSelect("annuitySlicerBusinessType", slicers.business_types || [], currentFilters.business_type);
    populateSelect("annuitySlicerStatus", slicers.statuses || [], currentFilters.status);
  } catch (err) {
    console.error("Failed to load cascading slicers:", err);
  }
}

function populateSelect(selectId, items, selectedValue) {
  const select = document.getElementById(selectId);
  if (!select) return;

  const prevVal = selectedValue || select.value;
  select.innerHTML = "";

  items.forEach(val => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    if (val === prevVal) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });

  // If previous selection is no longer valid, default to first (usually 'All ...')
  if (!items.includes(prevVal) && items.length > 0) {
    select.selectedIndex = 0;
  }
}

// ── 3. Reset, Export & Pagination Controls ──────────────────────────────────
function initAnnuityControls() {
  // Reset slicers button
  const btnReset = document.getElementById("btnResetAnnuityFilters");
  if (btnReset) {
    btnReset.addEventListener("click", async () => {
      ["annuitySlicerYear", "annuitySlicerDate", "annuitySlicerFund", "annuitySlicerBusiness", "annuitySlicerBusinessType", "annuitySlicerStatus"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.selectedIndex = 0;
      });
      await refreshAnnuitySlicersCascading(true);
      fetchAnnuityData(currentAnnuityTab);
    });
  }

  // Export CSV button
  const btnExport = document.getElementById("btnExportAnnuityCsv");
  if (btnExport) {
    btnExport.addEventListener("click", () => exportAnnuityViewCsv());
  }

  // Consultant details search & pagination (Page 6)
  const searchConsultants = document.getElementById("annuitySearchConsultants");
  if (searchConsultants) {
    searchConsultants.addEventListener("input", () => {
      annuityConsultantsPage = 1;
      renderConsultantsTablePage();
    });
  }
  const btnPrevCons = document.getElementById("btnPrevConsultants");
  const btnNextCons = document.getElementById("btnNextConsultants");
  if (btnPrevCons) {
    btnPrevCons.addEventListener("click", () => {
      if (annuityConsultantsPage > 1) {
        annuityConsultantsPage--;
        renderConsultantsTablePage();
      }
    });
  }
  if (btnNextCons) {
    btnNextCons.addEventListener("click", () => {
      annuityConsultantsPage++;
      renderConsultantsTablePage();
    });
  }

  // Transaction Ledger search & pagination (Page 7)
  const searchLedger = document.getElementById("annuitySearchLedger");
  if (searchLedger) {
    searchLedger.addEventListener("input", () => {
      annuityLedgerPage = 1;
      renderLedgerTablePage();
    });
  }
  const btnPrevLedger = document.getElementById("btnPrevLedger");
  const btnNextLedger = document.getElementById("btnNextLedger");
  if (btnPrevLedger) {
    btnPrevLedger.addEventListener("click", () => {
      if (annuityLedgerPage > 1) {
        annuityLedgerPage--;
        renderLedgerTablePage();
      }
    });
  }
  if (btnNextLedger) {
    btnNextLedger.addEventListener("click", () => {
      annuityLedgerPage++;
      renderLedgerTablePage();
    });
  }
}

// ── 4. Main Query & KPI Dispatcher ──────────────────────────────────────────
async function fetchAnnuityData(tab) {
  setDashboardLoading("annuityReportingView", true);
  const t0 = performance.now();

  try {
    const filters = getAnnuityCurrentFilters();
    const params = new URLSearchParams({
      tab: tab || "acceptances_over_time",
      role: currentRole
    });

    Object.entries(filters).forEach(([k, v]) => {
      if (v && v !== "All" && v !== "All Years" && v !== "All Dates" && v !== "All Funds" && v !== "All Businesses" && v !== "All Types" && v !== "All Statuses") {
        params.append(k, v);
      }
    });

    const res = await fetch(`/api/annuity/query?${params.toString()}`);
    if (!res.ok) {
      console.error("Failed to fetch annuity query:", res.statusText);
      return;
    }

    const data = await res.json();
    annuityActiveData = data;

    const elapsed = data.execution_time_ms !== undefined ? data.execution_time_ms : Math.round(performance.now() - t0);
    updateFetchTelemetry(elapsed);

    // Update 9 KPI strip
    if (data.kpis) {
      updateAnnuityKpiStrip(data.kpis);
    }

    // Render tab-specific visuals
    switch (tab) {
      case "acceptances_over_time":
        renderAnnuityTimelineVisual(data.timeline);
        renderAnnuityBusinessByMonthVisual(data.business_by_month);
        break;
      case "ytd_figures":
        renderAnnuityYtdProgressionVisual(data.ytd_progression);
        renderAnnuityYtdProductsTable(data.products_table);
        break;
      case "business_summary":
        renderAnnuityBusinessSummaryVisual(data.business_summary);
        break;
      case "top_consultants":
        renderAnnuityTop20Visual(data.top_consultants_chart);
        renderAnnuityTop20Table(data.top_consultants_table);
        break;
      case "purchase_price_distribution":
        renderAnnuityBandsTable(data.bands_table);
        renderAnnuityHighValueTable(data.high_value_quotes);
        break;
      case "consultant_details":
        annuityConsultantsMasterList = data.consultants_table || [];
        annuityConsultantsPage = 1;
        renderConsultantsTablePage();
        break;
      case "detailed_ledger":
        annuityLedgerMasterList = data.ledger_table || [];
        annuityLedgerPage = 1;
        renderLedgerTablePage();
        break;
      case "alexforbes":
        renderAnnuityAlexforbesTable(data.alexforbes_table);
        break;
      case "graviton":
        renderAnnuityGravitonTable(data.graviton_table);
        break;
      case "new_business_dc":
        renderAnnuityDcNewBusinessTable(data.dc_new_business_table);
        break;
      default:
        break;
    }
  } catch (err) {
    console.error("Error in fetchAnnuityData:", err);
  } finally {
    setDashboardLoading("annuityReportingView", false);
  }
}

// ── 5. KPI Strip Updater ────────────────────────────────────────────────────
function updateAnnuityKpiStrip(kpis) {
  const setTxt = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val !== undefined && val !== null ? val : "--";
  };

  setTxt("annuityKpiQuotedMembers", kpis.quoted_members);
  setTxt("annuityKpiAcceptedMembers", kpis.accepted_members);
  setTxt("annuityKpiQuoteCount", kpis.quotation_count);
  setTxt("annuityKpiAcceptedQuotes", kpis.accepted_quotations);
  setTxt("annuityKpiQuotedPrice", kpis.quoted_purchase_price);
  setTxt("annuityKpiAcceptedPrice", kpis.accepted_purchase_price);
  setTxt("annuityKpiMemberConv", kpis.member_conversion_rate);
  setTxt("annuityKpiPriceConv", kpis.price_conversion_rate);
  setTxt("annuityKpiTopBusiness", kpis.top_business);
}

// ── 6. Visual Renderers (Pages 1 - 10) ──────────────────────────────────────

// Page 1 Visual A: Timeline (Bar + Line)
function renderAnnuityTimelineVisual(timeline) {
  if (!timeline || !timeline.dates || timeline.dates.length === 0) return;

  createOrUpdateChart("annuityTimeline", "chartAnnuityTimeline", {
    type: "bar",
    data: {
      labels: timeline.dates,
      datasets: [
        {
          type: "bar",
          label: "Quoted Price (R)",
          data: timeline.quoted_prices,
          backgroundColor: "#0075C9",
          borderRadius: 3,
          yAxisID: "y"
        },
        {
          type: "bar",
          label: "Accepted Price (R)",
          data: timeline.accepted_prices,
          backgroundColor: "#00205B",
          borderRadius: 3,
          yAxisID: "y"
        },
        {
          type: "line",
          label: "Member Conv. Rate %",
          data: timeline.conversion_rates,
          borderColor: "#FF8200",
          backgroundColor: "#FF8200",
          borderWidth: 2.5,
          tension: 0.25,
          pointRadius: 4,
          pointHoverRadius: 6,
          yAxisID: "y1"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              if (ctx.dataset.yAxisID === "y1") {
                return `${ctx.dataset.label}: ${ctx.raw.toFixed(1)}%`;
              }
              const val = ctx.raw;
              return `${ctx.dataset.label}: R ${(val / 1e6).toFixed(2)}M`;
            }
          }
        }
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          position: "left",
          ticks: {
            callback: v => `R ${(v / 1e6).toFixed(0)}M`,
            font: { size: 10 }
          },
          grid: { color: "rgba(0,0,0,0.06)" }
        },
        y1: {
          position: "right",
          min: 0,
          max: 100,
          ticks: { callback: v => `${v}%`, font: { size: 10 } },
          grid: { display: false }
        }
      }
    }
  });
}

// Page 1 Visual B: Accepted Purchase Price per Business by Month
function renderAnnuityBusinessByMonthVisual(bizMonth) {
  if (!bizMonth || !bizMonth.months) return;

  const colors = ["#0075C9", "#00205B", "#00B2A9", "#E05A47", "#8C827A", "#FFB612", "#5C768D"];
  const datasets = (bizMonth.series || []).map((s, idx) => ({
    label: s.name,
    data: s.data,
    backgroundColor: colors[idx % colors.length],
    borderRadius: 2
  }));

  createOrUpdateChart("annuityBusinessByMonth", "chartAnnuityBusinessByMonth", {
    type: "bar",
    data: {
      labels: bizMonth.months,
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: R ${(ctx.raw / 1e6).toFixed(2)}M`
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          stacked: true,
          ticks: { callback: v => `R ${(v / 1e6).toFixed(0)}M`, font: { size: 10 } },
          grid: { color: "rgba(0,0,0,0.06)" }
        }
      }
    }
  });
}

// Page 2: YTD Progression (Multi-Line)
function renderAnnuityYtdProgressionVisual(ytd) {
  if (!ytd || !ytd.months) return;

  createOrUpdateChart("annuityYtd", "chartAnnuityYtd", {
    type: "line",
    data: {
      labels: ytd.months,
      datasets: [
        {
          label: "Cumulative Quoted Price (R)",
          data: ytd.cum_quoted,
          borderColor: "#0075C9",
          backgroundColor: "rgba(0, 117, 201, 0.08)",
          fill: true,
          tension: 0.25,
          borderWidth: 2.5,
          pointRadius: 3
        },
        {
          label: "Cumulative Accepted Price (R)",
          data: ytd.cum_accepted,
          borderColor: "#00205B",
          backgroundColor: "rgba(0, 32, 91, 0.1)",
          fill: true,
          tension: 0.25,
          borderWidth: 2.5,
          pointRadius: 3
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: R ${(ctx.raw / 1e6).toFixed(2)}M`
          }
        }
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          ticks: { callback: v => `R ${(v / 1e6).toFixed(0)}M`, font: { size: 10 } },
          grid: { color: "rgba(0,0,0,0.06)" }
        }
      }
    }
  });
}

// Page 2: YTD Products Table
function renderAnnuityYtdProductsTable(products) {
  const tbody = document.querySelector("#tableAnnuityYtdProducts tbody");
  if (!tbody || !products) return;
  tbody.innerHTML = "";

  products.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${p.product_name}</strong></td>
      <td class="num-col">${Number(p.quote_count).toLocaleString()}</td>
      <td class="num-col">${Number(p.accepted_count).toLocaleString()}</td>
      <td class="num-col" style="font-weight: 600; color: #0075C9;">${p.conversion_rate}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 600;">${p.accepted_purchase_price}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Page 3: Business Summary Visual (Stacked Bar by Product)
function renderAnnuityBusinessSummaryVisual(summary) {
  if (!summary || !summary.businesses) return;

  const colors = ["#0075C9", "#00B2A9", "#00205B", "#FF8200", "#5C768D", "#8C827A", "#FFB612"];
  const datasets = (summary.series || []).map((s, idx) => ({
    label: s.name,
    data: s.data,
    backgroundColor: colors[idx % colors.length],
    borderRadius: 2
  }));

  createOrUpdateChart("annuityBusSummary", "chartAnnuityBusSummary", {
    type: "bar",
    data: {
      labels: summary.businesses,
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: R ${(ctx.raw / 1e6).toFixed(2)}M`
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 45 } },
        y: {
          stacked: true,
          ticks: { callback: v => `R ${(v / 1e6).toFixed(0)}M`, font: { size: 10 } },
          grid: { color: "rgba(0,0,0,0.06)" }
        }
      }
    }
  });
}

// Page 4: Top 20 Consultants 100% Stacked Horizontal Bar
function renderAnnuityTop20Visual(chartData) {
  if (!chartData || !chartData.consultants) return;

  const colors = ["#0075C9", "#00205B", "#00B2A9", "#FF8200", "#8C827A"];
  const datasets = (chartData.series || []).map((s, idx) => ({
    label: s.name,
    data: s.data,
    backgroundColor: colors[idx % colors.length],
    borderRadius: 2
  }));

  createOrUpdateChart("annuityTop20", "chartAnnuityTop20", {
    type: "bar",
    data: {
      labels: chartData.consultants,
      datasets: datasets
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", labels: { boxWidth: 12, font: { size: 10 } } },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(1)}%`
          }
        }
      },
      scales: {
        x: {
          stacked: true,
          min: 0,
          max: 100,
          ticks: { callback: v => `${v}%`, font: { size: 10 } },
          grid: { color: "rgba(0,0,0,0.06)" }
        },
        y: {
          stacked: true,
          grid: { display: false },
          ticks: { font: { size: 10 } }
        }
      }
    }
  });
}

// Page 4: Top 20 Consultants Leaderboard Table
function renderAnnuityTop20Table(top20) {
  const tbody = document.querySelector("#tableAnnuityTop20 tbody");
  if (!tbody || !top20) return;
  tbody.innerHTML = "";

  top20.forEach(c => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${c.consultant_name}</strong></td>
      <td><span class="status-pill status-active">${c.consultant_business}</span></td>
      <td class="num-col">${Number(c.quoted_members).toLocaleString()}</td>
      <td class="num-col">${Number(c.accepted_members).toLocaleString()}</td>
      <td class="num-col">${c.quoted_purchase_price}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 700; color: #00205B;">${c.accepted_purchase_price}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Page 5: Bands Table
function renderAnnuityBandsTable(bands) {
  const tbody = document.querySelector("#tableAnnuityBands tbody");
  if (!tbody || !bands) return;
  tbody.innerHTML = "";

  bands.forEach(b => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${b.price_band}</strong></td>
      <td class="num-col">${Number(b.quoted_members).toLocaleString()}</td>
      <td class="num-col">${Number(b.quote_count).toLocaleString()}</td>
      <td class="num-col">${Number(b.accepted_members).toLocaleString()}</td>
      <td class="num-col">${b.quoted_price}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 600;">${b.accepted_price}</td>
      <td class="num-col" style="font-weight: 700; color: #0075C9;">${b.member_conversion_rate}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Page 5: High Value Quotes Table (> R10M)
function renderAnnuityHighValueTable(quotes) {
  const tbody = document.querySelector("#tableAnnuityHighValue tbody");
  if (!tbody || !quotes) return;
  tbody.innerHTML = "";

  quotes.forEach(q => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${q.report_month || "-"}</td>
      <td>${q.source}</td>
      <td>${q.business}</td>
      <td>${q.business_type}</td>
      <td><strong>${q.quotation_number}</strong></td>
      <td><span class="status-pill status-completed">${q.status}</span></td>
      <td>${q.consultant_name}</td>
      <td style="font-family: 'Roboto Mono', monospace;">${q.member_id}</td>
      <td>${q.product_description}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 700; color: #00205B;">${q.purchase_price}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Page 6: Consultant Details with Search & Pagination
function renderConsultantsTablePage() {
  const tbody = document.querySelector("#tableAnnuityConsultants tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const query = (document.getElementById("annuitySearchConsultants")?.value || "").toLowerCase().trim();
  const filtered = annuityConsultantsMasterList.filter(c => {
    return (
      (c.consultant_name && c.consultant_name.toLowerCase().includes(query)) ||
      (c.business && c.business.toLowerCase().includes(query)) ||
      (c.team && c.team.toLowerCase().includes(query))
    );
  });

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / ANNUITY_CONSULTANTS_PAGE_SIZE));
  if (annuityConsultantsPage > totalPages) annuityConsultantsPage = totalPages;

  const startIdx = (annuityConsultantsPage - 1) * ANNUITY_CONSULTANTS_PAGE_SIZE;
  const pageRows = filtered.slice(startIdx, startIdx + ANNUITY_CONSULTANTS_PAGE_SIZE);

  pageRows.forEach(c => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${c.consultant_name}</strong></td>
      <td>${c.white_label || "-"}</td>
      <td>${c.business}</td>
      <td>${c.team}</td>
      <td class="num-col">${Number(c.quoted_members).toLocaleString()}</td>
      <td class="num-col">${Number(c.accepted_members).toLocaleString()}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 600;">${c.accepted_purchase_price}</td>
    `;
    tbody.appendChild(tr);
  });

  const countEl = document.getElementById("annuityConsultantsCount");
  if (countEl) {
    countEl.textContent = `Showing ${Math.min(startIdx + 1, total)} - ${Math.min(startIdx + pageRows.length, total)} of ${total} consultants`;
  }
  const pageIndicator = document.getElementById("pageIndicatorConsultants");
  if (pageIndicator) {
    pageIndicator.textContent = `Page ${annuityConsultantsPage} of ${totalPages}`;
  }
}

// Page 7: Transaction Ledger with Search & Pagination
function renderLedgerTablePage() {
  const tbody = document.querySelector("#tableAnnuityLedger tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const query = (document.getElementById("annuitySearchLedger")?.value || "").toLowerCase().trim();
  const filtered = annuityLedgerMasterList.filter(r => {
    return (
      (r.quotation_number && r.quotation_number.toLowerCase().includes(query)) ||
      (r.member_id && r.member_id.toLowerCase().includes(query)) ||
      (r.consultant_name && r.consultant_name.toLowerCase().includes(query)) ||
      (r.business && r.business.toLowerCase().includes(query))
    );
  });

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / ANNUITY_LEDGER_PAGE_SIZE));
  if (annuityLedgerPage > totalPages) annuityLedgerPage = totalPages;

  const startIdx = (annuityLedgerPage - 1) * ANNUITY_LEDGER_PAGE_SIZE;
  const pageRows = filtered.slice(startIdx, startIdx + ANNUITY_LEDGER_PAGE_SIZE);

  pageRows.forEach(r => {
    const tr = document.createElement("tr");
    const isAccepted = r.status === "Accepted";
    tr.innerHTML = `
      <td>${r.date || "-"}</td>
      <td><strong>${r.quotation_number}</strong></td>
      <td><span class="status-pill ${isAccepted ? 'status-completed' : 'status-active'}">${r.status}</span></td>
      <td style="font-family: 'Roboto Mono', monospace;">${r.member_id}</td>
      <td>${r.source}</td>
      <td>${r.white_label || "-"}</td>
      <td>${r.business}</td>
      <td>${r.team}</td>
      <td>${r.business_type}</td>
      <td>${r.consultant_id}</td>
      <td>${r.consultant_name}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 600;">${r.purchase_price}</td>
    `;
    tbody.appendChild(tr);
  });

  const countEl = document.getElementById("annuityLedgerCount");
  if (countEl) {
    countEl.textContent = `Showing ${Math.min(startIdx + 1, total)} - ${Math.min(startIdx + pageRows.length, total)} of ${total} quotations`;
  }
  const pageIndicator = document.getElementById("pageIndicatorLedger");
  if (pageIndicator) {
    pageIndicator.textContent = `Page ${annuityLedgerPage} of ${totalPages}`;
  }
}

// Page 8: Alexforbes Summary Table
function renderAnnuityAlexforbesTable(rows) {
  const tbody = document.querySelector("#tableAnnuityAlexforbes tbody");
  if (!tbody || !rows) return;
  tbody.innerHTML = "";

  rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${r.consultant_name}</strong></td>
      <td>${r.white_label || "-"}</td>
      <td>${r.business}</td>
      <td>${r.team}</td>
      <td>${r.products || "-"}</td>
      <td class="num-col">${Number(r.quoted_members).toLocaleString()}</td>
      <td class="num-col">${Number(r.accepted_members).toLocaleString()}</td>
      <td class="num-col">${r.quoted_price}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 600; color: #00205B;">${r.accepted_price}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Page 9: Graviton Summary Table
function renderAnnuityGravitonTable(rows) {
  const tbody = document.querySelector("#tableAnnuityGraviton tbody");
  if (!tbody || !rows) return;
  tbody.innerHTML = "";

  rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${r.consultant_name}</strong></td>
      <td>${r.white_label || "-"}</td>
      <td>${r.business}</td>
      <td>${r.team}</td>
      <td>${r.products || "-"}</td>
      <td class="num-col">${Number(r.quoted_members).toLocaleString()}</td>
      <td class="num-col">${Number(r.accepted_members).toLocaleString()}</td>
      <td class="num-col">${r.quoted_price}</td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 600; color: #00205B;">${r.accepted_price}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Page 10: SCInvest DC New Business Table
function renderAnnuityDcNewBusinessTable(rows) {
  const tbody = document.querySelector("#tableAnnuityDcNewBusiness tbody");
  if (!tbody || !rows) return;
  tbody.innerHTML = "";

  rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.business_type}</td>
      <td><strong>${r.business}</strong></td>
      <td>${r.team}</td>
      <td>${r.quotation_number}</td>
      <td>${r.fund_name}</td>
      <td><span class="status-pill status-completed">${r.status}</span></td>
      <td class="num-col" style="font-family: 'Roboto Mono', monospace; font-weight: 600;">${r.purchase_price}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ── 7. CSV Export Utility ───────────────────────────────────────────────────
function exportAnnuityViewCsv() {
  if (!annuityActiveData) {
    alert("No active data to export.");
    return;
  }

  let rows = [];
  let filename = `sanlam_annuity_${currentAnnuityTab}_${new Date().toISOString().slice(0, 10)}.csv`;

  // Select appropriate dataset based on current tab
  switch (currentAnnuityTab) {
    case "acceptances_over_time":
      if (annuityActiveData.timeline?.dates) {
        rows.push(["Date", "Quoted Price", "Accepted Price", "Member Conversion Rate %"]);
        annuityActiveData.timeline.dates.forEach((d, i) => {
          rows.push([d, annuityActiveData.timeline.quoted_prices[i], annuityActiveData.timeline.accepted_prices[i], annuityActiveData.timeline.conversion_rates[i]]);
        });
      }
      break;
    case "ytd_figures":
      if (annuityActiveData.products_table) {
        rows.push(["Product Name", "Quotation Count", "Accepted Count", "Conversion Rate", "Accepted Purchase Price"]);
        annuityActiveData.products_table.forEach(p => {
          rows.push([p.product_name, p.quote_count, p.accepted_count, p.conversion_rate, p.accepted_purchase_price]);
        });
      }
      break;
    case "top_consultants":
      if (annuityActiveData.top_consultants_table) {
        rows.push(["Consultant Name", "Business", "Quoted Members", "Accepted Members", "Quoted Price", "Accepted Price"]);
        annuityActiveData.top_consultants_table.forEach(c => {
          rows.push([c.consultant_name, c.consultant_business, c.quoted_members, c.accepted_members, c.quoted_purchase_price, c.accepted_purchase_price]);
        });
      }
      break;
    case "purchase_price_distribution":
      if (annuityActiveData.bands_table) {
        rows.push(["Price Band", "Quoted Members", "Quotation Count", "Accepted Members", "Quoted Price", "Accepted Price", "Conversion %"]);
        annuityActiveData.bands_table.forEach(b => {
          rows.push([b.price_band, b.quoted_members, b.quote_count, b.accepted_members, b.quoted_price, b.accepted_price, b.member_conversion_rate]);
        });
      }
      break;
    case "consultant_details":
      if (annuityConsultantsMasterList.length > 0) {
        rows.push(["Consultant Name", "White Label", "Business", "Team", "Quoted Members", "Accepted Members", "Accepted Price"]);
        annuityConsultantsMasterList.forEach(c => {
          rows.push([c.consultant_name, c.white_label, c.business, c.team, c.quoted_members, c.accepted_members, c.accepted_purchase_price]);
        });
      }
      break;
    case "detailed_ledger":
      if (annuityLedgerMasterList.length > 0) {
        rows.push(["Date", "Quotation Number", "Status", "Member ID", "Source", "White Label", "Business", "Team", "Business Type", "Consultant ID", "Consultant Name", "Purchase Price"]);
        annuityLedgerMasterList.forEach(r => {
          rows.push([r.date, r.quotation_number, r.status, r.member_id, r.source, r.white_label, r.business, r.team, r.business_type, r.consultant_id, r.consultant_name, r.purchase_price]);
        });
      }
      break;
    case "alexforbes":
      if (annuityActiveData.alexforbes_table) {
        rows.push(["Consultant Name", "White Label", "Business", "Team", "Products", "Quoted Members", "Accepted Members", "Quoted Price", "Accepted Price"]);
        annuityActiveData.alexforbes_table.forEach(r => {
          rows.push([r.consultant_name, r.white_label, r.business, r.team, r.products, r.quoted_members, r.accepted_members, r.quoted_price, r.accepted_price]);
        });
      }
      break;
    case "graviton":
      if (annuityActiveData.graviton_table) {
        rows.push(["Consultant Name", "White Label", "Business", "Team", "Products", "Quoted Members", "Accepted Members", "Quoted Price", "Accepted Price"]);
        annuityActiveData.graviton_table.forEach(r => {
          rows.push([r.consultant_name, r.white_label, r.business, r.team, r.products, r.quoted_members, r.accepted_members, r.quoted_price, r.accepted_price]);
        });
      }
      break;
    case "new_business_dc":
      if (annuityActiveData.dc_new_business_table) {
        rows.push(["Business Type", "Business", "Team", "Quotation Number", "Fund Name", "Status", "Purchase Price"]);
        annuityActiveData.dc_new_business_table.forEach(r => {
          rows.push([r.business_type, r.business, r.team, r.quotation_number, r.fund_name, r.status, r.purchase_price]);
        });
      }
      break;
    default:
      break;
  }

  if (rows.length === 0) {
    alert("No exportable rows found in current tab view.");
    return;
  }

  const csvContent = "data:text/csv;charset=utf-8," + rows.map(e => e.map(cell => `"${String(cell || '').replace(/"/g, '""')}"`).join(",")).join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/* ── 14. SysAdmin Platform & Cloud Telemetry Cockpit Module ─────────────── */

let cockpitPollingTimer = null;
let cockpitPollIntervalMs = 2000;
let chartCockpitCpuMemInstance = null;
let chartCockpitLatencyInstance = null;
let chartCockpitEnginesInstance = null;
let cockpitRawLlmBundle = null;
let cockpitRawLlmMarkdown = "";
let cockpitActiveModalTab = "markdown";

function initSysAdminCockpit() {
  initCockpitCharts();

  const selInterval = document.getElementById("cockpitRefreshInterval");
  if (selInterval) {
    selInterval.addEventListener("change", (e) => {
      cockpitPollIntervalMs = parseInt(e.target.value, 10);
      if (currentDashboard === "sysadmin_cockpit") {
        restartSysAdminPolling();
      }
    });
  }

  const btnRefresh = document.getElementById("btnCockpitRefresh");
  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => {
      fetchSysAdminOverview();
      fetchSysAdminExecutions();
      fetchSysAdminLogs();
      showCockpitToast("Telemetry snapshot refreshed");
    });
  }

  const btnOpenModal = document.getElementById("btnOpenLlmModal");
  if (btnOpenModal) {
    btnOpenModal.addEventListener("click", () => openLlmBundleModal());
  }

  const btnCloseModal = document.getElementById("btnCloseLlmModal");
  const modalOverlay = document.getElementById("llmModalOverlay");
  if (btnCloseModal) {
    btnCloseModal.addEventListener("click", () => closeLlmBundleModal());
  }
  if (modalOverlay) {
    modalOverlay.addEventListener("click", (e) => {
      if (e.target === modalOverlay) closeLlmBundleModal();
    });
  }

  const btnCopyQuick = document.getElementById("btnCopyQuickPrompt");
  if (btnCopyQuick) {
    btnCopyQuick.addEventListener("click", async () => {
      await copyLlmPromptDirect();
    });
  }

  const btnTabMd = document.getElementById("btnTabLlmMarkdown");
  const btnTabJson = document.getElementById("btnTabLlmJson");
  if (btnTabMd) {
    btnTabMd.addEventListener("click", () => {
      cockpitActiveModalTab = "markdown";
      btnTabMd.classList.add("active");
      if (btnTabJson) btnTabJson.classList.remove("active");
      renderLlmModalPreview();
    });
  }
  if (btnTabJson) {
    btnTabJson.addEventListener("click", () => {
      cockpitActiveModalTab = "json";
      btnTabJson.classList.add("active");
      if (btnTabMd) btnTabMd.classList.remove("active");
      renderLlmModalPreview();
    });
  }

  const btnDlJson = document.getElementById("btnDownloadJson");
  if (btnDlJson) {
    btnDlJson.addEventListener("click", () => downloadLlmFile("json"));
  }

  const btnDlMd = document.getElementById("btnDownloadMd");
  if (btnDlMd) {
    btnDlMd.addEventListener("click", () => downloadLlmFile("markdown"));
  }

  const btnCopyFromModal = document.getElementById("btnCopyPromptFromModal");
  if (btnCopyFromModal) {
    btnCopyFromModal.addEventListener("click", async () => {
      await copyLlmPromptDirect();
    });
  }

  const btnRefLogs = document.getElementById("btnRefreshLogs");
  if (btnRefLogs) {
    btnRefLogs.addEventListener("click", () => {
      fetchSysAdminLogs();
      showCockpitToast("Container logs refreshed");
    });
  }

  const ledgerSearch = document.getElementById("cockpitLedgerSearch");
  if (ledgerSearch) {
    ledgerSearch.addEventListener("input", debounce(() => fetchSysAdminExecutions(), 250));
  }

  const ledgerFilter = document.getElementById("cockpitLedgerFilter");
  if (ledgerFilter) {
    ledgerFilter.addEventListener("change", () => fetchSysAdminExecutions());
  }
}

function startSysAdminPolling() {
  stopSysAdminPolling();
  fetchSysAdminOverview();
  fetchSysAdminExecutions();
  fetchSysAdminLogs();

  if (cockpitPollIntervalMs > 0) {
    cockpitPollingTimer = setInterval(() => {
      if (currentDashboard === "sysadmin_cockpit") {
        fetchSysAdminOverview();
        fetchSysAdminExecutions();
      }
    }, cockpitPollIntervalMs);
  }
}

function stopSysAdminPolling() {
  if (cockpitPollingTimer) {
    clearInterval(cockpitPollingTimer);
    cockpitPollingTimer = null;
  }
}

function restartSysAdminPolling() {
  stopSysAdminPolling();
  startSysAdminPolling();
}

function initCockpitCharts() {
  // Chart 1: Real-Time CPU & Memory
  const ctxCpuMem = document.getElementById("chartCockpitCpuMem");
  if (ctxCpuMem) {
    chartCockpitCpuMemInstance = new Chart(ctxCpuMem.getContext("2d"), {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Process Memory (MB)",
            data: [],
            borderColor: "#0075C9",
            backgroundColor: "rgba(0, 117, 201, 0.1)",
            borderWidth: 2,
            fill: true,
            tension: 0.35,
            yAxisID: "yMemory"
          },
          {
            label: "Process CPU %",
            data: [],
            borderColor: "#F59E0B",
            backgroundColor: "transparent",
            borderWidth: 2,
            borderDash: [4, 4],
            tension: 0.35,
            yAxisID: "yCpu"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: { mode: "index", intersect: false }
        },
        scales: {
          x: { grid: { color: "#F1F5F9" }, ticks: { font: { size: 10 } } },
          yMemory: {
            type: "linear",
            position: "left",
            grid: { color: "#F1F5F9" },
            ticks: { callback: v => `${v} MB`, font: { size: 10 } }
          },
          yCpu: {
            type: "linear",
            position: "right",
            min: 0,
            max: 100,
            grid: { display: false },
            ticks: { callback: v => `${v}%`, font: { size: 10 } }
          }
        }
      }
    });
  }

  // Chart 2: Query Latency
  const ctxLatency = document.getElementById("chartCockpitLatency");
  if (ctxLatency) {
    chartCockpitLatencyInstance = new Chart(ctxLatency.getContext("2d"), {
      type: "bar",
      data: {
        labels: [],
        datasets: [{
          label: "Duration (ms)",
          data: [],
          backgroundColor: [],
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.raw} ms` } }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 9 }, maxRotation: 45 } },
          y: { grid: { color: "#F1F5F9" }, ticks: { callback: v => `${v}ms`, font: { size: 10 } } }
        }
      }
    });
  }

  // Chart 3: Engine Breakdown
  const ctxEngines = document.getElementById("chartCockpitEngines");
  if (ctxEngines) {
    chartCockpitEnginesInstance = new Chart(ctxEngines.getContext("2d"), {
      type: "doughnut",
      data: {
        labels: ["DuckDB Direct", "DuckDB Cache", "Cube.js Cloud Run"],
        datasets: [{
          data: [1, 1, 1],
          backgroundColor: ["#0075C9", "#10B981", "#7E22CE"],
          borderWidth: 2,
          borderColor: "#FFFFFF"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } }
        },
        cutout: "68%"
      }
    });
  }
}

async function fetchSysAdminOverview() {
  try {
    const res = await fetch("/api/telemetry/overview");
    if (!res.ok) return;
    const data = await res.json();

    const sys = data.system || {};
    const qa = data.query_analytics || {};
    const gcp = data.gcp || {};

    // 1. Update Headline KPI Cards
    const cloudRunPill = document.getElementById("cockpitCloudRunPill");
    if (cloudRunPill && gcp.cloud_run) {
      cloudRunPill.textContent = `Ready (${gcp.cloud_run.length}/${gcp.cloud_run.length})`;
    }
    const cubePingEl = document.getElementById("cockpitCubePing");
    if (cubePingEl && gcp.cube_ping) {
      cubePingEl.innerHTML = `Ping: <strong>${gcp.cube_ping.latency_ms} ms</strong>`;
      cubePingEl.style.color = gcp.cube_ping.status === "HEALTHY" ? "#00875A" : "#DC2626";
    }
    const memEl = document.getElementById("cockpitProcessMemory");
    if (memEl) memEl.textContent = `${sys.process_rss_mb || 0} MB (RSS)`;
    const cpuEl = document.getElementById("cockpitProcessCpu");
    if (cpuEl) cpuEl.textContent = `${sys.process_cpu_percent || 0}%`;
    const hostCpuEl = document.getElementById("cockpitHostCpu");
    if (hostCpuEl) hostCpuEl.textContent = `${sys.host_cpu_percent || 0}%`;
    const threadsEl = document.getElementById("cockpitThreads");
    if (threadsEl) threadsEl.textContent = sys.threads_count || 1;

    const cacheRatioEl = document.getElementById("cockpitCacheRatioBadge");
    if (cacheRatioEl) cacheRatioEl.textContent = `${qa.cache_hit_ratio_percent || 100}% Cache`;

    const avgLatEl = document.getElementById("cockpitAvgLatency");
    if (avgLatEl) avgLatEl.textContent = `${qa.avg_duration_ms || 0} ms avg`;
    const p50El = document.getElementById("cockpitP50");
    if (p50El) p50El.textContent = `${qa.p50_ms || 0}ms`;
    const p95El = document.getElementById("cockpitP95");
    if (p95El) p95El.textContent = `${qa.p95_ms || 0}ms`;
    const p99El = document.getElementById("cockpitP99");
    if (p99El) p99El.textContent = `${qa.p99_ms || 0}ms`;

    const totQEl = document.getElementById("cockpitTotalQueries");
    if (totQEl) totQEl.textContent = qa.total_queries || 0;
    const upEl = document.getElementById("cockpitUptime");
    if (upEl) upEl.textContent = sys.uptime_formatted || "--";

    // 2. Update Real-Time Chart 1: CPU & Memory Timeline
    if (chartCockpitCpuMemInstance && data.metrics_history) {
      const history = data.metrics_history;
      chartCockpitCpuMemInstance.data.labels = history.map(h => h.timestamp);
      chartCockpitCpuMemInstance.data.datasets[0].data = history.map(h => h.process_rss_mb);
      chartCockpitCpuMemInstance.data.datasets[1].data = history.map(h => h.process_cpu_percent);
      chartCockpitCpuMemInstance.update("none");
    }

    // 3. Update Chart 2: Latency distribution
    if (chartCockpitLatencyInstance && data.recent_queries) {
      const recent = data.recent_queries.slice(0, 16).reverse();
      chartCockpitLatencyInstance.data.labels = recent.map(q => q.tab.length > 10 ? q.tab.slice(0, 8) + '..' : q.tab);
      chartCockpitLatencyInstance.data.datasets[0].data = recent.map(q => q.duration_ms);
      chartCockpitLatencyInstance.data.datasets[0].backgroundColor = recent.map(q => {
        if (q.duration_ms < 50) return "#10B981";
        if (q.duration_ms < 500) return "#0075C9";
        if (q.duration_ms < 1500) return "#F59E0B";
        return "#EF4444";
      });
      chartCockpitLatencyInstance.update("none");
    }

    // 4. Update Chart 3: Engine breakdown
    if (chartCockpitEnginesInstance && qa.engine_counts) {
      const counts = qa.engine_counts;
      chartCockpitEnginesInstance.data.datasets[0].data = [
        counts["DuckDB-Direct"] || 0,
        counts["DuckDB-Cached"] || 0,
        counts["Cube.js-CloudRun"] || 0
      ];
      chartCockpitEnginesInstance.update("none");
    }
  } catch (err) {
    console.warn("Error fetching SysAdmin overview:", err);
  }
}

async function fetchSysAdminExecutions() {
  try {
    const filterEl = document.getElementById("cockpitLedgerFilter");
    const searchEl = document.getElementById("cockpitLedgerSearch");
    const selectedDashboard = filterEl ? filterEl.value : "all";
    const searchQuery = searchEl ? searchEl.value.trim().toLowerCase() : "";

    const res = await fetch(`/api/telemetry/executions?limit=60&dashboard=${selectedDashboard}`);
    if (!res.ok) return;
    let queries = await res.json();

    if (searchQuery) {
      queries = queries.filter(q => 
        (q.tab && q.tab.toLowerCase().includes(searchQuery)) ||
        (q.dashboard && q.dashboard.toLowerCase().includes(searchQuery)) ||
        (q.engine && q.engine.toLowerCase().includes(searchQuery)) ||
        (q.sql_summary && q.sql_summary.toLowerCase().includes(searchQuery))
      );
    }

    const tbody = document.getElementById("cockpitLedgerBody");
    const countEl = document.getElementById("cockpitLedgerCount");
    if (countEl) countEl.textContent = `${queries.length} logged`;
    if (!tbody) return;

    if (queries.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #94A3B8; padding: 24px;">No query executions logged yet. Interacting with dashboard slicers and tabs will stream live rows here.</td></tr>`;
      return;
    }

    tbody.innerHTML = queries.map(q => {
      const isCached = q.cache_status === "HIT" || (q.engine && q.engine.includes("Cached"));
      const durBadge = q.duration_ms < 50 ? "badge-green" : (q.duration_ms < 500 ? "badge-blue" : (q.duration_ms < 1500 ? "badge-amber" : "badge-red"));
      const filterSummary = q.filters && Object.keys(q.filters).length > 0
        ? Object.entries(q.filters).slice(0, 3).map(([k, v]) => `${k}=${v}`).join(", ")
        : "None (Default)";

      return `<tr>
        <td style="font-family: 'Roboto Mono', monospace; font-size: 11px;">${q.timestamp}</td>
        <td><span class="cockpit-badge badge-blue">${q.dashboard}</span></td>
        <td style="font-weight: 600; color: #00205B;">${q.tab}</td>
        <td><span class="cockpit-badge ${isCached ? 'badge-green' : 'badge-purple'}">${q.engine}</span></td>
        <td class="num-col"><span class="cockpit-badge ${durBadge}">${q.duration_ms}ms</span></td>
        <td class="num-col">${q.memory_rss_mb} MB</td>
        <td><span class="cockpit-badge ${isCached ? 'badge-green' : 'badge-amber'}">${q.cache_status}</span></td>
        <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; font-size: 11px; color: #64748B;" title="${JSON.stringify(q.filters || {})}">
          ${filterSummary}
        </td>
      </tr>`;
    }).join("");
  } catch (err) {
    console.warn("Error fetching SysAdmin executions:", err);
  }
}

async function fetchSysAdminLogs() {
  try {
    const res = await fetch("/api/telemetry/cloud");
    if (!res.ok) return;
    const data = await res.json();
    const terminal = document.getElementById("cockpitLogTerminal");
    if (!terminal) return;

    const logs = data.logs || [];
    terminal.innerHTML = logs.map(l => {
      let sevClass = "terminal-info";
      if (l.severity === "WARNING" || l.severity === "WARN") sevClass = "terminal-warn";
      if (l.severity === "ERROR" || l.severity === "CRITICAL") sevClass = "terminal-err";
      return `<div class="terminal-line"><span class="terminal-time">[${l.timestamp}]</span> <span class="${sevClass}">[${l.severity}]</span> ${escapeHtml(l.message)}</div>`;
    }).join("");

    terminal.scrollTop = terminal.scrollHeight;
  } catch (err) {
    console.warn("Error fetching SysAdmin container logs:", err);
  }
}

async function openLlmBundleModal() {
  const overlay = document.getElementById("llmModalOverlay");
  if (overlay) overlay.style.display = "flex";

  const preview = document.getElementById("llmBundlePreview");
  if (preview) preview.textContent = "Bundling live platform telemetry, GCP specifications, and generating LLM prompt...";

  try {
    const [resJson, resMd] = await Promise.all([
      fetch("/api/telemetry/export-bundle"),
      fetch("/api/telemetry/export-markdown")
    ]);
    cockpitRawLlmBundle = await resJson.json();
    cockpitRawLlmMarkdown = await resMd.text();
    renderLlmModalPreview();
  } catch (err) {
    if (preview) preview.textContent = "Failed to bundle diagnostic telemetry: " + err;
  }
}

function closeLlmBundleModal() {
  const overlay = document.getElementById("llmModalOverlay");
  if (overlay) overlay.style.display = "none";
}

function renderLlmModalPreview() {
  const preview = document.getElementById("llmBundlePreview");
  if (!preview) return;

  if (cockpitActiveModalTab === "markdown") {
    preview.textContent = cockpitRawLlmMarkdown || "Loading markdown...";
  } else {
    preview.textContent = cockpitRawLlmBundle ? JSON.stringify(cockpitRawLlmBundle, null, 2) : "Loading JSON...";
  }
}

async function copyLlmPromptDirect() {
  try {
    let contentToCopy = cockpitRawLlmMarkdown;
    if (!contentToCopy) {
      const res = await fetch("/api/telemetry/export-markdown");
      contentToCopy = await res.text();
      cockpitRawLlmMarkdown = contentToCopy;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(contentToCopy);
    } else {
      const ta = document.createElement("textarea");
      ta.value = contentToCopy;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    showCockpitToast("✓ LLM Diagnostic Bundle & Prompt copied to clipboard!");
  } catch (err) {
    alert("Could not copy prompt: " + err);
  }
}

function downloadLlmFile(format) {
  let content = "";
  let filename = "";
  let type = "";

  if (format === "json") {
    content = JSON.stringify(cockpitRawLlmBundle || {}, null, 2);
    filename = `sanlam_platform_diagnostic_bundle_${new Date().toISOString().slice(0, 10)}.json`;
    type = "application/json";
  } else {
    content = cockpitRawLlmMarkdown || "";
    filename = `sanlam_platform_diagnostic_bundle_${new Date().toISOString().slice(0, 10)}.md`;
    type = "text/markdown";
  }

  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showCockpitToast(`Downloaded ${filename}`);
}

function showCockpitToast(message) {
  const existing = document.querySelector(".cockpit-toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.className = "cockpit-toast";
  toast.innerHTML = `<span>⚡</span><span>${message}</span>`;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = "opacity 0.3s ease, transform 0.3s ease";
    toast.style.opacity = "0";
    toast.style.transform = "translateY(20px)";
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}


