# Handoff: VRL Fantasy Vaterpolo (Regionalna liga)

## Overview
Fantasy web app za VRL — Vaterpolo regionalnu ligu (Premijer liga, klubovi iz Srbije i Crne Gore, sezona 2025/26). Korisnik sastavlja tim od 7 startera + 5 rezervi u okviru 100 kredita, ima 5 transfera po kolu i prati raspored i tabelu lige. Prototip sadrži 4 ekrana: **Početna**, **Moj tim**, **Raspored**, **Tabela**.

## About the Design Files
Fajlovi u ovom paketu su **dizajnerske reference napisane u HTML-u** — prototip koji pokazuje željeni izgled i ponašanje, a ne produkcioni kod za direktno kopiranje. Zadatak je da se ovi dizajni **rekreiraju u postojećem okruženju ciljnog koda** (React, Vue, Next, SwiftUI…) uz postojeće konvencije i biblioteke tog projekta. Ako okruženje još ne postoji, izabrati odgovarajući framework i implementirati dizajn u njemu.

`VRL Fantasy.dc.html` je jedan samostalan HTML fajl: markup + jedna JS klasa sa stanjem, svi stilovi su inline. `support.js` je runtime koji renderuje taj fajl u pregledaču — **nije deo dizajna** i ne treba ga portovati.

## Fidelity
**High-fidelity.** Boje, tipografija, spacing i stanja su finalni; rekreirati piksel-verno, ali koristeći komponente/design-system ciljnog projekta gde postoje ekvivalenti (tabela, kartice, dugmad).

## Screens / Views

### 1. Zajednički okvir (na svim ekranima)
- **Pozadina stranice:** `#a8cbe9` (puna plava, bez teksture).
- **Sticky header** (`position: sticky; top: 0; z-index: 50`), `background #fff`, `border-bottom 1px solid #dbe5ec`, padding `12px 24px`, `display:flex; justify-content:space-between; align-items:center; gap:24px`.
  - **Logo blok:** kvadrat 40×40, `border-radius 9px`, `linear-gradient(160deg, #0b3a5c, #0a2237)`, tekst „VRL“ — Barlow Condensed 800, 17px, letter-spacing .06em, bela. Pored: „FANTASY VATERPOLO“ (Barlow Condensed 800, 17px, uppercase, `#0a2237`) i podnaslov „Regionalna liga · 2025/26“ (11px/600, `#5c7488`).
  - **Nav:** `display:flex; gap:4px`. Stavke: Početna, Moj tim, Raspored, Tabela (klikabilne) + „Igrači“ (neaktivna, `#7b93a6`, tooltip „U pripremi“). Neaktivna stavka: 14px/500, `#4a6478`, padding `9px 13px`, `border-radius 8px`, transparentna. Aktivna: 14px/700, `#0a2237`, `background #e4f1f7`, `box-shadow: inset 0 -3px 0 <accent>`.
  - **Desno:** chip sa korisnikom (`background #eef3f6`, `border-radius 999px`, padding `6px 12px`, 13px/600, zelena tačka 8px `#1fa971` sa `box-shadow 0 0 0 3px rgba(31,169,113,.18)`) i dugme „Odjava“ (`border 1px solid #dbe5ec`, `background #fff`, `border-radius 8px`, 13px/600, hover `#eef3f6`).
- **Sadržaj:** `max-width 1400px` (Raspored i Tabela: `1120px`), `margin 0 auto`, padding `22–30px 24px 56px`.

