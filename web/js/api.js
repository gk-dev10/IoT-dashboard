/**
 * Smart Posture T-Shirt v2 — API Client & Real-Time SSE Stream Manager.
 */

export class ApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.eventSource = null;
    this.sseFailures = 0;
    this.pollingIntervalId = null;
    this.telemetryListeners = new Set();
    this.commandListeners = new Set();
    this.connectionListeners = new Set();
    this.isPolling = false;
  }

  // --- REST Requests ---

  async fetchLive() {
    try {
      const res = await fetch(`${this.baseUrl}/api/live`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn("fetchLive failed:", err);
      return null;
    }
  }

  async fetchHistory(minutes = 2, limit = 120) {
    try {
      const res = await fetch(`${this.baseUrl}/api/history?minutes=${minutes}&limit=${limit}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn("fetchHistory failed:", err);
      return [];
    }
  }

  async fetchEpisodes(limit = 5) {
    try {
      const res = await fetch(`${this.baseUrl}/api/episodes?limit=${limit}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn("fetchEpisodes failed:", err);
      return [];
    }
  }

  async fetchStats(hours = 24) {
    try {
      const res = await fetch(`${this.baseUrl}/api/stats?hours=${hours}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn("fetchStats failed:", err);
      return null;
    }
  }

  async fetchAnalysis(minutes = 60, excludeMoving = 1, deviceId = "") {
    try {
      let url = `${this.baseUrl}/api/analysis?minutes=${minutes}&exclude_moving=${excludeMoving ? 1 : 0}`;
      if (deviceId) {
        url += `&device_id=${encodeURIComponent(deviceId)}`;
      }
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn("fetchAnalysis failed:", err);
      return null;
    }
  }

  async sendCommand(commandPayload) {
    const res = await fetch(`${this.baseUrl}/api/commands`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(commandPayload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  // --- Real-Time Stream (SSE with Polling Fallback) ---

  onTelemetry(callback) {
    this.telemetryListeners.add(callback);
    return () => this.telemetryListeners.delete(callback);
  }

  onCommand(callback) {
    this.commandListeners.add(callback);
    return () => this.commandListeners.delete(callback);
  }

  onConnectionChange(callback) {
    this.connectionListeners.add(callback);
    return () => this.connectionListeners.delete(callback);
  }

  _notifyTelemetry(data) {
    for (const cb of this.telemetryListeners) {
      try { cb(data); } catch (e) { console.error("Telemetry listener error:", e); }
    }
  }

  _notifyCommand(data) {
    for (const cb of this.commandListeners) {
      try { cb(data); } catch (e) { console.error("Command listener error:", e); }
    }
  }

  _notifyConnection(status) {
    for (const cb of this.connectionListeners) {
      try { cb(status); } catch (e) { console.error("Connection listener error:", e); }
    }
  }

  startStream() {
    this.stopStream();

    try {
      this.eventSource = new EventSource(`${this.baseUrl}/api/stream`);

      this.eventSource.onopen = () => {
        this.sseFailures = 0;
        this.stopPolling();
        this._notifyConnection({ mode: "sse", connected: true });
      };

      this.eventSource.addEventListener("telemetry", (evt) => {
        try {
          const data = JSON.parse(evt.data);
          this._notifyTelemetry(data);
        } catch (e) {
          console.error("Malformed telemetry event:", e);
        }
      });

      this.eventSource.addEventListener("command", (evt) => {
        try {
          const data = JSON.parse(evt.data);
          this._notifyCommand(data);
        } catch (e) {
          console.error("Malformed command event:", e);
        }
      });

      this.eventSource.onerror = () => {
        this.sseFailures++;
        this.eventSource.close();
        this.eventSource = null;
        this._notifyConnection({ mode: "sse", connected: false });

        if (this.sseFailures >= 2) {
          console.warn("SSE failed twice consecutively. Falling back to 1 Hz polling.");
          this.startPolling();
        } else {
          // Retry SSE in 3 seconds
          setTimeout(() => this.startStream(), 3000);
        }
      };
    } catch (err) {
      console.error("EventSource initialization failed:", err);
      this.startPolling();
    }
  }

  stopStream() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  startPolling() {
    if (this.pollingIntervalId) return;
    this.isPolling = true;
    this._notifyConnection({ mode: "polling", connected: true });

    const poll = async () => {
      const data = await this.fetchLive();
      if (data) {
        this._notifyTelemetry(data);
      }
    };

    poll();
    this.pollingIntervalId = setInterval(poll, 1000);

    // Periodically attempt to upgrade back to SSE every 20 seconds
    setTimeout(() => {
      if (this.isPolling) {
        console.info("Attempting to restore SSE stream...");
        this.startStream();
      }
    }, 20000);
  }

  stopPolling() {
    if (this.pollingIntervalId) {
      clearInterval(this.pollingIntervalId);
      this.pollingIntervalId = null;
    }
    this.isPolling = false;
  }
}

export const api = new ApiClient();
