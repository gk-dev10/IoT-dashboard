/**
 * Smart Posture T-Shirt v2 — Application Shell & Router Entrypoint.
 */

import { api } from "./api.js";
import { store } from "./store.js";
import { LiveView } from "./views/live.js";
import { AnalysisView } from "./views/analysis.js";

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
    } catch (err) {
      console.warn("Initial hydration warning:", err);
    }

    // 4. Start Real-time SSE Stream
    api.startStream();
  }

  handleRoute() {
    const hash = window.location.hash || "#/live";

    // Update navigation active states
    this.navLinks.forEach((link) => {
      if (link.getAttribute("href") === hash) {
        link.classList.add("active");
      } else {
        link.classList.remove("active");
      }
    });

    // Unmount existing view if any
    if (this.currentView && typeof this.currentView.unmount === "function") {
      this.currentView.unmount();
    }

    if (hash === "#/analysis") {
      this.currentView = new AnalysisView(this.appContainer);
      this.currentView.mount();
    } else if (hash === "#/history") {
      this.renderPlaceholder("Historical Analytics", "Detailed posture and vitals history is in active development.");
    } else if (hash === "#/alerts") {
      this.renderPlaceholder("Alert History & Audits", "Comprehensive posture episode and alert logs are in active development.");
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