### 2. Početna
- **Hero:** `linear-gradient(180deg, #071c2e 0%, #0b3a5c 60%, #0f5279 100%)`, beli tekst, padding `40px 24px 46px`, ispod hero-a puna traka `height 6px; background: <accent>`.
  - Levo (flex `1 1 380px`): pill „PREMIJER LIGA · 7. KOLO“ (11px/700, uppercase, letter-spacing .09em, `background rgba(240,169,43,.18)`, `color #ffdca0`, `border-radius 999px`, padding `4px 11px`); H1 „Sastavi svoj tim / regionalne lige“ (Barlow Condensed 800, 52px, line-height .96); paragraf 15px/1.6 `rgba(255,255,255,.88)`, `max-width 46ch`: „Osam klubova iz Srbije i Crne Gore, 100 kredita i pet transfera po kolu. Bodovi se računaju iz zvanične statistike utakmica.“; dva dugmeta — primarno „Uredi moj tim“ (`background <accent>`, `color #241704`, 13px padding `13px 20px`, `border-radius 9px`, 14px/700, hover `filter: brightness(.94)`) i sekundarno „Raspored kola“ (`border 1px solid rgba(255,255,255,.4)`, transparentno, hover `rgba(255,255,255,.12)`).
  - Desno (flex `0 1 330px`): kartica `background rgba(255,255,255,.08)`, `border 1px solid rgba(255,255,255,.18)`, `border-radius 14px`, padding 20. Sadrži **countdown** „Zaključavanje sastava“ (JetBrains Mono, cifre 30px/700, `font-variant-numeric: tabular-nums`, labele „sati/min/sek“ 9px uppercase `rgba(255,255,255,.82)`, separator „:“ 22px `opacity .4`) i grid 2 kolone: „Tim“ = naziv tima, „Mesto“ = 1.204 (Barlow Condensed 700, 22px).
- **Body:** flex-wrap, gap 18px. Leva kolona (`flex 2 1 420px`):
  - Kartica „Tvoje kolo“ — eyebrow 10px uppercase `#4a6478`, H2 „6. kolo — 68,4 poena“ (Barlow Condensed 700, 26px), badge „+312 mesta“ (12px/700, `color #14804f`, `background #e7f6ee`, `border-radius 999px`); grid `repeat(auto-fit, minmax(130px,1fr))` sa 3 statistike (Kapiten / Prosek lige / Transferi) u pločicama `background #f2f8fd`, `border 1px solid #e2edf4`, `border-radius 11px`, padding 14.
  - Kartica „Utakmice ovog kola“ (7. kolo) — lista 4 utakmice, red = `grid: minmax(0,1fr) auto`, padding `13px 0`, `border-top 1px solid #e6edf2`; naziv 14px/600, termin 12px/600 `#4a6478`. Dugme „Ceo raspored“ vodi na Raspored.
  - Desna kolona (`flex 1 1 300px; max-width 360px`): kartica „Vrh Premijer lige“ (top 4, prvo mesto broj u `<accent>`, poeni JetBrains Mono 13px/700) + dugme „Cela tabela“; tamna kartica saveta `background #0b3a5c`, beli tekst, naslov Barlow Condensed 22px/700 „Centri protiv Šapca“.
- **Sve kartice:** `background #fff`, `border 1px solid #dbe5ec`, `border-radius 14px`, `box-shadow 0 1px 2px rgba(10,34,55,.05)`, padding 20.

