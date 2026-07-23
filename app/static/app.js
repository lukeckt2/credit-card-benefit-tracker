const activeBody = document.querySelector("#active-body");
const dueBody = document.querySelector("#due-body");
const activeCount = document.querySelector("#active-count");
const dueCount = document.querySelector("#due-count");
const asOfLabel = document.querySelector("#as-of");
const errorBox = document.querySelector("#error");
const noticeBox = document.querySelector("#notice");
const refreshButton = document.querySelector("#refresh");
const themeToggleButton = document.querySelector("#theme-toggle");
const dashboardTab = document.querySelector("#dashboard-tab");
const cardTabs = document.querySelector("#card-tabs");
const dashboardView = document.querySelector("#dashboard-view");
const cardView = document.querySelector("#card-view");
const cardDetail = document.querySelector("#card-detail");

const currencyFormatter = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});
const numberFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 2,
});
const integerFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
});

const unitLabels = {
  usd_credit: "USD",
  spend_to_goal_usd: "Spend",
  miles: "Miles",
  cert: "Cert",
};

const cycleOrder = [
  "monthly",
  "quarterly",
  "semiannual",
  "annual",
  "membership_year",
  "anniversary",
  "cert",
  "multi_year",
];

const cycleLabels = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  semiannual: "Semi-Annual",
  annual: "Annual",
  membership_year: "Membership Year",
  anniversary: "Anniversary",
  cert: "Certificate",
  multi_year: "Multi-Year",
};

const millisecondsPerDay = 24 * 60 * 60 * 1000;

let cards = [];
const cardDetails = new Map();

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function showNotice(message) {
  noticeBox.textContent = message;
  noticeBox.hidden = false;
}

function clearNotice() {
  noticeBox.hidden = true;
  noticeBox.textContent = "";
}

window.addEventListener("error", (event) => {
  if (event.message) showError(`Frontend error: ${event.message}`);
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  const message = reason && reason.message ? reason.message : String(reason || "Unknown frontend error.");
  showError(`Frontend error: ${message}`);
});

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

function replaceChildrenCompat(element) {
  while (element.firstChild) {
    element.removeChild(element.firstChild);
  }

  for (let index = 1; index < arguments.length; index += 1) {
    const child = arguments[index];
    if (child === null || child === undefined) continue;
    element.appendChild(child);
  }
}

function formatCycle(value) {
  if (!value) return "-";
  return String(value)
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function cycleLabel(value) {
  return cycleLabels[value] || formatCycle(value);
}

function formatAmount(value, unit) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);

  if (unit === "usd_credit") return currencyFormatter.format(number);
  if (unit === "spend_to_goal_usd") return currencyFormatter.format(number);
  if (unit === "miles") return integerFormatter.format(number);
  if (unit === "cert") return numberFormatter.format(number);
  return numberFormatter.format(number);
}

function formatUsedInput(value) {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return Number.isInteger(number) ? String(number) : String(number);
}

function parseIsoDate(value) {
  if (!value) return null;
  const parts = String(value).split("-").map((part) => Number(part));
  if (parts.length !== 3 || parts.some((part) => !Number.isInteger(part))) return null;
  return new Date(parts[0], parts[1] - 1, parts[2]);
}

function daysUntilDate(value) {
  const target = parseIsoDate(value);
  if (!target) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / millisecondsPerDay);
}

function deadlineText(days) {
  if (days === null || days === undefined || days === "") return "No date";
  const number = Number(days);
  if (!Number.isFinite(number)) return "No date";
  if (number < 0) return `Overdue ${Math.abs(number)}d`;
  if (number === 0) return "Today";
  return `${number}d`;
}

function urgency(row) {
  const rawDays = row.days_until_deadline;
  const days = rawDays === null || rawDays === undefined ? Number.NaN : Number(rawDays);
  if (!Number.isFinite(days) || days > 45) {
    return { level: "green", label: deadlineText(days) };
  }
  if (days > 14) {
    return { level: "orange", label: deadlineText(days) };
  }
  return { level: "red", label: deadlineText(days) };
}

function periodStatusVisual(period) {
  if (period.status === "pending") {
    return urgency({ days_until_deadline: daysUntilDate(period.deadline) });
  }
  if (period.status === "completed") return { level: "green", label: "Completed" };
  if (period.status === "expired") return { level: "red", label: "Expired" };
  if (period.status === "skipped") return { level: "orange", label: "Skipped" };
  return { level: "green", label: formatCycle(period.status) };
}

