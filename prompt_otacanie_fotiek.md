# Prompt pre Claude Code: program na otáčanie fotiek z merania + extrakcia ID čísel zo štítku

## Cieľ
Vytvor Python program (skript spustiteľný z príkazového riadku), ktorý spracuje priečinok s fotkami
z telefónu (fotky z elektro merania) a:

1. Každú fotku otočí do vodorovnej (landscape) orientácie – správnou stranou hore, nie hore nohami.
2. Zachová presné pôvodné poradie fotiek (podľa času vytvorenia) – poradie sa NESMIE pomiešať,
   keďže ide o súvislú sekvenciu záberov z jedného merania.
3. Nové (otočené) fotky ulož do NOVÉHO podpriečinka vo vnútri zadaného priečinka (napr. `otocene/`),
   aby sa výstup nikdy nezmiešal s originálmi.
4. Na prvej fotke (na štítku prístroja) rozpozná text a vytiahne hodnoty za "Seriennr.:" a
   "Zählernr.:", a:
   - zapíše ich do textového súboru vedľa otočených fotiek,
   - po skončení behu ich zobrazí aj v jednoduchom okienku / v konzole, aby sa dali hneď skopírovať.

## Vstup
- Cesta k priečinku (argument príkazového riadku; ak chýba, program sa na ňu opýta).
- Vo vnútri sú fotky z bežného telefónu – podporuj aspoň JPG/JPEG, PNG a HEIC/HEIF (iPhone).

## Poradie fotiek – KRITICKY DÔLEŽITÉ
- Zoraď fotky podľa dátumu/času vytvorenia: najprv skús EXIF `DateTimeOriginal`, ak chýba, použi
  dátum poslednej zmeny súboru.
- Toto poradie musí zostať zachované aj vo výstupe – výstupné súbory pomenuj s číselným prefixom
  podľa poradia (napr. `001_povodnynazov.jpg`, `002_...`), aby bolo poradie 100 % rovnaké ako pri
  nahraní, aj keby sa niekde po ceste stratili pôvodné časové metadáta.
- Program nesmie fotky žiadnym spôsobom preusporiadať ani premiešať.

## Otáčanie fotiek
- Najprv skontroluj EXIF `Orientation` tag – ak existuje, aplikuj ho.
- Over pomer strán (šírka < výška = fotka je na výšku a treba ju otočiť).
- Na zistenie SPRÁVNEHO smeru otočenia (90° vľavo/vpravo, aby text a obsah boli vzpriamené, nie
  hore nohami) použi Tesseract OCR funkciu na detekciu orientácie (OSD – Orientation and Script
  Detection, `image_to_osd`). Over všetky 4 možné rotácie (0°/90°/180°/270°) a vyber tú s najvyššou
  spoľahlivosťou/najčitateľnejším textom.
- Ak sa orientácia nedá spoľahlivo určiť (napr. na fotke nie je dosť textu), fotku napriek tomu ulož
  (v najlepšom odhadovanom natočení) a zapíš ju do log súboru ako "neistá rotácia – skontrolovať
  manuálne".
- Fotky, ktoré sú už vodorovné, nechaj bez zmeny.

## Extrakcia ID čísel zo štítku
- Na (aspoň) prvej fotke v priečinku spusti OCR (Tesseract, jazyk `deu+eng`, keďže text na štítku
  je v nemčine).
- Vyhľadaj v rozpoznanom texte "Seriennr." a "Zählernr." – tolerantne aj na drobné OCR chyby
  (napr. "Serien-Nr", "Ser.Nr", "Zahlernr", "Zähler-Nr" a pod.) a vytiahni hodnotu nasledujúcu za
  dvojbodkou/za týmto textom.
- Tieto dve hodnoty:
  - zapíš do textového súboru `identifikacne_cisla.txt` v novom podpriečinku s otočenými fotkami,
  - na konci behu ich vypíš aj do konzoly a zobraz v jednoduchom okienku (napr. `tkinter
    messagebox`), aby sa dali hneď skopírovať.
- Ak OCR na prvej fotke zlyhá alebo nenájde ani jeden z týchto reťazcov, program to jasne oznámi
  (nesmie spadnúť na chybe) a skúsi to aj na ďalších fotkách v poradí, keby štítok náhodou nebol
  presne na prvej.

## Výstupná štruktúra
V zadanom priečinku vytvor nový podpriečinok (napr. `otocene` alebo s časovou pečiatkou v názve,
aby sa dalo spustiť opakovane bez prepísania predošlého výstupu) obsahujúci:
- všetky otočené fotky, očíslované podľa poradia (`001_...`, `002_...`, ...),
- `identifikacne_cisla.txt` s vytiahnutými hodnotami,
- `log.txt` s prehľadom spracovania (ktorá fotka bola ako otočená, ktoré mali neistú rotáciu,
  prípadné chyby).

Originálne fotky sa nesmú nijako meniť ani mazať – program z nich iba číta.

## Technické poznámky pre Claude Code
- Jazyk: Python 3.
- Odporúčané knižnice: `Pillow` (práca s obrázkami a EXIF), `pillow-heif` (podpora HEIC z iPhone),
  `pytesseract` + systémovo nainštalovaný `Tesseract OCR` s jazykovým balíčkom `deu`.
- Over, či je Tesseract nainštalovaný (na Windows cez inštalátor UB-Mannheim) – ak nie, napíš presný
  návod, čo a odkiaľ doinštalovať, vrátane nemeckého jazykového balíčka.
- Program má fungovať úplne OFFLINE (bez internetu/API kľúča) – toto je hlavný režim.
- VOLITEĽNÉ vylepšenie (implementuj ako prepínateľnú možnosť, nie ako povinnosť): ak lokálny OCR na
  čítanie štítku nebude dostatočne presný (napr. kvôli odleskom alebo uhlu fotenia), pridaj možnosť
  prepnúť len tento jeden krok (čítanie Seriennr./Zählernr.) na Anthropic Claude API (vision). Použije
  sa výhradne na fotku so štítkom, nie na všetky fotky (kvôli nákladom a rýchlosti). API kľúč sa berie
  z premennej prostredia `ANTHROPIC_API_KEY`. Toto je záložný režim, hlavný je lokálny Tesseract.
- Spracovanie má byť dávkové (celý priečinok naraz), nie fotku po fotke ručne.
- Ošetri chyby (poškodený súbor, nepodporovaný formát) tak, aby program nespadol, len danú fotku
  preskočil a zapísal chybu do logu.

## Ako to otestovať
Priprav aj krátky testovací postup na malej vzorke 3–5 fotiek (rôzne natočené), aby sa dalo overiť:
1. poradie zostalo správne,
2. rotácia sedí (žiadna fotka nie je hore nohami ani na výšku),
3. ID čísla sa vytiahli správne z prvej fotky.
