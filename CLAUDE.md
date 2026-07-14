# FotoRotator — kontext projektu pre Claude Code

## O projekte

**FotoRotator** je samostatný Windows program (CLI skript s pár tkinter
okienkami), ktorý spracuje priečinok s fotkami z telefónu — konkrétne
fotky z elektro merania — a:

1. otočí každú fotku do vodorovnej (landscape) orientácie, správnou stranou
   hore,
2. zachová presné pôvodné poradie fotiek (podľa času vytvorenia),
3. uloží otočené fotky do nového podpriečinka (originály sa nemenia),
4. z prvej fotky (štítok meracieho prístroja) vytiahne OCR-om hodnoty
   `Seriennr.` a `Zählernr.` a zobrazí ich na konci behu.

Plné pôvodné zadanie je v [prompt_otacanie_fotiek.md](prompt_otacanie_fotiek.md).

## Používateľ

Tomáš — elektrikár, nie programátor. Komunikuj po slovensky, vysvetľuj
jednoducho.

## Technológie

- **Python 3**, `Pillow` + `pillow-heif` (HEIC z iPhonu), `pytesseract` +
  systémovo nainštalovaný **Tesseract OCR** (jazykový balík `deu`)
- Hlavný režim je vždy **offline** (žiadne API, žiadny kľúč potrebný)
- Voliteľný záložný režim (`--use-claude-api`): Claude API (vision) sa použije
  **iba** na fotku so štítkom, ak lokálny OCR na jej prečítanie nestačí —
  API kľúč sa berie z `ANTHROPIC_API_KEY`
- **PyInstaller** — zabalenie do jedného `.exe` (`build_exe.bat`)

## Štruktúra súborov

```
FotoRotator/
  app/
    main.py              — vstupný bod, orchestrácia celého behu
    rotate.py            — triedenie fotiek podľa času, EXIF/OCR rotácia
    id_extract.py        — extrakcia Seriennr./Zählernr. (lokálny OCR + regexy)
    claude_check.py      — voliteľný API režim (--use-claude-api): každá fotka sa
                           pošle na Claude vision v DVOCH orientáciách (A + B=180°)
                           a AI vyberie správnu — jedna fotka sama nestačí, model
                           (aj lokálne OSD) oklamú naopak nalepené nálepky na
                           elektromeroch; navyše prečíta stav elektromera zo
                           sedemsegmentového LCD (lokálny Tesseract ho neprečíta,
                           testované aj so ssd/lets traineddata — samý šum)
    tesseract_check.py   — kontrola inštalácie Tesseractu (diagnose: ok/missing/no_deu)
    tesseract_install.py — automatická tichá inštalácia Tesseractu + deu.traineddata
                           (najnovší inštalátor sa hľadá cez GitHub API releasov
                           tesseract-ocr/tesseract aj UB-Mannheim/tesseract; nemčina
                           sa sťahuje zvlášť z tessdata_fast, lebo tichá inštalácia
                           /S jazykové balíky nepridáva)
  run.py                 — vstupný skript pre PyInstaller
  build_exe.bat
  requirements.txt
  README.md
  CLAUDE.md               — tento súbor
```

## Balenie a distribúcia (rovnaký princíp ako StrategyScribe)

1. **PyInstaller** zabalí appku do jedného `.exe` (`build_exe.bat`), spolu sa
   vypočíta aj SHA-256 kontrolný súčet.
2. **Distribúcia cez GitHub Releases**, repozitár pod **neutrálnou
   organizáciou** (nie pod osobným menom), rovnako ako pri StrategyScribe —
   aby v odkaze na stiahnutie nebolo vidieť, kto appku vytvoril/odkiaľ sa
   presne sťahuje zdrojový kód. Používateľ sťahuje iba hotový `.exe` zo
   sekcie Releases, nie priamo súbory repozitára.

## Pracovné pravidlá

1. Vždy sa opýtaj pred väčšou/nezvratnou zmenou (napr. založenie GitHub repa,
   push, vytvorenie Release).
2. Postupuj krok po kroku, over funkčnosť pred tým, než povieš "hotovo".
3. Vývoj je vždy lokálny (VS Code na PC) — žiadny server, žiadny deploy.
   Git/GitHub sa používa len ako záloha a na distribúciu hotového `.exe`.
4. Píš po slovensky, vysvetľuj jednoducho.

## Poznámky k presnosti OCR

Rozpoznanie smeru otočenia aj čítanie štítku závisí od kvality fotky
(ostrosť, odlesky, uhol). Pri neistej rotácii sa fotka aj tak uloží (najlepší
odhad) a označí v `log.txt` — treba ju skontrolovať ručne. Pri zlyhaní
extrakcie ID čísel na prvej fotke sa skúša aj na ďalších (max.
`MAX_LABEL_ATTEMPTS` v `main.py`).