### 3. Moj tim
- **Hero traka:** isti gradijent kao Početna, padding `22px 24px 34px`, tri zone: broj kola („07“ Barlow Condensed 800, 54px + labela „KOLO / Premijer liga“), centar (pill „TRANSFERI OTVORENI“ sa zelenom tačkom `#1fa971` na `rgba(31,169,113,.18)`, H1 „Tim <naziv>“ Barlow Condensed 40px) i countdown desno (isti pattern kao na Početnoj, cifre 28px). Ispod: traka 6px `<accent>`.
- **Grid:** flex-wrap — leva kolona `1 1 280px / max 320px`, centar `4 1 460px`, desni rail `1 1 300px / max 340px` (uslovno, prop `rightRail`).
- **Leva kartica „Pregled tima“:** naziv tima (Barlow Condensed 27px/700), help dugme 28×28; **formacija** — segmented control `grid: repeat(3,1fr)` u `background #eef3f6`, `border-radius 10px`, padding 3, gap 3; opcije **3-3, 4-2, 2-4**; aktivno = `background #fff`, `color #0a2237`, `box-shadow 0 1px 2px rgba(10,34,55,.10)`, neaktivno = transparentno, `color #4a6478`, 13px/600, `border-radius 8px`, padding `8px 10px`.
- **Gauge blok** (Krediti 86/100, Transferi 2/5): labela 13px/600, vrednosti JetBrains Mono, traka `height 6px`, `background #e2eaf0`, `border-radius 999px`; ispuna krediti `linear-gradient(90deg, #0f5279, #35b6d4)`, transferi `<accent>`; subline 11px `#4a6478`.
- **KV grid 2×2:** Vrednost tima 86,5 kr · Projekcija 71,4 pt · Ukupno poena 438 · Mesto 1.204 (labela 10px uppercase `#4a6478`, vrednost Barlow Condensed 24px/700).
- **CTA:** „Zaključaj sastav“ — full-width, `background <accent>`, `color #241704`, `border-radius 9px`, padding `13px 16px`, 14px/700; hint ispod 11px `#4a6478`: „Popuni 7 startera + 5 sa klupe“.
- **Bazen (centar):** kartica `#fff` padding 14; unutra „voda“ = `linear-gradient(180deg, #35b6d4 0%, #1a7fa8 55%, #0f5279 100%)`, `border-radius 10px`, padding `26px 18px`; preko nje tekstura `repeating-linear-gradient(0deg, rgba(255,255,255,.07) 0 1px, transparent 1px 8px)` i „gol“ — apsolutno pozicioniran okvir na vrhu, širina 32%, visina 46px, `border 2.5px solid rgba(255,255,255,.75)` bez gornje ivice, `border-radius 0 0 14px 14px`.
  - **Raspored pozicija:** grid `repeat(3, minmax(0,1fr))`, gap `18px 14px`, `max-width 620px`, centrirano. Redovi: GOL (kol. 2) → VAN (1) i VAN (3) → CEN (2) → VAN (1) i VAN (3) → ODB (2).
  - **Kartica pozicije:** `background rgba(255,255,255,.97)`, `border 1px solid rgba(255,255,255,.6)`, `border-radius 13px`, padding 10, `box-shadow 0 6px 16px rgba(7,28,46,.28)`, hover `translateY(-2px)` + `0 12px 24px rgba(7,28,46,.34)`. Gore: tag pozicije (Barlow Condensed 12px/800, letter-spacing .08em, `color #0b3a5c`, `background #e4f1f7`, `border-radius 5px`, padding `3px 7px`; CEN tag koristi `<accent>` sa `color #241704`) i cena „~12kr…~22kr“ (JetBrains Mono 10px, `#4a6478`). Sredina: krug 38×38 `border-radius 999px`, `background #eef3f6`, `border 1.5px dashed rgba(11,58,92,.35)`, „+“ 22px; ispod „Izaberi igrača“ 10px `#4a6478`. Dole: `border-top 1px dashed #e6edf2`, naziv role centrirano 10px `#4a6478` (Golman / Spoljni napadač / Centar / Centarbek).
  - **Cene po poziciji:** GOL ~12kr, VAN ~14kr, CEN ~22kr, ODB ~18kr.
- **Desni rail:** kartica „Sledeće kolo“ (badge „DERBI“ u `<accent>`, klub-badge 30×30 `border-radius 8px` `background #0b3a5c` bela oznaka RAD/JAD, nazivi Barlow Condensed 19px/700, meta „Sub 20:00 · Kragujevac“ / „Arena Sport“ 12px `#4a6478` iznad `border-top`) i kartica „Preporučeno / Najbolji izbori za 7. kolo“ — lista 4 igrača, red `grid: 32px minmax(0,1fr) auto 26px`, avatar 32px krug `linear-gradient(140deg, #0b3a5c, #1a7fa8)` sa inicijalima, ime 13px/600, tag kluba 10px/700 `#0b3a5c` na `#e4f1f7`, pozicija 10px/700 `#4a6478`, cena JetBrains Mono 12px/700, projekcija 10px/700 `#14804f`, „+“ dugme 26×26 (hover `background <accent>`).
- **Rezerve (ispod grida):** kartica padding 22; header „KLUPA I STRUČNI ŠTAB“ + H2 „Rezerve“ (Barlow Condensed 26px) + chip „0 od 5 popunjeno“; grid `repeat(auto-fit, minmax(150px,1fr))`, gap 14. Pet pločica: TRENER (istaknuta — `linear-gradient(180deg, #e9f4fa, #d3e8f3)`, `border 1px solid rgba(15,82,121,.35)`, tag bela na `#0b3a5c`), GOL, CEN/ODB, VAN, VAN (bele, `border #dbe5ec`, hover `border-color #b9cfdd`). Krug „+“ 44×44.

