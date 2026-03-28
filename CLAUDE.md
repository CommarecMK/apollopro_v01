# 🗂 Commarec Zápisy v2 — Handoff dokument pro Claude
*Aktualizováno: 26. 3. 2026 | Verze: FINAL9*

---

## 🔗 Klíčové odkazy

| | |
|---|---|
| **Live URL** | https://web-production-6e134.up.railway.app |
| **GitHub** | https://github.com/CommarecMK/commarec-zapisy-v2 |
| **Login** | admin@commarec.cz / heslo z `ADMIN_PASSWORD` env var |
| **Railway** | asia-southeast1-eqsg3a, PostgreSQL perzistentní DB |
| **Aktuální ZIP** | `commarec-v2-FINAL9.zip` |

---

## 🏗 Architektura

```
run.py                          ← vstupní bod (gunicorn run:app)
app/
  __init__.py                   ← app factory, blueprinty, DB init
  extensions.py                 ← db, env vars (FREELO_EMAIL, FREELO_API_KEY atd.)
  models.py                     ← DB modely (User, Klient, Projekt, Zapis, Nabidka...)
  auth.py                       ← role systém, ROLE_PERMISSIONS, login_required
  config.py                     ← TEMPLATE_PROMPTS, SECTION_TITLES, TEMPLATE_NAMES
  seed.py                       ← testovací data (guard: if Klient.query.first(): return)
  services/
    freelo.py                   ← HTTP helpery + per-user credentials
    ai_service.py               ← Anthropic volání, FORMAT_INSTRUCTIONS, prompty
  routes/
    main.py      ← Blueprint "main"      — dashboard, login, přehled klientů
    klienti.py   ← Blueprint "klienti"   — detail klienta, Freelo nastavení
    nabidky.py   ← Blueprint "nabidky"   — nabídky
    zapisy.py    ← Blueprint "zapisy"    — generování zápisů, detail, sekce
    freelo.py    ← Blueprint "freelo"    — Freelo API endpointy
    admin.py     ← Blueprint "admin_bp"  — správa uživatelů, šablon
    report.py    ← Blueprint "report"    — měsíční AI report
    portal.py    ← Blueprint "portal"    — klientský portál
templates/                      ← Jinja2 šablony
static/
  format.js                     ← legacy helper (jen formatZapis)
  detail.js                     ← veškerý JS pro detail zápisu (čistý, testovaný)
```

### railway.toml
```toml
[deploy]
startCommand = "gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120"
```

---

## 🔑 Railway Environment Variables

| Proměnná | Popis | Povinná |
|---|---|---|
| `SECRET_KEY` | Flask session secret | ✅ ANO |
| `DATABASE_URL` | PostgreSQL URL (Railway auto) | ✅ ANO |
| `ANTHROPIC_API_KEY` | Claude API klíč | ✅ ANO |
| `FREELO_API_KEY` | Globální Freelo API klíč | ✅ ANO |
| `FREELO_EMAIL` | Globální Freelo email | ✅ ANO |
| `FREELO_PROJECT_ID` | `501350` (API ID, ne URL ID!) | ✅ ANO |
| `ADMIN_PASSWORD` | Heslo výchozího admina | doporučeno |
| `ENABLE_SEED` | `true` = spustí demo data | NE (nikdy v produkci) |

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

Každý uživatel může mít vlastní Freelo email + API klíč (přepíše globální).

---

## 🔵 Freelo API — OVĚŘENÁ FAKTA (23. 3. 2026)

### Fungující endpointy
```
GET  /projects                               → projekty + embedded tasklists
GET  /tasklist/{id}                          → POUZE aktivní úkoly (state=null = aktivní)
GET  /tasklist/{id}/finished-tasks           → {"total":N,"data":{"finished_tasks":[...]}} ✅
GET  /task/{id}                              → detail + comments[] (popis = is_description:true)
GET  /task/{id}/subtasks                     → {"data":{"subtasks":[...]}}
GET  /project/{id}/workers                   → {"data":{"workers":[...]}}
POST /project/{pid}/tasklist/{tlid}/tasks    → vytvořit úkol
POST /task/{id}                              → EDITACE (name, due_date, worker_id)
POST /task/{id}/description                  → popis (POUZE neprázdný content!)
POST /task/{id}/finish / /activate           → stav
POST /project/{pid}/tasklists                → nový tasklist
```

### NEFUNGUJÍCÍ endpointy (nikdy nezkoušet)
```
PUT/PATCH /task/{id}                         → 404
GET /tasklist/{id}?include_finished=1        → ignorováno
GET /tasklist/{id}?finished=1                → ignorováno
GET /project/{pid}/finished-tasks            → 404
GET /project/{pid}/tasks?finished=1          → 404
```

