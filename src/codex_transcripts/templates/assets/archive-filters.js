(function() {
  var container = document.querySelector("[data-archive-filter-root]");
  if (!container) return;

  var rows = Array.prototype.slice.call(
    container.querySelectorAll(".archive-session-item"),
  );
  if (!rows.length) return;

  var fromInput = document.getElementById("filter-from-date");
  var toInput = document.getElementById("filter-to-date");
  var toolInput = document.getElementById("filter-tool");
  var repoInput = document.getElementById("filter-repo");
  var branchInput = document.getElementById("filter-branch");
  var errorOnlyInput = document.getElementById("filter-error-only");
  var resetBtn = document.getElementById("filter-reset-btn");
  var countLabel = document.getElementById("filter-result-count");

  function parseDay(value) {
    if (!value) return null;
    var date = new Date(value + "T00:00:00");
    if (isNaN(date.getTime())) return null;
    return date;
  }

  function parseRowDay(value) {
    if (!value) return null;
    var date = new Date(value + "T00:00:00");
    if (isNaN(date.getTime())) return null;
    return date;
  }

  function normalize(value) {
    return (value || "").trim().toLowerCase();
  }

  function persistState() {
    var params = new URLSearchParams(window.location.search);
    var fields = [
      ["from", fromInput && fromInput.value],
      ["to", toInput && toInput.value],
      ["tool", toolInput && toolInput.value],
      ["repo", repoInput && repoInput.value],
      ["branch", branchInput && branchInput.value],
      ["errors", errorOnlyInput && errorOnlyInput.checked ? "1" : ""],
    ];
    for (var i = 0; i < fields.length; i++) {
      var key = fields[i][0];
      var val = fields[i][1];
      if (val) params.set(key, val);
      else params.delete(key);
    }
    var query = params.toString();
    var suffix = query ? "?" + query : "";
    history.replaceState(null, "", window.location.pathname + suffix);
  }

  function applyFilters() {
    var fromDate = parseDay(fromInput && fromInput.value);
    var toDate = parseDay(toInput && toInput.value);
    var tool = normalize(toolInput && toolInput.value);
    var repo = normalize(repoInput && repoInput.value);
    var branch = normalize(branchInput && branchInput.value);
    var errorOnly = Boolean(errorOnlyInput && errorOnlyInput.checked);

    var visible = 0;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var rowDate = parseRowDay(row.getAttribute("data-date"));
      var rowTools = normalize(row.getAttribute("data-tools"));
      var rowRepo = normalize(row.getAttribute("data-repo"));
      var rowBranch = normalize(row.getAttribute("data-branch"));
      var rowErrorTurns = Number(row.getAttribute("data-error-turns") || "0");

      var show = true;
      if (fromDate && rowDate && rowDate < fromDate) show = false;
      if (toDate && rowDate && rowDate > toDate) show = false;
      if (tool && rowTools.indexOf(tool) === -1) show = false;
      if (repo && rowRepo.indexOf(repo) === -1) show = false;
      if (branch && rowBranch.indexOf(branch) === -1) show = false;
      if (errorOnly && rowErrorTurns < 1) show = false;

      row.style.display = show ? "" : "none";
      if (show) visible += 1;
    }

    if (countLabel) {
      countLabel.textContent = "Showing " + visible + " of " + rows.length + " sessions";
    }
    persistState();
  }

  function loadState() {
    var params = new URLSearchParams(window.location.search);
    if (fromInput && params.get("from")) fromInput.value = params.get("from");
    if (toInput && params.get("to")) toInput.value = params.get("to");
    if (toolInput && params.get("tool")) toolInput.value = params.get("tool");
    if (repoInput && params.get("repo")) repoInput.value = params.get("repo");
    if (branchInput && params.get("branch")) branchInput.value = params.get("branch");
    if (errorOnlyInput && params.get("errors") === "1") errorOnlyInput.checked = true;
  }

  function resetFilters() {
    if (fromInput) fromInput.value = "";
    if (toInput) toInput.value = "";
    if (toolInput) toolInput.value = "";
    if (repoInput) repoInput.value = "";
    if (branchInput) branchInput.value = "";
    if (errorOnlyInput) errorOnlyInput.checked = false;
    applyFilters();
  }

  var controls = [fromInput, toInput, toolInput, repoInput, branchInput, errorOnlyInput];
  for (var i = 0; i < controls.length; i++) {
    if (!controls[i]) continue;
    controls[i].addEventListener("input", applyFilters);
    controls[i].addEventListener("change", applyFilters);
  }
  if (resetBtn) resetBtn.addEventListener("click", resetFilters);

  loadState();
  applyFilters();
})();
