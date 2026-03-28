# 🗂 Commarec Zápisy v2 — Handoff dokument
*Aktualizováno: 28. 3. 2026 | Verze: FINAL10*

---

## 🔗 Klíčové odkazy

| | |
|---|---|
| **Live URL (produkce)** | https://crm.superskladnik.cz |
| **Live URL (Railway)** | https://web-production-9185b.up.railway.app |
| **GitHub** | https://github.com/CommarecMK/apollopro_v01 |
| **Login** | admin@commarec.cz / heslo z `ADMIN_PASSWORD` env var |
| **Railway projekt** | apollo_v1, asia-southeast1 |
| **Databáze** | PostgreSQL (Railway, perzistentní Volume) |
| **Knowledge Base** | https://github.com/CommarecMK/commarec-kb (samostatné repo) |

---

## 🏗 Architektura aplikace

```
run.py                          ← vstupní bod (gunicorn run:app)
app/
  __init__.py                   ← app factory, blueprinty, DB init + migrace
  extensions.py                 ← db, env vars
  models.py                     ← DB modely (User, Klient, Projekt, Zapis, Nabidka...)
  auth.py                       ← role systém, ROLE_PERMISSIONS, login_required
  config.py                     ← TEMPLATE_PROMPTS, SECTION_TITLES, TEMPLATE_NAMES
  seed.py                       ← testovací data (guard: ENABLE_SEED=true)
  services/
    freelo.py                   ← HTTP helpery + per-user credentials
    ai_service.py               ← Anthropic volání, FORMAT_INSTRUCTIONS, prompty
  routes/
    main.py      ← Blueprint "main"      — dashboard, login, přehled, /navod
    klienti.py   ← Blueprint "klienti"   — detail klienta, Freelo nastavení
    nabidky.py   ← Blueprint "nabidky"   — nabídky
    zapisy.py    ← Blueprint "zapisy"    — generování zápisů, detail, sekce
    freelo.py    ← Blueprint "freelo"    — Freelo API endpointy
    admin.py     ← Blueprint "admin_bp"  — správa uživatelů, šablon
    report.py    ← Blueprint "report"    — měsíční AI report
    portal.py    ← Blueprint "portal"    — klientský portál
templates/                      ← Jinja2 šablony (včetně navod.html)
static/
  format.js                     ← legacy helper
  detail.js                     ← veškerý JS pro detail zápisu
```

---

## 🗄 Databáze — DŮLEŽITÉ

### Aktuální stav
- **Typ:** PostgreSQL (Railway managed)
- **Perzistence:** Ano — data přežijí každý deploy, restart i update kódu
- **Volume:** `postgres-volume` (viditelné v Railway dashboardu)
- **Připojení:** env var `DATABASE_URL` (Railway auto-inject z Postgres service)

### Jak fungují migrace
Migrace jsou **automatické** — spouštějí se při každém startu app v `app/__init__.py`:
```python
db.create_all()  # vytvoří nové tabulky, přeskočí existující
# pak ALTER TABLE IF NOT EXISTS pro nové sloupce
```
**Nikdy nemazat PostgreSQL service na Railway** — přijdete o všechna data!

### Záloha dat
Railway nemá automatické zálohy na free/hobby plánu. Před velkými změnami:
1. Jděte na Railway → Postgres service → záložka Data → Export

### Co se stane při deployi
1. Railway builduje nový kontejner z GitHub kódu
2. Spustí gunicorn → Flask → `create_app()`
3. `db.create_all()` přeskočí existující tabulky ✅
4. Migrace přidají případné nové sloupce ✅
5. Data zůstanou netknutá ✅

---

## 🔑 Railway Environment Variables

| Proměnná | Popis | Povinná |
|---|---|---|
| `SECRET_KEY` | Flask session secret | ✅ ANO |
| `DATABASE_URL` | PostgreSQL URL (Railway Reference) | ✅ ANO |
| `ANTHROPIC_API_KEY` | Claude API klíč | ✅ ANO |
| `FREELO_API_KEY` | Globální Freelo API klíč | ✅ ANO |
| `FREELO_EMAIL` | Globální Freelo email | ✅ ANO |
| `FREELO_PROJECT_ID` | `501350` (API ID, ne URL ID!) | ✅ ANO |
| `ADMIN_PASSWORD` | Heslo výchozího admina | doporučeno |
| `ENABLE_SEED` | `true` = demo data — NIKDY v produkci | NE |

### Jak DATABASE_URL nastavit správně
V Railway → apollo_v1 → Variables → + New Variable:
- Název: `DATABASE_URL`
- Hodnota: klikněte na ikonu `{}` → Add Reference → Postgres → DATABASE_URL
- **Nikdy nezadávejte URL ručně** — Railway ji spravuje automaticky

---

## 🌐 Vlastní doména

