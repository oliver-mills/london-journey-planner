const state = {
  stations: [], // [{id, name}]
  selected: { start: null, end: null }, // station ids chosen via autocomplete
};

const els = {
  form: document.getElementById("route-form"),
  startInput: document.getElementById("start-input"),
  endInput: document.getElementById("end-input"),
  swapButton: document.getElementById("swap-button"),
  avoidDisruptions: document.getElementById("avoid-disruptions"),
  routeError: document.getElementById("route-error"),
  routeResult: document.getElementById("route-result"),
  statTime: document.getElementById("stat-time"),
  statDistance: document.getElementById("stat-distance"),
  statChanges: document.getElementById("stat-changes"),
  routeLegs: document.getElementById("route-legs"),
  statusList: document.getElementById("status-list"),
  refreshStatus: document.getElementById("refresh-status"),
  reviewsCard: document.getElementById("reviews-card"),
  reviewsStation: document.getElementById("reviews-station"),
  reviewsList: document.getElementById("reviews-list"),
  reviewForm: document.getElementById("review-form"),
  reviewComment: document.getElementById("review-comment"),
  reviewAuthor: document.getElementById("review-author"),
  starRating: document.getElementById("star-rating"),
};

let currentEndStationId = null;

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

// ---------- Autocomplete ----------

function setupAutocomplete(field) {
  const wrapper = document.querySelector(`.autocomplete[data-field="${field}"]`);
  const input = wrapper.querySelector("input");
  const list = wrapper.querySelector(".suggestions");
  let activeIndex = -1;
  let matches = [];

  function close() {
    list.hidden = true;
    list.innerHTML = "";
    activeIndex = -1;
  }

  function render() {
    if (matches.length === 0) {
      close();
      return;
    }
    list.innerHTML = matches
      .map(
        (station, i) =>
          `<li data-id="${escapeHtml(station.id)}" class="${i === activeIndex ? "active" : ""}">${escapeHtml(station.name)}</li>`
      )
      .join("");
    list.hidden = false;
  }

  function select(station) {
    input.value = station.name;
    state.selected[field] = station.id;
    close();
  }

  input.addEventListener("input", () => {
    state.selected[field] = null;
    const query = input.value.trim().toLowerCase();
    if (!query) {
      matches = [];
      close();
      return;
    }
    matches = state.stations
      .filter((s) => s.name.toLowerCase().includes(query))
      .slice(0, 8);
    activeIndex = -1;
    render();
  });

  input.addEventListener("keydown", (event) => {
    if (list.hidden) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, matches.length - 1);
      render();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      render();
    } else if (event.key === "Enter") {
      if (activeIndex >= 0) {
        event.preventDefault();
        select(matches[activeIndex]);
      }
    } else if (event.key === "Escape") {
      close();
    }
  });

  list.addEventListener("mousedown", (event) => {
    const li = event.target.closest("li");
    if (!li) return;
    const station = matches.find((s) => s.id === li.dataset.id);
    if (station) select(station);
  });

  document.addEventListener("click", (event) => {
    if (!wrapper.contains(event.target)) close();
  });

  return { setValue: select };
}

// ---------- Route search ----------

function resolveStationId(field, inputEl) {
  if (state.selected[field]) return state.selected[field];
  const typed = inputEl.value.trim();
  const match = state.stations.find((s) => s.name.toLowerCase() === typed.toLowerCase());
  return match ? match.id : typed.toUpperCase();
}

function renderRoute(route) {
  els.statTime.textContent = route.total_time_min;
  els.statDistance.textContent = route.total_distance_km;
  els.statChanges.textContent = route.interchanges.length;

  const interchangeByStation = new Map(route.interchanges.map((i) => [i.station, i]));

  const rows = [{ station: route.stations[0], line: null, colour: null }];
  route.legs.forEach((leg) => {
    rows.push({ station: leg.to_station, line: leg.line, colour: leg.colour });
  });

  els.routeLegs.innerHTML = rows
    .map((row) => {
      const interchange = interchangeByStation.get(row.station);
      const colour = row.colour || "var(--text-muted)";
      const body = row.line
        ? `<span class="line-chip" style="--line-colour:${colour}">${escapeHtml(row.line)}</span>`
        : `<span class="leg-meta">Start</span>`;
      const badge = interchange
        ? `<div class="interchange-badge">Change ${escapeHtml(interchange.from_line)} &rarr; ${escapeHtml(interchange.to_line)}</div>`
        : "";
      return `
        <li class="leg" style="--line-colour:${colour}">
          <span class="leg-dot"></span>
          <div class="leg-body">
            <div class="leg-station">${escapeHtml(row.station)}</div>
            ${body}
            ${badge}
          </div>
        </li>`;
    })
    .join("");

  els.routeResult.hidden = false;
  currentEndStationId = route.end_station_id;
  loadReviews(currentEndStationId, route.stations[route.stations.length - 1]);
}

