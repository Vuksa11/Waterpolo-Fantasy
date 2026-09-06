import {
  FORMATIONS,
  autoLineup,
  lineupErrors,
  rosterErrors,
  changeFormation,
  buyPlayer,
  safeDraft,
  roleAccepts,
} from "./lineup.js";
import { roundTitle } from "./round.js";
import { request, catalogQuery, peekCache, clearPublicCache } from "./api.js";
import {
  demoPlayers,
  demoCompetition,
  demoMatches,
  demoStandings,
  demoDraft,
} from "./demo.js";
const $ = (s) => document.querySelector(s),
  $$ = (s) => document.querySelectorAll(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const money = (n) => Number(n || 0).toFixed(1);
const short = (n) =>
  n
    .split(" ")
    .map((s) => s[0])
    .join("")
    .slice(0, 3)
    .toUpperCase();
const names = {
  home: "Početna",
  team: "Moj tim",
  players: "Igrači",
  fixtures: "Raspored",
  standings: "Tabela",
  news: "Vesti",
};
const emptyDraft = {
  name: "Moj tim",
  formation: "THREE_THREE",
  roster: [],
  active: Array(7).fill(null),
  captain: null,
  coach: null,
  savedAt: null,
};
let mode = localStorage.getItem("vrl-mode") || "demo",
  page = location.hash.slice(1) || "home",
  competition = "",
  competitions = [],
  matchdays = [],
  selectedDay = "",
  matches = [],
  standings = [],
  catalog = { items: [], total: 0, limit: 24, offset: 0 },
  facets = { clubs: [], positions: [] },
  draft = structuredClone(demoDraft),
  status = "loading",
  error = "",
  query = "",
  position = "",
  club = "",
  sort = "cost_desc",
  offset = 0,
  busy = false,
  user = null,
  token = sessionStorage.getItem("vrl-token"),
  viewId = 0,
  controller = null,
  searchTimer = null,
  squadView = "pool",
  serverTeam = null,
  coaches = [];
function key() {
  return `vrl-draft-v2:${mode}:${competition}:${mode === "api" ? user?.id || "guest" : "local"}`;
}
function readDraft() {
  const fallback = mode === "demo" ? demoDraft : emptyDraft;
  try {
    draft = safeDraft(
      JSON.parse(localStorage.getItem(key()) || "null"),
      fallback,
    );
  } catch {
    draft = structuredClone(fallback);
  }
}
function saveLocal() {
  try {
    localStorage.setItem(key(), JSON.stringify(draft));
    return true;
  } catch {
    toast("Browser ne dozvoljava čuvanje podataka.");
    return false;
  }
}
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => el.classList.remove("show"), 4500);
}
function setPage(value) {
  if (busy) return;
  page = value in names ? value : "home";
  location.hash = page;
  render();
  if (page === "standings" && rankingView === "fantasy" && mode === "api")
    loadRanking();
  if (page === "players") loadCatalog();
  window.scrollTo({ top: 0, behavior: "instant" });
}
addEventListener("hashchange", () => {
  const next = location.hash.slice(1) || "home";
  if (next !== page) {
    page = next;
    render();
    if (page === "players") loadCatalog();
    if (page === "standings" && rankingView === "fantasy" && mode === "api")
      loadRanking();
  }
});
const budget = () =>
  mode === "api" && serverTeam
    ? Number(serverTeam.credit_balance)
    : 100 -
      draft.roster.reduce((s, p) => s + p.current_cost, 0) -
      (draft.coach?.current_cost || 0);
