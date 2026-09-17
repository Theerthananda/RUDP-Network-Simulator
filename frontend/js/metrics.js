/* Displays authoritative snapshots supplied by the Python transfer session. */
(() => {
  const ids = { packets_sent: "packetsSent", total_transmissions: "totalTransmissions", packets_received: "packetsReceived", packets_lost: "packetsLost", retransmissions: "retransmissions", packets_corrupted: "packetsCorrupted", checksum_errors: "checksumErrors", integrity_retransmissions: "integrityRetransmissions", duplicates: "duplicates", acks_received: "acksReceived", acks_lost: "acksLost" };
  let current = {};
  const write = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
  function apply(metrics = {}) {
    current = { ...current, ...metrics };
    Object.entries(ids).forEach(([name, id]) => write(id, current[name] || 0));
    write("averageRtt", current.average_rtt_ms == null ? "N/A" : `${Number(current.average_rtt_ms).toFixed(1)} ms`);
    write("throughput", `${(Number(current.throughput_bps || 0) / 1024).toFixed(2)} KB/s`);
  }
  function reset() { current = {}; apply({}); }
  window.RUDPMetrics = { apply, reset, summary: () => ({ ...current }) };
  document.addEventListener("DOMContentLoaded", reset);
})();
