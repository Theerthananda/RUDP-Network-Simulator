/* Application controller for the real RUDP backend. */
const fileInput = document.getElementById("fileInput");
const fileName = document.getElementById("fileName");
const startTransferButton = document.getElementById("startTransfer");
const resetSimulatorButton = document.getElementById("resetSimulator");
const eventLog = document.getElementById("eventLog");
const eventCount = document.getElementById("eventCount");
const statusText = document.getElementById("connectionStatusText");
const statusDot = document.getElementById("connectionStatus");
const transferStatus = document.getElementById("transferStatus");
const transferPackets = document.getElementById("transferPackets");
const progressBar = document.getElementById("progressBar");
const progressPercentage = document.getElementById("progressPercentage");
const state = { file: null, running: false, events: 0, protocol: "RUDP" };
const API = "http://127.0.0.1:8000";

function configuration() {
  const value = id => Number(document.getElementById(id).value);
  const config = { protocol: state.protocol, packetLoss: value("packetLoss"), networkDelay: value("networkDelay"), corruptionRate: value("corruptionRate"), packetSize: value("packetSize") };
  if (state.protocol === "RUDP") config.ackLoss = value("ackLoss");
  config[state.protocol === "RUDP" ? "windowSize" : "sendBatchSize"] = value("windowSize");
  const percentages = [config.packetLoss, config.corruptionRate, ...(state.protocol === "RUDP" ? [config.ackLoss] : [])];
  const sendSize = config.windowSize ?? config.sendBatchSize;
  if (!percentages.every(x => Number.isFinite(x) && x >= 0 && x <= 100) || !Number.isFinite(config.networkDelay) || config.networkDelay < 0 || !Number.isInteger(config.packetSize) || config.packetSize < 1 || !Number.isInteger(sendSize) || sendSize < 1) throw new Error("Please provide valid network settings.");
  return config;
}
function setProtocol(protocol) {
  state.protocol = protocol;
  const udp = protocol === "UDP";
  const ackLoss = document.getElementById("ackLoss");
  ackLoss.type = udp ? "text" : "number";
  ackLoss.disabled = udp;
  ackLoss.value = udp ? "N/A" : (ackLoss.dataset.rudpValue || "0");
  document.getElementById("ackLossUnit").textContent = udp ? "" : "%";
  document.getElementById("sendSizeLabel").textContent = udp ? "Send Batch Size" : "Window Size";
  document.querySelectorAll("[data-protocol]").forEach(button => {
    const selected = button.dataset.protocol === protocol;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}
document.querySelectorAll("[data-protocol]").forEach(button => button.addEventListener("click", () => {
  const ackLoss = document.getElementById("ackLoss");
  if (!ackLoss.disabled) ackLoss.dataset.rudpValue = ackLoss.value;
  setProtocol(button.dataset.protocol);
}));
function setStatus(text, color = "var(--color-success)") { statusText.textContent = text; statusDot.style.background = color; }
function setProgress(received, total) { const percentage = total ? Math.min(100, received * 100 / total) : 0; progressBar.style.width = `${percentage}%`; progressPercentage.textContent = `${Math.round(percentage)}%`; transferPackets.textContent = `${received} / ${total} packets`; }
function addEvent(message) { eventLog.querySelector(".event-log__empty")?.remove(); const item = document.createElement("div"); item.className = "event-log__item"; item.textContent = message; eventLog.prepend(item); state.events += 1; eventCount.textContent = `${state.events} ${state.events === 1 ? "event" : "events"}`; }
function resetView() { state.events = 0; eventLog.innerHTML = '<div class="event-log__empty">Waiting for network activity...</div>'; eventCount.textContent = "0 events"; setProgress(0, 0); transferStatus.textContent = "Ready to transfer"; }
async function toBase64(file) { const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ""; for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000)); return btoa(binary); }

fileInput.addEventListener("change", event => { state.file = event.target.files[0] || null; fileName.textContent = state.file ? state.file.name : "Choose a file"; if (state.file) addEvent(`Selected ${state.file.name} (${state.file.size} bytes)`); });
startTransferButton.addEventListener("click", async () => {
  if (state.running) return;
  try {
    if (!state.file) throw new Error("Select a file before starting a transfer.");
    const config = configuration(); state.running = true; startTransferButton.disabled = true; resetView();
    setStatus("Transfer Running", "var(--color-warning)"); transferStatus.textContent = `Uploading file to ${state.protocol} bridge...`;
    window.RUDPSimulator.start();
    const response = await fetch(`${API}/api/transfer`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: state.file.name, data: await toBase64(state.file), config }) });
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.message || "Transfer could not be started.");
    addEvent(`Transfer accepted by backend (${result.session_id.slice(0, 8)})`); transferStatus.textContent = "UDP sender, gateway and receiver are starting...";
  } catch (error) {
    state.running = false; startTransferButton.disabled = false; setStatus("Simulator Ready"); transferStatus.textContent = "Transfer could not start"; addEvent(`Error: ${error.message}`);
  }
});
resetSimulatorButton.addEventListener("click", async () => {
  try { await fetch(`${API}/api/transfer/cancel`, { method: "POST" }); } catch (_) { /* Backend may be offline. */ }
  state.running = false; state.file = null; fileInput.value = ""; fileName.textContent = "Choose a file"; startTransferButton.disabled = false;
  ["packetLoss", "ackLoss", "corruptionRate"].forEach(id => document.getElementById(id).value = 0); document.getElementById("ackLoss").dataset.rudpValue = "0"; document.getElementById("networkDelay").value = 100; document.getElementById("packetSize").value = 1024; document.getElementById("windowSize").value = 3; setProtocol(state.protocol);
  window.RUDPSimulator.reset(); window.RUDPSimulator.connect(); resetView(); setStatus("Simulator Ready"); addEvent("Simulator reset; active UDP transfer cancelled.");
});
window.addEventListener("rudp:backend-event", ({ detail: event }) => {
  if (event.type !== "packet_delivered") addEvent(event.message || event.type);
  const total = event.total_packets ?? window.RUDPSimulator.getState().totalPackets;
  const received = event.received_packets ?? (event.metrics?.packets_received ?? 0);
  setProgress(received, total);
  if (event.type === "transfer_complete") { state.running = false; startTransferButton.disabled = false; setStatus("Transfer Complete"); transferStatus.textContent = event.integrity_verified === false ? "UDP transfer completed without reliability recovery" : "File reconstructed and SHA-256 verified"; }
  if (event.type === "transfer_failed") { state.running = false; startTransferButton.disabled = false; setStatus("Transfer Failed", "var(--color-danger)"); transferStatus.textContent = event.error || "Transfer failed"; }
  if (event.type === "transfer_cancelled") { transferStatus.textContent = "Transfer cancelled"; }
});
setProtocol("RUDP"); setStatus("Simulator Ready"); resetView();