function sectionByKey(data, key) {
  if (!data || !Array.isArray(data.sections)) return { key, title: key, rows: [] };
  return data.sections.find((section) => section.key === key) || { key, title: key, rows: [] };
}

async function readErrorMessage(response) {
  let fallback = `Request failed: ${response.status}`;
  if (response.statusText) fallback += ` ${response.statusText}`;

  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((item) => {
          const location = Array.isArray(item.loc) ? `${item.loc.join(".")}: ` : "";
          return `${location}${item.msg || JSON.stringify(item)}`;
        })
        .join("; ");
    }
    if (data.detail) return JSON.stringify(data.detail);
    return JSON.stringify(data);
  } catch (error) {
    return fallback;
  }
}

async function fetchJson(url, options) {
  const response = await fetch(url, options || {});
  if (!response.ok) throw new Error(await readErrorMessage(response));
  return response.json();
}

function emptyRow(message, colspan) {
  const row = document.createElement("tr");
  row.innerHTML = `<td colspan="${escapeHtml(colspan || 8)}" class="empty-cell">${escapeHtml(message)}</td>`;
  return row;
}

function cardHash(cardId, periodId) {
  const base = `#card-${encodeURIComponent(cardId)}`;
  if (periodId === null || periodId === undefined || periodId === "") return base;
  return `${base}-period-${encodeURIComponent(periodId)}`;
}

function routeFromHash(hash) {
  const value = hash || window.location.hash || "#dashboard";
  const match = /^#card-(\d+)(?:-period-(\d+))?$/.exec(value);
  if (!match) return { type: "dashboard" };
  return {
    type: "card",
    cardId: Number(match[1]),
    periodId: match[2] ? Number(match[2]) : null,
  };
}

function syncActiveTab(route) {
  const currentRoute = route || routeFromHash();
  const dashboardActive = currentRoute.type === "dashboard";
  dashboardTab.classList.toggle("is-active", dashboardActive);
  if (dashboardActive) dashboardTab.setAttribute("aria-current", "page");
  else dashboardTab.removeAttribute("aria-current");

  cardTabs.querySelectorAll(".tab-link").forEach((tab) => {
    const isActive = currentRoute.type === "card" && Number(tab.dataset.cardId) === currentRoute.cardId;
    tab.classList.toggle("is-active", isActive);
    if (isActive) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });

  cardTabs.querySelectorAll(".issuer-group").forEach((group) => {
    const hasActiveCard = Boolean(group.querySelector(".tab-link.is-active"));
    group.classList.toggle("has-active-card", hasActiveCard);
    if (hasActiveCard) group.open = true;
  });
}

function showDashboardView() {
  dashboardView.hidden = false;
  cardView.hidden = true;
  syncActiveTab({ type: "dashboard" });
}

function showCardView(cardId) {
  dashboardView.hidden = true;
  cardView.hidden = false;
  syncActiveTab({ type: "card", cardId: Number(cardId), periodId: null });
}

function cardDisplayName(card) {
  return card.display_name || card.card_name || `Card ${card.card_id}`;
}

function cardIssuerName(card) {
  return card.issuer || "Unknown Bank";
}

function groupedCardsByIssuer() {
  const groups = new Map();
  cards.forEach((card) => {
    const issuer = cardIssuerName(card);
    if (!groups.has(issuer)) groups.set(issuer, []);
    groups.get(issuer).push(card);
  });
  return Array.from(groups.entries()).sort(([leftIssuer], [rightIssuer]) => leftIssuer.localeCompare(rightIssuer));
}

function benefitLink(row) {
  return cardHash(row.card_id, row.period_id);
}