### Kritická pravidla
1. Auth: Basic Auth — username=FREELO_EMAIL, password=FREELO_API_KEY
2. Project ID 582553 (URL) ≠ 501350 (API ID projektu CMRC)
3. Popis: POST /task/{id}/description ZVLÁŠŤ, prázdný string = 400
4. Hotový úkol: `state.id=5`, `state.state="finished"`, `date_finished != null`
5. Aktivní úkol: `state=null` v tasklist odpovědi (state se v /tasklist nevrací)
6. Workers: Martin=236443, Pavel=236444, Markéta=236445, Jakub=236446
7. **NIKDY NEHÁDEJ Freelo API** — testuj přes debug endpointy

### Debug endpointy
```
GET /api/freelo/debug-finished-tasks/{tasklist_id}  → testuje různé způsoby načtení hotových
GET /api/freelo/debug-task-state/{task_id}           → stav konkrétního úkolu
GET /api/freelo/debug-comments/{task_id}             → surová odpověď komentářů
GET /api/freelo/debug-tasklist-raw/{tasklist_id}     → stav úkolů v tasklist
```

---

## 📝 Generování zápisů — Prompt architektura

### Formát výstupu (FORMAT_INSTRUCTIONS)
AI **musí** vracet `===SEKCE===` markery, ne JSON:
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
===FREELO_STATUS===    ← Nová sekce — stav Freelo úkolů (tabulka)
===TASKS===            ← Úkoly pro Freelo (parsované zvlášť)
```

### Klíčová pravidla generování
- Freelo úkoly patří **VÝHRADNĚ** do `===FREELO_STATUS===`, nikam jinam
- `user_message` nesmí obsahovat "Vrat POUZE validni JSON" — to je konflikt s FORMAT_INSTRUCTIONS
- Skóre v tabulce se detekuje regexem a obarví `applyScoreBadges()` v JS

### Nový zápis — Freelo kontext panel
- Při výběru klienta se načtou Freelo úkoly (`/api/klient/{id}/freelo-kontext`)
- Zobrazí dokončené od posledního zápisu + aktivní
- Zaškrtnuté úkoly jdou jako kontext do AI promptu
- Endpoint: `freelo.py` → `api_klient_freelo_kontext()`

---

## 🐛 Opravené chyby (tato session — 26. 3. 2026)

### Kritické bugy
| Bug | Příčina | Oprava |
|---|---|---|
| Nový zápis — prázdná stránka | `{% block content %}` smazán při slučování scriptů | Obnoveno z FINAL8 zálohy |
| Tlačítka nefungují (edit, PDF) | JS syntax error v `saveDetail()` — apostrof v stringu | Přesun do `detail.js` |
| Barvičky skóre zmizely | `sanitize_summary` regex `\x01` místo `\1` | Opraveno |
| Instrukce se nepropíšou | `user_message` obsahoval "Vrat POUZE validni JSON" — konflikt | Odstraněno |
| Admin Service Unavailable | `u.freelo_email` mimo for loop v Jinja2 | Přesunuto do JS |
| `table already exists` | `db.create_all(checkfirst=True)` — neexistuje parametr | Odstraněn |
| Hotové úkoly nenačítají | Špatný endpoint — správný je `/tasklist/{id}/finished-tasks` | Opraveno |
| format.js bug | Inline JS v `<script src="">` tagu — prohlížeč ignoruje | Oddělen tag |
| Dvě `onKlientChange` definice | Duplikátní funkce v různých script blocích | Sloučeno |

### JS architektura po opravě
```
novy.html: jeden <script> blok v <body> se VŠEMI funkcemi
detail.html: inline <script> jen s Jinja2 proměnnými + <script src="/static/detail.js">
detail.js: veškerá logika, čistý JS, Node.js syntax ověřen
```

---

## ✅ Co funguje (ověřeno)

- ✅ Přihlášení, role, session
- ✅ Přehled klientů s filtry a skóre
- ✅ Detail klienta — info, poznámky, projekty, zápisy, nabídky
- ✅ Freelo panel — aktivní + hotové úkoly (správný endpoint)
- ✅ Freelo editace, komentáře, podúkoly (modal s RTE)
- ✅ Profil skladu — vždy viditelný
- ✅ Nový zápis — prefill z API, datum, Freelo kontext panel
- ✅ Generování zápisů (audit/operativa/obchod)
- ✅ Detail zápisu — sekce, edit, AI úprava, PDF
- ✅ FREELO_STATUS sekce v zápisu
- ✅ Veřejný zápis (print/PDF)
- ✅ Zpět tlačítko → klient detail
- ✅ AI Report s Freelo daty + delta skóre
- ✅ Správa uživatelů — Freelo API klíč per user
- ✅ Per-user Freelo credentials (přepíše globální)
- ✅ /crm → redirect na /prehled
- ✅ Seed jen při ENABLE_SEED=true
- ✅ Admin heslo z ADMIN_PASSWORD env var

---

## ⏳ Pending / Nedokončeno

### Vysoká priorita
- [ ] **Import klientů ze SharePointu** — uživatel to chce, typ dat neznámý (Excel/CSV/složky)
- [ ] **Emailové odesílání zápisů** — MS 365 SMTP, neimplementováno
- [ ] **Tlačítka edit/AI v detail.html** — ověřit že oprava detail.js funguje v produkci

### Střední priorita
- [ ] **Hotové úkoly v klient detailu** — backend opravený, ověřit v produkci
- [ ] **Podúkoly** — vytváření funguje, ověřit v produkci
- [ ] **Responsivní CSS** — mobilní zobrazení není optimalizované

### Nízká priorita / Budoucnost
- [ ] **RAG / Knowledge base** — nahrávání dokumentů (PDF, Word, Excel) jako znalostní báze per klient
  - Přístup 1: pgvector embeddings (4-6 dní práce)
  - Přístup 2: strukturovaná extrakce do profilu klienta (2-3 dny)
- [ ] **Rate limiting** na API endpointech
- [ ] **Error tracking** (Sentry nebo podobné)
- [ ] **Unit testy**
- [ ] **Klientský portál** — `/portal` existuje ale není plně otestován

---

## 🔧 Před releasem kolegům — Checklist

```
Railway Variables:
  [x] SECRET_KEY nastaveno
  [x] ADMIN_PASSWORD nastaveno  
  [x] ANTHROPIC_API_KEY nastaveno
  [x] FREELO_API_KEY + FREELO_EMAIL + FREELO_PROJECT_ID nastaveny
  [ ] ENABLE_SEED = NESETTOVAT (nebo false)

