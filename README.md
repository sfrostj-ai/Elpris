# Elpris – din egen elpris-app

Elpriser for din adresse inkl. alle afgifter og tariffer, 7-døgnsprognose og prisalarmer som push-beskeder. Det kører gratis på GitHub og ligger som en app på din telefon.

- **I dag / I morgen:** Pris pr. time eller pr. kvarter med alle afgifter og moms (moms kan slås fra), laveste, gennemsnit, højeste og de billigste timer.
- **Prognose:** De næste 7 døgn med prisspænd, billigste periode og hvor sikker prognosen er.
- **Afgifter:** Konstants nettarif, rabat, system- og transmissionstarif, elafgift, abonnementer og kommende prisændringer. Henter altid de gældende satser selv.
- **Alarmer:** Push-besked via ntfy, fx "billigste timer i morgen" og "billig strøm nu".

## Sådan hænger det sammen

Et Python-script kører automatisk på GitHub en gang i timen. Det henter:

- spotpriser fra Energinet (Energi Data Service, `DayAheadPrices`),
- tariffer og abonnementer fra Energinets DataHub (`DatahubPricelist`) for Konstant Net og Energinet,
- prognosen fra elpriser.org (gratis, ingen nøgle).

Scriptet regner totalprisen ud, gemmer den i `docs/data.json` og sender eventuelle alarmer. Selve appen er én webside (`docs/index.html`), som GitHub Pages viser, og som kun læser `data.json`. Appen kører ikke i baggrunden på telefonen og bruger derfor ikke strøm, når den er lukket.

Tabellen viser, hvad hver fil i projektet bruges til, så du ved, hvor du skal rette hvad:

| Fil | Bruges til |
|---|---|
| `config.json` | Dine indstillinger: navn, netselskab, elselskabets tillæg, alarmer |
| `scripts/update.py` | Henter data, regner priser og sender alarmer |
| `.github/workflows/opdater-priser.yml` | Får GitHub til at køre scriptet hver time |
| `docs/` | Selve appen (side, ikoner, service worker) og den genererede `data.json` |
| `data/state.json` | Husker hvilke alarmer der er sendt, så du ikke får samme besked to gange |
| `tests/` | Testdata, så scriptet kan afprøves uden net |

## Opsætning (ca. 15 minutter)