function benefitRow(row) {
  const tr = document.createElement("tr");
  const status = urgency(row);
  const unit = unitLabels[row.unit] ? `<span class="unit-label">${escapeHtml(unitLabels[row.unit])}</span>` : "";
  const href = escapeHtml(benefitLink(row));

  tr.className = "dashboard-record";
  tr.dataset.cardId = row.card_id;
  tr.dataset.periodId = row.period_id;
  tr.innerHTML = `
    <td data-label="Status">
      <span class="status-dot status-${status.level}" aria-hidden="true"></span>
      <span class="status-text">${escapeHtml(status.label)}</span>
    </td>
    <td class="card-name" data-label="Card Name"><a class="record-link" href="${href}">${escapeHtml(row.card_name)}</a></td>
    <td class="benefit-name" data-label="Coupon/Benefit"><a class="record-link" href="${href}">${escapeHtml(row.benefit_name)}</a></td>
    <td data-label="Type">${escapeHtml(formatCycle(row.cycle_type))}</td>
    <td class="numeric" data-label="Total">${escapeHtml(formatAmount(row.amount_total, row.unit))} ${unit}</td>
    <td class="numeric used-column" data-label="Used">
      <form class="used-form" data-period-id="${escapeHtml(row.period_id)}" data-card-id="${escapeHtml(row.card_id)}" data-note="Updated from dashboard Used column">
        <input name="current_used_amount" type="text" inputmode="decimal" autocomplete="off" value="${escapeHtml(formatUsedInput(row.amount_used))}" aria-label="Used amount for ${escapeHtml(row.benefit_name)}" />
        <button type="submit">Save</button>
      </form>
    </td>
    <td class="numeric remaining-cell" data-label="Remaining">${escapeHtml(formatAmount(row.amount_remaining, row.unit))} ${unit}</td>
    <td data-label="Deadline" class="deadline-col"><strong>${escapeHtml(row.deadline)}</strong><span class="period-key">${escapeHtml(row.period_key)}</span></td>
  `;
  return tr;
}

function renderTable(section, body, countElement, emptyMessage) {
  const rows = Array.isArray(section.rows) ? section.rows : [];
  const fragment = document.createDocumentFragment();
  countElement.textContent = `${rows.length} benefit${rows.length === 1 ? "" : "s"}`;

  if (!rows.length) {
    fragment.appendChild(emptyRow(emptyMessage));
  } else {
    rows.forEach((row) => fragment.appendChild(benefitRow(row)));
  }

  replaceChildrenCompat(body, fragment);
}

async function loadDashboard(options) {
  const keepNotice = options && options.keepNotice;
  clearError();
  if (!keepNotice) clearNotice();
  refreshButton.disabled = true;
  activeCount.textContent = "Loading...";
  dueCount.textContent = "Loading...";
  replaceChildrenCompat(activeBody, emptyRow("Loading current benefits..."));
  replaceChildrenCompat(dueBody, emptyRow("Loading 45-day due benefits..."));

  try {
    const data = await fetchJson("/api/dashboard");
    asOfLabel.textContent = data.as_of || "-";
    renderTable(
      sectionByKey(data, "active_current"),
      activeBody,
      activeCount,
      "No active current benefits.",
    );
    renderTable(
      sectionByKey(data, "due_within_45_days"),
      dueBody,
      dueCount,
      "No active benefits due in the next 45 days.",
    );
  } catch (error) {
    activeCount.textContent = "Load failed";
    dueCount.textContent = "Load failed";
    replaceChildrenCompat(activeBody, emptyRow("Unable to load dashboard."));
    replaceChildrenCompat(dueBody, emptyRow("Unable to load dashboard."));
    showError(error.message || "Unable to load dashboard.");
  } finally {
    refreshButton.disabled = false;
  }
}

function renderCardTabs() {
  const fragment = document.createDocumentFragment();

  if (!cards.length) {
    const empty = document.createElement("span");
    empty.className = "tab-empty muted";
    empty.textContent = "No cards found.";
    fragment.appendChild(empty);
  } else {
    groupedCardsByIssuer().forEach(([issuer, issuerCards]) => {
      const group = document.createElement("details");
      const summary = document.createElement("summary");
      const issuerName = document.createElement("span");
      const issuerCount = document.createElement("span");
      const list = document.createElement("div");

      group.className = "issuer-group";
      summary.className = "issuer-summary";
      issuerName.className = "issuer-name";
      issuerCount.className = "issuer-count";
      list.className = "issuer-card-list";
      list.setAttribute("aria-label", `${issuer} cards`);

      issuerName.textContent = issuer;
      issuerCount.textContent = `${issuerCards.length} card${issuerCards.length === 1 ? "" : "s"}`;
      summary.appendChild(issuerName);
      summary.appendChild(issuerCount);
      group.appendChild(summary);

      issuerCards.forEach((card) => {
        const link = document.createElement("a");
        link.className = "tab-link";
        link.href = cardHash(card.card_id);
        link.dataset.cardId = card.card_id;
        link.textContent = cardDisplayName(card);
        list.appendChild(link);
      });

      group.appendChild(list);
      fragment.appendChild(group);
    });
  }

  replaceChildrenCompat(cardTabs, fragment);
  syncActiveTab();
}

