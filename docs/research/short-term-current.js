/* Latest dated public recommendations, separate from historical playbook tables. */
"use strict";
(async function () {
  const target = document.getElementById("latest-review");
  const node = (tag, text) => { const value = document.createElement(tag); if (text) value.textContent = text; return value; };
  try {
    const response = await fetch("../data/research.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Latest journal is unavailable");
    const data = await response.json();
    const entry = data.entries?.[0];
    if (!entry || typeof entry.id !== "string") throw new Error("Latest journal is missing");
    const view = ResearchActions.presentation(entry);
    const time = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Chicago" }).format(new Date(entry.checked_at));
    const eyebrow = node("p", `Latest published review · ${time} Chicago`); eyebrow.className = "eyebrow";
    const content = [eyebrow, node("h2", view.heading), node("p", entry.summary), node("p", view.entryLabel)];
    if (view.actions.length) {
      const table = node("table");
      const head = node("thead"), headings = node("tr");
      ["Recorded call", "Reason at this check"].forEach((label) => headings.append(node("th", label)));
      head.append(headings); table.append(head);
      const body = node("tbody");
      for (const action of view.actions) {
        const row = node("tr"), call = node("th", `${action.symbol} — ${action.label}`); call.scope = "row";
        row.append(call, node("td", action.reason)); body.append(row);
      }
      table.append(body); content.push(table);
    }
    content.push(node("p", "These are recommendations recorded at the displayed review time, not executed orders or streaming market prices. Recheck prices and any later fills before acting."));
    const link = node("a", "Open this exact journal entry →"); link.href = `../#journal/entry/${encodeURIComponent(entry.id)}`; content.push(link);
    target.replaceChildren(...content);
  } catch (_) {
    target.replaceChildren(node("h2", "Latest actions could not be loaded"), node("p", "The tables below are historical and must not substitute for a current review."));
    const link = node("a", "Open the latest journal →"); link.href = "../#journal"; target.append(link);
  }
})();
