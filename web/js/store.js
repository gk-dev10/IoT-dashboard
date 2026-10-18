/**
 * Smart Posture T-Shirt v2 — Client Reactive Store.
 */

class AppStore {
  constructor() {
    this.state = {
      online: false,
      seconds_since_last: null,
      telemetry: null,
      commands: [],
      history: [],
      episodes: [],
      stats: null,
      streamConnected: false,
      streamMode: "init", // 'sse' | 'polling' | 'init'
    };
    this.listeners = new Set();
  }

  getState() {
    return this.state;
  }

  subscribe(callback) {
    this.listeners.add(callback);
    callback(this.state);
    return () => this.listeners.delete(callback);
  }

  notify() {
    for (const cb of this.listeners) {
      try { cb(this.state); } catch (e) { console.error("Store listener error:", e); }
    }
  }

  setLive(liveData) {
    if (!liveData) return;
    this.state.online = Boolean(liveData.online);
    this.state.seconds_since_last = liveData.seconds_since_last;
    if (liveData.telemetry) {
      this.state.telemetry = liveData.telemetry;
      // Append to local rolling history if ts is newer
      this._appendHistory(liveData.telemetry);
    }
    if (Array.isArray(liveData.commands)) {
      this.state.commands = liveData.commands;
    }
    this.notify();
  }

  setHistory(historyData) {
    if (Array.isArray(historyData)) {
      this.state.history = historyData;
      this.notify();
    }
  }

  setEpisodes(episodesData) {
    if (Array.isArray(episodesData)) {
      this.state.episodes = episodesData;
      this.notify();
    }
  }

  setStats(statsData) {
    if (statsData) {
      this.state.stats = statsData;
      this.notify();
    }
  }

  setCommands(commandsData) {
    if (Array.isArray(commandsData)) {
      this.state.commands = commandsData;
      this.notify();
    }
  }

  setConnection(status) {
    this.state.streamConnected = Boolean(status.connected);
    this.state.streamMode = status.mode || this.state.streamMode;
    this.notify();
  }

  _appendHistory(newPoint) {
    if (!newPoint || !newPoint.ts) return;
    const existing = this.state.history;
    if (existing.length > 0 && existing[existing.length - 1].ts === newPoint.ts) {
      return;
    }
    // Keep last 150 points in memory
    const updated = [...existing, newPoint];
    if (updated.length > 150) {
      this.state.history = updated.slice(updated.length - 150);
    } else {
      this.state.history = updated;
    }
  }
}

export const store = new AppStore();
