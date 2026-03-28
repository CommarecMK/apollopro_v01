# Commarec Zápisy v2 — CLEAN START

## Stav: Čistý restart (po problémech s migrací databáze 28.3.2026)

## Co funguje
- Přihlášení, role (superadmin, admin, user, klient)
- Přehled klientů (/prehled)
- Seznam zápisů (/dashboard) — záložka "Zápisy" v menu
- Detail zápisu, generování AI, PDF export
- Správa uživatelů (/admin)
- Freelo integrace
- Měsíční AI report
- Manuál pro tým (/manual)
- Po přihlášení → redirect na /prehled

## Architektura
- Flask + SQLAlchemy (BEZ Flask-Migrate — záměrně)
- db.create_all() — vytvoří tabulky pokud neexistují, NEMAŽE data
- PostgreSQL na Railway
- Gunicorn, 2 workers

## Railway — Produkce
- URL: app.apollopro.io
- Větev: main
- ENABLE_SEED: false (nebo nenastaveno)

## Railway — Staging
- URL: staging.apollopro.io
- Větev: staging
- ENABLE_SEED: true
- Vlastní databáze (oddělená od produkce!)

## Workflow pro nové funkce
1. Uprav kód → nahraj na GitHub větev `staging`
2. Otestuj na staging.apollopro.io
3. Funguje? → nahraj do `main` → jde do produkce

## Důležité
- NIKDY nenastavovat ENABLE_SEED=true na produkci
- Staging a produkce MUSÍ mít oddělené databáze
- Flask-Migrate odstraněn záměrně — způsoboval problémy při deployi
