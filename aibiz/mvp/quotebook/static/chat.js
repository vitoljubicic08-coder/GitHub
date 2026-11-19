// Chat widget for the demo site. No external libraries; text is inserted with textContent only.
(function () {
  "use strict";
  var log = document.getElementById("log");
  var opts = document.getElementById("opts");
  var form = document.getElementById("f");
  var input = document.getElementById("msg");
  var KEY = "qb_conversation";
  var conversationId = null;
  try { conversationId = sessionStorage.getItem(KEY); } catch (e) { conversationId = null; }

  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return String(Date.now()) + Math.random().toString(16).slice(2);
  }

  function bubble(text, who) {
    var div = document.createElement("div");
    div.className = "msg " + who;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function showOptions(labels, values) {
    opts.textContent = "";
    (labels || []).forEach(function (label, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.addEventListener("click", function () { send((values && values[i]) || label, label); });
      opts.appendChild(b);
    });
  }

  var busy = false;
  function send(text, shown) {
    if (busy || !text.trim()) return;
    busy = true;
    bubble(shown || text, "me");
    showOptions([]);
    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message_id: uid(), text: text })
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    }).then(function (res) {
      if (res.status === 429) { bubble("Previše poruka u kratkom vremenu. Pokušajte za minutu.", "bot err"); return; }
      if (res.status !== 200) { bubble("Došlo je do greške. Pokušajte ponovno ili nas nazovite.", "bot err"); return; }
      conversationId = res.data.conversation_id;
      try { sessionStorage.setItem(KEY, conversationId); } catch (e) { /* private mode */ }
      bubble(res.data.text, "bot");
      showOptions(res.data.options, res.data.option_values);
    }).catch(function () {
      bubble("Veza nije uspjela. Provjerite internet i pokušajte ponovno.", "bot err");
    }).then(function () { busy = false; input.focus(); });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var t = input.value;
    input.value = "";
    send(t);
  });
  bubble("Pozdrav! Napišite koju uslugu trebate i kada vam odgovara. / Hi! Tell me which service you need and when.", "bot");
})();
