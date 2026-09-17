/* Backend-event adapter: the browser visualizes; it never simulates packets. */
(() => {
  const API = "http://127.0.0.1:8000";
  let stream = null;
  let state = { running: false, totalPackets: 0, receivedPackets: 0, metrics: {} };
  function connect() {
    if (stream) return;
    stream = new EventSource(`${API}/api/events`);
    stream.onmessage = ({ data }) => { try { handleEvent(JSON.parse(data)); } catch (error) { console.error("Invalid RUDP event", error); } };
  }
  function animate(event) {
    const animation = window.RUDPAnimation; if (!animation) return;
    const sequence = event.sequence_number || 0;
    if (event.type === "packet_sent" || event.type === "retransmission") { animation.sender(); animation.network(); animation.packet(sequence, event.retransmission); }
    else if (event.type === "ack_sent" || event.type === "ack_received") { animation.receiver(); animation.network(); animation.ack(sequence); }
    else if (event.type === "packet_lost") animation.lost(sequence);
    else if (event.type === "packet_corrupted") animation.corrupted(sequence);
    else if (event.type === "packet_received") animation.receiver();
  }
  function handleEvent(event) {
    if (event.metrics) { state.metrics = event.metrics; window.RUDPMetrics?.apply(event.metrics); }
    if (Number.isFinite(event.total_packets)) state.totalPackets = event.total_packets;
    if (Number.isFinite(event.received_packets)) state.receivedPackets = event.received_packets;
    if (event.type === "transfer_started") { state.running = true; state.totalPackets = event.total_packets || 0; }
    if (["transfer_complete", "transfer_failed", "transfer_cancelled"].includes(event.type)) state.running = false;
    animate(event); window.dispatchEvent(new CustomEvent("rudp:backend-event", { detail: event }));
    if (event.type === "transfer_complete") window.dispatchEvent(new Event("rudp:transfer-complete"));
    if (event.type === "transfer_failed") window.dispatchEvent(new Event("rudp:transfer-failed"));
  }
  window.RUDPSimulator = {
    start() { state = { running: true, totalPackets: 0, receivedPackets: 0, metrics: {} }; window.RUDPMetrics?.reset(); connect(); },
    reset() { state = { running: false, totalPackets: 0, receivedPackets: 0, metrics: {} }; if (stream) { stream.close(); stream = null; } window.RUDPMetrics?.reset(); window.dispatchEvent(new Event("rudp:simulator-reset")); },
    connect, getState: () => ({ ...state }),
  };
  connect();
})();