async function loadCards() {
  try {
    const data = await fetchJson("/api/cards?include_inactive=true");
    cards = Array.isArray(data.cards) ? data.cards : [];
    renderCardTabs();
  } catch (error) {
    cards = [];
    renderCardTabs();
    showError(error.message || "Unable to load card tabs.");
  }
}

function cycleSortIndex(cycleType) {
  const index = cycleOrder.indexOf(cycleType);
  return index === -1 ? cycleOrder.length : index;
}

function periodSortValue(period) {
  return `${period.deadline || "9999-12-31"}|${period.period_start || ""}|${period.period_key || ""}`;
}

function sortedPeriods(periods) {
  return (Array.isArray(periods) ? periods.slice() : []).sort((left, right) =>
    periodSortValue(left).localeCompare(periodSortValue(right)),
  );
}

function sortedDefinitions(definitions) {
  return (Array.isArray(definitions) ? definitions.slice() : []).sort((left, right) => {
    const cycleDifference = cycleSortIndex(left.cycle_type) - cycleSortIndex(right.cycle_type);
    if (cycleDifference !== 0) return cycleDifference;
    return String(left.name || "").localeCompare(String(right.name || ""));
  });
}

function groupDefinitions(definitions) {
  const groups = new Map();
  sortedDefinitions(definitions).forEach((definition) => {
    const key = definition.cycle_type || "other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(definition);
  });
  return Array.from(groups.entries());
}

function cardOpenDateText(card) {
  if (card.open_date) return card.open_date;
  if (card.open_month && card.open_day) return `${card.open_month}/${card.open_day}`;
  return "-";
}

function cardSourceLink(card) {
  if (!card.source_url) return "-";
  return `<a class="inline-link" href="${escapeHtml(card.source_url)}" target="_blank" rel="noreferrer">Source</a>`;
}

function cardSummaryItems(card, definitionCount, periodCount) {
  const items = [
    ["Issuer", card.issuer || "-"],
    ["Annual Fee", formatAmount(card.annual_fee, "usd_credit")],
    ["Status", formatCycle(card.status)],
    ["Open Date", cardOpenDateText(card)],
    ["Benefits", definitionCount],
    ["Periods", periodCount],
  ];
  return items
    .map(
      ([label, value]) => `
        <div class="summary-item">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `,
    )
    .join("");
}

function cardPeriodRow(period, definition, cardId) {
  const row = document.createElement("tr");
  const visual = periodStatusVisual(period);
  const unit = unitLabels[definition.unit] ? `<span class="unit-label">${escapeHtml(unitLabels[definition.unit])}</span>` : "";
  const days = daysUntilDate(period.deadline);
  const pendingDeadlineText = period.status === "pending" ? `<span class="period-key">${escapeHtml(deadlineText(days))}</span>` : "";

  row.id = `period-${period.benefit_period_id}`;
  row.className = `card-period-row period-status-${escapeHtml(period.status)}`;
  row.dataset.periodId = period.benefit_period_id;
  if (period.status !== "pending") row.classList.add("is-muted");
  row.innerHTML = `
    <td data-label="Status">
      <span class="status-dot status-${visual.level}" aria-hidden="true"></span>
      <span class="status-text">${escapeHtml(visual.label)}</span>
      ${pendingDeadlineText}
    </td>
    <td data-label="Period"><strong>${escapeHtml(period.period_key)}</strong><span class="period-key">${escapeHtml(period.period_start)} to ${escapeHtml(period.period_end)}</span></td>
    <td data-label="Deadline" class="deadline-col"><strong>${escapeHtml(period.deadline)}</strong></td>
    <td class="numeric" data-label="Total">${escapeHtml(formatAmount(period.amount_total, definition.unit))} ${unit}</td>
    <td class="numeric used-column" data-label="Used">
      <form class="used-form" data-period-id="${escapeHtml(period.benefit_period_id)}" data-card-id="${escapeHtml(cardId)}" data-note="Updated from card tab Used column">
        <input name="current_used_amount" type="text" inputmode="decimal" autocomplete="off" value="${escapeHtml(formatUsedInput(period.amount_used))}" aria-label="Used amount for ${escapeHtml(definition.name)} ${escapeHtml(period.period_key)}" />
        <button type="submit">Save</button>
      </form>
    </td>
    <td class="numeric remaining-cell" data-label="Remaining">${escapeHtml(formatAmount(period.amount_remaining, definition.unit))} ${unit}</td>
  `;
  return row;
}

