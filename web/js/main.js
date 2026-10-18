/**
 * Smart Posture T-Shirt v2 — Application Shell & Router Entrypoint.
 */

import { api } from "./api.js";
import { store } from "./store.js";
import { LiveView } from "./views/live.js";
import { AnalysisView } from "./views/analysis.js";
import { HistoryView } from "./views/history.js";
import { AlertsView } from "./views/alerts.js";

class Application {
  constructor() {
    this.appContainer = document.getElementById("app-viewport");
    this.currentView = null;
    this.navLinks = document.querySelectorAll(".nav-link");
  }

  async init() {
    console.info("Initializing Smart Posture T-Shirt Web Platform v2...");

    // 1. Setup Hash Router
    window.addEventListener("hashchange", () => this.handleRoute());
    this.handleRoute();

    // 2. Wire API events into reactive Store
    api.onTelemetry((livePayload) => {
      store.setLive(livePayload);
    });

    api.onCommand((commandsPayload) => {
      store.setCommands(commandsPayload);
    });

    api.onConnectionChange((status) => {
      store.setConnection(status);
    });

    // 3. Initial baseline data hydration
    try {
      const [liveData, historyData, episodesData] = await Promise.all([
        api.fetchLive(),
        api.fetchHistory(2, 120),
        api.fetchEpisodes(5),
      ]);

      if (liveData) store.setLive(liveData);
      if (historyData) store.setHistory(historyData);
      if (episodesData) store.setEpisodes(episodesData);
      this._updateAlertsBadge(episodesData);
    } catch (err) {
      console.warn("Initial hydration warning:", err);
    }

    // 4. Start Real-time SSE Stream
    api.startStream();
  }

  _updateAlertsBadge(episodes) {
    if (!episodes || episodes.length === 0) return;
    const badgeEl = document.getElementById("nav-alerts-badge");
    if (!badgeEl) return;

    let lastSeen = null;
    try {
      lastSeen = localStorage.getItem("vest_last_seen_alerts");
    } catch (e) {}

    const lastSeenDt = lastSeen ? new Date(lastSeen) : new Date(0);
    const unseenCount = episodes.filter(ep => {
      const epDt = new Date(ep.end_ts || ep.start_ts);
      return epDt > lastSeenDt;
    }).length;

    if (unseenCount > 0 && window.location.hash !== "#/alerts") {
      badgeEl.textContent = unseenCount > 99 ? "99+" : String(unseenCount);
      badgeEl.classList.remove("hidden");
    } else {
      badgeEl.classList.add("hidden");
    }
  }

  handleRoute() {
    const rawHash = window.location.hash || "#/live";
    const routePath = rawHash.split("?")[0];

    // Update navigation active states
    this.navLinks.forEach((link) => {
      const linkHref = link.getAttribute("href") || "";
      const linkBase = linkHref.split("?")[0];
      if (linkBase === routePath) {
        link.classList.add("active");
      } else {
        link.classList.remove("active");
      }
    });

    // Unmount existing view if any
    if (this.currentView && typeof this.currentView.unmount === "function") {
      this.currentView.unmount();
    }

    if (routePath === "#/analysis") {
      this.currentView = new AnalysisView(this.appContainer);
      this.currentView.mount();
    } else if (routePath === "#/history") {
      this.currentView = new HistoryView(this.appContainer);
      this.currentView.mount();
    } else if (routePath === "#/alerts") {
      this.currentView = new AlertsView(this.appContainer);
      this.currentView.mount();
    } else {
      // Default to #/live
      this.currentView = new LiveView(this.appContainer);
      this.currentView.mount();
    }
  }

  renderPlaceholder(title, description) {
    this.appContainer.innerHTML = `
      <div class="placeholder-page">
        <div class="placeholder-card">
          <div class="placeholder-icon">🚧</div>
          <h2>${title}</h2>
          <p>${description}</p>
          <a href="#/live" class="btn btn-primary" style="margin-top: 1rem; display: inline-block;">Return to Live View</a>
        </div>
      </div>
    `;
  }
}

// Bootstrap on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  const app = new Application();
  app.init();
});
