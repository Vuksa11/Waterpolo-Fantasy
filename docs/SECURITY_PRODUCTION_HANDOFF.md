# Claude — priprema Waterpolo Fantasy aplikacije za produkciju

Pregled: 2026-09-07, main `99a4e8b`; frontend security površina pregledana na `9bc027d`. Korisnik traži security pregled i konkretan plan implementacije, ne deployment. Ovaj dokument je i `Desktop/Problems/problemV19.md`. Nemoj tvrditi „production ready“ dok ne priložiš dokaze za kriterijume ispod. Izmene implementiraj u tematskim commit-ima i upiši status/testove u handoff.

## Dogovor sa korisnikom: Cattaro nije prepreka

Nasumične pozicije Cattara su odobrene. Ne troši vreme na istraživanje pravih pozicija i ne blokiraj produkcionu pripremu zbog njihove autentičnosti. Zadrži raspodelu koja omogućava validne postave; ako generišeš ponovo, koristi stabilan seed/mapiranje, da ponovni import ne menja već kupljene igrače.

Pravila: starteri uvek GK1 + OT4; 3×3 dodaje CF1/CB1, 4×2 CF2/CB0, 2×4 CF0/CB2. Klupa GK1 + OT2 + jedan CF/CB, plus trener izvan 11 igrača. Ne primenjuj broj od 7/11 kao broj svih igrača realnog kluba. Poslednji pregledani Cattaro pool GK5/OT11/CB4/CF3 ima dovoljno svih uloga. Ako random raspodela ostaje, oznaka porekla može ostati interna/informativna; ne pretvarati je u zabranu izbora. Formacije na frontu ne menjati.

## Šta je potvrđeno u ovoj rundi

- `99a4e8b` rešava V18: query `db` uklonjen i efektivna Redis baza proverena; cache koristi shield i nezavisnu DB sesiju; backfill je ograničen competition/source_slug-om; roster sada prenosi position_verified.
- Nezavisni cancellation primer: otkazivanje drugog čekaoca daje `[dict, CancelledError]`, prvi dobija rezultat. Prethodno su oba otkazivana.
- 30 izabranih backend testova prolazi uz `REDIS_URL=''`: cache, rate limiter, frontend API, teams i fixtures. PostgreSQL auth/crash/load testovi nisu izvršavani nad glavnom bazom u ovoj rundi.
- Live localhost3000: `/.env` i `/server.mjs` su 404; `/api/auth/me` i `/api/teams/me` bez tokena 401 sa `Cache-Control: private, no-store`. Front ima nosniff i no-referrer, nema CSP ni zaštitu od iframe ugradnje.
- Kontrola vlasništva na team/lineup/transfer rutama postoji; cene i pozicije uzimaju se iz DB; Decimal, row-lock i expected_version štite bitne invarijante. Ne uklanjati te zaštite radi performansi.
- Pregledani ORM upiti su parametrizovani, catalog pretraga escapuje SQL wildcard-e; nije pronađen SQL injection u tim putanjama. Nazivi timova/korisnika se escapuju u ključnim frontend renderima. To nije dokaz da su svi budući renderi bezbedni.

## 1. P1 — tačan production build koristi drugačije i poznato ranjive biblioteke

**Dokaz:** lokalni venv ima FastAPI0.141.1/Starlette1.6.0/PyJWT2.13.0, a requirements.txt pin-uje FastAPI0.115.0/PyJWT2.9.0. `pip install --dry-run --ignore-installed -r requirements.txt --report ...` razrešava 50 paketa, uključujući Starlette0.38.6. Prolaz lokalnih testova nije test tog Docker build-a.

OSV querybatch za svih 50 razrešenih verzija prijavljuje nalaze za Starlette0.38.6, PyJWT2.9.0, requests2.32.3, lxml5.3.0 i python-dotenv1.0.1. Potpun spisak ID-eva je u `docs/security/problemV19-dependencies.json`. GHSA i PYSEC često predstavljaju isti problem; ne brojati ih kao nezavisne napade.

