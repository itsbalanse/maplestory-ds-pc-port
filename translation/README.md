# MapleStory DS — English translation

All in-game text lives in `.GMM.JAPANESE` message tables inside `RESOURCE.NXARC`.
`tools/export_text.py` exports every **unique** Japanese string once into `strings/*.json`;
`tools/build_english.py` injects the English, word-wraps it to the real pixel widths, patches
the font spacing and writes `build/MapleStory DS (English).nds`.

## Workflow

1. Pick a `strings/<group>.json` file (stage files are `stage_AABBCC.json`, roughly story order).
2. Write a batch file `batches/NNN_<group>.json` mapping Japanese → English:
   `{"<jp exactly as in the file>": "<english>"}`. Keys must match the `jp` field byte-for-byte
   (copy them; they contain literal `[\n]` sequences, written `[\\n]` inside JSON).
3. `python tools/apply_tr.py "translation/batches/*.json"` merges batches into `strings/`.
4. `python tools/build_english.py` builds the ROM and writes `build/layout_report.txt`
   listing every string that overflows its box. Fix those by shortening the English.
5. Check in-game with the headless harness (`tools/dsharness/harness.exe rom script outdir`),
   see `work/*.txt` scripts for examples. Savestates are only valid for the build that made them.

Strings with `"dev": true` are developer memos (★…) that never appear in game; translate them
last or leave them.

## Markup (must be preserved exactly)

| Markup | Meaning |
|---|---|
| `[\n]` | hard line break |
| `\[name:A_PC\]` (also `S_PC`, `R_PC`, `M_PC`) | player's name |
| `<Name>` | green text (people) — the `<` `>` are not displayed |
| `{Place}` | blue text (places, items) |
| `「text」` | yellow text (key terms / objectives). Brackets are **not** displayed, so do not add English quotes inside unless wanted |
| `『text』` | red text (important warnings, techniques) |
| `[color:w/r/g/b/y]` | explicit colour change |
| `[A] [B] [X] [Y] [L] [R]` | DS button icons; `[>] [<] [^] [v]` D-pad icons |
| `\[` `\]` | literal square brackets |
| `[]` | a space |

Keep colour markup around the English equivalent of the same words.

## Layout rules

The renderer draws 1 px between letters and wraps per character at the box edge, which would
split English words. `build_english.py` therefore re-wraps any line that is too wide at word
boundaries. Lines that already fit are left untouched, so hand-placed breaks and leading spaces
(used for menu choices such as `[\n] Yes[\n] No`) survive.

* Dialogue boxes: **216 px wide, up to 4 lines** (3 is ideal). About 40–45 average English
  characters per line. If the report says `lines=5/4`, shorten the text.
* Keep the Japanese line structure for menus/choices (blank lines, leading spaces).
* Single-line labels (item/monster/map names, chapter titles) have tight widths, see
  `tools/textdb.py` `RULES`. Abbreviate if needed.
* The player's name is budgeted at 60 px.

## Style

* Use official Global MapleStory names wherever they exist (see `glossary.json`):
  ペリオン Perion, ヘネシス Henesys, エリニア Ellinia, カニングシティ Kerning City,
  リス港口 Lith Harbor, スリーピーウッド Sleepywood, エルナス El Nath, オルビス Orbis,
  ルディブリアム Ludibrium, メイプルアイランド Maple Island, ビクトリアアイランド Victoria Island,
  戦士 Warrior, 盗賊 Thief, 弓使い Bowman, 魔法使い Magician, メル mesos, ＨＰ/ＭＰ HP/MP.
* Natural, lively English that fits each character's voice; no translationese, no
  untranslated honorifics.
* Japanese `・・・` → `...`; full-width digits → ASCII digits; avoid curly quotes, em dashes
  and other characters outside printable ASCII (the font only has ASCII plus Japanese).