### 4. Raspored
- Header: eyebrow „PREMIJER LIGA 2025/26“, H1 „Raspored“ (Barlow Condensed 800, 40px); desno prekidač kola (6./7./8. kolo) u belom kontejneru `border 1px solid #dbe5ec`, `border-radius 10px`, padding 4 — aktivno `background #e4f1f7`, 13px/700.
- **Kartica predstojećeg kola:** header traka `background #f2f8fd`, `border-bottom 1px solid #e2edf4`, padding `14px 20px`: „7. KOLO · 20—21. SEPTEMBAR“ (Barlow Condensed 18px/700, uppercase) + badge „PREDSTOJI“ (`background <accent>`, `color #241704`, 11px/700, `border-radius 999px`).
  - Red utakmice: `grid: 92px minmax(0,1fr) auto`, gap 16, padding `16px 20px`, `border-bottom 1px solid #e6edf2`. Termin JetBrains Mono 12px/700 `#4a6478` („SUB 20:00“); parovi = badge kluba 30×30 + naziv 15px/700, razdvojeno „—“; opcioni badge „Derbi“ (10px/700 uppercase, `background #fdf3c4`, `color #241704`); desno mesto igranja 12px/600 `#4a6478`.
  - Utakmice: RAD–JAD (Sub 20:00, Park kupatilo, Kragujevac, Derbi) · NBG–ŠAB (Sub 18:00, 11. april, Beograd) · PRI–PAR (Ned 19:00, Nikša Bućin, Kotor) · BUD–CZV (Ned 20:30, Morača, Podgorica).
- **Kartica „6. KOLO · REZULTATI“** (badge „Odigrano“, 11px/700 `#4a6478`): redovi `grid: minmax(0,1fr) auto`, rezultat JetBrains Mono 14px/700 — Jadran–Novi Beograd 11:10 · Crvena zvezda–Radnički 9:14 · Partizan–Budućnost 12:8 · Šabac–Primorac 10:13.

### 5. Tabela
- Header: eyebrow „PREMIJER LIGA 2025/26 · POSLE 6 KOLA“, H1 „Tabela“; desno legenda — kvadrat 10×10 `border-radius 3px` u `<accent>` = „Fajnal for“, `#cfdde8` = „Plej-of“.
- **Tabela** u kartici `overflow: hidden`. Kolone (isti grid u headeru i redovima): `44px minmax(0,1fr) 46px 46px 46px 46px 66px 56px`, gap 8, padding `12–14px 18px`.
  - Header red: `background #0b3a5c`, beli tekst, 10px/700 uppercase letter-spacing .12em: `#`, Klub, OD, P, N, I, Gol, Bod.
  - Redovi: `border-bottom 1px solid #e6edf2`, `border-left 4px solid` — mesta 1–4 `<accent>`, 5–7 `#cfdde8`, 8. transparent. Pozicija Barlow Condensed 19px/800; klub = badge 28×28 (`#0b3a5c`, bela oznaka) + naziv 14px/700 + grad 11px `#4a6478`; brojevi JetBrains Mono 13px, gol-razlika `#4a6478`, bodovi 14px/700.
  - Podaci: 1. Radnički Kragujevac 6-6-0-0 +27 **18** · 2. Jadran Herceg Novi 6-5-0-1 +18 **15** · 3. Novi Beograd 6-4-1-1 +15 **13** · 4. Primorac Kotor 6-4-0-2 +9 **12** · 5. Crvena zvezda 6-2-1-3 −4 **7** · 6. Partizan 6-2-0-4 −7 **6** · 7. Šabac 6-1-0-5 −22 **3** · 8. Budućnost Podgorica 6-0-0-6 −36 **0**.
- Fusnota 12px `#4a6478`: „Pobeda 3 boda · pobeda posle peteraca 2 · poraz posle peteraca 1. Prva četiri kluba idu na Fajnal for.“