### 1. Læg projektet på GitHub
1. Opret en gratis konto på [github.com](https://github.com), hvis du ikke har en.
2. Klik **New repository**, kald det fx `elpris`, vælg **Public** og klik **Create repository**.
3. Klik **uploading an existing file**, og træk **indholdet** af mappen `elpris-app` ind (ikke selve mappen). Klik **Commit changes**.
4. Tjek, at mappen `.github/workflows` er kommet med. Mapper med punktum foran bliver nogle gange skjult ved upload. Mangler den, så klik **Add file → Create new file**, skriv `.github/workflows/opdater-priser.yml` som navn, indsæt indholdet af filen og gem.

> Repositoriet skal være offentligt, for at GitHub Pages er gratis. Der ligger ingen personlige data i det: ingen adresse og intet forbrug. Dit ntfy-emne gemmes som en hemmelighed (se trin 3).

### 2. Giv scriptet lov til at gemme data
**Settings → Actions → General → Workflow permissions →** vælg **Read and write permissions → Save**.

### 3. Push-beskeder med ntfy
1. Installer **ntfy** fra Google Play på telefonen.
2. Find på et langt, hemmeligt emnenavn, fx `elpris-soeren-7Kq2xP9w`. Alle, der kender navnet, kan læse beskederne, så gør det svært at gætte.
3. Abonnér på emnet i ntfy-appen (**+** → skriv emnenavnet).
4. På GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Name: `NTFY_TOPIC`, Secret: dit emnenavn.

Lad "Instant delivery" være slået fra i ntfy. Så kommer beskederne via Androids almindelige push-system og bruger ikke ekstra batteri.

### 4. Slå appen til (GitHub Pages)
**Settings → Pages → Source: Deploy from a branch → Branch: `main`, mappe: `/docs` → Save.**
Efter et minut ligger appen på `https://DIT-BRUGERNAVN.github.io/elpris/`.

### 5. Første kørsel
**Actions → Opdater elpriser → Run workflow.** Når den er grøn (ca. 30 sek.), har den hentet dagens priser. I loggen kan du se fx:

```
2026-11-15: 24 timer, 1,23–2,31 kr/kWh (gns. 1,65)
Prognose: 7 dage fra elpriser
```

Derefter kører den selv hver time.

### 6. Læg appen på telefonen
Åbn adressen i Chrome på telefonen → menuen **⋮** → **Føj til startskærm** / **Installer app**.

## Tilpasning

Ret `config.json` direkte på GitHub (klik på filen → blyanten):

- `navn`: Teksten øverst i appen (fx "Hjem").
- `elselskab_tillaeg_oere_inkl_moms`: Dit elselskabs tillæg i øre/kWh. Bruges i alarmerne. I appen kan du også skrive det under Afgifter, og så gemmes det på telefonen.
- `alarmer`: Slå hver alarm til og fra (`"aktiv": true/false`) og ret grænserne.
- `ekstra_abonnementer_kr_pr_md_inkl_moms`: Faste beløb, der ikke ligger i DataHub (kun til visning).
- `prognose.kilde`: `"elpriser"` (standard) eller `"carnot"`. Carnot kræver en gratis API-nøgle fra carnot.dk, gemt som hemmelighederne `CARNOT_APIKEY` og `CARNOT_USERNAME`.

Flytter du til et andet netselskab, skal du ændre `netselskab.gln` og koderne. Kør `python scripts/update.py --discover` på din computer for at se netselskabets gældende tariffer og koder. Kør den med det nye GLN i `config.json`.

## Fejlsøgning

- **Appen siger "ikke opdateret siden …":** Se under **Actions**, om kørslerne fejler. Tryk på den røde kørsel for at se fejlen.
- **"ADVARSEL: ingen tariflinjer fundet":** Konstant har ændret deres tarifkoder. Find de nye med `--discover`, og ret `config.json`.
- **Push-fejl ved "Gem nye data":** Tjek trin 2 (Read and write permissions).
- **Kørslerne kommer lidt sent:** GitHubs tidsplan kan blive forsinket 5–20 minutter, når der er travlt. Det er normalt.
- **Afprøv uden net:**
  ```
  python tests/make_fixtures.py
  python scripts/update.py --fixtures tests/fixtures/efter-13 --now 2026-11-15T14:00 --dry-run --out /tmp/data.json --state /tmp/state.json
  ```

## Sikkerhed

Appen er en almindelig hjemmeside i Chromes sandkasse. Den beder ikke om tilladelser og har ingen adgang til telefonens filer, SMS'er eller andre apps. Den henter kun sine egne filer fra din GitHub Pages-adresse. Der er ingen login og ingen personlige data. De svage punkter ligger uden for telefonen:

- **Slå totrinsbekræftelse til på din GitHub-konto.** Kommer en anden ind på den, kan vedkommende ændre appen.
- **Hold ntfy-emnet hemmeligt og langt.** Den, der kender det, kan læse og sende beskeder til det.
- **Tryk ikke på uventede links i beskeder.** Dine rigtige alarmer åbner kun din egen app-adresse.

Workflowet kører kun efter tidsplanen eller når du selv starter det. Fremmede kan ikke få det til at køre deres kode, heller ikke via pull requests.

## Kilder og licens

- Spotpriser, tariffer og abonnementer: Energinet ([energidataservice.dk](https://www.energidataservice.dk)), CC BY 4.0.
- Prognose: [elpriser.org](https://elpriser.org), som er gratis til al brug. Valgfrit [Carnot.dk](https://www.carnot.dk).
- Push: [ntfy.sh](https://ntfy.sh).
- Skrifttype: [Inter](https://github.com/rsms/inter), SIL Open Font License 1.1 (se `docs/fonts/OFL.txt`). Den ligger i appen selv, så siden ikke henter noget fra andre servere.

Priserne er vejledende. Din endelige regning kan afvige, fx på grund af elselskabets tillæg, abonnement og afrunding.
