# Folio MCP – fakturaer til kjøp og bankbevegelser

Lokal MCP for **Folio Norge (folio.no)**, Claude Desktop og Claude Code på Mac.
Hovedoppgaven er å lese fakturaer, finne riktig bankbevegelse og knytte fakturafilen
som bilag til den tilhørende Folio-hendelsen etter godkjenning.

**Pilot 0.1:** 12 verktøy. Kan lese bankdata og laste opp godkjente bilagsvedlegg.
Kan ikke opprette betalinger, slette vedlegg, endre kategorier eller eksplisitt
markere hendelser ferdige. Ikke en offisiell Folio-integrasjon.

## Arbeidsflyt

1. Du angir en lokal PDF, PNG eller JPEG. Claude leser alle sidene og identifiserer
   leverandør, fakturanummer, dato, beløp og valuta.
2. Claude søker i bankbevegelsene for perioden. Matching bruker eksakt beløp og
   valuta, med leverandør-/referansetekst som ekstra holdepunkter.
3. Du får se kandidater, mottaker, konto, dato, betalingsretning og eksisterende vedlegg.
   Like beløp gir ikke automatisk et sikkert treff. Ved tvil velger du mål.
4. Claude klargjør et forslag med en fast kopi av filen og en forhåndsvisning av
   Folio-hendelsen. **Ingen opplasting skjer i dette steget.**
5. Du kjører godkjenningskommandoen som vises, i Terminal, og skriver `JA` etter
   å ha kontrollert filnavn, hendelse og beløp. Claude skal ikke gjøre dette for deg.
6. Du ber Claude fullføre. `folio_attach_invoice` laster filen opp til den godkjente
   hendelsen én gang. Godkjenningen varer ti minutter fra forslaget ble opprettet.

Folio bruker **eventId** for bilagstilknytning. `transactionId` identifiserer
bankbevegelsen og skal ikke brukes direkte som mål for opplastingen.

## Innlogging og API-grunnlag

