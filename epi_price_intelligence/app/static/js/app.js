const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const recEl = document.getElementById("recommendation");
const resultsSection = document.getElementById("results-section");
const resultsBody = document.getElementById("results-body");
const crawlMeta = document.getElementById("crawl-meta");
const emptyState = document.getElementById("empty-state");
const searchBtn = document.getElementById("search-btn");

function inr(amount) {
  if (amount === null || amount === undefined) return "—";
  return "₹" + Number(amount).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function setStatus(message, isError = false) {
  statusEl.hidden = !message;
  statusEl.textContent = message || "";
  statusEl.classList.toggle("error", isError);
}

async function fetchEmi(listingId, tenure, downPayment) {
  try {
    const res = await fetch(`/api/offers/${listingId}?tenure_months=${tenure}&down_payment=${downPayment}`);
    if (!res.ok) return null;
    const data = await res.json();
    return data.emi_estimate;
  } catch {
    return null;
  }
}

function renderRecommendation(rec) {
  if (!rec) {
    recEl.hidden = true;
    return;
  }
  recEl.hidden = false;
  const best = rec.best_effective_price || rec.best_listed_price;
  recEl.innerHTML = `
    <h3>Best deal</h3>
    <div class="rec-grid">
      <div class="rec-item">
        <div class="label">Best current price</div>
        <div class="value">${inr(rec.best_listed_price.amount)} <span style="color:var(--text-dim);font-size:0.75rem">${rec.best_listed_price.source}</span></div>
      </div>
      <div class="rec-item">
        <div class="label">Best effective price</div>
        <div class="value">${rec.best_effective_price ? inr(rec.best_effective_price.amount) + " " : "—"}<span style="color:var(--text-dim);font-size:0.75rem">${rec.best_effective_price ? rec.best_effective_price.source : ""}</span></div>
      </div>
      <div class="rec-item">
        <div class="label">Top pick</div>
        <div class="value" style="font-size:0.95rem">${rec.top_pick.product ? rec.top_pick.product.product_name : "—"}</div>
      </div>
    </div>
    <div class="reasons">Why: ${rec.top_pick.reasons.join(" · ")}</div>
  `;
}

async function renderResults(results, tenure, downPayment) {
  resultsBody.innerHTML = "";
  if (!results.length) {
    resultsSection.hidden = true;
    emptyState.hidden = false;
    emptyState.querySelector("p").textContent = "No comparable listings found for that search. Try a different model or widen your filters.";
    return;
  }
  emptyState.hidden = true;
  resultsSection.hidden = false;

  const minEffective = Math.min(...results.filter(r => r.effective_price != null).map(r => r.effective_price));

  for (const r of results) {
    const tr = document.createElement("tr");
    if (r.effective_price === minEffective) tr.classList.add("best-row");

    const offerTexts = (r.offers || []).slice(0, 2).map(o => o.offer_text).join(" · ") || "—";
    const availClass = r.availability || "unknown";
    const emi = await fetchEmi(r.id, tenure, downPayment);
    const emiText = emi && !emi.error ? `${inr(emi.monthly_emi)}/mo` : "—";

    tr.innerHTML = `
      <td>${r.source.replace("_", " ")}</td>
      <td>${r.product_id_name || ""}${r.sku ? `<div class="offer-text">SKU: ${r.sku}</div>` : ""}</td>
      <td class="price">${inr(r.selling_price)}${r.mrp && r.mrp > r.selling_price ? `<span class="price-strike">${inr(r.mrp)}</span>` : ""}</td>
      <td class="offer-text">${offerTexts}</td>
      <td class="price">${inr(r.effective_price)}</td>
      <td class="price">${emiText}</td>
      <td><span class="badge ${availClass}">${availClass.replace("_", " ")}</span></td>
      <td>${r.deal_score ?? "—"}</td>
      <td><a class="source-link" href="${r.product_url}" target="_blank" rel="noopener">View →</a></td>
    `;
    resultsBody.appendChild(tr);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  searchBtn.disabled = true;
  setStatus("Searching Croma, Vijay Sales and Reliance Digital…");
  emptyState.hidden = true;
  resultsSection.hidden = true;
  recEl.hidden = true;

  const fd = new FormData(form);
  const tenure = fd.get("tenure") || "12";
  const downPayment = fd.get("down_payment") || "0";
  const body = {
    query: fd.get("query"),
    storage: fd.get("storage"),
    colour: fd.get("colour"),
    budget_min: fd.get("budget_min") || null,
    budget_max: fd.get("budget_max") || null,
  };

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.error || "Search failed.", true);
      return;
    }

    // attach a display name per listing (fetched product map isn't inlined per-row by the API)
    const productNameById = {};
    for (const l of data.results) {
      if (!productNameById[l.product_id]) {
        productNameById[l.product_id] = null;
      }
    }
    // fetch product names for the small set of distinct product ids in this result
    await Promise.all(
      Object.keys(productNameById).map(async (pid) => {
        const r = await fetch(`/api/product/${pid}`);
        if (r.ok) {
          const p = await r.json();
          productNameById[pid] = `${p.product_name}${p.storage ? " · " + p.storage : ""}${p.colour ? " · " + p.colour : ""}`;
        }
      })
    );
    for (const l of data.results) {
      l.product_id_name = productNameById[l.product_id] || "";
    }

    const failures = data.partial_failures || [];
    if (failures.length) {
      setStatus(`Completed with partial results — ${failures.map(f => f.source).join(", ")} had issues.`);
    } else {
      setStatus("");
    }

    crawlMeta.textContent = `Crawl #${data.crawl.crawl_id} · ${data.crawl.sources_succeeded}/${data.crawl.sources_attempted} sources responded · ${new Date(data.crawl.finished_at || data.crawl.started_at).toLocaleString()}`;

    renderRecommendation(data.recommendation);
    await renderResults(data.results, tenure, downPayment);
  } catch (err) {
    setStatus("Something went wrong reaching the server.", true);
  } finally {
    searchBtn.disabled = false;
  }
});