function showError(message) {
  els.routeError.textContent = message;
  els.routeError.hidden = false;
  els.routeResult.hidden = true;
}

async function handleRouteSubmit(event) {
  event.preventDefault();
  els.routeError.hidden = true;

  const start = resolveStationId("start", els.startInput);
  const end = resolveStationId("end", els.endInput);

  if (!start || !end) {
    showError("Please choose a valid start and destination station.");
    return;
  }

  try {
    const response = await fetch("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start,
        end,
        avoid_disruptions: els.avoidDisruptions.checked,
      }),
    });
    const body = await response.json();
    if (!response.ok) {
      showError(body.detail || "Something went wrong finding that route.");
      return;
    }
    renderRoute(body);
  } catch (err) {
    showError("Couldn't reach the journey planner API.");
  }
}

// ---------- Live status ----------

async function loadStatus() {
  els.statusList.innerHTML = `<li class="status-row"><span class="status-text">Loading&hellip;</span></li>`;
  try {
    const response = await fetch("/api/status");
    const statuses = await response.json();
    if (!response.ok) throw new Error(statuses.detail || "TfL API unavailable");

    els.statusList.innerHTML = statuses
      .map(
        (s) => `
        <li class="status-row" style="--line-colour:${s.colour}">
          <span class="status-dot"></span>
          <span class="status-line">${escapeHtml(s.line)}</span>
          <span class="status-text ${s.blocked ? "blocked" : s.status === "Good Service" ? "good" : ""}">${escapeHtml(s.status)}</span>
        </li>`
      )
      .join("");
  } catch (err) {
    els.statusList.innerHTML = `<li class="status-row"><span class="status-text blocked">Couldn't load live status right now.</span></li>`;
  }
}

// ---------- Reviews ----------

async function loadReviews(stationId, displayName) {
  els.reviewsCard.hidden = false;
  els.reviewsStation.textContent = displayName;
  els.reviewsList.innerHTML = `<p class="stat-label">Loading reviews&hellip;</p>`;

  try {
    const response = await fetch(`/api/reviews/${encodeURIComponent(stationId)}`);
    const reviewsData = await response.json();
    if (!response.ok) throw new Error(reviewsData.detail);

    els.reviewsList.innerHTML = reviewsData.length
      ? reviewsData
          .map(
            (r) => `
        <li class="review">
          <div class="review-stars">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</div>
          <p class="review-comment">${escapeHtml(r.comment)}</p>
          <div class="review-author">&mdash; ${escapeHtml(r.author)}</div>
        </li>`
          )
          .join("")
      : `<p class="stat-label">No reviews yet &mdash; be the first!</p>`;
  } catch (err) {
    els.reviewsList.innerHTML = `<p class="stat-label">Couldn't load reviews.</p>`;
  }
}

function setupStarRating() {
  const buttons = [...els.starRating.querySelectorAll("button")];

  function paint(value) {
    buttons.forEach((btn) => btn.classList.toggle("selected", Number(btn.dataset.value) <= value));
  }

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      els.starRating.dataset.rating = btn.dataset.value;
      paint(Number(btn.dataset.value));
    });
  });

  paint(Number(els.starRating.dataset.rating));
}

async function handleReviewSubmit(event) {
  event.preventDefault();
  if (!currentEndStationId) return;

  const payload = {
    author: els.reviewAuthor.value.trim(),
    rating: Number(els.starRating.dataset.rating),
    comment: els.reviewComment.value.trim(),
  };

  const response = await fetch(`/api/reviews/${encodeURIComponent(currentEndStationId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (response.ok) {
    els.reviewComment.value = "";
    els.reviewAuthor.value = "";
    loadReviews(currentEndStationId, els.reviewsStation.textContent);
  }
}

// ---------- Init ----------

async function init() {
  setupAutocomplete("start");
  setupAutocomplete("end");
  setupStarRating();

  els.form.addEventListener("submit", handleRouteSubmit);
  els.reviewForm.addEventListener("submit", handleReviewSubmit);
  els.refreshStatus.addEventListener("click", loadStatus);

  els.swapButton.addEventListener("click", () => {
    const startValue = els.startInput.value;
    const endValue = els.endInput.value;
    const startId = state.selected.start;
    const endId = state.selected.end;

    els.startInput.value = endValue;
    els.endInput.value = startValue;
    state.selected.start = endId;
    state.selected.end = startId;
  });

  try {
    const response = await fetch("/api/stations");
    state.stations = await response.json();
  } catch (err) {
    showError("Couldn't load the station list from the API.");
  }

  loadStatus();
}

init();
