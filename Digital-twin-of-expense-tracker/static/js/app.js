// app.js — Digital Twin Avatar frontend
// Changes: bigger viewer, 30-second auto-refresh with countdown, insights panel, forecast strip.

import * as THREE from "three";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const MODEL_BASE = "/static/models/";

const ANIMATION_FILES = {
  idle:  "Idle.fbx",
  happy: "Happy_Idle.fbx",
  tired: "Running_Tired.fbx",
  sad:   "Sad_Idle.fbx",
};

const STAT_THRESHOLDS = { caution: 50, low: 30 };
const AUTO_REFRESH_SECS = 30;

// ---------------------------------------------------------------------------
// Theme toggle (persisted in localStorage, applied by inline script on load)
// ---------------------------------------------------------------------------

const themeToggleBtn = document.getElementById("theme-toggle");
if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    localStorage.setItem("dt-theme", next);
  });
}

// ---------------------------------------------------------------------------
// Three.js scene setup
// ---------------------------------------------------------------------------

const viewerFrame = document.querySelector(".viewer-frame");
const canvas      = document.getElementById("avatar-canvas");
const loadingEl   = document.getElementById("viewer-loading");
const badgeEl     = document.getElementById("viewer-state-badge");
const stateTextEl = document.getElementById("animation-state-text");

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(32, 16 / 10, 0.1, 100);
camera.position.set(0, 1.6, 3.2);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1, 0);
controls.enableDamping = true;
controls.minDistance = 1.5;
controls.maxDistance = 6;
controls.maxPolarAngle = Math.PI * 0.55;

scene.add(new THREE.HemisphereLight(0xbfd9ff, 0x14181d, 1.2));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.8);
keyLight.position.set(2.5, 4, 2.5);
scene.add(keyLight);
const rimLight = new THREE.DirectionalLight(0x4eddbe, 0.6);
rimLight.position.set(-3, 1.5, -2);
scene.add(rimLight);

const ground = new THREE.Mesh(
  new THREE.CircleGeometry(2.4, 48),
  new THREE.MeshStandardMaterial({ color: 0x0c1118, roughness: 1 })
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground);

function resizeRenderer() {
  const w = viewerFrame.clientWidth;
  const h = viewerFrame.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resizeRenderer).observe(viewerFrame);
resizeRenderer();

const clock = new THREE.Clock();
let mixer = null;
const actions = {};
let currentAction = null;

function renderLoop() {
  const delta = clock.getDelta();
  if (mixer) mixer.update(delta);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(renderLoop);
}
requestAnimationFrame(renderLoop);

function playAnimationState(state) {
  const next = actions[state] || actions.idle;
  if (!next || next === currentAction) return;
  if (currentAction) currentAction.fadeOut(0.4);
  next.reset().fadeIn(0.4).play();
  currentAction = next;

  stateTextEl.textContent = state;
  badgeEl.textContent = state;
  badgeEl.className = "viewer-state-badge" + (state !== "idle" ? ` is-${state}` : "");
}

// ---------------------------------------------------------------------------
// Avatar loading
// ---------------------------------------------------------------------------

function loadFbx(filename) {
  return new Promise((resolve, reject) => {
    new FBXLoader().load(
      MODEL_BASE + filename,
      (object) => resolve(object),
      undefined,
      (err) => reject(err)
    );
  });
}

async function loadAvatar() {
  const base = await loadFbx(ANIMATION_FILES.idle);
  base.scale.setScalar(0.01);
  base.traverse((child) => {
    if (child.isMesh) { child.castShadow = false; child.receiveShadow = false; }
  });
  scene.add(base);

  mixer = new THREE.AnimationMixer(base);
  if (base.animations.length) {
    actions.idle = mixer.clipAction(base.animations[0]);
  }

  const others = Object.entries(ANIMATION_FILES).filter(([s]) => s !== "idle");
  await Promise.all(
    others.map(async ([state, filename]) => {
      const obj = await loadFbx(filename);
      if (obj.animations.length) {
        actions[state] = mixer.clipAction(obj.animations[0]);
      }
    })
  );

  Object.values(actions).forEach((a) => { a.enabled = true; });
  playAnimationState("idle");
  loadingEl.classList.add("is-hidden");
}

// ---------------------------------------------------------------------------
// Pulse strip
// ---------------------------------------------------------------------------

const pulseLine       = document.getElementById("pulse-line");
const pulseEnergyValue = document.getElementById("pulse-energy-value");
let energyRatio = 0.5;