Primeri: requests GHSA-9hjg-9r4m-mvj7 (.netrc leak, ispravljeno2.32.4), PyJWT GHSA-752w-5fwx-jx9f (crit header, ispravljeno2.12.0), lxml GHSA-vfmq-68hx-4jfw (određeni XML parseri/XXE, ispravljeno6.1.0), dotenv GHSA-mf9w-mj56-hr94 (set_key/symlink, ispravljeno1.2.2). Ovo su minimalne verzije za navedeni pojedinačni advisory, ne tvrdnja da su te verzije danas bez svih ostalih problema. Primena zahteva odgovarajuću putanju: nisam dokazao da aplikacija koristi ranjivi lxml parser, dotenv set_key ili napadački kontrolisan requests URL. Poznat advisory nije automatski demonstriran exploit aplikacije.

**Implementacija:** odaberi kompatibilne podržane verzije, razdvoji runtime/scraper/test dependencies, napravi zaključan reproducibilan skup sa hash-evima. Dodaj OSV/pip-audit i image scan u CI. Testiraj taj isti dependency set i image koji se objavljuje. Ne menjaj naslepo samo Starlette mimo FastAPI ograničenja.

**Gotovo kada:** clean build iz zaključanih zavisnosti prolazi API/frontend testove i audit; svaki preostali advisory ima dokumentovanu primenljivost, vlasnika i rok. Sačuvaj SBOM, image digest i verzije uz release.

## 2. P1 — postojeća Compose konfiguracija je razvojna, nije bezbedan produkcioni profil

**Dokaz:** docker-compose.yml objavljuje `5432:5432` uz waterpolo/waterpolo, API `8000:8000`; nema TLS edge konfiguracije niti Redis servisa. ENVIRONMENT podrazumeva development; zaštita JWT tajne važi tek kada environment nije development. Dockerfile nema USER, pa proces podrazumevano radi kao root. Ovo je rizik ako se baš taj profil postavi na javni host, ne tvrdnja da je lokalna baza trenutno dostupna sa interneta.

**Implementacija:** zaseban production profil, bez javnih DB/Redis/backend portova; jedini javni ulaz reverse proxy na443 (80 samo redirect/ACME). Zahtevaj production environment, jaku zasebnu JWT tajnu, HTTPS frontend_base_url, eksplicitnu trusted proxy/host listu i odvojene DB role (migrator/app/scraper). Tajne iz deploy secret store-a, nikad u image/git. Non-root user, minimalni image, drop capabilities, no-new-privileges, read-only filesystem gde može, CPU/RAM/PID granice. Scraper/Chromium odvojen od API-ja, bez privilegija i auth/DB tajni koje mu ne trebaju.

**Gotovo kada:** staging start odbija nedostajuće/default tajne i pogrešan production URL; izvana su DB/Redis/backend nedostupni, HTTPS radi, restore i rollback testirani. Proveriti git istoriju secret scanner-om bez štampanja vrednosti; eventualno nađene tajne prvo rotirati. U ovom pregledu je proverena lista praćenih env fajlova (samo .env.example), nije skenirana kompletna git istorija niti host infrastruktura.

## 3. P1 — auth zaštita nestaje pri Redis kvaru, proxy topologija nije definisana za produkciju

**Dokaz:** core/ratelimit.py pri nedostupnom/izostavljenom Redis-u pušta login/register/forgot zahteve. `_TRUSTED_PROXY_IPS` je hardkodovan na loopback. Node proxy ispravno prepisuje korisnički XFF direktnim peer-om, ali iza dodatnog edge proxy-ja taj peer postaje edge: svi dele isti IP. Uvicorn takođe može obrađivati forwarded headers; ne smeju dva sloja različito tumačiti lanac.

**Implementacija:** cache sme da degradira bez prekida rada, auth limiter treba sopstvenu odluku i zaštitu. Dodaj obavezan production limiter backend i nezavisan edge limit; pri kvaru vrati kontrolisan503 na osetljivim auth operacijama ili koristi dokazano ograničen fallback. Po-IP i po-nalogu ograničenja, ograničen broj paralelnih bcrypt poslova i razuman backoff. Konfiguriši tačno ko prepisuje forwarded headers i koji CIDR se veruje; odbaci proizvoljan browser XFF/Forwarded. Nema `trust all`.

**Gotovo kada:** dva klijenta imaju nezavisne limite kroz stvarni production proxy lanac; spoofovani XFF ne resetuje limit; Redis outage ne otvara neograničen bcrypt/registraciju; istovremeni pokušaji ne zaobilaze prihvaćen limit. Meriti i legitimne korisnike iza NAT-a da ih limit ne blokira nepotrebno.

