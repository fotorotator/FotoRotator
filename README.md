# FotoRotator

Program, ktorý spracuje priečinok s fotkami z telefónu (fotky z elektro
merania), otočí ich do vodorovnej (landscape) orientácie správnou stranou hore
a z prvej fotky (štítok meracieho prístroja) vytiahne **Seriennr.** a
**Zählernr.**

## Inštalácia (pre bežného používateľa)

1. Stiahni najnovší `FotoRotator.exe` zo sekcie [Releases](../../releases)
   a spusti ho (odkiaľkoľvek, napr. z priečinka Stiahnuté)
2. Pri **prvom spustení** sa program sám presunie do `Dokumenty\FotoRotator`
   a na Plochu si vytvorí odkaz **FotoRotator** (s vlastnou ikonou) — nabudúce
   stačí spúšťať cez túto skratku. Pôvodný stiahnutý súbor môžeš pokojne
   zmazať, netreba ho už.
3. Otvorí sa **okno programu**: vyber priečinok (zákazku alebo jedno meranie),
   prípadne vlož **Claude API kľúč** (voliteľné, zapne AI kontrolu — kľúč sa
   uloží bezpečne a stačí ho zadať raz) a klikni **Spustiť**. Okno ukazuje
   priebeh (ktorá fotka sa spracúva), živý log a na konci výsledky
   s tlačidlom "Otvoriť výstupný priečinok".
4. Tlačidlom **"Skryť do lišty"** (alebo klikom na bežné minimalizovanie okna)
   sa program schová do systémovej lišty vedľa hodín a spracovanie beží ďalej
   na pozadí — po dokončení príde upozornenie priamo z lišty. Klikom na
   ikonu sa okno vráti späť.
5. Ak na počítači chýba **Tesseract OCR** (potrebný na rozpoznanie správneho
   smeru otočenia a čítanie štítku), program ho pri spustení **sám ponúkne
   stiahnuť a nainštalovať** — vždy aktuálnu verziu, automaticky aj
   s nemeckým jazykovým balíkom. Stačí potvrdiť a povoliť inštaláciu v okne
   Windows (UAC). Ručná inštalácia je tiež možná: inštalátor z
   [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki),
   pri inštalácii zaškrtnúť jazyk **German (deu)**.

Tip: cestu k priečinku možno dať aj ako argument (`FotoRotator.exe "C:\..."`)
— spracovanie sa potom spustí hneď po otvorení okna.

Originálne fotky sa nikdy nemenia ani nemažú — program z nich iba číta.

## Čo program robí

1. Zoradí fotky presne podľa času vytvorenia (EXIF `DateTimeOriginal`, inak
   dátum poslednej zmeny súboru) a toto poradie zachová aj vo výstupe
   (`001_...`, `002_...`, ...)
0. **Podpriečinky:** ak vybraný priečinok obsahuje podpriečinky s fotkami
   (napr. jeden priečinok na zákazku a v ňom 8–10 podpriečinkov s jednotlivými
   meraniami), program spracuje **každý podpriečinok samostatne** — vlastné
   poradie, číslovanie od 001 aj vlastné ID čísla. Fotky z rôznych
   podpriečinkov sa nikdy nepomiešajú. Výstup zrkadlí pôvodnú štruktúru
   a navrch pribudne súhrnný `prehlad.txt` so všetkými nájdenými hodnotami.
2. Otočí každú fotku do landscape orientácie — najprv aplikuje EXIF
   `Orientation`, a ak je fotka stále na výšku, cez Tesseract OCR (spoľahlivosť
   rozpoznaného textu pri 90°/270° otočení) zistí správny smer
3. Fotky, ktoré sú už vodorovné, necháva bez zmeny
4. Ak sa smer otočenia nedá spoľahlivo určiť (napr. nedostatok textu na
   fotke), fotku aj tak uloží v najlepšom odhade a označí v `log.txt` ako
   "NEISTA ROTACIA — skontroluj rucne"
5. Na prvých pár fotkách skúša OCR (`deu+eng`) nájsť `Seriennr.:` a
   `Zählernr.:` (tolerantne aj na drobné OCR chyby) a zapíše ich do
   `identifikacne_cisla.txt`

### AI kontrola (Claude API) — odporúčané

V okne programu vlož **Claude API kľúč** (získaš na
[console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys))
a klikni "Uložiť kľúč" — kľúč sa overí a uloží **zašifrovaný** (Windows DPAPI,
viazaný na tvoj účet; nikam sa neposiela okrem priamych volaní na Claude API).
Zadáva sa iba raz. S uloženým kľúčom sa automaticky zapne AI kontrola, ktorá
zvládne to, čo lokálny OCR nie:

**Kde a ako je kľúč uložený:** v súbore `%APPDATA%\FotoRotator\config.json`
(typicky `C:\Users\<meno>\AppData\Roaming\FotoRotator\config.json`). Kľúč v
tomto súbore **nie je čitateľný text** — je zašifrovaný cez Windows DPAPI
naviazané na tvoj Windows účet na tomto konkrétnom počítači. Aj keby niekto
otvoril súbor alebo si ho skopíroval, bez prihlásenia ako ty na tomto PC sa
kľúč nedá rozšifrovať. Kľúč sa posiela výhradne priamo na `api.anthropic.com`
pri AI kontrole — nikam inam.

**Výber modelu:** v okne je rozbaľovací zoznam "Model AI kontroly" so 4
možnosťami zoradenými od najlacnejšej po najdrahšiu, s poznámkou o cene
(za milión tokenov, vstup/výstup) a orientačnou kvalitou:

| Model | Cena | Poznámka |
|---|---|---|
| **Claude Haiku 4.5** (odporúčané, default) | $1 / $5 | najlacnejší, na túto úlohu overene postačuje |
| Claude Sonnet 5 | $2 / $10 | kvalitnejší, cca 2× drahší |
| Claude Opus 4.8 | $5 / $25 | najkvalitnejší bežne dostupný, cca 5× drahší |
| Claude Fable 5 | $10 / $50 | najsilnejší vôbec, cca 10× drahší — na fotky zvyčajne zbytočne drahé |

Voľba sa uloží a použije pri každom ďalšom behu.

- **overí správnosť otočenia každej fotky** — fotka sa porovná so svojou 180°
  otočenou verziou a AI vyberie tú správnu; rieši to tmavé zábery displejov
  zblízka aj elektromery s naopak nalepenými kontrolnými nálepkami, ktoré
  oklamú lokálnu detekciu
- **prečíta stav elektromera** zo sedemsegmentového LCD displeja (napr.
  `02854.4 kWh` pri kóde 1.8.0) — zapíše sa do `identifikacne_cisla.txt`
  k Seriennr./Zählernr.
- **zálohuje čítanie štítku** (Seriennr./Zählernr.), keby lokálny OCR zlyhal

Cena je rádovo centy za celú dávku fotiek (Claude Haiku 4.5 — najlacnejší
model s podporou obrázkov). Program priebežne sleduje minutú sumu:
- po každom behu sa cena zapíše do `identifikacne_cisla.txt` (a `prehlad.txt`
  pri viacerých priečinkoch),
- v okne programu vidno pri API kľúči aj **celkovú sumu minutú doteraz**
  (ukladá sa lokálne, sčítava sa naprieč všetkými behmi).

Bez kľúča program funguje úplne offline (lokálny Tesseract) — ale tmavé
fotky displejov zblízka môžu ostať zle otočené a stav elektromera sa
neprečíta.

## Vývoj / spustenie zo zdrojového kódu

```bash
pip install -r requirements.txt
python -m app.main [priecinok]
```

## Balenie do .exe

```bash
build_exe.bat
```

Vytvorí `dist/FotoRotator.exe` a kontrolný súčet `dist/FotoRotator.exe.sha256`.

## Štruktúra projektu

```
app/
  main.py              — vstupný bod, spúšťa okno programu
  gui.py               — okno programu (výber priečinka, API kľúč, priebeh, log)
  pipeline.py          — samotné spracovanie (priečinky, poradie, výstupy)
  rotate.py            — triedenie podľa času, EXIF/OCR otáčanie do landscape
  id_extract.py        — vytiahnutie Seriennr./Zählernr. (lokálny OCR)
  claude_check.py      — voliteľná AI kontrola cez Claude API (orientácia, stav elektromera)
  config.py            — uloženie API kľúča (šifrovaný cez Windows DPAPI)
  tesseract_check.py   — overenie inštalácie Tesseractu + návod na doinštalovanie
  tesseract_install.py — automatické stiahnutie a tichá inštalácia Tesseractu + nemčiny
run.py                 — vstupný skript pre PyInstaller
build_exe.bat          — zabalenie do .exe
requirements.txt
```

## Výstupná štruktúra

V zadanom priečinku vznikne nový podpriečinok `otocene_<dátum_čas>/` s:
- otočenými fotkami, očíslovanými podľa poradia (`001_...`, `002_...`, ...)
  — HEIC/HEIF fotky sa ukladajú ako `.jpg` (kvôli spoľahlivosti ukladania)
- `identifikacne_cisla.txt` s vytiahnutými hodnotami
- `log.txt` s prehľadom spracovania (ako bola ktorá fotka otočená, ktoré mali
  neistú rotáciu, prípadné chyby)