function renderBenefitCard(definition, cardId) {
  const article = document.createElement("article");
  const periods = sortedPeriods(definition.periods);
  article.className = `card-benefit${definition.active ? "" : " is-inactive"}`;
  article.innerHTML = `
    <div class="benefit-heading">
      <div>
        <h4>${escapeHtml(definition.name)}</h4>
        <p class="muted">${escapeHtml(periods.length)} period${periods.length === 1 ? "" : "s"}</p>
      </div>
      <span class="benefit-status ${definition.active ? "active" : "inactive"}">${definition.active ? "Active" : "Inactive"}</span>
    </div>
    <div class="table-wrap card-table-wrap">
      <table class="benefit-table card-period-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Period</th>
            <th>Deadline</th>
            <th class="numeric">Total</th>
            <th class="numeric used-column">Used</th>
            <th class="numeric">Remaining</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  `;

  const body = article.querySelector("tbody");
  if (!periods.length) {
    body.appendChild(emptyRow("No periods for this benefit yet.", 6));
  } else {
    periods.forEach((period) => body.appendChild(cardPeriodRow(period, definition, cardId)));
  }
  return article;
}

function renderCycleGroup(cycleType, definitions, cardId) {
  const section = document.createElement("section");
  const periodCount = definitions.reduce(
    (total, definition) => total + (Array.isArray(definition.periods) ? definition.periods.length : 0),
    0,
  );
  section.className = "cycle-section";
  section.innerHTML = `
    <div class="cycle-heading">
      <div>
        <p class="eyebrow">${escapeHtml(cycleLabel(cycleType))}</p>
        <h3>${escapeHtml(cycleLabel(cycleType))}</h3>
      </div>
      <p class="muted">${escapeHtml(definitions.length)} benefit${definitions.length === 1 ? "" : "s"}, ${escapeHtml(periodCount)} period${periodCount === 1 ? "" : "s"}</p>
    </div>
    <div class="card-benefit-list"></div>
  `;
  const list = section.querySelector(".card-benefit-list");
  definitions.forEach((definition) => list.appendChild(renderBenefitCard(definition, cardId)));
  return section;
}

function highlightPeriodRow(periodId) {
  if (!periodId) return;
  const row = cardDetail.querySelector(`[data-period-id="${periodId}"]`);
  if (!row) return;
  row.classList.add("linked-highlight");
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => row.classList.remove("linked-highlight"), 2600);
}

function renderCardDetail(card, highlightPeriodId) {
  const definitions = Array.isArray(card.benefit_definitions) ? card.benefit_definitions : [];
  const periodCount = definitions.reduce(
    (total, definition) => total + (Array.isArray(definition.periods) ? definition.periods.length : 0),
    0,
  );

  cardDetail.innerHTML = `
    <div class="card-summary-header">
      <div>
        <p class="eyebrow">${escapeHtml(card.issuer || "Credit Card")}</p>
        <h2>${escapeHtml(cardDisplayName(card))}</h2>
        <p class="muted">${escapeHtml(card.card_name || cardDisplayName(card))}</p>
      </div>
      <div class="card-source">${cardSourceLink(card)}</div>
    </div>
    <div class="summary-grid">
      ${cardSummaryItems(card, definitions.length, periodCount)}
    </div>
    <div id="card-cycle-sections" class="card-cycle-sections"></div>
  `;

  const sections = cardDetail.querySelector("#card-cycle-sections");
  const groups = groupDefinitions(definitions);
  if (!groups.length) {
    sections.innerHTML = `<p class="muted empty-card-detail">No benefit definitions found for this card.</p>`;
  } else {
    groups.forEach(([cycleType, groupDefinitionsForCycle]) => {
      sections.appendChild(renderCycleGroup(cycleType, groupDefinitionsForCycle, card.card_id));
    });
  }

  if (highlightPeriodId) {
    window.requestAnimationFrame(() => highlightPeriodRow(highlightPeriodId));
  }
}

function renderCardLoading(cardId) {
  const knownCard = cards.find((card) => Number(card.card_id) === Number(cardId));
  const label = knownCard ? cardDisplayName(knownCard) : `card ${cardId}`;
  cardDetail.innerHTML = `<p class="muted card-loading">Loading ${escapeHtml(label)}...</p>`;
}

