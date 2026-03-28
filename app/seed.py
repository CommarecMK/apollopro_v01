"""seed.py"""
import json
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from .extensions import db
from .models import User, Klient, Zapis, Projekt, Nabidka, NabidkaPolozka
from .services.ai_service import assemble_output_text

def seed_test_data():
    """Vytvoř testovací data s českou diakritikou."""
    try:
        if Klient.query.first():
            return
    except Exception:
        db.session.rollback()
        return
    import time, random
    time.sleep(random.uniform(0, 0.5))
    try:
        if Klient.query.first():
            return
    except Exception:
        db.session.rollback()
        return

    print("Seeduji testovací data...")

    admin = User.query.filter_by(email="admin@commarec.cz").first()

    # Konzultant Martin Komárek
    martin = User.query.filter_by(email="martin@commarec.cz").first()
    if not martin:
        try:
            martin = User(
                email="martin@commarec.cz", name="Martin Komárek",
                role="konzultant", is_admin=False, is_active=True,
                password_hash=generate_password_hash("test123")
            )
            db.session.add(martin)
            db.session.flush()
        except Exception:
            db.session.rollback()
            martin = User.query.filter_by(email="martin@commarec.cz").first()

    # Klient 1
    k1 = Klient(
        nazev="Testovací Logistika s.r.o.",
        slug="testovaci-logistika",
        kontakt="Petr Novotný",
        email="novotny@testlogistika.cz",
        telefon="+420 777 123 456",
        adresa="Průmyslová 14, Brno 615 00",
        poznamka="Distribuční sklad, klient od roku 2023. Zaměřujeme se na optimalizaci pickování a procesů expedice.",
        profil_json=json.dumps({
            "typ_skladu": "distribuční",
            "pocet_sku": "4 200",
            "metody_pickingu": "batch picking, zone picking",
            "pocet_zamestnanci": "28",
            "pocet_smen": "2",
            "wms_system": "Helios Orange",
            "prumerna_denni_expedice": "850",
            "hlavni_problemy": "Vysoký backlog, chybovost při pickování B2B objednávek",
        }, ensure_ascii=False)
    )
    db.session.add(k1)
    db.session.flush()

    # Klient 2
    k2 = Klient(
        nazev="Demo Expres a.s.",
        slug="demo-expres",
        kontakt="Jana Horáčková",
        email="horacekova@demoexpres.cz",
        adresa="Letňanská 8, Praha 9, 190 00",
        poznamka="Výrobní a expediční sklad. Implementace WMS v řešení.",
    )
    db.session.add(k2)
    db.session.flush()

    # Projekt 1
    p1 = Projekt(
        nazev="Optimalizace skladu 2025",
        popis="Procesní audit a návrh optimalizace pickování a layoutu skladu.",
        klient_id=k1.id,
        user_id=admin.id if admin else None,
        datum_od=datetime(2025, 1, 15).date(),
        datum_do=datetime(2025, 12, 31).date(),
        is_active=True,
    )
    db.session.add(p1)
    db.session.flush()

    # Projekt 2
    p2 = Projekt(
        nazev="WMS implementace",
        popis="Výběr a implementace WMS systému.",
        klient_id=k2.id,
        user_id=admin.id if admin else None,
        datum_od=datetime(2025, 3, 1).date(),
        is_active=True,
    )
    db.session.add(p2)
    db.session.flush()

    # Zápis 1  -  audit Testovací Logistika
    summary1 = {
        "participants_commarec": "<p>Martin Komárek  -  vedoucí konzultant</p>",
        "participants_company": "<p>Petr Novotný (ředitel logistiky), Pavel Beneš (vedoucí skladu)</p>",
        "introduction": "<p>Diagnostická návštěva zaměřená na identifikaci příčin rostoucího backlogu a chybovosti při expedici B2B objednávek.</p>",
        "meeting_goal": "<p>Zmapovat aktuální stav pickování, změřit výkonnost a navrhnout konkrétní opatření.</p>",
        "findings": "<ul><li><strong>Pozitivní:</strong> Motivovaný tým, dobrá znalost sortimentu, zavedené ranní porady</li><li><strong>Rizika:</strong> Chybovost pickování 4,2 % (standard je pod 0,5 %), backlog 3 dny, WMS bez wave-planningu</li></ul>",
        "ratings": "<table><tr><th>Oblast</th><th>Hodnocení (%)</th><th>Komentář</th></tr><tr><td>Procesní dokumentace</td><td>35</td><td>Chybí standardy pro B2B picking</td></tr><tr><td>WMS utilizace</td><td>45</td><td>Nevyužívají wave planning ani ABC analýzu</td></tr><tr><td>Layout skladu</td><td>60</td><td>Základní zónování, reserve locations OK</td></tr><tr><td>Produktivita pickování</td><td>40</td><td>58 řádků/hod, potenciál 90+</td></tr><tr><td colspan='3'><strong>Celkové skóre: 45 %</strong> | Nejlepší: Layout | Nejkritičtější: Chybovost</td></tr></table>",
        "processes_description": "<p>Picking probíhá single-order metodou bez batch zpracování. Pracovníci chodí pro každou objednávku zvlášť, průměrná vzdálenost 340 m/objednávka. ABC analýza nebyla nikdy provedena - fast-movers jsou rozmísteny náhodně po celém skladu.</p>",
        "dangers": "<ul><li><strong>Chybovost 4,2 %</strong> → reklamace, ztráta zákazníků, přepracování</li><li><strong>Backlog 3 dny</strong> → nesplněné SLA, pokuty od odběratelů</li><li><strong>Odchod klíčových lidí</strong> → frustrace z chaosu, 2 výpovědi za Q4 2024</li></ul>",
        "suggested_actions": "<p><strong>Krátkodobé (0 - 1 měsíc):</strong></p><ul><li>ABC analýza sortimentu  -  přesunout top 200 SKU do pick zóny A</li><li>Zavedení batch pickingu pro B2C objednávky (skupiny po 8 - 12 obj.)</li></ul><p><strong>Střednědobé (1 - 3 měsíce):</strong></p><ul><li>Konfigurace wave planningu v Helios Orange</li><li>Tvorba standardů a SOP pro picking B2B</li></ul>",
        "expected_benefits": "<ul><li><strong>Snížení chybovosti</strong> z 4,2 % na pod 0,8 %  -  úspora 280 tis. Kč/rok na reklamacích</li><li><strong>Zvýšení produktivity</strong> o 35 - 45 % po zavedení batch pickingu</li><li><strong>Odbourání backlogu</strong> do 2 týdnů od implementace ABC zónování</li></ul>",
        "additional_notes": "<p>Velmi pozitivní přístup vedení  -  okamžitě souhlasili s navrhovanými změnami. Pavel Beneš je silný interní champion. Sklad je čistý a dobře organizovaný co se týče fyzického uspořádání  -  problém je v procesech, ne v prostoru.</p>",
        "summary": "<p>Sklad Testovací Logistika má solidní základy, ale trpí procesními neduhy typickými pro organicky rostoucí e-commerce/B2B operaci. Priorita č. 1: ABC analýza a přesun fast-movers. Priorita č. 2: batch picking. Očekáváme rychlé výsledky  -  tým je motivovaný a vedení plně podporuje změny.</p>",
    }

    z1 = Zapis(
        title="Testovací Logistika s.r.o.  -  Audit skladu",
        template="audit",
        input_text="[Testovací zápis  -  vygenerováno jako seed data]",
        output_json=json.dumps(summary1, ensure_ascii=False),
        output_text="",
        tasks_json=json.dumps([
            {"name": "ABC analýza sortimentu", "desc": "Provést analýzu pohyblivosti SKU a navrhnout rozmístění fast-movers do zóny A", "deadline": "do 1 měsíce"},
            {"name": "Návrh batch picking procesu", "desc": "Zpracovat návrh wave plánu pro B2C objednávky, skupiny 8 - 12 obj.", "deadline": "do 3 týdnů"},
            {"name": "Konfigurace wave planningu v Helios", "desc": "Spolupráce s IT na nastavení wave planning modulu v Helios Orange", "deadline": "do 2 měsíců"},
        ], ensure_ascii=False),
        interni_prompt="",
        freelo_sent=False,
        user_id=admin.id if admin else 1,
        klient_id=k1.id,
        projekt_id=p1.id,
        created_at=datetime(2025, 2, 14, 10, 30),
    )
    client_info = {"meeting_date": "2025-02-14", "commarec_rep": "Martin Komárek",
                   "client_contact": "Petr Novotný", "client_name": "Testovací Logistika s.r.o.", "meeting_place": "Sídlo klienta, Brno"}
    all_blocks = set(["uvod","zjisteni","hodnoceni","procesy","rizika","kroky","prinosy","poznamky","dalsi_krok"])
    z1.output_text = assemble_output_text(client_info, summary1, all_blocks)
    db.session.add(z1)

    # Zápis 2  -  kick-off Demo Expres
    summary2 = {
        "participants_commarec": "<p>Martin Komárek</p>",
        "participants_company": "<p>Jana Horáčková (COO), Tomáš Král (IT ředitel)</p>",
        "introduction": "<p>Kick-off meeting k výběru WMS systému. Diskuse požadavků a harmonogramu implementace.</p>",
        "meeting_goal": "<p>Definovat klíčové požadavky na WMS, odsouhlasit shortlist dodavatelů a nastavit harmonogram výběrového řízení.</p>",
        "findings": "<ul><li>Aktuálně používají Excel + papírové průvodky  -  žádný WMS</li><li>Denní expedice 1 200 ks, 3 směny, 45 zaměstnanců</li><li>Požadavek na go-live do září 2025</li></ul>",
        "suggested_actions": "<p><strong>Krátkodobé:</strong></p><ul><li>Commarec připraví RFP dokument do 28. 2.</li><li>Demo Expres dodá kompletní seznam SKU a procesní mapu do 7. 3.</li></ul><p><strong>Střednědobé:</strong></p><ul><li>Demo prezentace 3 dodavatelů  -  duben 2025</li><li>Výběr dodavatele  -  květen 2025</li></ul>",
        "summary": "<p>Kick-off proběhl konstruktivně. Obě strany shodnuty na harmonogramu. Hlavní riziko: krátký timeline na go-live (6 měsíců). Commarec doporučuje zvážit fázovaný rollout.</p>",
    }
    z2 = Zapis(
        title="Demo Expres a.s.  -  WMS Kick-off",
        template="operativa",
        input_text="[Testovací zápis  -  vygenerováno jako seed data]",
        output_json=json.dumps(summary2, ensure_ascii=False),
        output_text="",
        tasks_json=json.dumps([
            {"name": "Připravit RFP dokument", "desc": "Zpracovat požadavky na WMS pro Demo Expres", "deadline": "2025-02-28"},
            {"name": "Demo prezentace WMS dodavatelů", "desc": "Organizace demo dnů pro 3 vybrané dodavatele", "deadline": "2025-04-15"},
        ], ensure_ascii=False),
        interni_prompt="",
        freelo_sent=False,
        user_id=admin.id if admin else 1,
        klient_id=k2.id,
        projekt_id=p2.id,
        created_at=datetime(2025, 3, 5, 14, 0),
    )
    client_info2 = {"meeting_date": "2025-03-05", "commarec_rep": "Martin Komárek",
                    "client_contact": "Jana Horáčková", "client_name": "Demo Expres a.s.", "meeting_place": "Praha 9, Letňany"}
    z2.output_text = assemble_output_text(client_info2, summary2, all_blocks)
    db.session.add(z2)



    db.session.commit()
    print("Seed data vytvořena: 5 klientů, 5 projektů, 10+ zápisů")
