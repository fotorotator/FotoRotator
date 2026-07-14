# FotoRotator

Program, ktorý spracuje priečinok s fotkami z telefónu (fotky z elektro
merania), otočí ich do vodorovnej (landscape) orientácie správnou stranou hore
a z prvej fotky (štítok meracieho prístroja) vytiahne **Seriennr.** a
**Zählernr.**

## Inštalácia (pre bežného používateľa)

1. Stiahni najnovší `FotoRotator.exe` zo sekcie [Releases](../../releases)
2. Spusti `FotoRotator.exe` — buď mu daj cestu k priečinku ako argument,
   alebo (bez argumentu) sa otvorí okno na výber priečinka
3. Ak na počítači chýba **Tesseract OCR** (potrebný na rozpoznanie správneho
   smeru otočenia a čítanie štítku), program ho pri prvom spustení **sám
   ponúkne stiahnuť a nainštalovať** — vždy aktuálnu verziu, automaticky aj
   s nemeckým jazykovým balíkom. Stačí potvrdiť a povoliť inštaláciu v okne
   Windows (UAC). Ručná inštalácia je tiež možná: inštalátor z
   [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki),
   pri inštalácii zaškrtnúť jazyk **German (deu)**.
4. Program otočí fotky, vytvorí nový podpriečinok `otocene_<dátum_čas>/` a na
   konci zobrazí Seriennr./Zählernr. v konzole aj v okienku (dá sa hneď
   skopírovať)

Originálne fotky sa nikdy nemenia ani nemažú — program z nich iba číta.

## Čo program robí

1. Zoradí fotky presne podľa času vytvorenia (EXIF `DateTimeOriginal`, inak
   dátum poslednej zmeny súboru) a toto poradie zachová aj vo výstupe
   (`001_...`, `002_...`, ...)
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

### Voliteľný režim: Claude API (vision)

Prepínač `--use-claude-api` pošle každú fotku (zmenšenú) aj na Claude API,
ktoré zvládne to, čo lokálny OCR nie:

- **overí správnosť otočenia** — fotka sa porovná so svojou 180° otočenou
  verziou a AI vyberie tú správnu; rieši to napr. elektromery s naopak
  nalepenými kontrolnými nálepkami, ktoré oklamú lokálnu detekciu
- **prečíta stav elektromera** zo sedemsegmentového LCD displeja (napr.
  `02854.4 kWh` pri kóde 1.8.0) — zapíše sa do `identifikacne_cisla.txt`
  k Seriennr./Zählernr.
- **zálohuje čítanie štítku** (Seriennr./Zählernr.), keby lokálny OCR zlyhal

Vyžaduje premennú prostredia `ANTHROPIC_API_KEY` (získaš na
[console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)).
Cena je rádovo centy za celú dávku fotiek. Hlavný režim ostáva vždy lokálny
Tesseract — appka funguje aj úplne offline (bez stavu elektromera).

```
FotoRotator.exe "C:\cesta\k\fotkam" --use-claude-api
```

## Vývoj / spustenie zo zdrojového kódu

```bash
pip install -r requirements.txt
python -m app.main [priecinok] [--use-claude-api]
```

## Balenie do .exe

```bash
build_exe.bat
```

Vytvorí `dist/FotoRotator.exe` a kontrolný súčet `dist/FotoRotator.exe.sha256`.

## Štruktúra projektu

```
app/
  main.py              — vstupný bod, spracovanie priečinka, GUI dialógy
  rotate.py            — triedenie podľa času, EXIF/OCR otáčanie do landscape
  id_extract.py        — vytiahnutie Seriennr./Zählernr. (lokálny OCR)
  claude_check.py      — voliteľná kontrola cez Claude API (orientácia, stav elektromera)
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