## Interactions & Behavior
- **Navigacija:** klik na nav stavku menja ekran (client-side, bez rutiranja u prototipu). U produkciji: rute `/`, `/moj-tim`, `/raspored`, `/tabela`.
- **Countdown:** tik svake sekunde, format `HH:MM:SS` sa `padStart(2,'0')`, staje na 00:00:00. Startna vrednost u prototipu 23:14:08 — u produkciji računati od deadline timestamp-a kola.
- **Formacija:** segmented control, jedna od 3-3 / 4-2 / 2-4; menja samo aktivno stanje (u produkciji treba i da preuredi pozicije u bazenu).
- **Hover:** nav stavke → `background #eef3f6`; kartice igrača/rezervi → `translateY(-2px)` + jača senka; „+“ dugmad → pozadina `<accent>`; primarna dugmad → `filter: brightness(.94)`; sekundarna → svetlija pozadina. Tranzicije kratke (~120–150ms, ease).
- **Responsive:** sve kolone su flex sa `flex-basis` i `flex-wrap`, pa se rail spušta pod sadržaj na užim ekranima; tabela ima fiksne numeričke kolone i skraćuje kolonu kluba (`minmax(0,1fr)`).
- Nema loading/error stanja u prototipu — dodati po konvencijama ciljnog projekta.

## State Management
- `screen`: `"home" | "team" | "fix" | "tab"` (default `"home"`).
- `formation`: `"3-3" | "4-2" | "2-4"` (default `"3-3"`).
- `h, m, s`: countdown, interval 1s, čisti se na unmount.
- Props (tweakable): `teamName` (string, default „Gasolina“), `accent` (hex, default `#f0a92b`; alternative `#e2483d`, `#35b6d4`, `#1fa971`), `rightRail` (boolean, default `true`).
- Podaci koje treba dovući iz API-ja: sastav tima i cene igrača, krediti/transferi, raspored kola, rezultati, tabela, preporučeni igrači, deadline kola.

## Design Tokens
**Boje**
- Pozadina stranice `#a8cbe9`
- Kartica `#fff`, ivica `#dbe5ec`, tanka linija `#e6edf2`, alt površina `#f2f8fd` / `#eef3f6` / `#e4f1f7`, ivica alt `#e2edf4`, siva ivica reda `#cfdde8`, traka gauge-a `#e2eaf0`
- Tekst: primarni `#0a2237`, sekundarni `#4a6478`, tercijarni `#5c7488`, neaktivni `#7b93a6`
- Navy: `#071c2e`, `#0a2237`, `#0b3a5c`, `#0f5279`; voda: `#1a7fa8`, `#35b6d4`
- Akcent (prop): `#f0a92b`, tekst na akcentu `#241704`; svetli akcent `#fdf3c4`, na tamnom `#ffdca0`
- Uspeh: `#1fa971` (tačke/indikatori), `#14804f` (tekst), `#e7f6ee` (pozadina badge-a)

**Tipografija** — Barlow Condensed (500–800; naslovi, brojevi, tagovi), Public Sans (400–800; UI tekst), JetBrains Mono (400–700; brojevi, vreme, statistika).
Skala: 52 / 40 / 27 / 26 / 24 / 22 / 19 / 18 / 15 / 14 / 13 / 12 / 11 / 10 / 9px. Eyebrow labele: 10px, 700, uppercase, letter-spacing .12–.14em.

**Spacing:** 3, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 32, 40, 46, 56px.
**Radius:** 5, 7, 8, 9, 10, 11, 13, 14, 999px.
**Senke:** kartica `0 1px 2px rgba(10,34,55,.05)`; pločica u bazenu `0 6px 16px rgba(7,28,46,.28)`, hover `0 12px 24px rgba(7,28,46,.34)`; aktivni segment `0 1px 2px rgba(10,34,55,.10)`.

## Assets
Nema slika ni ikona — sve je tipografija, CSS gradijenti i tekstualne oznake klubova (RAD, JAD, NBG, ŠAB, PRI, CZV, PAR, BUD). Ako projekat ima zvanične logotipe klubova i lige, zameniti tekstualne badge-ove logotipima istih dimenzija (30×30 / 28×28, radius 7–8px). Fontovi se učitavaju sa Google Fonts.

## Files
- `VRL Fantasy.dc.html` — kompletan dizajn (sva 4 ekrana, markup + logika + inline stilovi). Otvara se direktno u pregledaču.
- `support.js` — runtime za pregled tog fajla; **ne portovati**.

Podaci o klubovima su realni (VRL Premijer liga 2025/26: Radnički Kragujevac, Jadran Herceg Novi, Novi Beograd, Šabac, Primorac Kotor, Crvena zvezda, Partizan, Budućnost Podgorica), a rezultati, tabela i statistika igrača u prototipu su ilustrativni.
