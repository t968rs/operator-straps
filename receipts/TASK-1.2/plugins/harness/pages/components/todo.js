(function () {
  "use strict";
  // One reload per live stamp: a page that still disagrees with todo_live.js after reloading for that
  // stamp waits for the next render instead of reloading every interval.
  var KEY = "todo-reloaded-for:" + window.location.pathname;
  function reloadFor(stamp) {
    try {
      if (window.sessionStorage.getItem(KEY) === stamp) { return; }
      window.sessionStorage.setItem(KEY, stamp);
    } catch (e) { /* storage unavailable: reload as before */ }
    window.location.reload();
  }
  function load() {
    var old = document.getElementById("todo-live");
    if (old) { old.parentNode.removeChild(old); }
    window.TODO_LIVE = undefined;
    var tag = document.createElement("script");
    tag.id = "todo-live";
    tag.src = TODO_PAGE.src + Date.now();
    tag.onload = function () {
      var live = window.TODO_LIVE;
      if (live && live.stamp && live.stamp !== TODO_PAGE.stamp) { reloadFor(live.stamp); }
    };
    document.head.appendChild(tag);
  }
  load();
  window.setInterval(load, TODO_PAGE.reloadMs);
})();