## 4. P1 — email registracija i oporavak još nisu produkcioni tok

**Dokaz:** send_email je stub; register izdaje pun access token, a get_current_user ne zahteva email_verified. Moguća je upotreba proizvoljne tuđe adrese bez dokazivanja vlasništva. Password reset se sada atomarno troši i uvećava credentials_version — zadržati.

**Implementacija:** pravi email provider i pouzdan queue/outbox, vremenski ograničen resend sa po-IP/po-adresi kontrolama. Odvoji unverified status: dozvoli /me/verifikaciju/resend, ali zabrani pune fantasy write operacije dok email nije potvrđen. Bez lažnog „poslato“ ako delivery sistem nije podešen. Forgot i verify/reset imaju ograničenu dužinu tokena, uniformne odgovore i rate limit; forgot i po-adresi da distribuirani zahtevi ne preplavljuju inbox. Dvostruka verify upotreba mora imati definisanu idempotentnu/atomarnu semantiku. Send provider kvar ne sme napraviti nejasan ishod već commitovane registracije.

**Gotovo kada:** staging inbox stvarno prima link; istekao/iskorišćen token ne radi, dva konkurentna reset-a daju samo jednu promenu; stari JWT ne radi posle reset-a; neproveren korisnik ne može kupiti/menjati tim; resend/opravak rade i posle privremenog provider kvara. Frontend dobija dogovoren status/grešku i posebnu poruku za nepotvrđen nalog, bez iznenadne generičke403.

## 5. P1 — auth tokeni se i dalje mogu naći u access logovima

**Dokaz:** frontend/account-link šalje GET `/api/auth/verify-email?token=...`; Docker Uvicorn koristi podrazumevan access log. Izolovano pozivanje Uvicorn `get_path_with_query_string` sa lažnim tokenom daje `/api/auth/verify-email?token=FAKE_AUDIT_TOKEN`. Produkcijska zaštita u send_email ne pokriva ovaj sloj. Prvi frontend reset/verify URL takođe mora biti redigovan u budućem edge/CDN logu, pre nego što JS ukloni token iz browser URL-a.

**Implementacija:** backend verification POST sa tokenom u JSON telu i usklađen front; redakcija query-ja/auth zaglavlja/request body-ja u svakom loggeru, edge-u, APM-u i error tracker-u. Logovati request ID, putanju bez query-ja, status i trajanje. Tokeni u bazi trenutno su plaintext; čuvati digest jednokratnih reset/verify tokena, porediti digest dolazne vrednosti, TTL/unique/atomic consume očuvati. Migracija treba da poništi ili bezbedno prebaci stare linkove.

**Gotovo kada:** test sa sentinel tokenom prođe kroz frontend, proxy, API, success i error putanje; sentinel ne postoji ni u jednom prikupljenom logu. DB dump ne sadrži upotrebljive reset/verify tokene. no-referrer ostaje.

## 6. P2 — sesije, logout i JWT validacija

**Dokaz:** access token traje7 dana, čuva se u sessionStorage; logout samo briše lokalnu kopiju. Ukradena kopija ostaje validna do isteka/resetovanja. Decode ne zahteva exp: potpisan token bez exp je prihvaćen u izolovanoj proveri. Potpisan token sa `cv:null` izaziva TypeError. Napadač bez signing ključa ne može proizvoljno potpisati te tokene; to su tvrdoća validacije i lifecycle gap, ne dokazan zaobilazak potpisa.

**Implementacija:** zahtevati sub/exp/cv i ispravne tipove, kontrolisati issuer/audience, algoritam allowlist, sve malformed varijante vratiti401 bez500. Uvesti kratkotrajni access token i rotirajuće server-side refresh sesije sa revoke/logout i reuse detekcijom, ili BFF server-side sesiju u HttpOnly Secure SameSite cookie-ju. Izbor zapisati pre promene ugovora. Ako se uvedu cookies, eksplicitna CSRF zaštita na write rutama, Origin provera i precizan CORS; trenutni bearer iz JS nije automatski cookie-CSRF ranjivost. Dugoročno ne čuvati refresh tajnu u Web Storage. Za admin/deploy pristup MFA, ne nametati svim igračima bez produkt odluke.