function ecgOffset(x, t, ratio) {
  const speed       = 0.7 + ratio * 2.0;
  const amplitude   = 4 + ratio * 13;
  const cycleLength = 2.4;
  const phase       = (x * 0.03 + t * speed) % cycleLength;
  const cyclePos    = (phase / cycleLength) * Math.PI * 2;
  let y = Math.sin(cyclePos * 2) * 1.2;
  const distFromPeak = Math.min(Math.abs(cyclePos - Math.PI), Math.PI * 2 - Math.abs(cyclePos - Math.PI));
  if (distFromPeak < 0.35) y += amplitude * (1 - distFromPeak / 0.35);
  return y;
}

function animatePulse() {
  const t = performance.now() / 1000;
  const pts = [];
  for (let x = 0; x <= 400; x += 4) {
    const y = 20 - ecgOffset(x, t, energyRatio);
    pts.push(`${x},${y.toFixed(2)}`);
  }
  pulseLine.setAttribute("points", pts.join(" "));
  requestAnimationFrame(animatePulse);
}
requestAnimationFrame(animatePulse);

// ---------------------------------------------------------------------------
// Stat bars
// ---------------------------------------------------------------------------

const vitalRows     = document.querySelectorAll(".vital-row");
const lastSyncEl    = document.getElementById("last-sync");
const refreshBtn    = document.getElementById("refresh-btn");
const refreshStatus = document.getElementById("refresh-status");

function fillClass(value) {
  if (value <= STAT_THRESHOLDS.low)    return "is-low";
  if (value <= STAT_THRESHOLDS.caution) return "is-caution";
  return "";
}

function renderStats(stats) {
  vitalRows.forEach((row) => {
    const key   = row.dataset.stat;
    const value = stats[key];
    if (value == null) return;
    row.querySelector("[data-value]").textContent = Math.round(value);
    const fill = row.querySelector("[data-fill]");
    fill.style.width = `${Math.max(0, Math.min(100, value))}%`;
    fill.className   = "vital-fill " + fillClass(value);
  });

  energyRatio = Math.max(0, Math.min(100, stats.energy ?? 50)) / 100;
  pulseEnergyValue.textContent = Math.round(stats.energy ?? 0);
}

