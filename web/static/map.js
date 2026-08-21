/* Interactive network map.
 *
 * The backend hands over the whole tube network already projected into SVG
 * coordinates (see tube_planner/geo.py), so this file is only concerned with
 * drawing it and letting the user move around: pan by dragging, zoom with the
 * wheel or the buttons, and highlight a route on top of the base network.
 *
 * Zoom narrows the viewBox rather than transforming a group, which would
 * otherwise shrink strokes and dots along with the map. A `--zoom` custom
 * property on the <svg> counteracts that in CSS, keeping line weights and
 * station dots visually constant at every zoom level.
 */

const TubeMap = (() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const MIN_ZOOM = 1;
  const MAX_ZOOM = 14;
  const ROUTE_FIT_PADDING = 60;
  const DRAG_THRESHOLD_PX = 4;

  let root = null; // container element
  let svg = null;
  let tooltip = null;
  let network = null; // { width, height, stations, edges }
  let stationsById = new Map();
  let layers = {};
  let onStationSelect = null;

  let home = { x: 0, y: 0, w: 0, h: 0 }; // viewBox showing the whole network
  let view = { x: 0, y: 0, w: 0, h: 0 }; // current viewBox
  let animation = null;

  // ---------- viewBox plumbing ----------

  function zoomLevel() {
    return home.w / view.w;
  }

  function applyView() {
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
    const zoom = zoomLevel();
    svg.style.setProperty("--zoom", zoom.toFixed(3));
    // Labels arrive in tiers as there becomes room for them: interchanges
    // first, then every station.
    svg.classList.toggle("labels-interchange", zoom >= 2.2);
    svg.classList.toggle("labels-all", zoom >= 4.5);
    scheduleDeclutter();
  }

  // ---------- Label decluttering ----------

  function overlaps(a, b) {
    return (
      a.x < b.x + b.width &&
      b.x < a.x + a.width &&
      a.y < b.y + b.height &&
      b.y < a.y + a.height
    );
  }

  /** Hides labels that would overlap one already on screen.
   *
   * Central London packs a dozen stations into the space one name needs, so
   * without this the labels there turn into an unreadable smear. Candidates
   * are placed greedily in priority order -- stations on the current route,
   * then interchanges, then the rest -- so the names worth keeping win the
   * space they contend for.
   */
  function declutterLabels() {
    const candidates = [...layers.labels.querySelectorAll(".map-label")]
      .filter((label) => !label.classList.contains("endpoint"))
      .filter((label) => {
        label.classList.remove("collides");
        // getComputedStyle reflects the tier classes and the route state, so
        // this asks "would this be drawn?" without duplicating that logic.
        return getComputedStyle(label).opacity !== "0";
      });

    candidates.sort((a, b) => priority(a) - priority(b));

    // The start/end markers draw their own names and are never dropped, so
    // they claim their space before anything else competes for it.
    const placed = [...layers.markers.querySelectorAll(".marker-label")].map((node) =>
      node.getBBox()
    );
    candidates.forEach((label) => {
      const box = label.getBBox();
      if (placed.some((other) => overlaps(other, box))) {
        label.classList.add("collides");
      } else {
        placed.push(box);
      }
    });
  }

  function priority(label) {
    if (label.classList.contains("on-route")) return 0;
    if (label.classList.contains("interchange")) return 1;
    return 2;
  }

  let declutterTimer = null;

  function scheduleDeclutter() {
    // Panning and zooming call applyView every frame; re-measuring every
    // label that often would make the map crawl, so this settles first.
    clearTimeout(declutterTimer);
    declutterTimer = setTimeout(declutterLabels, 120);
  }

  function clampView(next) {
    const maxW = home.w / MIN_ZOOM;
    const minW = home.w / MAX_ZOOM;
    const w = Math.min(maxW, Math.max(minW, next.w));
    const h = w * (home.h / home.w);
    // Keep at least a third of the map on screen so it cannot be lost offscreen.
    const slackX = home.w - w / 3;
    const slackY = home.h - h / 3;
    return {
      w,
      h,
      x: Math.min(home.w - w + slackX, Math.max(-slackX, next.x)),
      y: Math.min(home.h - h + slackY, Math.max(-slackY, next.y)),
    };
  }

  function setView(next, { animate = false, duration = 450 } = {}) {
    const target = clampView(next);
    if (animation) {
      cancelAnimationFrame(animation);
      animation = null;
    }
    if (!animate) {
      view = target;
      applyView();
      return;
    }

    const from = { ...view };
    const start = performance.now();
    const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const k = ease(t);
      view = {
        x: from.x + (target.x - from.x) * k,
        y: from.y + (target.y - from.y) * k,
        w: from.w + (target.w - from.w) * k,
        h: from.h + (target.h - from.h) * k,
      };
      applyView();
      animation = t < 1 ? requestAnimationFrame(step) : null;
    };
    animation = requestAnimationFrame(step);
  }

  /** Converts a pointer position into map coordinates. */
  function toMapPoint(event) {
    const rect = svg.getBoundingClientRect();
    return {
      x: view.x + ((event.clientX - rect.left) / rect.width) * view.w,
      y: view.y + ((event.clientY - rect.top) / rect.height) * view.h,
    };
  }

  /** Zooms by `factor`, keeping the map point under `anchor` in place. */
  function zoomAt(anchor, factor) {
    const w = view.w / factor;
    const h = view.h / factor;
    setView({
      w,
      h,
      x: anchor.x - ((anchor.x - view.x) / view.w) * w,
      y: anchor.y - ((anchor.y - view.y) / view.h) * h,
    });
  }

  function zoomCentre(factor) {
    zoomAt({ x: view.x + view.w / 2, y: view.y + view.h / 2 }, factor);
  }

  function reset() {
    setView({ ...home }, { animate: true });
  }

  /** Recomputes the home viewBox so the network fills its container.
   *
   * The projection has its own aspect ratio, which almost never matches the
   * shape of the box on the page. Rather than let the SVG letterbox itself,
   * the shorter axis of the viewBox is padded outwards -- keeping the
   * network centred and unstretched, but using the full width or height.
   */
  function fitHomeToContainer() {
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    const containerAspect = rect.height / rect.width;
    let w = network.width;
    let h = network.height;
    if (h / w < containerAspect) {
      h = w * containerAspect;
    } else {
      w = h / containerAspect;
    }

    home = {
      x: (network.width - w) / 2,
      y: (network.height - h) / 2,
      w,
      h,
    };
  }

  // ---------- Rendering ----------

  function el(name, attrs = {}) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attrs)) {
      node.setAttribute(key, value);
    }
    return node;
  }

  function drawBaseNetwork() {
    const edges = el("g", { class: "map-edges" });
    network.edges.forEach((edge) => {
      edges.appendChild(
        el("line", {
          class: "map-edge",
          x1: edge.x1,
          y1: edge.y1,
          x2: edge.x2,
          y2: edge.y2,
          stroke: edge.colour,
        })
      );
    });

    const dots = el("g", { class: "map-stations" });
    const labels = el("g", { class: "map-labels" });

    network.stations.forEach((station) => {
      const interchange = station.lines.length > 1;

      const dot = el("circle", {
        class: `map-station${interchange ? " interchange" : ""}`,
        cx: station.x,
        cy: station.y,
        // Radius is really driven by CSS so it can track the zoom level; this
        // attribute is only a fallback, since a CSS `r` outranks it.
        r: interchange ? 3.4 : 2.2,
        "data-id": station.id,
      });
      dots.appendChild(dot);

      const label = el("text", {
        class: `map-label${interchange ? " interchange" : ""}`,
        x: station.x + 5,
        y: station.y - 4,
        "data-id": station.id,
      });
      label.textContent = station.name;
      labels.appendChild(label);
    });

    layers = {
      edges,
      route: el("g", { class: "map-route" }),
      dots,
      labels,
      markers: el("g", { class: "map-markers" }),
    };
    // Order matters: the route sits above the base network but below the
    // station dots, so dots stay clickable and legible over a thick route.
    svg.append(layers.edges, layers.route, layers.dots, layers.labels, layers.markers);
  }

  /** Splits the route into runs of consecutive stations sharing one line. */
  function routeSegments(route) {
    const segments = [];
    route.legs.forEach((leg, i) => {
      const from = stationsById.get(route.station_ids[i]);
      const to = stationsById.get(route.station_ids[i + 1]);
      if (!from || !to) return;

      const current = segments[segments.length - 1];
      if (current && current.line === leg.line) {
        current.points.push(to);
      } else {
        segments.push({ line: leg.line, colour: leg.colour, points: [from, to] });
      }
    });
    return segments;
  }

  function marker(station, kind, label) {
    const group = el("g", { class: `map-marker ${kind}` });
    group.appendChild(el("circle", { cx: station.x, cy: station.y, class: "marker-ring" }));
    const text = el("text", { x: station.x, y: station.y - 12, class: "marker-label" });
    text.textContent = label;
    group.appendChild(text);
    return group;
  }

  function fitTo(points) {
    if (points.length === 0) return;
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);

    // Grow the tighter axis so the fitted box keeps the map's aspect ratio;
    // otherwise a north-south route would come out horizontally stretched.
    const aspect = home.h / home.w;
    let w = Math.max(maxX - minX + ROUTE_FIT_PADDING * 2, 1);
    let h = Math.max(maxY - minY + ROUTE_FIT_PADDING * 2, 1);
    if (h / w > aspect) {
      w = h / aspect;
    } else {
      h = w * aspect;
    }

    setView(
      {
        w,
        h,
        x: (minX + maxX) / 2 - w / 2,
        y: (minY + maxY) / 2 - h / 2,
      },
      { animate: true, duration: 620 }
    );
  }

  function showRoute(route) {
    clearRoute();
    const segments = routeSegments(route);
    if (segments.length === 0) return;

    segments.forEach((segment) => {
      const points = segment.points.map((p) => `${p.x},${p.y}`).join(" ");
      layers.route.appendChild(el("polyline", { class: "route-halo", points }));
      layers.route.appendChild(
        el("polyline", { class: "route-line", points, stroke: segment.colour })
      );
    });

    const onRoute = new Set(route.station_ids);
    layers.dots.querySelectorAll(".map-station").forEach((dot) => {
      dot.classList.toggle("on-route", onRoute.has(dot.dataset.id));
    });
    layers.labels.querySelectorAll(".map-label").forEach((label) => {
      label.classList.toggle("on-route", onRoute.has(label.dataset.id));
    });

    const ids = route.station_ids;
    const first = stationsById.get(ids[0]);
    const last = stationsById.get(ids[ids.length - 1]);
    if (first) layers.markers.appendChild(marker(first, "start", first.name));
    if (last) layers.markers.appendChild(marker(last, "end", last.name));

    // The markers carry their own names, so the ordinary labels underneath
    // them would just print each endpoint twice.
    [ids[0], ids[ids.length - 1]].forEach((id) => {
      const label = layers.labels.querySelector(`.map-label[data-id="${CSS.escape(id)}"]`);
      if (label) label.classList.add("endpoint");
    });

    svg.classList.add("has-route");
    fitTo(ids.map((id) => stationsById.get(id)).filter(Boolean));
  }

  function clearRoute() {
    if (!svg) return;
    layers.route.replaceChildren();
    layers.markers.replaceChildren();
    svg.classList.remove("has-route");
    svg.querySelectorAll(".on-route, .endpoint").forEach((node) => {
      node.classList.remove("on-route", "endpoint");
    });
  }

  // ---------- Interaction ----------

  function setupTooltip() {
    svg.addEventListener("mousemove", (event) => {
      const dot = event.target.closest(".map-station");
      const station = dot && stationsById.get(dot.dataset.id);
      if (!station) {
        tooltip.hidden = true;
        return;
      }

      const rect = root.getBoundingClientRect();
      const zone = station.zone ? `<span class="tooltip-zone">Zone ${station.zone}</span>` : "";
      tooltip.innerHTML =
        `<strong>${station.name}</strong>${zone}` +
        `<span class="tooltip-lines">${station.lines.join(" &middot; ")}</span>`;
      tooltip.style.left = `${event.clientX - rect.left}px`;
      tooltip.style.top = `${event.clientY - rect.top}px`;
      tooltip.hidden = false;
    });

    svg.addEventListener("mouseleave", () => {
      tooltip.hidden = true;
    });
  }

  function setupPanAndZoom() {
    let dragging = null;

    svg.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const dot = event.target.closest(".map-station");
      dragging = {
        pointerX: event.clientX,
        pointerY: event.clientY,
        view: { ...view },
        moved: false,
        // Pointer capture (taken below, once a drag is under way) retargets
        // every later pointer event to the <svg> itself, so which station was
        // pressed has to be noted now rather than read off pointerup.
        stationId: dot ? dot.dataset.id : null,
      };
    });

    svg.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const rect = svg.getBoundingClientRect();
      const dx = ((event.clientX - dragging.pointerX) / rect.width) * dragging.view.w;
      const dy = ((event.clientY - dragging.pointerY) / rect.height) * dragging.view.h;

      if (!dragging.moved) {
        const travelled = Math.hypot(
          event.clientX - dragging.pointerX,
          event.clientY - dragging.pointerY
        );
        // A small wobble while clicking is not a drag; ignore it so the click
        // still selects the station underneath.
        if (travelled <= DRAG_THRESHOLD_PX) return;

        dragging.moved = true;
        svg.classList.add("dragging");
        // Capture only once the gesture is definitely a drag, so the pointer
        // keeps panning the map even when it leaves the SVG.
        svg.setPointerCapture(event.pointerId);
      }
      setView({ ...dragging.view, x: dragging.view.x - dx, y: dragging.view.y - dy });
    });

    const endDrag = (event) => {
      if (!dragging) return;
      const { moved, stationId } = dragging;
      dragging = null;
      svg.classList.remove("dragging");
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);

      // Only treat this as a click if the pointer stayed put -- otherwise
      // every pan that happened to start on a station would select it.
      if (moved || !stationId) return;
      const station = stationsById.get(stationId);
      if (station && onStationSelect) onStationSelect(station);
    };

    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", endDrag);

    svg.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        zoomAt(toMapPoint(event), event.deltaY < 0 ? 1.18 : 1 / 1.18);
      },
      { passive: false }
    );
  }

  function setupResize() {
    // The home viewBox is derived from the container's shape, so it has to be
    // recomputed whenever that changes. A view the user has zoomed or panned
    // is left alone -- only an untouched map re-fits itself.
    const observer = new ResizeObserver(() => {
      const wasHome = Math.abs(zoomLevel() - 1) < 0.001;
      fitHomeToContainer();
      if (wasHome) setView({ ...home });
    });
    observer.observe(svg);
  }

  function setupControls() {
    root.querySelector(".map-zoom-in").addEventListener("click", () => zoomCentre(1.5));
    root.querySelector(".map-zoom-out").addEventListener("click", () => zoomCentre(1 / 1.5));
    root.querySelector(".map-reset").addEventListener("click", reset);
  }

  // ---------- Public API ----------

  async function init(container, { onStationSelect: handler } = {}) {
    root = container;
    onStationSelect = handler || null;
    svg = root.querySelector(".map-svg");
    tooltip = root.querySelector(".map-tooltip");

    const response = await fetch("/api/network");
    if (!response.ok) throw new Error("Couldn't load the network map.");
    network = await response.json();

    stationsById = new Map(network.stations.map((s) => [s.id, s]));

    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    drawBaseNetwork();

    fitHomeToContainer();
    view = { ...home };
    applyView();

    setupPanAndZoom();
    setupTooltip();
    setupControls();
    setupResize();
  }

  return { init, showRoute, clearRoute, reset };
})();
