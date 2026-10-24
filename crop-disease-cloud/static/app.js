const $ = (id) => document.getElementById(id);
let currentFile = null;

function setFile(file) {
  currentFile = file;
  const url = URL.createObjectURL(file);
  $("preview").src = url;
  $("preview").hidden = false;
  $("dropText").hidden = true;
  $("analyze").disabled = false;
}

$("file").addEventListener("change", (e) => e.target.files[0] && setFile(e.target.files[0]));
const drop = $("drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && setFile(e.dataTransfer.files[0]));

document.querySelectorAll(".chip").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const res = await fetch(`/api/sample/${btn.dataset.class}?t=${Date.now()}`);
    const blob = await res.blob();
    setFile(new File([blob], `${btn.dataset.class}_sample.jpg`, { type: "image/jpeg" }));
    analyze();
  })
);

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = false;
  $("result").hidden = true;
  $("empty").hidden = true;
}

async function analyze() {
  if (!currentFile) return;
  $("analyze").disabled = true;
  $("analyze").textContent = "Analyzing...";
  $("error").hidden = true;
  const fd = new FormData();
  fd.append("image", currentFile);
  try {
    const res = await fetch("/api/predict", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) return showError(data.error || "Request failed");
    render(data);
    loadDashboard();
  } catch (e) {
    showError("Could not reach the server.");
  } finally {
    $("analyze").disabled = false;
    $("analyze").textContent = "Analyze leaf";
  }
}
$("analyze").addEventListener("click", analyze);

function render(d) {
  $("empty").hidden = true;
  $("result").hidden = false;
  $("rLabel").textContent = d.display_name;
  $("rConf").textContent = (d.confidence * 100).toFixed(1) + "%";
  $("rSev").textContent = d.severity_percent + "% of leaf";
  $("rLat").textContent = d.latency_ms + " ms";
  $("rNode").textContent = d.served_by;
  $("rCause").textContent = d.advice.cause || "";
  $("rTreat").innerHTML = "";
  (d.advice.treatment || []).forEach((t) => {
    const li = document.createElement("li");
    li.textContent = t;
    $("rTreat").appendChild(li);
  });
  $("rBars").innerHTML = "";
  Object.entries(d.probabilities).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `<span></span><div class="track"><div class="fill"></div></div><span></span>`;
    row.children[0].textContent = k.replace(/_/g, " ");
    row.children[1].firstChild.style.width = v * 100 + "%";
    row.children[2].textContent = (v * 100).toFixed(1) + "%";
    $("rBars").appendChild(row);
  });
}

async function loadDashboard() {
  const [stats, hist, health] = await Promise.all([
    fetch("/api/stats").then((r) => r.json()),
    fetch("/api/history?limit=10").then((r) => r.json()),
    fetch("/api/health").then((r) => r.json()),
  ]);
  $("node").textContent = "node: " + health.instance;
  $("sTotal").textContent = stats.total_scans;
  $("sLat").textContent = stats.avg_latency_ms;
  $("sStore").textContent = stats.storage === "s3" ? "Amazon S3" : "local bucket";
  $("sNodes").textContent = Object.keys(stats.by_node).length || "-";
  $("hist").innerHTML = "";
  hist.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><img alt=""></td><td></td><td></td><td></td><td></td><td></td>`;
    tr.children[0].firstChild.src = r.image_url;
    tr.children[1].textContent = r.created_at;
    tr.children[2].textContent = r.display_name;
    tr.children[3].textContent = (r.confidence * 100).toFixed(1) + "%";
    tr.children[4].textContent = r.severity + "%";
    tr.children[5].textContent = r.served_by;
    $("hist").appendChild(tr);
  });
}
$("refresh").addEventListener("click", loadDashboard);
loadDashboard();