**Gotovo kada:** logout opoziva odgovarajuću sesiju, reset sve sesije, refresh reuse se odbija, nema beskonačne sesije bez exp; frontend korektno tretira401 bez gubitka korisničkog nacrta ili automatskog ponavljanja neizvesnih write zahteva.

## 7. P2 — enumeracija naloga i lockout zloupotreba

Register odgovara409 „Email already registered“, login za nepostojećeg korisnika preskače bcrypt. To otkriva postojanje adrese statusom/tajmingom. Fiksno zaključavanje po email-u može se koristiti za ometanje legitimnog korisnika.

Ujednačiti spoljne poruke/odgovore, za nepostojeći nalog koristiti prethodno pripremljen dummy hash uz iste CPU limite; ne uvoditi neograničene sleep task-ove. Progresivno ograničavanje i oporavak od lockout-a, bez stalnog zaključavanja koje napadač lako održava. Testirati razliku odgovora i distribuiranu zloupotrebu. Referenca: [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).

## 8. P1 za integritet/availability — idempotency crash recovery i zloupotreba upisa

teams.py i dalje dokumentuje pending claim zauvek posle crash-a, bez hash poređenja tela. Header nema ograničenje dužine; zapisi nemaju politiku retencije. Write API nema zaseban limiter, pa prijavljen korisnik može praviti mnogo novih claim-ova/upita i čekanja na Season/team lock.

Implementirati request fingerprint (kanonsko telo+endpoint+korisnik), mismatch409, maksimalnu dužinu ključa, retention/kvote i lease/ownership-fencing ili ekvivalentan crash-safe dizajn. Ne brisati samo „stare pending“ dok stara transakcija još može commit-ovati: time se otvara dvostruki upis. Očuvati atomarnost business update+response i validno ponavljanje istog uspeha. Dodati per-user write limit, DB statement/lock timeout i ograničen red čekanja.

Gotovo: kill procesa posle claim-a, tokom business tx i posle commit-a/pre odgovora, restart/retry -> najviše jedna promena budžeta/transfera i oporavljiv odgovor. Isti ključ/drugo telo409; dva korisnika izolovana; retention ne briše žive operacije. Pred narrowing Season lock-a dodati DB jedinstvenost user/league; sadašnja zaštita postoji i ne treba je predstavljati kao otvoren duplicate-team exploit.

## 9. P2 — zaštita od skupih zahteva i nepotrebnog izlaganja podataka

`GET /api/players` nema paginaciju; katalog ima limit100 ali offset nema gornju granicu, razni proizvoljni filteri mogu praviti mnogo cache miss-eva. Proxy nema eksplicitnu application body size politiku; Pydantic validacija dolazi posle učitavanja tela. Verify/reset tokeni nemaju max_length. Shield task-ovi nastavljaju rad posle otkazivanja, pa treba limit ukupnog in-flight rada i DB timeout, ne samo deduplikacija istog ključa.

Dodati edge+ASGI body/header/URL limite (uključujući chunked zahteve), request/read timeout, korisničke/public kvote, bounded pagination ili cursor, ograničen broj istovremenih expensive compute-a i metrika. JSON422/413 ne sme logovati lozinku/telo. Javni leaderboard sme imati samo namerno javne display name/poene, nikad email/hash/token. Proveriti kompletne response schema-e i authorization matrix za sve metode, ne samo GET. SSRF nije potvrđen: scraper ciljevi su trenutno server-controlled; ako se ikad uvede korisnički URL, allowlist/egress kontrola i redirect/DNS proveravanje pre fetch-a.

Gotovo: oversized/chunked i visoki offset/filter nalet imaju bounded memoriju/DB vreme; tuđi team GET/PUT/transfer odbijeni i bez promena stanja; strani competition player ne ulazi u tim; raw bodies/PII nisu u greškama/logovima.

## 10. P2 — frontend CSP i clickjacking

Live HTML nema CSP/frame zaštitu. Postoji no-referrer/nosniff i većina ključnih stringova se escapuje. To nije potvrđena XSS rupa, već nedostajuća zaštita od posledica budućeg XSS-a i iframe UI prevare. sessionStorage token pojačava posledice bilo kog XSS-a.