const currentCompetition = () => competitions.find((c) => c.id === competition);
const currentDay = () => matchdays.find((d) => d.id === selectedDay);
function formControl() {
  return `<div class="formation-control" role="group" aria-label="Formacija">${Object.entries(
    FORMATIONS,
  )
    .map(
      ([id, f]) =>
        `<button data-formation="${id}" aria-pressed="${draft.formation === id}" class="${draft.formation === id ? "chosen" : ""}">${f.label}</button>`,
    )
    .join("")}</div>`;
}
function errorsView() {
  const issues = [
    ...lineupErrors(draft.formation, draft.active, draft.roster, draft.captain),
    ...rosterErrors(draft.roster, draft.active),
  ];
  if (!draft.coach) issues.push("Trener nije izabran.");
  return issues.length
    ? `<div class="validation" role="status"><b>Još malo do spremnog tima</b><ul>${issues.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>`
    : '<div class="valid-note">✓ Sastav i klupa odgovaraju formaciji.</div>';
}
function playerSlot(role, id, index, compact = false) {
  const p = draft.roster.find((p) => p.id === id);
  return `<button class="pool-player ${p ? "filled" : ""}" data-slot="${index}" aria-label="${role}: ${p ? esc(p.name) : "Izaberi igrača"}"><span class="slot-top"><b class="role-tag ${["CF", "CB"].includes(role) ? "special" : ""}">${role}</b><span>${p ? money(p.current_cost) + " kr" : "—"}</span></span><span class="player-circle">${p ? short(p.name) : "+"}</span><strong>${p ? esc(p.name.split(" ").slice(1).join(" ") || p.name) : "Izaberi igrača"}</strong><span class="slot-bottom">${p ? esc(p.real_club) : { GK: "Golman", OT: "Spoljni napadač", CF: "Centar", CB: "Centarbek" }[role]}</span>${draft.captain === id && id ? '<span class="c-badge">C</span>' : ""}</button>`;
}
function pool(compact = false) {
  const f = FORMATIONS[draft.formation];
  return `<div class="pool ${compact ? "compact" : ""}" aria-label="Bazen, formacija ${f.label}"><div class="pool-lines"><div class="goal"></div><div class="two-meter"></div><div class="six-meter"></div></div>${f.roles.map((role, i) => `<div class="pool-position" style="--x:${f.positions[i][0]}%;--y:${f.positions[i][1]}%">${playerSlot(role, draft.active[i], i, compact)}</div>`).join("")}</div>`;
}
function fixtureRows(list = matches) {
  if (!list.length)
    return '<div class="empty">Nema utakmica za izabrano kolo.</div>';
  return list
    .map((m) => {
      const date = m.kickoff_at ? new Date(m.kickoff_at) : null;
      const valid = date && !Number.isNaN(date.getTime());
      return `<button class="match-row" data-match="${esc(m.id)}"><span class="match-time">${valid ? new Intl.DateTimeFormat("sr-Latn", { day: "2-digit", month: "short", timeZone: "Europe/Belgrade" }).format(date) : "Termin"}<small>${valid ? new Intl.DateTimeFormat("sr-Latn", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Belgrade" }).format(date) : "nije objavljen"}</small></span><span class="match-team"><i class="club-badge">${short(m.home_club)}</i><b>${esc(m.home_club)}</b></span><span class="match-result">${m.home_score !== null && m.away_score !== null ? `${m.home_score} : ${m.away_score}` : "—"}<small>${m.status === "FINISHED" ? "KRAJ" : m.status === "LIVE" ? "U TOKU" : "PREDSTOJI"}</small></span><span class="match-team away"><i class="club-badge">${short(m.away_club)}</i><b>${esc(m.away_club)}</b></span></button>`;
    })
    .join("");
}
function tableRows(limit = 100) {
  return standings
    .slice(0, limit)
    .map(
      (r, i) =>
        `<tr><td class="place">${i + 1}</td><td><span class="club-cell"><i class="club-badge">${short(r.club)}</i><span><b>${esc(r.club)}</b></span></span></td><td>${r.played}</td><td>${r.won}</td><td>${r.lost}</td><td>${r.goal_difference > 0 ? "+" : ""}${r.goal_difference}</td><td><strong>${r.points}</strong></td></tr>`,
    )
    .join("");
}
function miniStandings() {
  return `<section class="card"><div class="card-head"><h3>Vrh regionalne lige</h3><span class="eyebrow">BOD.</span></div>${
    (homeTop ?? standings)
      .slice(0, 4)
      .map(
        (r, i) =>
          `<div class="list-player"><span class="rank">${i + 1}</span><i class="club-badge">${short(r.club)}</i><span class="name">${esc(r.club)}</span><b class="points">${r.points}</b></div>`,
      )
      .join("") || '<div class="empty">Tabela još nije dostupna.</div>'
  }<div class="card-foot"><button class="secondary" data-go="standings">Cela tabela →</button></div></section>`;
}
function home() {
  return `<section class="claude-hero"><div><span class="hero-pill">${esc(currentCompetition()?.name || "REGIONALNA LIGA")} · ${esc(currentDay()?.label || "SEZONA")}</span><h1>Sastavi svoj tim<br><span>regionalne lige.</span></h1><p>Svaki gol je prilika. Svaka odluka pravi razliku.<br>Okupi svoju sedmorku i preuzmi klupu.</p><div class="hero-actions"><button class="primary" data-go="team">Uredi moj tim ↗</button><button class="hero-secondary" data-go="fixtures">Raspored kola</button></div></div><div class="hero-summary"><div class="eyebrow">${mode === "demo" ? "TVOJ DEMO TIM" : "TVOJ LOKALNI NACRT"}</div><h2>${esc(draft.name)}</h2><div class="hero-kv"><div><span>Formacija</span><strong>${FORMATIONS[draft.formation].label}</strong></div><div><span>Budžet</span><strong>${money(budget())} <small>kr</small></strong></div></div><div class="summary-bottom">${mode === "demo" ? "Istraži taktiku bez ograničenja." : "Raspored i igrači direktno iz API-ja."}</div></div></section><div class="home-grid"><div><section class="card"><div class="card-head"><div><div class="eyebrow">PREGLED TIMA</div><h3>Tvoje sledeće kolo</h3></div><span class="pill">${FORMATIONS[draft.formation].name}</span></div><div class="summary-stats"><div><span>Starteri</span><strong>${draft.active.filter(Boolean).length} / 7</strong></div><div><span>Kapiten</span><strong>${esc(
    draft.roster
      .find((p) => p.id === draft.captain)
      ?.name.split(" ")
      .at(-1) || "Izaberi",
  )}</strong></div><div><span>Vrednost tima</span><strong>${money(100 - budget())} <small>kr</small></strong></div></div></section><section class="card"><div class="card-head"><h3>Utakmice ovog kola</h3><button class="text-link" data-go="fixtures">Ceo raspored ↗</button></div>${fixtureRows(matches.slice(0, 4))}</section><section class="card"><div class="card-head"><h3>Tvoja lepeza</h3><button class="text-link" data-go="team">Uredi postavu ↗</button></div>${pool(true)}</section></div><aside>${miniStandings()}<section class="tactic-tip"><div class="eyebrow">IZ SVLAČIONICE</div><h3>Tri postave.<br>Bezbroj mogućnosti.</h3><p>3×3 za balans, 4×2 za napad ili 2×4 za odbranu. Tvoj stil igre počinje izborom formacije.</p><button class="hero-secondary" data-go="team">Izaberi taktiku →</button></section></aside></div>`;
}
function squadList() {
  return `<div class="squad-list">${FORMATIONS[draft.formation].roles
    .map((role, i) => {
      const p = draft.roster.find((p) => p.id === draft.active[i]);
      return `<button class="squad-list-row" data-slot="${i}"><span class="role-tag">${role}</span><span><b>${esc(p?.name || "Izaberi igrača")}</b><small>${esc(p?.real_club || "Slobodno mesto")}</small></span><span>${p ? money(p.current_cost) + " kr" : "+"}</span>${draft.captain === p?.id ? '<strong class="list-captain">C</strong>' : "<span>↗</span>"}</button>`;
    })
    .join("")}</div>`;
}
function bench() {
  const list = draft.roster.filter((p) => !draft.active.includes(p.id));
  return `<section class="card bench-card"><div class="card-head"><div><div class="eyebrow">KLUPA I STRUČNI ŠTAB</div><h3>Rezerve</h3></div><span class="pill">${list.length} igrača + ${draft.coach ? "1 trener" : "trener"}</span></div><div class="bench-grid"><button class="bench-slot coach" id="coach"><span class="role-tag">TRENER</span><span class="player-circle">${draft.coach ? "T" : "+"}</span><b>${esc(draft.coach?.name || "Izaberi trenera")}</b><small>${draft.coach ? money(draft.coach.current_cost) + " kr" : "Čeka potvrđene podatke"}</small></button>${list.map((p) => `<button class="bench-slot" data-bench="${esc(p.id)}"><span class="role-tag">${p.position || "?"}</span><span class="player-circle">${short(p.name)}</span><b>${esc(p.name)}</b><small>${esc(p.real_club)} · ${money(p.current_cost)} kr</small></button>`).join("")}${Array.from({ length: Math.max(0, 4 - list.length) }, (_, i) => `<button class="bench-slot" data-go="players"><span class="role-tag">REZERVA</span><span class="player-circle">+</span><b>Izaberi igrača</b><small>GK · CF/CB · OT · OT</small></button>`).join("")}</div></section>`;
}
function team() {
  if (teamLoading) return loadingCards("Učitavam tvoj sačuvani tim…");
  if (
    mode === "api" &&
    dataStates.team &&
    !["ready", "loading"].includes(dataStates.team)
  )
    return "";
  const f = FORMATIONS[draft.formation];
  return `<section class="team-banner"><div class="round-number">${esc(roundTitle(currentDay()).title)}<small>${roundTitle(currentDay()).caption}</small></div><div><span class="hero-pill">${mode === "demo" ? "DEMO SASTAV" : serverTeam ? "TIM NA SERVERU" : "LOKALNI NACRT"}</span><h1>Tim ${esc(draft.name)}</h1></div><div class="deadline-copy"><span>Zaključavanje sastava</span><strong>${currentDay()?.deadline ? new Date(currentDay().deadline).toLocaleString("sr-Latn", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "Rok nije objavljen"}</strong></div></section><div class="team-layout"><aside class="team-summary card"><div class="card-head"><h3>Pregled tima</h3><button class="text-link" id="rename" aria-label="Promeni ime tima">✎</button></div><div class="summary-content"><h2>${esc(draft.name)}</h2><label class="eyebrow">FORMACIJA</label>${formControl()}<p class="formation-description">${f.description}</p><div class="gauge-head"><b>Krediti</b><span>${money(100 - budget())} / 100</span></div><div class="gauge"><i style="width:${Math.min(100, 100 - budget())}%"></i></div><div class="sub">${money(budget())} kredita za pojačanja</div><div class="summary-stats"><div><span>Igrači</span><strong>${draft.roster.length}/11</strong></div><div><span>Kapiten</span><strong>${esc(
    draft.roster
      .find((p) => p.id === draft.captain)
      ?.name.split(" ")
      .at(-1) || "—",
  )}</strong></div></div><button class="primary full" id="save-lineup" ${busy ? "disabled" : ""}>${busy ? "Proveravam…" : mode === "demo" ? "Sačuvaj demo sastav" : "Sačuvaj sastav"}</button><p class="sub">7 startera + 4 rezervna igrača + trener.</p>${draft.savedAt ? `<p class="saved-at">✓ ${mode === "api" && serverTeam ? "Server" : "Lokalno"} · sačuvano ${new Date(draft.savedAt).toLocaleTimeString("sr-Latn", { hour: "2-digit", minute: "2-digit" })}</p>` : ""}${errorsView()}</div></aside><section class="card pool-card"><div class="card-head"><h3>${f.label} · ${f.name}</h3><span class="tiny">C = KAPITEN</span></div><div class="squad-toolbar"><div class="view-switch" role="group" aria-label="Prikaz tima"><button data-view="pool" aria-pressed="${squadView === "pool"}">▦ Bazen</button><button data-view="list" aria-pressed="${squadView === "list"}">☷ Lista</button></div><span class="tiny">Klikni na igrača za zamenu</span></div>${squadView === "pool" ? pool() : squadList()}<div class="card-foot pool-legend">GK Golman &nbsp; OT Spoljni &nbsp; CF Centar &nbsp; CB Bek</div></section>${bench()}<aside class="right-rail"><section class="card"><div class="card-head"><h3>Sledeći izazov</h3><span class="hero-pill small">VRL</span></div>${fixtureRows(matches.slice(0, 1))}</section><section class="card"><div class="card-head"><h3>Tvoj roster</h3><button class="text-link" data-go="players">Transferi ↗</button></div>${
    draft.roster
      .slice(0, 5)
      .map(
        (p) =>
          `<button class="list-player" data-detail="${p.id}" style="width:100%;text-align:left"><span class="avatar">${short(p.name).slice(0, 2)}</span><span class="name">${esc(p.name)}<span class="sub" style="display:block">${p.position} · ${esc(p.real_club)}</span></span><b>${money(p.current_cost)}</b></button>`,
      )
      .join("") || '<div class="notice">Prvo dodaj igrače iz kataloga.</div>'
  }</section><div class="tactic-tip"><h3>Promena taktike</h3><p>Formacija čuva tvoje igrače. Ako nedostaje odgovarajuća pozicija, mesto ostaje prazno dok ne dovedeš pojačanje.</p></div></aside></div><div class="mobile-validation">${errorsView()}</div><div class="mobile-team-action"><div><span>Preostalo</span><strong>${money(budget())} kr</strong></div><button class="primary" id="mobile-save">Sačuvaj sastav ✓</button></div>`;
}
function playersPage() {
  return `<div class="page-title section-banner"><div><div class="eyebrow">SKAUTING I TRANSFERI</div><h1>Igrači</h1><p>Pronađi pravo pojačanje za svoju lepezu.</p></div><div class="credit-chip">${money(budget())} <small>kr na raspolaganju</small></div></div><section class="card"><div class="toolbar"><input id="search" type="search" aria-label="Pretraži igrače" placeholder="Pretraži ime igrača…" maxlength="100" value="${esc(query)}"><select id="position" aria-label="Pozicija"><option value="">Sve pozicije</option>${["GK", "OT", "CF", "CB"].map((p) => `<option ${position === p ? "selected" : ""}>${p}</option>`).join("")}</select><select id="club" aria-label="Klub"><option value="">Svi klubovi</option>${facets.clubs.map((c) => `<option ${club === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select><select id="sort" aria-label="Sortiranje">${[
    ["cost_desc", "Najskuplji prvo"],
    ["cost_asc", "Najjeftiniji prvo"],
    ["name_asc", "Ime A–Z"],
    ["name_desc", "Ime Z–A"],
  ]
    .map(
      ([v, l]) =>
        `<option value="${v}" ${sort === v ? "selected" : ""}>${l}</option>`,
    )
    .join(
      "",
    )}</select></div><div id="catalog-result" aria-live="polite">${catalogContent()}</div></section><div class="notice">${mode === "demo" ? "Demo cene i klubovi služe isprobavanju aplikacije." : "Igrači bez potvrđene pozicije prikazani su sa oznakom „Nepoznata“. Ne mogu u validan sastav dok se podaci ne dopune."}</div>`;
}
function catalogContent() {
  if (status === "catalog-loading")
    return '<div class="loading"><span class="spinner"></span> Učitavam igrače…</div>';
  if (error)
    return `<div class="error-box">${esc(error)}<button id="retry-catalog" class="secondary">Pokušaj ponovo</button></div>`;
  return `<div class="table-scroll"><table class="player-table"><thead><tr><th>Igrač</th><th>Pozicija</th><th>Klub</th><th>Cena</th><th></th></tr></thead><tbody>${catalog.items.map((p) => `<tr><td><button data-detail="${p.id}" class="catalog-name"><span class="avatar">${short(p.name).slice(0, 2)}</span><b>${esc(p.name)}</b></button></td><td data-label="Pozicija"><span class="role-tag">${p.position || "Nepoznata"}</span></td><td data-label="Klub">${esc(p.real_club)}</td><td data-label="Cena"><b>${money(p.current_cost)} kr</b></td><td><button class="secondary ${draft.roster.some((r) => r.id === p.id) ? "" : "dark"}" data-buy="${p.id}" ${!p.position ? 'disabled title="Nedostaje potvrđena pozicija"' : ""}>${draft.roster.some((r) => r.id === p.id) ? "U timu ✓" : "+ Dovedi"}</button></td></tr>`).join("")}</tbody></table>${catalog.items.length ? "" : '<div class="empty">Nema igrača za izabrane filtere.</div>'}</div><div class="pagination"><span>${catalog.total ? offset + 1 : 0}–${Math.min(offset + catalog.items.length, catalog.total)} od ${catalog.total} igrača</span><div><button class="secondary" id="prev-page" ${offset === 0 ? "disabled" : ""}>← Prethodna</button><button class="secondary" id="next-page" ${offset + 24 >= catalog.total ? "disabled" : ""}>Sledeća →</button></div></div>`;
}
function fixturesPage() {
  return `<div class="page-title section-banner"><div><div class="eyebrow">${esc(currentCompetition()?.name)}</div><h1>Raspored</h1><p>Vreme početka prikazano za Beograd.</p></div><select id="matchday" aria-label="Izaberi kolo">${matchdays.map((d) => `<option value="${d.id}" ${selectedDay === d.id ? "selected" : ""}>${esc(d.label)}</option>`).join("")}</select></div><section class="card"><div class="card-head tinted"><h3>${esc(currentDay()?.label || "Utakmice")}</h3><span class="pill">${matches.length} utakmica</span></div>${fixtureRows()}</section>`;
}
let rankingView = "clubs";
let ranking = { entries: [], total: 0, offset: 0, limit: 25 };
let rankingState = "idle";
let rankingVersion = 0;
let rankingController;
function rankingTabs() {
  return `<div class="ranking-tabs view-switch" role="group" aria-label="Vrsta tabele"><button data-ranking="clubs" aria-pressed="${rankingView === "clubs"}">Klubovi</button><button data-ranking="fantasy" aria-pressed="${rankingView === "fantasy"}">Fantasy timovi</button></div>`;
}
async function loadRanking(offset = 0) {
  const version = ++rankingVersion;
  rankingController?.abort();
  rankingController = new AbortController();
  rankingState = "loading";
  if (page === "standings") render();
  try {
    const result = await request(
      `/competitions/${competition}/leaderboard?limit=25&offset=${offset}`,
      { signal: rankingController.signal, cacheMs: 30000 },
    );
    if (version !== rankingVersion) return;
    ranking = result;
    rankingState = "ready";
  } catch (e) {
    if (version !== rankingVersion || e.name === "AbortError") return;
    rankingState =
      e.status === 404
        ? "Rang-lista još nije dostupna za ovo takmičenje."
        : e.message;
  }
  if (page === "standings") render();
}
function fantasyRanking() {
  const head = `<div class="page-title section-banner"><div><div class="eyebrow">${esc(currentCompetition()?.name)}</div><h1>Fantasy tabela</h1><p>Timovi i menadžeri regionalne lige.</p></div></div>${rankingTabs()}`;
  if (mode === "demo")
    return (
      head +
      '<section class="card"><div class="empty">Fantasy rang-lista dostupna je u API režimu.</div></section>'
    );
  const notice =
    '<div class="notice">Obračun bodova fantasy timova još je u pripremi. Prikazani bodovi su trenutno upisane vrednosti, a ne konačan plasman.</div>';
  if (rankingState === "loading" || rankingState === "idle")
    return head + notice + loadingCards("Učitavam fantasy tabelu…");
  if (rankingState !== "ready")
    return (
      head +
      notice +
      `<div class="error-box" role="alert">${esc(rankingState)} <button class="secondary" id="retry-ranking">Pokušaj ponovo</button></div>`
    );
  return (
    head +
    notice +
    `<section class="card"><div class="table-scroll"><table class="standings-table fantasy-table"><thead><tr><th>#</th><th>Tim / menadžer</th><th>Bodovi</th></tr></thead><tbody>${ranking.entries.map((r) => `<tr><td>${r.rank}</td><td><b>${esc(r.team_name)}</b><small>${esc(r.owner_display_name)}</small></td><td>${money(r.total_points)}</td></tr>`).join("")}</tbody></table>${ranking.entries.length ? "" : '<div class="empty">Još nema fantasy timova u ovoj ligi.</div>'}</div><div class="pagination"><span>${ranking.total ? ranking.offset + 1 : 0}–${Math.min(ranking.offset + ranking.entries.length, ranking.total)} od ${ranking.total} timova</span><div><button class="secondary" id="ranking-prev" ${ranking.offset === 0 ? "disabled" : ""}>← Prethodna</button><button class="secondary" id="ranking-next" ${ranking.offset + ranking.limit >= ranking.total ? "disabled" : ""}>Sledeća →</button></div></div></section>`
  );
}
function standingsPage() {
  if (rankingView === "fantasy") return fantasyRanking();
  return `<div class="page-title section-banner"><div><div class="eyebrow">${esc(currentCompetition()?.name)}</div><h1>Tabela</h1><p>Plasman klubova na osnovu odigranih utakmica.</p></div><span class="pill">${mode === "demo" ? "Ilustrativni rezultati" : "Sportski API"}</span></div>${rankingTabs()}<section class="card table-scroll"><table class="standings-table"><thead><tr><th>#</th><th>Klub</th><th>OD</th><th>P</th><th>I</th><th>Gol</th><th>Bod.</th></tr></thead><tbody>${tableRows()}</tbody></table>${standings.length ? "" : '<div class="empty">Nema odigranih utakmica u bazi.</div>'}</section><div class="notice">Tabela prikazuje podatke koje vraća backend. Obračun posebnih rezultata posle peteraca i sezonски filter još čekaju backend podršku.</div>`;
}
const articles = [
  {
    title: "Svaki detalj pravi razliku.",
    tag: "FANTASY VODIČ",
    body: "U standardnoj lepezi 3×3 igraš sa jednim centrom, jednim bekom i četiri spoljna igrača. Golman je sedmi starter. Promeni formaciju na stranici Moj tim i vidi koji igrači odgovaraju novoj taktici.",
  },
  {
    title: "Dva centra. Više pritiska.",
    tag: "TAKTIKA · 4×2",
    body: "Formacija 4×2 ima dva centra CF, četiri OT igrača i golmana. Nema beka CB. Promena formacije ne kupuje igrače: nedostajuće mesto ostaje prazno, a postojeći igrač se čuva u rosteru.",
  },
  {
    title: "Sigurnost počinje pozadi.",
    tag: "TAKTIKA · 2×4",
    body: "U formaciji 2×4 igraju dva beka CB i četiri OT igrača uz golmana. Nema centra. Za klupu su predviđeni rezervni golman, dva spoljna i jedan CF/CB, uz trenera.",
  },
];
function newsPage() {
  return `<div class="page-title section-banner"><div><div class="eyebrow">IZMEĐU DVA KOLA</div><h1>Vesti i vodiči</h1><p>Saznaj više o svojoj sledećoj taktici.</p></div></div><div class="news-grid">${articles.map((a, i) => `<button class="news" data-article="${i}"><div class="news-art ${i === 1 ? "alt" : i === 2 ? "third" : ""}">${i === 0 ? '<img src="/assets/vrl-logo.jpg" alt="VRL konferencija">' : i === 1 ? "4×2" : "2×4"}</div><div class="news-body"><div class="eyebrow">${a.tag}</div><h3>${a.title}</h3><p>Vodič kroz fantasy formacije</p><span class="text-link">Pročitaj više ↗</span></div></button>`).join("")}</div>`;
}
function render() {
  if (!(page in names)) page = "home";
  document.title = names[page] + " · VRL Fantasy";
  $("#app").innerHTML =
    `<header class="site-header"><a class="brand" href="#home"><span class="brand-mark">VRL</span><span class="brand-text"><strong>FANTASY VATERPOLO</strong>Regionalna liga · Fantasy</span></a><nav aria-label="Glavna navigacija">${Object.entries(
      names,
    )
      .map(
        ([id, name]) =>
          `<button class="${page === id ? "active" : ""}" data-go="${id}" ${page === id ? 'aria-current="page"' : ""}>${name}</button>`,
      )
      .join(
        "",
      )}</nav><button class="user-chip" id="account"><span class="online-dot"></span>${esc(user?.display_name || "Moj nalog")}</button></header><div class="context-bar"><select id="competition" aria-label="Takmičenje">${competitions.map((c) => `<option value="${c.id}" ${c.id === competition ? "selected" : ""}>${esc(c.name)}</option>`).join("") || "<option>Izaberi takmičenje</option>"}</select><div class="mode-switch"><span class="tiny">Izvor podataka</span><button data-mode="demo" class="${mode === "demo" ? "chosen" : ""}">Demo</button><button data-mode="api" class="${mode === "api" ? "chosen" : ""}">API</button></div></div><main id="main">${status === "loading" ? loadingCards("Povezujem podatke…") : status === "error" ? `<div class="error-box"><h2>Podaci nisu dostupni</h2><p>${esc(error)}</p><button class="primary" id="retry">Pokušaj ponovo</button><button class="secondary" data-mode="demo">Istraži Demo</button></div>` : dataNotices() + { home, team, players: playersPage, fixtures: fixturesPage, standings: standingsPage, news: newsPage }[page]()}</main><footer><span>VRL FANTASY · Nezvanični koncept &nbsp; / &nbsp; ${mode === "demo" ? "DEMO PODACI" : "PODACI IZ API-JA"}</span><span><button id="rules">Kako se igra</button> &nbsp; · &nbsp; <a href="https://wpolo.me/odrzan-sastanak-vaterpolo-i-plivackog-saveza-crne-gore-i-vaterpolo-saveza-srbije/" target="_blank" rel="noopener">VRL ↗</a></span></footer>`;
  bind();
  $$("#retry-data").forEach((b) => (b.onclick = bootstrap));
  if (busy)
    $$("#app button, #app select, #app input").forEach(
      (el) => (el.disabled = true),
    );
}
let homeTop = null;
let teamLoading = false;
let dataStates = {};
function loadingCards(label = "Učitavam podatke…") {
  return `<div class="loading-cards" role="status" aria-label="${label}"><p>${label}</p><div></div><div></div><div></div></div>`;
}
function dataNotices() {
  const relevant =
    {
      home: ["home"],
      team: ["home", "days", "team", "coaches"],
      players: ["facets"],
      fixtures: ["home", "days"],
      standings: ["standings"],
      news: [],
    }[page] || [];
  return relevant
    .map((key) =>
      dataStates[key] === "loading"
        ? loadingCards()
        : dataStates[key] && dataStates[key] !== "ready"
          ? `<div class="notice" role="alert">${esc(dataStates[key])} <button class="text-link" id="retry-data">Pokušaj ponovo</button></div>`
          : "",
    )
    .join("");
}
async function bootstrap() {
  const id = ++viewId;
  controller?.abort();
  catalogController?.abort();
  ++catalogVersion;
  ++rankingVersion;
  rankingController?.abort();
  rankingState = "idle";
  rankingView = "clubs";
  ranking = { entries: [], total: 0, offset: 0, limit: 25 };
  dataStates = {};
  homeTop = null;
  teamLoading = false;
  controller = new AbortController();
  status = "loading";
  error = "";
  render();
  try {
    if (mode === "demo") {
      serverTeam = null;
      coaches = [];
      competitions = [demoCompetition];
      competition = "demo";
      matchdays = [
        { id: "demo-7", label: "7. kolo", number: 7, status: "UPCOMING" },
      ];
      selectedDay = "demo-7";
      matches = demoMatches;
      standings = demoStandings;
      facets = {
        clubs: [...new Set(demoPlayers.map((p) => p.real_club))],
        positions: ["GK", "OT", "CF", "CB"],
      };
      readDraft();
      status = "ready";
      render();
      if (page === "players") loadCatalog();
      return;
    }
    competitions = await request("/competitions", {
      signal: controller.signal,
    });
    if (id !== viewId) return;
    if (!competitions.length) throw new Error("Baza još nema takmičenja.");
    if (!competitions.some((c) => c.id === competition))
      competition = competitions[0].id;
    readDraft();
    const signal = controller.signal;
    const scope = competition;
    matches = [];
    standings = [];
    matchdays = [];
    coaches = [];
    serverTeam = null;
    facets = { clubs: [], positions: ["GK", "OT", "CF", "CB"] };
    teamLoading = Boolean(token && user);
    const job = async (key, action) => {
      dataStates[key] = "loading";
      try {
        await action();
        if (id === viewId) dataStates[key] = "ready";
      } catch (e) {
        if (id === viewId && e.name !== "AbortError")
          dataStates[key] = e.message;
      }
      if (id === viewId) render();
    };
    const homeTask = job("home", async () => {
      let bundle;
      try {
        bundle = await request(`/home?competition_id=${scope}`, {
          signal,
          cacheMs: 30000,
        });
      } catch (e) {
        if (e.status !== 404) throw e;
        // Older validated backend deployments retain the existing public routes.
        const days = await request(`/competitions/${scope}/matchdays`, {
          signal,
        });
        const day = days.find((d) => d.status === "UPCOMING") || days.at(-1);
        const items = day
          ? await request(`/matchdays/${day.id}/matches`, { signal })
          : [];
        bundle = { selected_matchday: day, matches: items };
      }
      if (id !== viewId) return;
      if (bundle.selected_matchday) {
        matchdays = [bundle.selected_matchday];
        selectedDay = bundle.selected_matchday.id;
      } else selectedDay = "";
      matches = bundle.matches;
      homeTop = bundle.standings_top4 ?? null;
    });
    const daysTask = job("days", async () => {
      const days = await request(`/competitions/${scope}/matchdays`, {
        signal,
        cacheMs: 30000,
      });
      await homeTask;
      if (id === viewId) {
        const selected = currentDay();
        matchdays = days.map((d) =>
          d.id === selected?.id ? { ...d, ...selected } : d,
        );
      }
    });
    const otherTasks = [
      job("standings", async () => {
        const value = await request(`/competitions/${scope}/standings`, {
          signal,
          cacheMs: 30000,
        });
        if (id === viewId) standings = value;
      }),
      job("facets", async () => {
        const value = await request(`/players/facets?competition_id=${scope}`, {
          signal,
          cacheMs: 60000,
        });
        if (id === viewId) facets = value;
      }),
      job("coaches", async () => {
        const value = await request(`/coaches?competition_id=${scope}`, {
          signal,
          cacheMs: 30000,
        });
        if (id === viewId) coaches = value;
      }),
    ];
    status = "ready";
    render();
    if (page === "players") loadCatalog();
    const privateTask = job("team", async () => {
      await daysTask;
      if (id !== viewId) return;
      try {
        if (token && user) await loadServerTeam(id);
      } finally {
        if (id === viewId) teamLoading = false;
      }
    });
    await Promise.all([homeTask, daysTask, privateTask, ...otherTasks]);
  } catch (e) {
    if (id !== viewId || e.name === "AbortError") return;
    status = "error";
    error = e.message || "Neuspešno povezivanje sa API-jem.";
    render();
  }
}
let catalogVersion = 0,
  catalogController;