Po deployi:
  [ ] Přihlásit se a změnit admin heslo
  [ ] Vytvořit účty pro kolegy (Správa → Uživatelé)
  [ ] Každý konzultant nastaví vlastní Freelo email + API klíč
  [ ] Smazat demo klienty pokud existují
  [ ] Otestovat generování prvního zápisu
```

---

## 🗄 DB Schéma — důležité sloupce

### User
```sql
id, email, name, password_hash, is_admin, is_active, role
klient_id         -- pro roli "klient"
freelo_email      -- vlastní Freelo email (přepíše globální)
freelo_api_key    -- vlastní Freelo API klíč
created_at
```

### Klient
```sql
id, nazev, slug, kontakt, email, telefon, adresa, sidlo, ic, dic
poznamka          -- volné poznámky
profil_json       -- AI-generovaný profil skladu (JSON)
freelo_tasklist_id -- propojení s Freelo
logo_url, is_active, created_at
```

### Zapis
```sql
id, title, template (audit/operativa/obchod)
input_text        -- přepis ze schůzky
output_json       -- AI výstup jako JSON sekce
output_text       -- HTML pro zobrazení
tasks_json        -- úkoly pro Freelo
notes_json        -- strukturované poznámky z terénu
interni_prompt    -- interní instrukce pro AI
freelo_sent       -- bool, odesláno do Freela
public_token, is_public  -- veřejný odkaz
klient_id, projekt_id, user_id
created_at
```

---

## 🔄 Freelo per-user credentials — jak funguje

```python
# services/freelo.py
def freelo_auth(user=None):
    """Preferuje credentials uživatele před globálními."""
    if user and user.freelo_email and user.freelo_api_key:
        return (user.freelo_email, user.freelo_api_key)
    return (FREELO_EMAIL, FREELO_API_KEY)  # fallback na env vars