- **Doména:** `crm.superskladnik.cz`
- **Registrátor:** Active24
- **Nastavení:** Railway → apollo_v1 → Settings → Networking → Custom Domain
- **DNS:** CNAME záznam na Railway URL, TXT pro ověření

---

## 👥 Role systém

| Role | Přístup |
|---|---|
| `superadmin` | Vše včetně správy |
| `admin` | Vše včetně správy |
| `konzultant` | Zápisy, klienti, Freelo |
| `obchodnik` | Nabídky, klienti |
| `junior` | Čtení zápisů |
| `klient` | Klientský portál (`/portal`) |

---

## 🔵 Freelo API — OVĚŘENÁ FAKTA

### Fungující endpointy
```
GET  /projects                               → projekty + embedded tasklists
GET  /tasklist/{id}                          → aktivní úkoly (state=null = aktivní)
GET  /tasklist/{id}/finished-tasks           → hotové úkoly
GET  /task/{id}                              → detail + comments[]
GET  /task/{id}/subtasks                     → podúkoly
GET  /project/{id}/workers                   → členové projektu
POST /project/{pid}/tasklist/{tlid}/tasks    → vytvořit úkol
POST /task/{id}                              → editace
POST /task/{id}/description                  → popis (POUZE neprázdný content!)
POST /task/{id}/finish / /activate           → stav
POST /project/{pid}/tasklists                → nový tasklist
```

### Kritická pravidla
1. Auth: Basic Auth — username=FREELO_EMAIL, password=FREELO_API_KEY
2. **Project ID 582553 (URL) ≠ 501350 (API ID)** — vždy použij 501350
3. Popis: POST /description ZVLÁŠŤ, prázdný string = 400 error
4. Hotový úkol: `state.id=5`, aktivní: `state=null`
5. Workers: Martin=236443, Pavel=236444, Markéta=236445, Jakub=236446

---

## 📝 Generování zápisů

### Formát výstupu (===SEKCE=== markery)
```
===PARTICIPANTS_COMMAREC===
===PARTICIPANTS_COMPANY===
===INTRODUCTION===
===MEETING_GOAL===
===FINDINGS===
===RATINGS===          ← HTML tabulka se skóre
===PROCESSES_DESCRIPTION===
===DANGERS===
===SUGGESTED_ACTIONS===
===EXPECTED_BENEFITS===
===ADDITIONAL_NOTES===
===SUMMARY===
===FREELO_STATUS===    ← stav Freelo úkolů
===TASKS===            ← úkoly pro Freelo (parsované zvlášť)
```

---

## 🐛 Opravené chyby (28. 3. 2026 — tato session)

| Bug | Příčina | Oprava |
|---|---|---|
| Admin stránka načítá věčně | `_db.engine.dispose()` při každém requestu zabíjel spojení | Odstraněno z admin route |
| `table already exists` při startu | Zbytečné migrace v admin route | Odstraněno — migrace jen v `__init__.py` |
| ALTER TABLE user bez uvozovek | `user` je rezervované slovo v PostgreSQL | Opraveno na `"user"` ve všech migracích |
| Chybějící `IF NOT EXISTS` | Crash při opakovaném přidání sloupce | Přidáno do všech ALTER TABLE |

---

## ✅ Co funguje (ověřeno 28. 3. 2026)

- ✅ Přihlášení, role, session
- ✅ PostgreSQL databáze s persistencí (data přežijí deploy)
- ✅ Vlastní doména crm.superskladnik.cz
- ✅ Přehled klientů s filtry a skóre
- ✅ Detail klienta — info, poznámky, projekty, zápisy, nabídky
- ✅ Freelo panel — aktivní + hotové úkoly
- ✅ Freelo editace, komentáře, podúkoly
- ✅ Nový zápis — prefill z API, Freelo kontext panel
- ✅ Generování zápisů (audit/operativa/obchod)
- ✅ Detail zápisu — sekce, edit, AI úprava, PDF
- ✅ FREELO_STATUS sekce v zápisu
- ✅ Veřejný zápis (print/PDF)
- ✅ AI Report s Freelo daty + delta skóre
- ✅ Správa uživatelů — Freelo API klíč per user
- ✅ Návod k aplikaci na `/navod` (v navigaci)
- ✅ Seed jen při ENABLE_SEED=true
- ✅ Admin heslo z ADMIN_PASSWORD env var

---

## ⏳ Nedokončeno / Plánováno

### Vysoká priorita
- [ ] **Knowledge Base** — samostatná Flask aplikace (repo: commarec-kb)
  - Nahrávání dokumentů per klient (PDF, Word, Excel, PPTX)
  - AI chat nad dokumenty klienta
  - API endpoint pro propojení se Zápisy
  - Status: kód hotový, čeká na nasazení na Railway
