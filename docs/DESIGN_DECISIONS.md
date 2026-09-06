# Vizuelni pravac i raspored

Primarna referenca je korisnikov Claude handoff (docs/CLAUDE_DESIGN_REFERENCE.md): belo sticky zaglavlje, plava pozadina, navy hero, zlatni akcent, bazen sa belim karticama.

Korisnik je izričito definisao pravila formacija. Inspiracija iz drugih sportova odnosi se samo na raspored, vizuelnu hijerarhiju i dostupnost akcija, nikada na ta pravila.

- Desktop: bazen je dominantna centralna kolona; levo su formacija, budžet i čuvanje. Desno su pomoćni podaci. Klupa je neposredno ispod sastava.
- Telefon: prvo kratka kontrola formacije/budžeta, zatim bazen, klupa, pa sekundarne informacije. Čuvanje i preostali budžet dostupni su u fiksnoj donjoj traci.
- Bazen/lista prikazi dele ista imena, pozicije i kapitena. Lista je alternativa za brzo čitanje, tastaturu i manje ekrane.
- Transferi koriste search debounce, backend filtere i strane od24; nijedan ekran ne iscrtava hiljade redova. Kartice na mobilnom zamenjuju široku tabelu igrača.
- Potvrda transfera prikazuje igrača koji izlazi i cenu pre izmene; ne prebacuje automatski igrače bez potvrde.
- Demo i stvarni API su vidljivo odvojeni. Ne prikazujemo izmišljene deadline-ove ni stvarne poene kada ih API ne vraća.

Inspiracija pregledana 2026-09-06:
- https://www.premierleague.com/en/news/4680259/whats-new-in-202627-fantasy-more-ways-to-view-your-squad/ — pitch/list pregledi i više informacija uz sastav.
- https://fantasy.premierleague.com/ — odvajanje glavne navigacije, početnog CTA i sekundarnog editorial sadržaja.
- https://euroleaguefantasy.euroleaguebasketball.net/ — pregled javne stranice; sadržaj aplikacije zavisi od učitavanja/prijave. Ne tvrdimo da smo pregledali privatne ekrane naloga.

Nisu kopirani tuđi logotipi, sportska pravila ni zaštićeni dizajnerski assets. VRL fotografije ostaju preuzete sa ranije navedenih izvora.
