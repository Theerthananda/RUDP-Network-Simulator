/*
 * Dashboard charts driven exclusively by backend metric snapshots.
 * Raw metric samples stay in chartState; only the SVG rendering is downsampled.
 */
(() => {
  const chartState = {
    loss: [],
    rtt: [],
    throughput: [],
    currentThroughput: null,
    delayMs: null,
    activeExperimentId: null,
    activeFilename: null,
    activeStartedAt: null,
    recordedExperimentId: null,
    activeFileSize: null,
    latestMetrics: null,
    lastLoss: null,
    lastRetransmissions: null,
    lastAckCount: 0,
    lastAverageRtt: 0,
  };

  const DIMENSIONS = {
    width: 1000,
    height: 360,
    left: 76,
    right: 30,
    top: 20,
    bottom: 58,
  };
  const MAX_RENDERED_POINTS = 240;
  const palette = {
    loss: "#ef4444",
    retransmissions: "#f59e0b",
    rtt: "#60a5fa",
    throughput: "#34d399",
  };
  const pendingRenders = new Set();
  let renderFrame = null;
  const svg = (name, attributes = {}, content = "") =>
    `<${name} ${Object.entries(attributes)
      .map(([key, value]) => `${key}="${String(value)}"`)
      .join(" ")}>${content}</${name}>`;
  const finite = (value) =>
    Number.isFinite(Number(value)) ? Number(value) : 0;
  const host = (id) => document.getElementById(id);

  function setPanel(id, content) {
    const panel = host(id);
    if (panel) panel.innerHTML = content;
  }

  function format(value, unit = "") {
    const number = finite(value);
    const digits = Math.abs(number) < 10 && number % 1 ? 1 : 0;
    return `${number.toFixed(digits)}${unit}`;
  }

  function formatBytes(value) {
    const bytes = finite(value);
    if (!bytes) return "0 B";
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatTime(timestamp) {
    const seconds = Number(timestamp);
    if (!Number.isFinite(seconds)) return "—";
    return new Date(seconds * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function experimentColor(index) {
    return ["#34d399", "#60a5fa", "#a855f7", "#f59e0b", "#06b6d4"][index % 5];
  }

  function statRow(label, value, color = "") {
    const dot = color
      ? `<i class="graph-series-dot" style="--series-color:${color}"></i>`
      : "";
    return `<div class="graph-stat-row"><span class="graph-stat-label">${dot}${label}</span><strong class="graph-stat-value">${value}</strong></div>`;
  }

  function niceStep(range, ticks = 4) {
    const rough = Math.max(range / ticks, 0.0001);
    const exponent = Math.floor(Math.log10(rough));
    const base = rough / 10 ** exponent;
    const factor = base <= 1 ? 1 : base <= 2 ? 2 : base <= 5 ? 5 : 10;
    return factor * 10 ** exponent;
  }

  function bounds(values, { includeZero = false } = {}) {
    const data = values.filter(Number.isFinite);
    if (!data.length) return { min: 0, max: 1, step: 0.25 };
    let min = Math.min(...data);
    let max = Math.max(...data);
    if (includeZero) min = Math.min(0, min);
    if (min === max) {
      const padding = Math.max(Math.abs(max) * 0.2, 1);
      min = includeZero ? 0 : min - padding;
      max += padding;
    } else {
      const padding = (max - min) * 0.12;
      min = includeZero ? 0 : min - padding;
      max += padding;
    }
    const step = niceStep(max - min);
    return {
      min: Math.floor(min / step) * step,
      max: Math.ceil(max / step) * step,
      step,
    };
  }

  function xBounds(values) {
    if (values.length < 2) {
      const value = values[0] ?? 0;
      const padding = Math.max(Math.abs(value) * 0.25, 10);
      return { min: Math.max(0, value - padding), max: value + padding };
    }
    return bounds(values);
  }

  // Retains first/last plus the local min/max in every rendering bucket.
  // The complete, authoritative metric stream remains untouched in chartState.
  function visualSamples(points, maximum = MAX_RENDERED_POINTS) {
    if (points.length <= maximum) return points;
    const interior = points.slice(1, -1);
    const bucketCount = Math.max(1, Math.floor((maximum - 2) / 4));
    const selected = [points[0]];
    for (let bucketIndex = 0; bucketIndex < bucketCount; bucketIndex += 1) {
      const start = Math.floor((bucketIndex * interior.length) / bucketCount);
      const end = Math.max(
        start + 1,
        Math.floor(((bucketIndex + 1) * interior.length) / bucketCount),
      );
      const bucket = interior.slice(start, end);
      const candidates = [bucket[0], bucket[bucket.length - 1]];
      candidates.push(
        bucket.reduce(
          (lowest, point) => (point.y < lowest.y ? point : lowest),
          bucket[0],
        ),
      );
      candidates.push(
        bucket.reduce(
          (highest, point) => (point.y > highest.y ? point : highest),
          bucket[0],
        ),
      );
      candidates
        .map((point) => ({ point, index: interior.indexOf(point) }))
        .sort((a, b) => a.index - b.index)
        .forEach(({ point }) => {
          if (selected[selected.length - 1] !== point) selected.push(point);
        });
    }
    if (selected[selected.length - 1] !== points[points.length - 1])
      selected.push(points[points.length - 1]);
    return selected;
  }

  function axes({
    x,
    y,
    xFormatter = (value) => format(value),
    yFormatter = (value) => format(value),
    xTitle = "Transfer update",
    yTitle = "Value",
  }) {
    const { width, height, left, right, top, bottom } = DIMENSIONS;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const scaleX = (value) =>
      left + ((value - x.min) / (x.max - x.min || 1)) * plotWidth;
    const scaleY = (value) =>
      top + (1 - (value - y.min) / (y.max - y.min || 1)) * plotHeight;
    const parts = [];
    for (let tick = y.min; tick <= y.max + y.step / 4; tick += y.step) {
      const py = scaleY(tick);
      parts.push(
        svg("line", {
          x1: left,
          y1: py,
          x2: width - right,
          y2: py,
          class: "rudp-chart__grid",
        }),
      );
      parts.push(
        svg(
          "text",
          {
            x: left - 10,
            y: py + 4,
            class: "rudp-chart__axis-label",
            "text-anchor": "end",
          },
          yFormatter(tick),
        ),
      );
    }
    const xStep = (x.max - x.min) / 5;
    for (let index = 0; index <= 5; index += 1) {
      const tick = x.min + xStep * index;
      const px = scaleX(tick);
      parts.push(
        svg("line", {
          x1: px,
          y1: top,
          x2: px,
          y2: height - bottom,
          class: "rudp-chart__grid rudp-chart__grid--vertical",
        }),
      );
      parts.push(
        svg(
          "text",
          {
            x: px,
            y: height - bottom + 20,
            class: "rudp-chart__axis-label",
            "text-anchor": "middle",
          },
          xFormatter(tick),
        ),
      );
    }
    parts.push(
      svg("line", {
        x1: left,
        y1: height - bottom,
        x2: width - right,
        y2: height - bottom,
        class: "rudp-chart__axis",
      }),
    );
    parts.push(
      svg("line", {
        x1: left,
        y1: top,
        x2: left,
        y2: height - bottom,
        class: "rudp-chart__axis",
      }),
    );
    parts.push(
      svg(
        "text",
        {
          x: left + plotWidth / 2,
          y: height - 10,
          class: "rudp-chart__axis-title",
          "text-anchor": "middle",
        },
        xTitle,
      ),
    );
    parts.push(
      svg(
        "text",
        {
          x: 18,
          y: top + plotHeight / 2,
          class: "rudp-chart__axis-title",
          transform: `rotate(-90 18 ${top + plotHeight / 2})`,
          "text-anchor": "middle",
        },
        yTitle,
      ),
    );
    return { parts, scaleX, scaleY };
  }

  function linePath(
    points,
    scaleX,
    scaleY,
    color,
    { marker = "circle", dashed = false } = {},
  ) {
    if (!points.length) return "";
    const coordinates = points.map(
      (point) => `${scaleX(point.x)},${scaleY(point.y)}`,
    );
    const line =
      points.length > 1
        ? svg("polyline", {
            points: coordinates.join(" "),
            class: `rudp-chart__line${dashed ? " rudp-chart__line--dashed" : ""}`,
            stroke: color,
          })
        : "";
    const markerPoints =
      points.length > 160 ? visualSamples(points, 80) : points;
    const markers = markerPoints
      .map((point) => {
        const x = scaleX(point.x);
        const y = scaleY(point.y);
        if (marker === "diamond")
          return svg("polygon", {
            points: `${x},${y - 5} ${x + 5},${y} ${x},${y + 5} ${x - 5},${y}`,
            class: "rudp-chart__point rudp-chart__point--retransmission",
            style: `stroke:${color}`,
          });
        return svg("circle", {
          cx: x,
          cy: y,
          r: 3.5,
          class: "rudp-chart__point",
          fill: color,
        });
      })
      .join("");
    return line + markers;
  }

  function scatter(points, scaleX, scaleY, color) {
    const repetitions = new Map();
    return points
      .map((point) => {
        const key = `${point.x}|${point.y}`;
        const occurrence = repetitions.get(key) || 0;
        repetitions.set(key, occurrence + 1);
        const radius = Math.min(3.8 + occurrence * 1.3, 9);
        const pointColor = point.color || color;
        return svg("circle", {
          cx: scaleX(point.x),
          cy: scaleY(point.y),
          r: radius,
          class: "rudp-chart__point rudp-chart__point--experiment",
          fill: occurrence ? "none" : pointColor,
          stroke: pointColor,
          "fill-opacity": occurrence ? 1 : 0.82,
        });
      })
      .join("");
  }

  function legend(items) {
    return `<div class="rudp-chart__legend">${items.map((item) => `<span><i style="--series-color:${item.color}"></i>${item.label}</span>`).join("")}</div>`;
  }

  function renderLossStats() {
    const metrics = chartState.latestMetrics;
    if (!metrics) {
      setPanel(
        "lossStats",
        '<div class="graph-side-panel__empty">Packet statistics will appear during a transfer.</div>',
      );
      return;
    }
    const total = finite(metrics.total_transmissions);
    const lost = finite(metrics.packets_lost);
    const retransmissions = finite(metrics.retransmissions);
    const rate = (value) =>
      total ? `${((value * 100) / total).toFixed(2)}%` : "0.00%";
    setPanel(
      "lossStats",
      `<h4 class="graph-stat-title">Packet Statistics</h4><div class="graph-stat-list">${statRow("Packets lost", format(lost), palette.loss)}${statRow("Retransmissions", format(retransmissions), palette.retransmissions)}<div class="graph-stat-divider"></div>${statRow("Total DATA transmissions", format(total))}${statRow("Loss rate", rate(lost))}${statRow("Retransmission rate", rate(retransmissions))}</div>`,
    );
  }

  function renderRttStats() {
    const metrics = chartState.latestMetrics;
    if (!metrics) {
      setPanel(
        "rttStats",
        '<div class="graph-side-panel__empty">RTT statistics will appear after acknowledgements arrive.</div>',
      );
      return;
    }
    const samples = chartState.rtt.map((sample) => sample.y);
    const minimum = samples.length ? Math.min(...samples) : 0;
    const maximum = samples.length ? Math.max(...samples) : 0;
    setPanel(
      "rttStats",
      `<h4 class="graph-stat-title">RTT Statistics</h4><div class="graph-stat-list">${statRow("Average RTT", format(metrics.average_rtt_ms, " ms"), palette.rtt)}${statRow("Minimum RTT", format(minimum, " ms"))}${statRow("Maximum RTT", format(maximum, " ms"))}${statRow("Total samples", format(chartState.rtt.length))}</div>`,
    );
  }

  function renderExperimentHistory() {
    const observations = chartState.throughput;
    if (!observations.length) {
      setPanel(
        "experimentHistory",
        '<h4 class="graph-stat-title">Experiment History</h4><div class="graph-side-panel__empty">Completed transfer experiments will appear here.</div>',
      );
      return;
    }
    const rows = observations
      .map(
        (observation, index) =>
          `<tr><td>${index + 1}</td><td><i class="graph-history__dot" style="--series-color:${experimentColor(index)}"></i>${format(observation.delay, " ms")}</td><td>${format(observation.throughput, " KB/s")}</td><td>${formatBytes(observation.fileSize)}</td><td>${formatTime(observation.completedAt)}</td></tr>`,
      )
      .join("");
    setPanel(
      "experimentHistory",
      `<h4 class="graph-stat-title">Experiment History</h4><div class="graph-history"><table class="graph-history__table"><thead><tr><th>#</th><th>Delay</th><th>Throughput</th><th>File size</th><th>Time</th></tr></thead><tbody>${rows}</tbody></table></div>`,
    );
  }

  function renderLineChart(id, series, options) {
    const container = host(id);
    if (!container) return;
    const allPoints = series.flatMap((item) => item.points);
    if (!allPoints.length) {
      container.innerHTML =
        '<div class="rudp-chart__empty">Waiting for data</div>';
      return;
    }
    const x = bounds(
      allPoints.map((point) => point.x),
      { includeZero: true },
    );
    const y = bounds(
      allPoints.map((point) => point.y),
      { includeZero: options.includeZero },
    );
    const chart = axes({ x, y, ...options });
    series.forEach((item) =>
      chart.parts.push(
        linePath(
          visualSamples(item.points),
          chart.scaleX,
          chart.scaleY,
          item.color,
          item.style,
        ),
      ),
    );
    container.innerHTML = `${legend(series.map((item) => ({ color: item.color, label: item.label })))}<svg class="rudp-chart" viewBox="0 0 ${DIMENSIONS.width} ${DIMENSIONS.height}" preserveAspectRatio="none" role="img" aria-label="${options.ariaLabel}">${chart.parts.join("")}</svg>`;
  }

  function renderLoss() {
    renderLineChart(
      "lossGraph",
      [
        {
          label: "Packets lost",
          color: palette.loss,
          points: chartState.loss.map((sample) => ({
            x: sample.x,
            y: sample.loss,
          })),
        },
        {
          label: "Retransmissions",
          color: palette.retransmissions,
          points: chartState.loss.map((sample) => ({
            x: sample.x,
            y: sample.retransmissions,
          })),
          style: { marker: "circle", dashed: true },
        },
      ],
      {
        includeZero: true,
        xFormatter: (value) => format(value),
        yFormatter: (value) => format(value),
        xTitle: "DATA transmissions",
        yTitle: "Packets",
        ariaLabel: "Packet loss and retransmissions over DATA transmissions",
      },
    );
    renderLossStats();
  }

  function renderRtt() {
    renderLineChart(
      "rttGraph",
      [
        {
          label: "RTT measurement",
          color: palette.rtt,
          points: chartState.rtt,
        },
      ],
      {
        includeZero: false,
        xFormatter: (value) => format(value),
        yFormatter: (value) => format(value, " ms"),
        xTitle: "Acknowledged DATA packets",
        yTitle: "RTT (ms)",
        ariaLabel: "Measured packet round-trip time in milliseconds",
      },
    );
    renderRttStats();
  }

  function renderThroughput() {
    const container = host("throughputGraph");
    if (!container) return;
    const observations = chartState.throughput;
    if (!observations.length) {
      container.innerHTML =
        '<div class="rudp-chart__empty">Completed transfer experiments will appear here</div>';
      renderExperimentHistory();
      return;
    }
    const x = xBounds(observations.map((observation) => observation.delay));
    const y = bounds(
      observations.map((observation) => observation.throughput),
      { includeZero: true },
    );
    const chart = axes({
      x,
      y,
      xFormatter: (value) => format(value, " ms"),
      yFormatter: (value) => format(value, " KB/s"),
      xTitle: "Configured network delay (ms)",
      yTitle: "Measured throughput (KB/s)",
      ariaLabel:
        "Measured throughput for completed file-transfer experiments by configured network delay",
    });
    chart.parts.push(
      scatter(
        observations.map((observation, index) => ({
          x: observation.delay,
          y: observation.throughput,
          color: experimentColor(index),
        })),
        chart.scaleX,
        chart.scaleY,
        palette.throughput,
      ),
    );
    const count = observations.length;
    const note =
      count === 1
        ? "1 completed experiment recorded."
        : `${count} completed experiments recorded.`;
    container.innerHTML = `${legend([{ color: palette.throughput, label: "Completed experiment" }])}<div class="rudp-chart__observation">${note}</div><svg class="rudp-chart" viewBox="0 0 ${DIMENSIONS.width} ${DIMENSIONS.height}" preserveAspectRatio="none" role="img" aria-label="Measured throughput by configured network delay">${chart.parts.join("")}</svg>`;
    renderExperimentHistory();
  }

  function schedule(render) {
    pendingRenders.add(render);
    if (renderFrame !== null) return;
    const flush = () => {
      renderFrame = null;
      const renders = [...pendingRenders];
      pendingRenders.clear();
      renders.forEach((draw) => draw());
    };
    renderFrame =
      typeof requestAnimationFrame === "function"
        ? requestAnimationFrame(flush)
        : setTimeout(flush, 0);
  }

  function reset() {
    chartState.loss = [];
    chartState.rtt = [];
    chartState.throughput = [];
    chartState.currentThroughput = null;
    chartState.delayMs = null;
    chartState.activeExperimentId = null;
    chartState.activeFilename = null;
    chartState.activeStartedAt = null;
    chartState.activeFileSize = null;
    chartState.latestMetrics = null;
    chartState.recordedExperimentId = null;
    chartState.lastLoss = chartState.lastRetransmissions = null;
    chartState.lastAckCount = chartState.lastAverageRtt = 0;
    renderLoss();
    renderRtt();
    renderThroughput();
  }

  function selectedDelay() {
    const input = document.getElementById("networkDelay");
    return input ? Math.max(0, finite(input.value)) : 0;
  }

  window.addEventListener("rudp:backend-event", ({ detail: event }) => {
    if (event.type === "transfer_started") {
      // Keep completed experiments for Graph 3, but begin fresh live series.
      chartState.loss = [];
      chartState.rtt = [];
      chartState.currentThroughput = null;
      chartState.lastLoss = chartState.lastRetransmissions = null;
      chartState.lastAckCount = chartState.lastAverageRtt = 0;
      chartState.delayMs = selectedDelay();
      chartState.activeExperimentId =
        event.session_id || `${event.timestamp || Date.now()}`;
      chartState.activeFilename = event.filename || "Unnamed transfer";
      chartState.activeStartedAt = event.timestamp || Date.now();
      chartState.activeFileSize = finite(event.file_size);
      chartState.recordedExperimentId = null;
      schedule(renderLoss);
      schedule(renderRtt);
    }
    if (!event.metrics) return;
    const metrics = event.metrics;
    chartState.latestMetrics = metrics;
    const total = finite(metrics.total_transmissions);
    const loss = finite(metrics.packets_lost);
    const retransmissions = finite(metrics.retransmissions);
    if (
      loss !== chartState.lastLoss ||
      retransmissions !== chartState.lastRetransmissions ||
      event.type === "transfer_complete"
    ) {
      chartState.loss.push({ x: total, loss, retransmissions });
      chartState.lastLoss = loss;
      chartState.lastRetransmissions = retransmissions;
      schedule(renderLoss);
    }

    const acknowledgements = finite(metrics.acks_received);
    const averageRtt = finite(metrics.average_rtt_ms);
    if (acknowledgements > chartState.lastAckCount) {
      // Keep the existing RTT derivation from the authoritative running average.
      const countDelta = acknowledgements - chartState.lastAckCount;
      const measuredRtt =
        (averageRtt * acknowledgements -
          chartState.lastAverageRtt * chartState.lastAckCount) /
        countDelta;
      chartState.rtt.push({ x: acknowledgements, y: Math.max(0, measuredRtt) });
      chartState.lastAckCount = acknowledgements;
      chartState.lastAverageRtt = averageRtt;
      schedule(renderRtt);
    }

    // Statistics panels use the same authoritative snapshot as the graphs.
    schedule(renderLoss);
    schedule(renderRtt);

    const throughput = finite(metrics.throughput_bps) / 1024;
    chartState.currentThroughput = {
      delay: chartState.delayMs ?? selectedDelay(),
      throughput,
      filename: chartState.activeFilename,
      sessionId: chartState.activeExperimentId,
      startedAt: chartState.activeStartedAt,
      fileSize: chartState.activeFileSize || finite(event.file_size),
    };
    if (
      event.type === "transfer_complete" &&
      chartState.recordedExperimentId !== chartState.activeExperimentId
    ) {
      chartState.throughput.push({
        ...chartState.currentThroughput,
        status: "completed",
        completedAt: event.timestamp || Date.now(),
      });
      chartState.currentThroughput = null;
      chartState.recordedExperimentId = chartState.activeExperimentId;
      schedule(renderThroughput);
    }
    if (event.type === "transfer_failed" || event.type === "transfer_cancelled")
      chartState.currentThroughput = null;
  });

  window.addEventListener("rudp:simulator-reset", reset);
  window.RUDPGraphs = { reset };
  document.addEventListener("DOMContentLoaded", reset);
})();