async function loadCardDetail(cardId, options) {
  const force = options && options.force;
  const highlightPeriodId = options && options.highlightPeriodId;
  const numericCardId = Number(cardId);
  showCardView(numericCardId);

  if (!Number.isInteger(numericCardId)) {
    cardDetail.innerHTML = `<p class="error-inline">Invalid card link.</p>`;
    return;
  }

  if (!force && cardDetails.has(numericCardId)) {
    renderCardDetail(cardDetails.get(numericCardId), highlightPeriodId);
    return;
  }

  renderCardLoading(numericCardId);
  try {
    const detail = await fetchJson(`/api/cards/${encodeURIComponent(numericCardId)}?include_inactive_definitions=true`);
    cardDetails.set(numericCardId, detail);
    renderCardDetail(detail, highlightPeriodId);
  } catch (error) {
    cardDetail.innerHTML = `<p class="error-inline">${escapeHtml(error.message || "Unable to load card detail.")}</p>`;
    showError(error.message || "Unable to load card detail.");
  }
}

async function handleRoute(hash) {
  const route = routeFromHash(hash || window.location.hash);
  if (route.type === "dashboard") {
    showDashboardView();
    return;
  }
  await loadCardDetail(route.cardId, { highlightPeriodId: route.periodId });
}

function isNumericInput(value) {
  const trimmed = String(value).trim();
  return trimmed !== "" && Number.isFinite(Number(trimmed));
}

function setFormBusy(form, busy) {
  form.querySelectorAll("input, button").forEach((control) => {
    control.disabled = busy;
  });
}

async function saveUsedAmount(form) {
  const input = form.elements.current_used_amount;
  const value = input.value.trim();
  if (!isNumericInput(value)) {
    showError("Used must be a numeric value.");
    input.focus();
    return;
  }

  const periodId = form.dataset.periodId;
  const cardId = form.dataset.cardId ? Number(form.dataset.cardId) : null;
  const route = routeFromHash();
  setFormBusy(form, true);
  clearError();
  clearNotice();

  try {
    await fetchJson(`/api/benefit-periods/${encodeURIComponent(periodId)}/usage-adjustment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_used_amount: value,
        event_type: "correction",
        note: form.dataset.note || "Updated from dashboard Used column",
      }),
    });

    if (cardId) cardDetails.delete(cardId);
    await loadDashboard({ keepNotice: true });
    if (route.type === "card") {
      cardDetails.delete(route.cardId);
      await loadCardDetail(route.cardId, {
        force: true,
        highlightPeriodId: route.periodId || periodId,
      });
    }
    if (errorBox.hidden) showNotice("Used amount saved. Remaining refreshed from backend totals.");
  } catch (error) {
    showError(error.message || "Unable to save used amount.");
  } finally {
    setFormBusy(form, false);
  }
}

async function refreshCurrentView() {
  const route = routeFromHash();
  await Promise.all([loadCards(), loadDashboard()]);
  if (route.type === "card") {
    cardDetails.delete(route.cardId);
    await loadCardDetail(route.cardId, { force: true, highlightPeriodId: route.periodId });
  }
}

document.addEventListener("submit", (event) => {
  const form = event.target.closest(".used-form");
  if (!form) return;
  event.preventDefault();
  saveUsedAmount(form);
});

document.addEventListener("click", (event) => {
  const hashLink = event.target.closest("a[href^='#']");
  if (hashLink) {
    const hash = hashLink.getAttribute("href");
    if (hash === window.location.hash) {
      event.preventDefault();
      handleRoute(hash);
    }
    return;
  }
});

window.addEventListener("hashchange", () => {
  handleRoute();
});

refreshButton.addEventListener("click", () => refreshCurrentView());

// Theme Toggle Logic
const savedTheme = localStorage.getItem("theme") || "light";
if (savedTheme === "dark") {
  document.documentElement.setAttribute("data-theme", "dark");
  themeToggleButton.textContent = "🌙";
} else {
  document.documentElement.removeAttribute("data-theme");
  themeToggleButton.textContent = "☀️";
}

themeToggleButton.addEventListener("click", () => {
  const currentTheme = document.documentElement.getAttribute("data-theme");
  const newTheme = currentTheme === "dark" ? "light" : "dark";

  if (newTheme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
    themeToggleButton.textContent = "🌙";
  } else {
    document.documentElement.removeAttribute("data-theme");
    themeToggleButton.textContent = "☀️";
  }

  localStorage.setItem("theme", newTheme);
});

async function initialize() {
  await Promise.all([loadDashboard(), loadCards()]);
  await handleRoute();
}

initialize();
