(function () {
  "use strict";
  var last = null;
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
  function code(text) { return el("code", "", text); }
  function link(prefix, id) { var a = el("a", "", id); a.href = "#" + prefix + id; return a; }
  function short(sha) { return String(sha || "").slice(0, 7); }
  function append(node, parts) {
    parts.forEach(function (p) { node.appendChild(typeof p === "string" ? document.createTextNode(p) : p); });
    return node;
  }
  function list(label, rows) {
    var wrap = append(el("div", "", null), [el("strong", "", label + ":")]);
    var ul = el("ul", "", null);
    rows.forEach(function (parts) { ul.appendChild(append(el("li", "", null), parts)); });
    wrap.appendChild(ul);
    return wrap;
  }
  function byItem(live) {
    var out = {}, rows = (live && live.receipts) || [];
    if (!Array.isArray(rows)) { rows = Object.keys(rows).map(function (k) { return rows[k]; }); }
    rows.forEach(function (r) { out[r.item] = r; });
    return out;
  }
  function where(prov) {
    if (prov.source === "commit") { return "commit " + short(prov.commit) + ", tree " + short(prov.tree); }
    return "staged, tree " + short(prov.tree);
  }
  function drawStatus(node, receipt) {
    var status = receipt ? (PIP.kinds[(receipt.outcome || {}).kind] || PIP.pending) : PIP.pending;
    node.textContent = status;
    node.setAttribute("data-status", status);
  }
  function drawStatuses(id, receipt) {
    var named = id.replace(/\\/g, "\\\\").replace(/"/g, "\\\"");
    Array.prototype.forEach.call(document.querySelectorAll(".status[data-status-for=\"" + named + "\"]"),
      function (node) { drawStatus(node, receipt); });
  }
  function cites(change) { return [" (cites ", link("change-", change), ")"]; }
  function drawDeviations(box, dev) {
    var extras = (dev.extra_files || []).map(function (x) { return [code(x.path)].concat(cites(x.change)); });
    var subs = (dev.substitutions || []).map(function (s) {
      return [code(s.planned), " replaced by ", code(s.node)].concat(cites(s.change));
    });
    if (extras.length) { box.appendChild(list("Extra files", extras)); }
    if (subs.length) { box.appendChild(list("Substitutions", subs)); }
  }
  function drawReceipt(box, r) {
    clear(box);
    if (!r) { box.appendChild(el("p", "note", "No receipt.")); return; }
    var outcome = r.outcome || {}, head = "Recorded " + r.date;
    if (outcome.provenance) { head += ", " + where(outcome.provenance); }
    box.appendChild(el("p", "", head));
    box.appendChild(append(el("p", "", null), [el("strong", "", "Evidence: "), String(r.evidence)]));
    if (outcome.tests) {
      var tests = outcome.tests;
      box.appendChild(list("Passed nodes", tests.nodes.map(function (n) { return [code(n)]; })));
      box.appendChild(append(el("p", "", null), [el("strong", "", "Command: "), code(tests.command)]));
    }
    drawDeviations(box, r.deviations || {});
  }
  function links(prefix, ids) {
    var parts = [];
    ids.forEach(function (id, i) {
      parts = parts.concat(i ? [", ", link(prefix, id)] : [link(prefix, id)]);
    });
    return parts;
  }
  function labelled(label, parts) {
    return append(el("p", "", null), [el("strong", "", label + ": ")].concat(parts));
  }
  function drawLinks(node, id, evo) {
    clear(node);
    var named = ((evo && evo.changes) || []).filter(function (c) {
      return (c.items || []).indexOf(id) >= 0;
    });
    node.hidden = !named.length;
    if (!named.length) { return; }
    append(node, [el("strong", "", "Design changes: ")].concat(links("change-", named.map(function (c) {
      return c.id;
    }))));
  }
  function drawChange(c) {
    var box = el("div", "change", null);
    box.id = "change-" + c.id;
    box.appendChild(el("h3", "", c.id + " (" + c.phase + ", " + c.date + ", " + c.discovered_by + ")"));
    var items = links("item-", c.items || []);
    box.appendChild(labelled("Items", items.length ? items : ["none"]));
    var was = c.original;
    box.appendChild(labelled("Was", [was.doc + " " + was.location + ": " + was.indicated]));
    box.appendChild(labelled("Issue", [c.issue.category + ": " + c.issue.why_free_form]));
    box.appendChild(labelled("Now", [c.new_outcome.doc + ": " + c.new_outcome.indicated]));
    box.appendChild(labelled("Why", [c.why_new_outcome.category + ": " + c.why_new_outcome.free_form]));
    return box;
  }
  function drawEvolution(evo) {
    var box = document.getElementById("evolution-entries");
    clear(box);
    var changes = (evo && evo.changes) || [];
    if (!evo) { box.appendChild(el("p", "note", "No DesignEvolution catalog in live.js.")); return; }
    if (!changes.length) { box.appendChild(el("p", "note", "The DesignEvolution catalog holds no change.")); }
    changes.forEach(function (c) { box.appendChild(drawChange(c)); });
  }
  function drawBuilt(live) {
    document.getElementById("live-missing").hidden = !!live;
    document.getElementById("live-built").hidden = !live;
    document.getElementById("live-built-at").textContent = live ? String(live.built) : "";
  }
  function draw(live) {
    var key = live ? JSON.stringify(live) : "";
    if (key === last) { return; }
    last = key;
    var receipts = byItem(live), evo = (live && live.evolution) || null;
    Array.prototype.forEach.call(document.querySelectorAll(".item[data-item]"), function (node) {
      var id = node.getAttribute("data-item");
      drawStatuses(id, receipts[id]);
      drawReceipt(node.querySelector(".receipt"), receipts[id]);
      drawLinks(node.querySelector(".changes"), id, evo);
    });
    drawEvolution(evo);
    drawBuilt(live);
  }
  function load() {
    var old = document.getElementById("plan-live");
    if (old) { old.parentNode.removeChild(old); }
    window.PLAN_LIVE = undefined;
    var tag = document.createElement("script");
    tag.id = "plan-live";
    tag.src = PIP.src + Date.now();
    tag.onload = function () { draw(window.PLAN_LIVE || null); };
    tag.onerror = function () { draw(null); };
    document.head.appendChild(tag);
  }
  load();
  window.setInterval(load, PIP.reloadMs);
})();