async function loadCatalog() {
  const id = ++catalogVersion;
  catalogController?.abort();
  catalogController = new AbortController();
  const cachedPath = catalogQuery({
    competition,
    search: query,
    position,
    club,
    sort,
    offset,
  });
  const cached = mode === "api" ? peekCache(cachedPath) : null;
  if (cached) catalog = cached;
  status = cached ? "ready" : "catalog-loading";
  error = "";
  if (page === "players") {
    $("#catalog-result").innerHTML = catalogContent();
  }
  try {
    if (mode === "demo") {
      let list = demoPlayers.filter(
        (p) =>
          p.name
            .toLocaleLowerCase("sr")
            .includes(query.toLocaleLowerCase("sr")) &&
          (!position || p.position === position) &&
          (!club || p.real_club === club),
      );
      list.sort((a, b) =>
        sort.startsWith("name")
          ? (sort === "name_asc" ? 1 : -1) * a.name.localeCompare(b.name)
          : (sort === "cost_asc" ? 1 : -1) *
              (a.current_cost - b.current_cost) || a.id.localeCompare(b.id),
      );
      catalog = {
        items: list.slice(offset, offset + 24),
        total: list.length,
        limit: 24,
        offset,
      };
    } else {
      const result = await request(
        catalogQuery({
          competition,
          search: query,
          position,
          club,
          sort,
          offset,
        }),
        { signal: catalogController.signal, cacheMs: 30000 },
      );
      if (id !== catalogVersion) return;
      catalog = result;
    }
    if (id !== catalogVersion) return;
    status = "ready";
    if (page === "players") {
      $("#catalog-result").innerHTML = catalogContent();
      bindCatalog();
    }
  } catch (e) {
    if (id !== catalogVersion || e.name === "AbortError") return;
    status = "ready";
    error = e.message;
    if (page === "players") {
      $("#catalog-result").innerHTML = catalogContent();
      bindCatalog();
    }
  }
}
function modal(html) {
  const d = $("#dialog");
  d.innerHTML = '<button class="close" aria-label="Zatvori">×</button>' + html;
  d.querySelector(".close").onclick = () => d.close();
  if (!d.open) d.showModal();
  d.onclick = (e) => {
    if (e.target === d) {
      const r = d.getBoundingClientRect();
      if (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      )
        d.close();
    }
  };
}
function pickSlot(index) {
  const role = FORMATIONS[draft.formation].roles[index],
    current = draft.roster.find((p) => p.id === draft.active[index]);
  const eligible = draft.roster.filter((p) => p.position === role);
  modal(
    `<div class="eyebrow">MESTO ${index + 1} · ${role}</div><h2>${current ? esc(current.name) : "Izaberi igrača"}</h2><p>${current ? "Promeni igrača ili ga postavi za kapitena." : "Za ovo mesto potreban je " + role + " iz tvog rostera."}</p>${current ? '<button class="primary" id="captain">Postavi za kapitena Ⓒ</button>' : ""}<div class="pick-list">${eligible.map((p) => `<button class="pick-row" data-pick="${p.id}"><span class="avatar">${short(p.name).slice(0, 2)}</span><span><b>${esc(p.name)}</b><small>${esc(p.real_club)}</small></span><span>${draft.active.includes(p.id) ? "U bazenu" : "Na klupi"} →</span></button>`).join("") || '<div class="empty">U rosteru nema odgovarajućeg igrača.</div>'}</div><button class="secondary" id="to-market">Pronađi ${role} na transferima →</button>`,
  );
  $("#captain")?.addEventListener("click", () => {
    draft.captain = current.id;
    draft.savedAt = null;
    saveLocal();
    $("#dialog").close();
    render();
    toast("Kapiten: " + current.name);
  });
  $$("[data-pick]").forEach(
    (b) =>
      (b.onclick = () => {
        const id = b.dataset.pick,
          previous = draft.active[index],
          other = draft.active.indexOf(id);
        if (other >= 0) draft.active[other] = previous;
        draft.active[index] = id;
        if (!draft.active.includes(draft.captain)) draft.captain = id;
        draft.savedAt = null;
        saveLocal();
        $("#dialog").close();
        render();
      }),
  );
  $("#to-market").onclick = () => {
    position = role;
    offset = 0;
    $("#dialog").close();
    setPage("players");
  };
}
function buyModal(p) {
  if (teamLoading || busy || (mode === "api" && dataStates.team !== "ready")) {
    toast("Sačekaj učitavanje svog tima pre transfera.");
    return;
  }
  if (draft.roster.some((r) => r.id === p.id)) {
    detail(p.id);
    return;
  }
  modal(
    `<div class="eyebrow">TRANSFER · ${p.position}</div><h2>${esc(p.name)}</h2><p>${esc(p.real_club)} · ${money(p.current_cost)} kredita</p><form id="transfer-form"><label for="outgoing">${draft.roster.length >= 11 ? "Izaberi igrača kojeg menjaš" : "Dodaj ili zameni igrača"}</label><select id="outgoing" name="outgoing"><option value="">${draft.roster.length >= 11 ? "Izaberi zamenu…" : "Slobodno mesto"}</option>${draft.roster.map((r) => `<option value="${r.id}">${esc(r.name)} · ${r.position} · ${money(r.current_cost)} kr</option>`).join("")}</select><p class="tiny">${mode === "demo" ? "Demo transfer" : serverTeam ? "Transfer se upisuje na server" : "Izmena lokalnog nacrta"} · raspoloživo ${money(budget())} kr</p><div id="transfer-error" class="inline-error" role="alert"></div><button class="primary">Potvrdi transfer</button></form>`,
  );
  $("#transfer-form").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    if (button.disabled) return;
    button.disabled = true;
    try {
      if (mode === "api" && serverTeam) {
        const outgoing = $("#outgoing").value;
        if (!outgoing) throw new Error("Izaberi igrača kojeg menjaš.");
        const updated = await request(`/teams/${serverTeam.id}/transfers`, {
          method: "POST",
          token,
          body: {
            drop_entity_type: "PLAYER",
            drop_entity_id: outgoing,
            add_entity_type: "PLAYER",
            add_entity_id: p.id,
          },
        });
        hydrateTeam(updated);
      } else draft = buyPlayer(draft, p, $("#outgoing").value || null);
      draft.savedAt = null;
      saveLocal();
      $("#dialog").close();
      render();
      toast(p.name + " je u tvom rosteru.");
    } catch (err) {
      $("#transfer-error").textContent = err.message;
      button.disabled = false;
    }
  };
}
async function detail(id) {
  let p =
    draft.roster.find((p) => p.id === id) ||
    catalog.items.find((p) => p.id === id) ||
    demoPlayers.find((p) => p.id === id);
  if (!p) return;
  modal('<div class="loading">Učitavam profil…</div>');
  try {
    if (mode === "api") p = await request(`/players/${id}`);
    if (!$("#dialog").open) return;
    modal(
      `<div class="eyebrow">${esc(p.real_club)} · ${p.position || "NEPOZNATA POZICIJA"}</div><h2>${esc(p.name)}</h2><div class="summary-stats"><div><span>Cena</span><strong>${money(p.current_cost)} kr</strong></div><div><span>Poeni</span><strong>${mode === "demo" ? p.points || "—" : money(p.season?.total_raw_points)}</strong></div></div><p>${p.position ? "Pozicija: " + p.position : "Pozicija još nije potvrđena u bazi. Igrač ne može u validan sastav."}</p>${draft.roster.some((r) => r.id === id) ? (serverTeam ? "<p>Zameni ovog igrača kroz transfere da roster ostane kompletan.</p>" : '<button class="secondary" id="sell">Ukloni iz lokalnog rostera</button>') : p.position ? '<button class="primary" id="profile-buy">Dovedi igrača</button>' : ""}`,
    );
    $("#sell")?.addEventListener("click", () => {
      draft.roster = draft.roster.filter((r) => r.id !== id);
      draft.active = draft.active.map((x) => (x === id ? null : x));
      if (draft.captain === id)
        draft.captain = draft.active.find(Boolean) || null;
      draft.savedAt = null;
      saveLocal();
      $("#dialog").close();
      render();
      toast("Igrač je uklonjen iz nacrta.");
    });
    $("#profile-buy")?.addEventListener("click", () => buyModal(p));
  } catch (e) {
    modal(`<h2>Profil nije dostupan</h2><p>${esc(e.message)}</p>`);
  }
}
function hydrateTeam(team, lineup = null) {
  serverTeam = team;
  draft.roster = team.roster
    .filter((r) => r.entity_type === "PLAYER")
    .map((r) => ({
      id: r.entity_id,
      name: r.name,
      position: r.position,
      real_club: r.real_club,
      current_cost: Number(r.current_cost),
    }));
  const c = team.roster.find((r) => r.entity_type === "COACH");
  draft.coach = c
    ? { id: c.entity_id, name: c.name, current_cost: Number(c.current_cost) }
    : null;
  draft.name = team.name;
  draft.savedAt = null;
  if (lineup?.formation) {
    draft.formation = lineup.formation;
    draft.active = autoLineup(
      draft.formation,
      draft.roster.filter((p) => lineup.active_player_ids.includes(p.id)),
      lineup.active_player_ids,
    );
    draft.captain = lineup.captain_id;
  } else draft = changeFormation(draft, draft.formation);
  saveLocal();
}
async function loadServerTeam(version) {
  const list = await request("/teams/me", { token, signal: controller.signal });
  if (version !== viewId) return;
  if (list.some((t) => !t.competition_id))
    throw new Error(
      "Backend treba uskladiti sa sačuvanim timovima. Tvoj nacrt nije prepisan.",
    );
  const team = list.find((t) => t.competition_id === competition);
  if (!team) {
    serverTeam = null;
    return;
  }
  let lineup = null;
  if (selectedDay)
    lineup = await request(
      `/teams/${team.id}/lineup?matchday_id=${selectedDay}`,
      { token, signal: controller.signal },
    );
  if (version !== viewId) return;
  hydrateTeam(team, lineup);
}
async function saveConfirmedLineup(path, options) {
  try {
    return await request(path, options);
  } catch (error) {
    if (error.status && error.status !== 409 && error.status < 500) throw error;
    try {
      const saved = await request(path, { token: options.token });
      const intended = options.body;
      if (
        saved.formation === intended.formation &&
        saved.captain_id === intended.captain_id &&
        JSON.stringify([...saved.active_player_ids].sort()) ===
          JSON.stringify([...intended.active_player_ids].sort())
      )
        return saved;
    } catch {}
    throw error;
  }
}
async function saveLineup() {
  if (busy || teamLoading || (mode === "api" && dataStates.team !== "ready"))
    return;
  const errors = [
    ...lineupErrors(draft.formation, draft.active, draft.roster, draft.captain),
    ...rosterErrors(draft.roster, draft.active),
  ];
  if (!draft.coach) errors.push("Izaberi trenera.");
  if (errors.length) {
    toast(errors[0]);
    return;
  }
  if (mode === "api" && !user) {
    authModal();
    return;
  }
  if (
    mode === "api" &&
    (!currentDay()?.deadline ||
      new Date(currentDay().deadline) <= new Date() ||
      currentDay().status !== "UPCOMING")
  ) {
    toast(
      "Sastav trenutno nije moguće upisati: nema otvorenog kola sa potvrđenim rokom. Nacrt ostaje sačuvan lokalno.",
    );
    saveLocal();
    return;
  }
  busy = true;
  render();
  try {
    if (mode === "api") {
      await request("/lineups/validate", {
        method: "POST",
        body: {
          formation: draft.formation,
          active_player_ids: draft.active,
          captain_id: draft.captain,
          competition_id: competition,
        },
      });
      if (!serverTeam)
        serverTeam = await request("/teams", {
          method: "POST",
          token,
          body: {
            competition_id: competition,
            name: draft.name,
            player_ids: draft.roster.map((p) => p.id),
            coach_id: draft.coach.id,
          },
        });
      const saved = await saveConfirmedLineup(
        `/teams/${serverTeam.id}/lineup?matchday_id=${selectedDay}`,
        {
          method: "PUT",
          token,
          body: {
            formation: draft.formation,
            active_player_ids: draft.active,
            captain_id: draft.captain,
            expected_version: serverTeam.version,
          },
        },
      );
      serverTeam.version = saved.version;
    }
    draft.savedAt = new Date().toISOString();
    if (saveLocal())
      toast(
        mode === "demo"
          ? "Demo sastav je sačuvan."
          : "Sastav je sačuvan na serveru.",
      );
  } catch (e) {
    toast(
      e.status === 409
        ? "Podaci su promenjeni ili je kolo zatvoreno. Osveži podatke pre ponovnog čuvanja."
        : e.message,
    );
  } finally {
    busy = false;
    render();
  }
}
function coachModal() {
  if (teamLoading || busy || (mode === "api" && dataStates.team !== "ready")) {
    toast("Sačekaj učitavanje svog tima.");
    return;
  }
  if (mode === "demo") {
    modal("<h2>Stručni štab</h2><p>Demo trener je deo tima i budžeta.</p>");
    return;
  }
  modal(
    `<h2>Izaberi trenera</h2><p>Imena sa oznakom TBD su privremeni zapisi iz baze.</p><div class="pick-list">${coaches.map((c) => `<button class="pick-row" data-coach="${c.id}"><span><b>${esc(c.name)}</b><small>${esc(c.real_club)}</small></span><b>${money(c.current_cost)} kr</b></button>`).join("") || '<div class="empty">Nema trenera u bazi.</div>'}</div>`,
  );
  $$("[data-coach]").forEach(
    (b) =>
      (b.onclick = async () => {
        if (busy) return;
        const c = coaches.find((c) => c.id === b.dataset.coach);
        if (budget() + (draft.coach?.current_cost || 0) < c.current_cost) {
          toast("Nema dovoljno kredita.");
          return;
        }
        busy = true;
        b.disabled = true;
        try {
          if (serverTeam) {
            const updated = await request(`/teams/${serverTeam.id}/transfers`, {
              method: "POST",
              token,
              body: {
                drop_entity_type: "COACH",
                drop_entity_id: draft.coach.id,
                add_entity_type: "COACH",
                add_entity_id: c.id,
              },
            });
            hydrateTeam(updated);
          } else {
            draft.coach = {
              id: c.id,
              name: c.name,
              current_cost: c.current_cost,
            };
            draft.savedAt = null;
            saveLocal();
          }
          $("#dialog").close();
          render();
          toast("Trener izabran.");
        } catch (e) {
          toast(e.message);
        } finally {
          busy = false;
          b.disabled = false;
        }
      }),
  );
}
function authModal(register = false) {
  if (user) {
    modal(
      `<h2>${esc(user.display_name)}</h2><p>${esc(user.email)}</p><button class="secondary" id="logout">Odjavi se</button>`,
    );
    $("#logout").onclick = () => {
      clearPublicCache();
      token = null;
      user = null;
      serverTeam = null;
      sessionStorage.removeItem("vrl-token");
      $("#dialog").close();
      bootstrap();
    };
    return;
  }
  modal(
    `<div class="eyebrow">DOBRO DOŠAO U EKIPU</div><h2>${register ? "Napravi nalog" : "Prijavi se"}</h2><form id="auth-form">${register ? '<label>Ime<input name="display_name" autocomplete="nickname" required maxlength="60"></label>' : ""}<label>Email<input name="email" type="email" autocomplete="email" required maxlength="254"></label><label>Lozinka<input name="password" type="password" autocomplete="${register ? "new-password" : "current-password"}" required minlength="8"></label><div id="auth-error" class="inline-error" role="alert"></div><button class="primary full">${register ? "Registruj se" : "Prijavi se"}</button></form><button class="text-link auth-switch" id="switch-auth">${register ? "Već imaš nalog? Prijavi se" : "Nemaš nalog? Registruj se"}</button>`,
  );
  $("#switch-auth").onclick = () => authModal(!register);
  $("#auth-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target,
      data = Object.fromEntries(new FormData(form));
    if (new TextEncoder().encode(data.password).length > 72) {
      $("#auth-error").textContent =
        "Lozinka može imati najviše 72 UTF-8 bajta.";
      return;
    }
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const out = await request("/auth/" + (register ? "register" : "login"), {
        method: "POST",
        body: data,
      });
      token = out.access_token;
      sessionStorage.setItem("vrl-token", token);
      user = await request("/auth/me", { token });
      $("#dialog").close();
      bootstrap();
      toast("Dobro došao, " + user.display_name);
    } catch (err) {
      $("#auth-error").textContent = err.message;
      button.disabled = false;
    }
  };
}
function bindCatalog() {
  $$("[data-detail]").forEach(
    (b) => (b.onclick = () => detail(b.dataset.detail)),
  );
  $$("[data-buy]").forEach(
    (b) =>
      (b.onclick = () =>
        buyModal(catalog.items.find((p) => p.id === b.dataset.buy))),
  );
  $("#prev-page")?.addEventListener("click", () => {
    offset = Math.max(0, offset - 24);
    loadCatalog();
  });
  $("#next-page")?.addEventListener("click", () => {
    offset += 24;
    loadCatalog();
  });
  $("#retry-catalog")?.addEventListener("click", loadCatalog);
}
function bind() {
  $$("[data-ranking]").forEach(
    (b) =>
      (b.onclick = () => {
        rankingView = b.dataset.ranking;
        render();
        if (rankingView === "fantasy" && mode === "api") loadRanking();
      }),
  );
  $("#ranking-prev")?.addEventListener("click", () =>
    loadRanking(Math.max(0, ranking.offset - ranking.limit)),
  );
  $("#ranking-next")?.addEventListener("click", () =>
    loadRanking(ranking.offset + ranking.limit),
  );
  $("#retry-ranking")?.addEventListener("click", () =>
    loadRanking(ranking.offset),
  );
  $$("[data-view]").forEach(
    (b) =>
      (b.onclick = () => {
        squadView = b.dataset.view;
        render();
      }),
  );
  $("#mobile-save")?.addEventListener("click", saveLineup);
  $$("[data-go]").forEach((b) => (b.onclick = () => setPage(b.dataset.go)));
  $$("[data-mode]").forEach(
    (b) =>
      (b.onclick = () => {
        if (mode === b.dataset.mode) return;
        mode = b.dataset.mode;
        localStorage.setItem("vrl-mode", mode);
        competition = "";
        serverTeam = null;
        offset = 0;
        club = "";
        position = "";
        query = "";
        catalogVersion++;
        catalogController?.abort();
        bootstrap();
      }),
  );
  $("#competition").onchange = (e) => {
    competition = e.target.value;
    serverTeam = null;
    catalogVersion++;
    catalogController?.abort();
    offset = 0;
    club = "";
    query = "";
    bootstrap();
  };
  $("#account").onclick = () => authModal();
  $("#rules").onclick = () =>
    modal(
      "<h2>Tvoja fantasy pravila</h2><p>100 kredita. Jedanaest igrača i trener. U bazenu je uvek 1 GK i 4 OT; formacija određuje da li preostala dva mesta pripadaju CF+CB, CF+CF ili CB+CB.</p><p>Klupa: rezervni GK, dva OT i jedan CF/CB, uz trenera. Kapiten mora biti starter. Transferi su u v1 neograničeni u otvorenom prozoru; demo nema pravi rok.</p>",
    );
  $("#retry")?.addEventListener("click", bootstrap);
  $$("[data-formation]").forEach(
    (b) =>
      (b.onclick = () => {
        draft = changeFormation(draft, b.dataset.formation);
        draft.savedAt = null;
        saveLocal();
        render();
        if (draft.active.some((id) => !id))
          toast("Formacija promenjena. Popuni označena prazna mesta.");
      }),
  );
  $$("[data-slot]").forEach(
    (b) => (b.onclick = () => pickSlot(Number(b.dataset.slot))),
  );
  $$("[data-bench]").forEach(
    (b) =>
      (b.onclick = () => {
        const p = draft.roster.find((p) => p.id === b.dataset.bench);
        const index = FORMATIONS[draft.formation].roles.findIndex(
          (r) => r === p.position,
        );
        if (index >= 0) pickSlot(index);
        else detail(p.id);
      }),
  );
  $("#coach")?.addEventListener("click", coachModal);
  $("#save-lineup")?.addEventListener("click", saveLineup);
  $("#rename")?.addEventListener("click", () => {
    if (serverTeam) {
      toast("Promena imena već kreiranog tima još nije dostupna.");
      return;
    }
    modal(
      `<h2>Ime tvog tima</h2><form id="rename-form"><input name="name" aria-label="Ime tima" value="${esc(draft.name)}" required maxlength="40"><button class="primary">Sačuvaj ime</button></form>`,
    );
    $("#rename-form").onsubmit = (e) => {
      e.preventDefault();
      const name = new FormData(e.target).get("name").trim();
      if (!name) return;
      draft.name = name;
      saveLocal();
      $("#dialog").close();
      render();
    };
  });
  $("#search")?.addEventListener("input", (e) => {
    query = e.target.value;
    offset = 0;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadCatalog, 250);
  });
  for (const id of ["position", "club", "sort"])
    $("#" + id)?.addEventListener("change", (e) => {
      if (id === "position") position = e.target.value;
      if (id === "club") club = e.target.value;
      if (id === "sort") sort = e.target.value;
      offset = 0;
      loadCatalog();
    });
  $("#matchday")?.addEventListener("change", async (e) => {
    selectedDay = e.target.value;
    const selected = selectedDay;
    try {
      const items = await request(`/matchdays/${selected}/matches`);
      if (selected === selectedDay) {
        matches = items;
        render();
      }
    } catch (err) {
      toast(err.message);
    }
  });
  $$("[data-match]").forEach(
    (b) =>
      (b.onclick = async () => {
        const m = matches.find((m) => m.id === b.dataset.match);
        modal(
          `<h2>${esc(m.home_club)} — ${esc(m.away_club)}</h2><p>${mode === "demo" ? "Demonstraciona utakmica." : "Učitavam statistiku…"}</p>`,
        );
        if (mode === "api")
          try {
            const data = await request(`/matches/${m.id}`);
            if (!$("#dialog").open) return;
            modal(
              `<h2>${esc(m.home_club)} — ${esc(m.away_club)}</h2><p>${m.home_score ?? "—"} : ${m.away_score ?? "—"}</p><div class="table-scroll"><table><thead><tr><th>Igrač</th><th>Golovi</th><th>Poeni</th></tr></thead><tbody>${data.player_stats.map((p) => `<tr><td>${esc(p.player_name)}</td><td>${p.goals}</td><td>${money(p.raw_points)}</td></tr>`).join("")}</tbody></table></div>`,
            );
          } catch (e) {
            modal(`<h2>Statistika nije dostupna</h2><p>${esc(e.message)}</p>`);
          }
      }),
  );
  $$("[data-article]").forEach(
    (b) =>
      (b.onclick = () => {
        const a = articles[Number(b.dataset.article)];
        modal(
          `<div class="eyebrow">${a.tag}</div><h2>${a.title}</h2><p>${a.body}</p>`,
        );
      }),
  );
  bindCatalog();
}
if (token)
  request("/auth/me", { token })
    .then((u) => {
      user = u;
    })
    .catch(() => {
      token = null;
      sessionStorage.removeItem("vrl-token");
    })
    .finally(bootstrap);
else bootstrap();
