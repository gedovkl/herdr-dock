// Shared Property Inspector script for the widget keys: every element with data-setting="name"
// is loaded from and saved to the key's settings. Checkboxes store true/false, the rest text.
(function () {
  let socket = null;
  let context = "";
  const fields = () => Array.from(document.querySelectorAll("[data-setting]"));

  function collect() {
    const settings = {};
    for (const el of fields()) {
      const name = el.dataset.setting;
      if (el.type === "checkbox") settings[name] = el.checked;
      else if (el.value.trim() !== "") settings[name] = el.value.trim();
    }
    return settings;
  }

  function save() {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ event: "setSettings", context, payload: collect() }));
    }
  }

  function load(settings) {
    for (const el of fields()) {
      const value = settings[el.dataset.setting];
      if (el.type === "checkbox") el.checked = value === undefined ? el.defaultChecked : !!value;
      else if (value !== undefined) el.value = value;
    }
  }

  // Called by the app (Elgato Stream Deck, OpenDeck) when the inspector opens.
  window.connectElgatoStreamDeckSocket = function (port, uuid, registerEvent, _info, actionInfo) {
    context = uuid;
    try {
      load(JSON.parse(actionInfo).payload.settings || {});
    } catch (_) { /* no settings yet */ }
    socket = new WebSocket("ws://127.0.0.1:" + port);
    socket.onopen = () => socket.send(JSON.stringify({ event: registerEvent, uuid }));
  };

  document.addEventListener("change", save);
})();
