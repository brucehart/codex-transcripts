document.querySelectorAll("time[data-timestamp]").forEach(function(el) {
  var timestamp = el.getAttribute("data-timestamp");
  if (!timestamp) return;
  var date = new Date(timestamp);
  if (isNaN(date.getTime())) return;
  var now = new Date();
  var isToday = date.toDateString() === now.toDateString();
  var timeStr = date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (isToday) {
    el.textContent = timeStr;
  } else {
    el.textContent =
      date.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
      " " +
      timeStr;
  }
});

document.querySelectorAll("pre.json").forEach(function(el) {
  var text = el.textContent || "";
  text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  text = text.replace(
    /"([^"]+)":/g,
    '<span style="color: #ce93d8">"$1"</span>:',
  );
  text = text.replace(
    /: "([^"]*)"/g,
    ': <span style="color: #81d4fa">"$1"</span>',
  );
  text = text.replace(
    /: (\d+)/g,
    ': <span style="color: #ffcc80">$1</span>',
  );
  text = text.replace(
    /: (true|false|null)/g,
    ': <span style="color: #f48fb1">$1</span>',
  );
  el.innerHTML = text;
});

document.querySelectorAll(".truncatable").forEach(function(wrapper) {
  var content = wrapper.querySelector(".truncatable-content");
  var btn = wrapper.querySelector(".expand-btn");
  if (!content || !btn) return;
  if (content.scrollHeight <= 250) return;

  wrapper.classList.add("truncated");
  btn.addEventListener("click", function() {
    if (wrapper.classList.contains("truncated")) {
      wrapper.classList.remove("truncated");
      wrapper.classList.add("expanded");
      btn.textContent = "Show less";
    } else {
      wrapper.classList.remove("expanded");
      wrapper.classList.add("truncated");
      btn.textContent = "Show more";
    }
  });
});
