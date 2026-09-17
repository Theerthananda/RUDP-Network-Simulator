/* =================================
   RUDP NETWORK SIMULATOR
   PACKET ANIMATION ENGINE
================================= */

/* ================================
   DOM ELEMENTS
================================ */

const packetContainer = document.getElementById("packetContainer");

const networkVisualization = document.getElementById("networkVisualization");

/* ================================
   ANIMATION CONFIGURATION
================================ */

const ANIMATION_DURATION = 900;

/* ================================
   CREATE PACKET ELEMENT
================================ */

function createPacketElement(sequenceNumber, isRetransmission = false) {
  const packetElement = document.createElement("div");

  packetElement.className = "network-packet";

  if (isRetransmission) {
    packetElement.classList.add("network-packet--retransmission");
  }

  packetElement.textContent = `#${sequenceNumber}`;

  packetElement.setAttribute(
    "aria-label",
    isRetransmission
      ? `Retransmitted packet ${sequenceNumber}`
      : `Data packet ${sequenceNumber}`,
  );

  return packetElement;
}

/* ================================
   ANIMATE PACKET
================================ */

function animateNetworkPacket(sequenceNumber, isRetransmission = false) {
  if (!packetContainer) {
    return;
  }

  const packetElement = createPacketElement(sequenceNumber, isRetransmission);

  packetContainer.appendChild(packetElement);

  /*
   * Force the browser to register
   * the initial position before
   * starting the animation.
   */

  packetElement.getBoundingClientRect();

  packetElement.classList.add("network-packet--moving");

  /*
   * Remove the element after
   * the animation finishes.
   */

  window.setTimeout(() => {
    packetElement.classList.add("network-packet--received");

    window.setTimeout(() => {
      packetElement.remove();
    }, 250);
  }, ANIMATION_DURATION);
}

/* ================================
   CREATE ACK ANIMATION
================================ */

function animateAck(sequenceNumber) {
  if (!packetContainer) {
    return;
  }

  const ackElement = document.createElement("div");

  ackElement.className = "network-packet network-packet--ack";

  ackElement.textContent = `ACK #${sequenceNumber}`;

  ackElement.setAttribute(
    "aria-label",
    `Acknowledgement for packet ${sequenceNumber}`,
  );

  packetContainer.appendChild(ackElement);

  ackElement.getBoundingClientRect();

  ackElement.classList.add("network-packet--ack-moving");

  window.setTimeout(() => {
    ackElement.remove();
  }, ANIMATION_DURATION);
}

/* ================================
   LOST PACKET ANIMATION
================================ */

function animateLostPacket(sequenceNumber) {
  if (!packetContainer) {
    return;
  }

  const packetElement = createPacketElement(sequenceNumber);

  packetElement.classList.add("network-packet--lost");

  packetContainer.appendChild(packetElement);

  packetElement.getBoundingClientRect();

  packetElement.classList.add("network-packet--lost-moving");

  window.setTimeout(() => {
    packetElement.remove();
  }, ANIMATION_DURATION);
}

/* ================================
   CORRUPTED PACKET ANIMATION
================================ */

function animateCorruptedPacket(sequenceNumber) {
  if (!packetContainer) {
    return;
  }

  const packetElement = createPacketElement(sequenceNumber);

  packetElement.classList.add("network-packet--corrupted");

  packetContainer.appendChild(packetElement);

  packetElement.getBoundingClientRect();

  packetElement.classList.add("network-packet--corrupted-moving");

  window.setTimeout(() => {
    packetElement.remove();
  }, ANIMATION_DURATION);
}

/* ================================
   NODE ACTIVITY
================================ */

function highlightNode(nodeId, duration = 500) {
  const node = document.getElementById(nodeId);

  if (!node) {
    return;
  }

  node.classList.add("network-node--active");

  window.setTimeout(() => {
    node.classList.remove("network-node--active");
  }, duration);
}

/* ================================
   SENDER ACTIVITY
================================ */

function highlightSender() {
  highlightNode("senderNode");
}

/* ================================
   RECEIVER ACTIVITY
================================ */

function highlightReceiver() {
  highlightNode("receiverNode");
}

/* ================================
   NETWORK ACTIVITY
================================ */

function highlightNetwork() {
  if (!networkVisualization) {
    return;
  }

  networkVisualization.classList.add("network-visualization--active");

  window.setTimeout(() => {
    networkVisualization.classList.remove("network-visualization--active");
  }, 500);
}

/* ================================
   DEMO PACKET
================================ */

function playDemoPacket(sequenceNumber = 1) {
  highlightSender();

  highlightNetwork();

  animateNetworkPacket(sequenceNumber);

  window.setTimeout(() => {
    highlightReceiver();
  }, ANIMATION_DURATION);
}

/* ================================
   PUBLIC ANIMATION API
================================ */

window.RUDPAnimation = {
  packet: animateNetworkPacket,

  ack: animateAck,

  lost: animateLostPacket,

  corrupted: animateCorruptedPacket,

  sender: highlightSender,

  receiver: highlightReceiver,

  network: highlightNetwork,

  demo: playDemoPacket,
};