- [ ] **Emailové odesílání zápisů** — MS 365 SMTP, neimplementováno

### Střední priorita
- [ ] **Propojení Zápisů s Knowledge Base** — až KB poběží, přidat volání API do generování zápisů
- [ ] **Responsivní CSS** — mobilní zobrazení není optimalizované

### Nízká priorita
- [ ] **Rate limiting** na API endpointech
- [ ] **Error tracking** (Sentry)
- [ ] **Unit testy**
- [ ] **Klientský portál** — existuje ale není plně otestován
- [ ] **Import klientů** — zatím ruční zadávání

---

## 🧠 Knowledge Base — samostatná aplikace

### Repozitář
- GitHub: `CommarecMK/commarec-kb`
- Větev: `main`
- Stack: Flask + PostgreSQL + Anthropic API

### Co umí
- Správa klientů (název = složka ze SharePointu)
- Upload dokumentů per klient (PDF, Word, Excel, PPTX, TXT)
- Automatická extrakce textu z dokumentů
- AI chat o klientovi (odpovídá z dokumentů)
- REST API pro externí aplikace

### API pro Zápisy
```
GET /api/klient/{slug}/kontext
Header: X-API-Secret: {API_SECRET}

Vrátí: { "klient": "...", "dokumenty_count": N, "kontext": "..." }
```

### Railway env vars (Knowledge Base)
| Proměnná | Popis |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API klíč |
| `API_SECRET` | Tajný klíč pro API volání (vymyslete) |
| `SECRET_KEY` | Flask session secret |
| `DATABASE_URL` | PostgreSQL URL (Railway Reference) |

---

## 🚀 Postup pro nový deploy (Zápisy)

```bash
# 1. Připrav soubory lokálně nebo přes Claude
# 2. Nahraj na GitHub (CommarecMK/apollopro_v01, větev main)
# 3. Railway automaticky deployuje
# 4. Zkontroluj logy — hledej "Starting gunicorn" bez ERROR
# 5. Otestuj přihlášení na crm.superskladnik.cz
```

### Co NIKDY nedělat
- ❌ Nesmazat PostgreSQL service na Railway
- ❌ Nenastavovat ENABLE_SEED=true v produkci
- ❌ Neměnit DATABASE_URL ručně — vždy přes Railway Reference

---

## ⚠️ Známé gotchas

### SQLAlchemy
- `db.create_all()` bez argumentů je správné (přeskočí existující tabulky)
- `db.create_all(checkfirst=True)` neexistuje → crash!
- `ALTER TABLE "user"` — user musí být v uvozovkách (rezervované slovo v PostgreSQL)

### Jinja2
- `u.atribut is defined` nefunguje pro atributy objektů
- Jinja2 modaly musí být prázdné — data plní JavaScript
- `{% for u in users %}` — `u` existuje POUZE uvnitř cyklu

### JS
- `<script src="...">` s inline obsahem — prohlížeč ignoruje inline kód!
- detail.js je externí soubor, novy.html má vše inline v jednom `<script>`

### Freelo
- Project ID 582553 (URL) ≠ 501350 (API ID) — vždy použij 501350
- `state=null` v tasklist = aktivní úkol
- Popis: POST /description ZVLÁŠŤ po vytvoření, prázdný content = 400

### Railway
- Po přidání env variable je nutný nový deploy (tlačítko Deploy)
- DATABASE_URL nastavovat přes Reference, ne ručně
- Logy: apollo_v1 → Deployments → View logs

---

## 🎨 Brand Guidelines

```css
--navy: #173767    /* hlavní barva */
--cyan: #00AFF0    /* akcent */
--orange: #FF8D00  /* CTA tlačítka */
Font: Montserrat (všude)
Nadpisy: font-weight 900
Tělo: 13-14px, weight 500
```

---

## 📋 Checklist před předáním kolegům

```
Railway:
  [x] SECRET_KEY nastaveno
  [x] ADMIN_PASSWORD nastaveno
  [x] ANTHROPIC_API_KEY nastaveno
  [x] FREELO_API_KEY + FREELO_EMAIL + FREELO_PROJECT_ID nastaveny
  [x] DATABASE_URL nastaveno (Railway Reference na Postgres)
  [x] ENABLE_SEED nenastaveno (nebo false)
  [x] Vlastní doména crm.superskladnik.cz funguje

Po deployi:
  [ ] Přihlásit se a otestovat admin stránku
  [ ] Vytvořit účty pro kolegy (Správa → Uživatelé)
  [ ] Každý konzultant nastaví vlastní Freelo email + API klíč
  [ ] Otestovat generování prvního zápisu
  [ ] Nasadit Knowledge Base (commarec-kb repo na Railway)
```

---

*Dokument aktualizován: 28. 3. 2026 | Commarec Zápisy v2 | Claude Sonnet 4.6*