def _get_current_user():
    """Auto-detekce přihlášeného uživatele z Flask session."""
    from flask import session
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None
```

---

## 📋 API endpointy — přehled

### Freelo (Blueprint: `freelo`)
```
GET  /api/klient/{id}/freelo-ukoly           → aktivní + hotové úkoly
GET  /api/klient/{id}/freelo-kontext         → kontext pro nový zápis (s komentáři)
GET  /api/klient/{id}/freelo-members         → členové projektu
GET  /api/freelo/projects                    → seznam projektů s tasklists
GET  /api/freelo/members/{project_id}        → členové projektu
POST /api/freelo/create-tasklist             → nový tasklist
POST /api/klient/{id}/freelo-nastavit        → nastavit tasklist klientovi
POST /api/klient/{id}/freelo-pridat-ukol     → přidat úkol
POST /api/klient/{id}/freelo-pridat-podukol  → přidat podúkol
POST /api/freelo/task/{id}/edit              → editovat úkol
POST /api/freelo/task/{id}/komentar          → přidat komentář
GET  /api/freelo/task/{id}/komentare         → načíst komentáře
GET  /api/freelo/task/{id}/podukoly          → načíst podúkoly
GET  /api/freelo/task/{id}/detail            → detail úkolu (s popisem)
POST /api/freelo/task/{id}/stav              → změnit stav (finish/activate)
POST /api/freelo/task/{id}/smazat            → smazat úkol
POST /api/freelo/{zapis_id}                  → odeslat úkoly ze zápisu do Freela
```

### Klienti (Blueprint: `klienti`)
```
GET  /klient/{id}                            → detail klienta
GET  /api/klient/{id}/info                   → základní info pro prefill formulářů
POST /api/klient/{id}/upravit                → uložit změny
POST /api/klient/{id}/profil                 → uložit profil skladu
```

### Zápisy (Blueprint: `zapisy`)
```
POST /api/generovat                          → generovat zápis (AI)
GET  /zapis/{id}                             → detail zápisu
POST /api/zapis/{id}/sekce                   → uložit sekci
POST /api/zapis/{id}/ai-sekce               → AI úprava sekce
POST /api/zapis/{id}/publikovat             → zveřejnit/skrýt
```

---

## 🎨 Brand Guidelines

```css
--navy: #173767    /* hlavní barva */
--cyan: #00AFF0    /* akcent */
--orange: #FF8D00  /* CTA tlačítka */
Font: Montserrat (všude)
Nadpisy: 26px, weight 800
Tělo: 13-14px, weight 500
```

---

## ⚠️ Známé problémy a gotchas

### Jinja2 gotchas
- `u.atribut is defined` nefunguje pro atributy objektů — použij prostě `u.atribut`
- Jinja2 modaly musí být prázdné — data plní JavaScript přes parametry funkcí
- `{% for u in users %}` — `u` existuje POUZE uvnitř cyklu

### SQLAlchemy gotchas
- `db.create_all()` bez argumentů je správné (přeskočí existující tabulky)
- `db.create_all(checkfirst=True)` neexistuje v Flask-SQLAlchemy — crash!
- Migrace `ALTER TABLE "user"` — user musí být v uvozovkách (rezervované slovo)

### JS gotchas
- `<script src="...">` s inline obsahem — prohlížeč ignoruje inline kód!
- `let` na top-level není na `window` (na rozdíl od `var`)
- detail.js je externí soubor, novy.html má vše inline v jednom `<script>`

### Freelo gotchas  
- Project ID 582553 (viditelné v URL) ≠ 501350 (API ID) — vždy použij 501350
- `state=null` v tasklist odpovědi = aktivní (ne "chybí stav")
- `state.state="active"` = aktivní, `state.id=5` = hotový
- Popis: POST /description ZVLÁŠŤ po vytvoření, prázdný content = 400

---

## 📁 Soubory k zachování

```
CLAUDE.md           ← tento soubor (pravidelně aktualizovat)
commarec-v2-FINAL9.zip  ← aktuální záloha
/tmp/test_v2.py     ← testovací script (spustit před každým deploye)
```

### Test script spouštění
```bash
cd /home/claude/v2
python3 /tmp/test_v2.py
```
Musí vrátit: `✅ VŠECHNY TESTY PROŠLY — připraven k deployi!`

---

## 🚀 Postup pro nový deploy

```bash
# 1. Ověř testy
cd /home/claude/v2 && python3 /tmp/test_v2.py

# 2. Vytvoř ZIP
find . -name "*.pyc" -delete
zip -r ../commarec-v2-FINAL9.zip . --exclude "*/.git/*" ...

# 3. Nahraj na GitHub (uživatel dělá ručně)
# 4. Railway automaticky deployuje
# 5. Zkontroluj logy — hledej "Starting gunicorn" bez ERROR
```

---

## 💡 Next session — Co dělat jako první

Doporučené pořadí:

1. **Ověřit v produkci** — jestli admin funguje, Freelo se načítá, generování funguje
2. **Import klientů ze SharePointu** — zjistit formát dat (Excel/CSV?) a implementovat
3. **Emailové odesílání zápisů** — MS 365 SMTP (Martin má credentials)
4. **RAG / Knowledge base** — až bude základní provoz stabilní

---

*Dokument generován: 26. 3. 2026 | Commarec Zápisy v2 | Claude Sonnet 4.6*