function formatTs(iso) {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

// ---------------------------------------------------------------------------
// Insights panel
// ---------------------------------------------------------------------------

const insightsBody = document.getElementById("insights-body");

const TAG_LABELS = {
  health:       "health",
  energy:       "energy",
  happiness:    "happiness",
  wealth_level: "wealth",
};

function renderInsights(insights) {
  if (!insights) return;
  const items = [];
  for (const [key, sentences] of Object.entries(insights)) {
    const tagClass = TAG_LABELS[key] || "health";
    const label    = TAG_LABELS[key] || key;
    for (const sentence of sentences) {
      items.push(
        `<div class="insight-item">
          <span class="insight-tag ${tagClass}">${label}</span>
          <span class="insight-text">${sentence}</span>
        </div>`
      );
    }
  }
  insightsBody.innerHTML = items.length
    ? items.join("")
    : `<span class="insight-text" style="color:var(--text-dim)">No insights generated.</span>`;
}

// ---------------------------------------------------------------------------
// Category breakdown
// ---------------------------------------------------------------------------

const categoryListEl = document.getElementById("category-list");

function renderCategoryBreakdown(rows) {
  if (!categoryListEl) return;
  if (!rows || !rows.length) {
    categoryListEl.innerHTML =
      `<div class="insight-text" style="color:var(--text-dim);font-size:12px;">No category data yet.</div>`;
    return;
  }

  const withSpend = rows.filter((r) => r.total > 0);
  const display = withSpend.length ? withSpend : rows.slice(0, 5);

  categoryListEl.innerHTML = display
    .map((r) => {
      const pct = Math.round((r.share || 0) * 100);
      return `
        <div class="category-row">
          <span class="category-dot ${r.bucket}"></span>
          <div class="category-bar-wrap">
            <div class="category-bar-label">
              <span>${r.category}</span>
              <span>${pct}%</span>
            </div>
            <div class="category-bar-track">
              <div class="category-bar-fill ${r.bucket}" style="width:${Math.min(100, pct)}%"></div>
            </div>
          </div>
          <span class="category-amount">₹${Math.round(r.total).toLocaleString()}</span>
        </div>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Forecast strip
// ---------------------------------------------------------------------------

const forecastStrip = document.getElementById("forecast-strip");
const forecastValue = document.getElementById("forecast-value");
const forecastTrend = document.getElementById("forecast-trend");

function renderForecast(forecast) {
  if (!forecast) { forecastStrip.style.display = "none"; return; }
  forecastStrip.style.display = "flex";
  forecastValue.textContent = `₹${forecast.projected_next_month.toLocaleString()}`;
  forecastTrend.textContent = forecast.trend;
  forecastTrend.className   = `forecast-trend ${forecast.trend}`;
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function fetchStatus() {
  const res = await fetch("/api/avatar/status");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Status fetch failed (${res.status})`);
  return res.json();
}

async function recalculate() {
  const res = await fetch("/api/avatar/recalculate", { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.message || `Recalculate failed (${res.status})`);
  }
  return res.json();
}

async function fetchInsights() {
  const res = await fetch("/api/avatar/insights");
  if (!res.ok) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// Main refresh
// ---------------------------------------------------------------------------

async function refreshUI({ triggerRecalculate = false } = {}) {
  refreshBtn.disabled = true;
  refreshStatus.classList.remove("is-error");
  refreshStatus.textContent = triggerRecalculate ? "Recalculating…" : "Loading…";

  try {
    let recalcData = null;
    if (triggerRecalculate) {
      recalcData = await recalculate();
    }

    let status = await fetchStatus();
    if (!status && !triggerRecalculate) {
      refreshStatus.textContent = "No data yet — running first calculation…";
      recalcData = await recalculate();
      status = await fetchStatus();
    }

    if (status) {
      renderStats(status.stats);
      playAnimationState(status.animation_state);
      lastSyncEl.textContent = `Last synced ${formatTs(status.timestamp)}`;
      refreshStatus.textContent = "Up to date";
    }

    // Insights: prefer what came back from recalculate, else fetch separately
    const insightData = recalcData || (await fetchInsights());
    if (insightData) {
      renderInsights(insightData.insights);
      renderForecast(insightData.forecast || null);
      renderCategoryBreakdown(insightData.category_breakdown || null);
    }

    await refreshHistoryChart();
  } catch (err) {
    console.error(err);
    refreshStatus.classList.add("is-error");
    refreshStatus.textContent = err.message || "Couldn't reach the avatar service.";
  } finally {
    refreshBtn.disabled = false;
  }
}

refreshBtn.addEventListener("click", () => {
  resetCountdown();
  refreshUI({ triggerRecalculate: true });
});

// ---------------------------------------------------------------------------
// 30-second auto-refresh with countdown pill
// ---------------------------------------------------------------------------

const countdownPill = document.getElementById("countdown-pill");
let secondsLeft = AUTO_REFRESH_SECS;
let countdownTimer = null;

function resetCountdown() {
  secondsLeft = AUTO_REFRESH_SECS;
}

function tickCountdown() {
  secondsLeft -= 1;
  if (secondsLeft <= 0) {
    secondsLeft = AUTO_REFRESH_SECS;
    countdownPill.classList.remove("ticking");
    countdownPill.textContent = "Syncing…";
    refreshUI({ triggerRecalculate: true }).finally(() => {
      countdownPill.classList.add("ticking");
    });
  } else {
    countdownPill.textContent = `Next sync in ${secondsLeft}s`;
    if (secondsLeft <= 10) {
      countdownPill.classList.add("ticking");
    } else {
      countdownPill.classList.remove("ticking");
    }
  }
}

countdownTimer = setInterval(tickCountdown, 1000);

// ---------------------------------------------------------------------------
// History chart
// ---------------------------------------------------------------------------

let historyChart = null;

async function refreshHistoryChart() {
  const res = await fetch("/api/avatar/history");
  if (!res.ok) return;
  const { history } = await res.json();

  const labels   = history.map((r) => formatTs(r.timestamp));
  const datasets = [
    { key: "health",       label: "Health",      color: "#4eddbe" },
    { key: "energy",       label: "Energy",       color: "#f0b84a" },
    { key: "happiness",    label: "Happiness",    color: "#5b9cf6" },
    { key: "wealth_level", label: "Wealth level", color: "#f0614f" },
  ].map((d) => ({
    label:           d.label,
    data:            history.map((r) => r[d.key]),
    borderColor:     d.color,
    backgroundColor: d.color,
    tension:         0.35,
    pointRadius:     2,
    borderWidth:     2,
  }));

  const ctx = document.getElementById("history-chart");
  if (!historyChart) {
    historyChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            min: 0, max: 100,
            ticks: { color: "#7a8fa3" },
            grid:  { color: "#1a2432" },
          },
          x: {
            ticks: { color: "#7a8fa3", maxRotation: 0, autoSkip: true },
            grid:  { display: false },
          },
        },
        plugins: {
          legend: { labels: { color: "#e4eaf0", boxWidth: 10, font: { size: 11 } } },
        },
      },
    });
  } else {
    historyChart.data.labels   = labels;
    historyChart.data.datasets = datasets;
    historyChart.update();
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

loadAvatar().catch((err) => {
  console.error("Failed to load avatar:", err);
  loadingEl.textContent = "Couldn't load avatar model.";
});

refreshUI({ triggerRecalculate: false });