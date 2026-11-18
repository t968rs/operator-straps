(function () {
  "use strict";
  // Viewer theme: auto follows prefers-color-scheme, light and dark set data-theme on <html>. The choice
  // lives in localStorage so a page that reloads itself after a render keeps it.
  var KEY = "harness-page-theme";
  var NEXT = {auto: "light", light: "dark", dark: "auto"};
  var root = document.documentElement;
  var current = "auto";
  try {
    var saved = window.localStorage.getItem(KEY);
    if (NEXT.hasOwnProperty(saved)) { current = saved; }
  } catch (e) { /* storage unavailable: auto */ }
  function apply() {
    if (current === "auto") { root.removeAttribute("data-theme"); }
    else { root.setAttribute("data-theme", current); }
  }
  function addButton() {
    var button = document.createElement("button");
    button.id = "theme-toggle";
    button.type = "button";
    button.title = "Cycle the page theme: auto, light, dark";
    button.textContent = "Theme: " + current;
    button.onclick = function () {
      current = NEXT[current];
      try { window.localStorage.setItem(KEY, current); } catch (e) { /* kept for this page only */ }
      apply();
      button.textContent = "Theme: " + current;
    };
    (document.querySelector(".corner") || document.body).appendChild(button);
  }
  apply();
  if (document.body) { addButton(); } else { document.addEventListener("DOMContentLoaded", addButton); }
})();