Hver bruker oppretter sin egen API-nøkkel via
[Folio API-tilgang](https://app.folio.no/til/api-tilgang). Nøkkelen skrives skjult i
Terminal og lagres i **macOS Nøkkelring**. Den skal aldri limes inn i Claude,
GitHub eller konfigurasjonsfilen.

Folios [offentlige API](https://api.folio.no/v2/api) dokumenterer API-nøkler.
[OAuth-spesifikasjonen](https://api.folio.no/v2/oauth2.yml) beskriver tokenutveksling
med HTTP Basic-klientautentisering, men dokumenterer ikke en komplett offentlig
PKCE-flyt for lokale apper. Derfor har denne piloten **ikke OAuth/PKCE** og deler
ingen klienthemmelighet. En generell OAuth-integrasjon må avklares med Folio før
implementasjon; ikke distribuer en felles API-nøkkel til brukere.

Kontrakten er kontrollert mot [OpenAPI](https://api.folio.no/v2/api.yml) 28. oktober
2026. API-et beskriver ikke paginering for transaksjoner/hendelser. Serveren bruker
avgrensede datoperioder og avviser svar over 15 MiB fremfor å kutte data i stillhet.
Kontoutskriftsendepunktene er dokumentert som ikke implementert (501) og er utelatt.

## Installer på Mac

Krever Git og Python 3.11+. Med Homebrew kan du bruke `brew install python@3.12`.

```bash
git clone https://github.com/dansheik/folio-mcp.git
cd folio-mcp
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/folio-mcp login
.venv/bin/folio-mcp doctor
.venv/bin/folio-mcp config
```

`doctor` gjør et GET-kall og viser bare profil og antall kontoer. `config` skriver
ferdig JSON med riktig absolutt sti; ingen eksisterende innstillinger endres.

### Claude Desktop

Åpne **Settings → Developer → Edit Config**. Legg `folio`-oppføringen fra `config`
inn i eksisterende `mcpServers` i
`~/Library/Application Support/Claude/claude_desktop_config.json`.
Behold Fiken og andre eksisterende servere. Eksempel:

```json
{
  "mcpServers": {
    "folio": {
      "command": "/ABSOLUTT/STI/folio-mcp/.venv/bin/folio-mcp",
      "args": ["serve"],
      "env": {"FOLIO_PROFILE": "default"}
    }
  }
}
```

Avslutt Claude helt og start på nytt.

### Claude Code

Fra klonen:

```bash
claude mcp add --scope user --transport stdio --env FOLIO_PROFILE=default folio -- "$PWD/.venv/bin/folio-mcp" serve
```

### Flere firmaer/profiler

Bruk én lokal profil per Folio-tilgang. Kjør for eksempel
`FOLIO_PROFILE=firma-a .venv/bin/folio-mcp login` og generer konfigurasjon med samme
profil. Hver profil har separat nøkkel, forslag og lokal opplastingshistorikk.
Profilnavnet er en lokal etikett; kontotilgangen bestemmes av Folio-nøkkelen.

## Eksempel i Claude

> Les fakturaen på /absolutt/sti/faktura.pdf. Finn mulige betalinger i Folio mellom
> 2026-10-01 og 2026-10-28. Vis mottaker, konto, beløp og eksisterende vedlegg før
> du foreslår hvilken hendelse fakturaen skal knyttes til.

MCP-prompten `match_faktura` gir hele arbeidsflyten med filsti og datointervall.

| Verktøy | Formål |
|---|---|
| `folio_list_accounts` | Kontooversikt |
| `folio_get_balance` | Historisk dagsaldo |
| `folio_list_transactions` / `folio_get_transaction` | Bankbevegelser og eventId |
| `folio_list_events` / `folio_get_event` | Kjøp, hendelser og eksisterende dokumentasjon |
| `folio_get_category` | Kategori og dokumentasjonskrav |
| `folio_read_invoice` | Les brukerangitt lokal faktura |
| `folio_read_attachment` | Les bilag som allerede tilhører en hendelse |
| `folio_match_invoice` | Foreslå mulige treff uten å gjøre endringer |
| `folio_prepare_invoice_assignment` | Lag lokal forhåndsvisning og låst filkopi |
| `folio_attach_invoice` | Last opp én uttrykkelig godkjent fil |

## Matchingens grenser

- Folio-beløp er **desimalstrenger i valutaen**, eksempel `1250.00`, ikke heltall i øre.
- Standardmatching tar bare med utgående betalinger der debetkontoen finnes blant
  brukerens Folio-kontoer. Innkommende, interne og ukjente retninger er utelatt og telles.
  `include_non_outgoing=true` viser også disse for manuell kontroll.
- Treff kan være på bankbeløp eller originalt valutabeløp. Serveren beregner ingen
  valutakurs og antar ikke at samme beløp betyr samme faktura.
- Delbetalinger, samlebetalinger, gebyrer, kreditnota og kortreservasjoner må vurderes
  manuelt. Bruk hendelseslisten når en bevegelse ennå ikke er bokført.
- Leverandør- og referansetekst er enkle søkeholdepunkter. Claude må lese fakturaen og
  eksisterende bilag før valg. Ett enkelt treff er heller ikke bevis.
- Søket omfatter valgt datointervall (maks 366 dager) og tilgjengelige kontoer.
  Det er ingen garanti for at hele bankhistorikken er tilgjengelig.

## Godkjenning, duplikater og personvern

- Serveren tillater bare dokumenterte leseendepunkter og
  `POST /events/{eventId}/attachments`. Ingen generell HTTP-funksjon eksponeres.
- Opplasting bruker rå PDF-/bildebytes slik Folio dokumenterer, ikke multipart.
- Filhash, profil, nøkkel og hele hendelsen kontrolleres før opplasting. Endringer
  gjør at forslaget må opprettes og godkjennes på nytt.
- Godkjenning finnes bare i den interaktive CLI-en, ikke som MCP-verktøy. Den er et
  ekstra menneskelig kontrollsteg, ikke en sikkerhetsgrense mot programmer som allerede
  har full tilgang til brukerens Mac. Ikke la agenten utføre godkjenningen for deg.
- Samme fil/hendelse avvises hvis lokal historikk viser en tidligere opplasting eller
  et ukjent utfall. Dette oppdager ikke filer lastet opp utenfor denne profilen eller
  ulike filversjoner av samme faktura; eksisterende Folio-vedlegg må kontrolleres.
- Ved timeout/feil kan filen allerede være lastet opp. Forslaget forbrukes før sending,
  og gjentas aldri automatisk. Kontroller Folio manuelt.
- Lokale forslag og fakturakopier ligger under
  `~/Library/Application Support/folio-mcp/<profil>/` med private filrettigheter.
  Filkopien slettes etter bekreftet opplasting. Utløpte/avbrutte forslag ryddes med
  `folio-mcp purge`. **Utløp sletter ikke filen automatisk.**
- `purge` sletter også historikken for lokal duplikatkontroll. Gjør dette først etter
  at du har avklart eventuelle ukjente opplastinger. Den sletter ingen data i Folio.
- Filinnhold og bankdata Claude leser sendes til Claude under din Claude-avtale.
  Bare et godkjent vedlegg lastes opp til Folio. Ingen ekstra analyse- eller lisensserver.
- `logout` fjerner nøkkelen lokalt, men sletter ikke forslag. Tilbakekall nøkkelen i
  Folio for å ugyldiggjøre den hos leverandøren.

## Utvikling og status

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Testene bruker syntetiske data og dekker matching, beløp/valuta/retning, PDF-lesing,
API-sperrer, godkjenning, endrede filer/hendelser, utløp, engangsbruk, ukjent utfall
og reell MCP-stdio-oppstart. GitHub Actions kjører på macOS med Python 3.11–3.13.

**Ikke testet mot en ekte Folio-konto eller i Claude Desktop ennå.** Før praktisk bruk:
logg inn med egen nøkkel, les kontoer og én kjent bevegelse, sammenlign bilaget manuelt,
og prøv en uttrykkelig godkjent vedleggsopplasting. Ingen faktisk faktura er lastet opp
under utviklingen. MIT-lisens, se [LICENSE](LICENSE).