Uvesti CSP prvo report-only i zatim enforce: script-src self bez unsafe-eval/unsafe-inline, object-src none, base-uri none, frame-ancestors none, connect-src prema stvarnom API-ju, form-action self. Uskladiti stilove jer sada postoje inline style atributi i Google Fonts; ne dodati wildcard samo da prođe. Po mogućnosti self-host fontove. X-Frame-Options DENY kao kompatibilni dodatak, HSTS tek na ispravnom HTTPS production domenu, permissions policy prema stvarno potrebnim mogućnostima. Nikakve implementacione/security poruke u korisničkom UI-ju osim kada mu pomažu da nastavi rad.

Gotovo: postojeći mobile/browser tokovi prolaze pod enforce CSP; tuđi origin ne može ugraditi aplikaciju; test imena sa HTML/atribut/URL payload-ima ne izvršava JS; iframe i external script su blokirani. Preskenirati sve innerHTML pozive, ne samo rang-listu.

## 11. P1 release kriterijum — izolovani CI, monitoring i oporavak

Test fixture i dalje briše `ratelimit:*` u DB15 koja nije globalno rezervisana. Koristiti zasebnu test Redis instancu i bazu, eksplicitni TEST_DATABASE_URL i guard protiv produkcije; ne oslanjati se na broj15. CI sada preskače deo stvarnih data-dependent testova i ne pokreće frontend suite. /health samo vraćaok, ne meri DB/Redis/email readiness.

Dodati sintetičke PostgreSQL fixtures bez skip-a za ključne auth/authorization/idempotency upise, Node/browser testove, dependency/secret/container scan sa minimalnim CI permissions. Veži release za iste artefakte koji su testirani. Liveness odvojiti od readiness/degraded auth stanja. Uvesti alert za5xx/429/DB pool/lock čekanje/Redis auth failure/email queue/pending claims/scraper zastoj, bez tajni u telemetry-ju. Enkriptovani backup-i, ograničen pristup, definisan RPO/RTO i stvaran restore drill na izdvojenoj instanci. Deploy migracije pre app readiness, backup, kompatibilan rollback plan.

Gotovo: nema ključnih security testova koji su samo skipped, crash/restore proba ima zapis, alert stvarno stiže, staru verziju možeš vratiti bez gubitka upisa. Cilj korisnika je do10.000 ukupnih i oko1.000 istovremeno aktivnih sesija: na staging-u meri realne sesije i broj zahteva u letu, read/write mešavinu i nalet pred deadline, p95/p99/greške i tačnost budžeta. Ne pokretati taj load protiv glavne poslovne baze.

## Redosled rada i handoff

1. Dependency lock/clean build + production konfiguracioni guardovi; izdvojene test servise obezbediti pre testnih mutacija.
2. Auth limiter/proxy topologija, delivery+verified status, uklanjanje tokena iz logova i digest tokeni.
3. Session lifecycle/JWT i frontend dogovor o verifikaciji/401/CSRF; CSP i iframe zaštita.
4. Crash-safe idempotency, resource limits, authorization/abuse regresije.
5. Staging deploy, audit/restore/load/monitoring dokazi; tek zatim ocena spremnosti za javni rad.

Za svaki odeljak napiši: commit, šta je promenjeno, test i rezultat, šta ostaje blokirano stvarnim kredencijalima/domenom/infrastrukturom. Ne glumi slanje emaila niti uspešan deploy kada provajder ne postoji. Git/branch ispravke i lokalne testove odradi samostalno; stvarno objavljivanje nije deo ovog naloga. Na frontend promene koje menjaju auth/API ugovor ostavi eksplicitan handoff.

Dodatne reference: [OWASP Forgot Password](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html), [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [OSV requests advisory](https://osv.dev/vulnerability/GHSA-9hjg-9r4m-mvj7), [OSV PyJWT advisory](https://osv.dev/vulnerability/GHSA-752w-5fwx-jx9f). OSV razrešeni spisak je snapshot, ponoviti ga na izabranim konačnim verzijama.

Ovo je pregled dostupnog koda, izolovane reprodukcije i lokalnih read-only zahteva, ne penetracioni test budućeg domena niti garancija odsustva svih ranjivosti. Nisu menjani glavni podaci, Cattaro pozicije, aplikacioni kod niti produkcioni servisi.
