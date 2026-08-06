// options.js — port/token config for the bridge. The token is stored in chrome.storage.local
// and read only by background.js's bridgeFetch(); it is never referenced from content.js or
// panel.js's page context.

async function load() {
  const { bridgePort, bridgeToken, sessionCap } =
    await chrome.storage.local.get(["bridgePort", "bridgeToken", "sessionCap"]);
  document.getElementById("port").value = bridgePort || 8765;
  document.getElementById("token").value = bridgeToken || "";
  document.getElementById("session-cap").value = sessionCap || 5;
}

document.getElementById("save").addEventListener("click", async () => {
  const port = parseInt(document.getElementById("port").value, 10) || 8765;
  const token = document.getElementById("token").value.trim();
  const sessionCap = parseInt(document.getElementById("session-cap").value, 10) || 5;
  await chrome.storage.local.set({ bridgePort: port, bridgeToken: token, sessionCap });
  const status = document.getElementById("status");
  status.textContent = "Saved.";
  setTimeout(() => { status.textContent = ""; }, 1500);
});

load();
