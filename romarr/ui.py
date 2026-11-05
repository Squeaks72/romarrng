"""The web UI.

Deliberately shaped like Radarr, Sonarr and Lidarr rather than like something
new. Anyone running an *arr stack already knows where things live -- Library,
Wanted, Activity, Settings, System, in that order down a dark rail on the left
-- and an *arr for games that invented its own arrangement would make its users
learn a layout for no benefit.

Where the concepts differ, the difference is real rather than cosmetic:

  * a Quality Profile has no meaning for a cartridge dump. There is no bitrate;
    what actually distinguishes two dumps of the same game is region, revision
    and whether it is a hack or a beta. So Profiles here rank regions.
  * Movies/Series/Artists become Games, and the Calendar has no equivalent at
    all -- a ROM has no air date -- so it is not in the nav rather than being
    present and permanently empty.

One file, no build step, no framework. This runs in a 512MB container beside a
download client and a database.
"""

import html
import json
from pathlib import Path

UI_CATALOG = json.loads(Path(__file__).with_name("ui-labels.json").read_text(encoding="utf-8"))
if UI_CATALOG.get("schemaVersion") != 3:
    raise ValueError("ROMarr UI translation catalog must use stable-key schema v3")
UI_CATALOG_JSON = (json.dumps(UI_CATALOG, ensure_ascii=False, separators=(",", ":"))
                   .replace("<", "\\u003c").replace(">", "\\u003e")
                   .replace("&", "\\u0026").replace("\u2028", "\\u2028")
                   .replace("\u2029", "\\u2029"))
UI_MESSAGES = UI_CATALOG["messages"]
UI_SOURCE_TO_ID = {message["source"]: key for key, message in UI_MESSAGES.items()}


def _ui_key(source: str) -> str:
    return UI_SOURCE_TO_ID.get(source, source)


UI_LOCALE_OPTIONS = UI_CATALOG["locales"]
UI_AVAILABLE_LOCALES = UI_CATALOG["availableLocales"]
# Kept as a source-keyed compatibility view for Python callers. Regional
# choices expose their actual inherited text so older callers see the same
# complete coverage as the browser runtime. The browser embeds stable IDs.
def _expanded_translations(values: dict[str, object]) -> dict[str, object]:
    expanded = {locale: value for locale, value in values.items() if locale != "en"}
    for locale in UI_AVAILABLE_LOCALES:
        current = locale
        seen = set()
        while current not in expanded and current not in seen:
            seen.add(current)
            current = UI_CATALOG.get("regionalParents", {}).get(current, "")
            if not current:
                break
        if current in expanded:
            expanded[locale] = expanded[current]
    return expanded


UI_LABELS = {message["source"]: _expanded_translations(message["translations"])
             for message in UI_MESSAGES.values()}
I18N_RUNTIME = Path(__file__).with_name("i18n_runtime.js").read_text(encoding="utf-8")

CSS = """
*{box-sizing:border-box;margin:0;padding:0}

/* ---- the theme -----------------------------------------------------------
   One accent, three modes. Every colour below is a token because a mode has to
   be nothing but a block of overrides -- a literal left anywhere in the sheet
   is a patch that stays dark when the operator asks for light, and that is how
   half-themed apps happen.

   Only three tokens are written from script: --accent, and the two that cannot
   be derived in CSS. A colour the user picked has no guaranteed contrast, and
   deciding whether it needs black or white on top of it, or how far to walk it
   before it is legible as link text, is luminance maths CSS has no way to do.
   Everything else here is derived with color-mix so a new accent costs one
   custom-property write rather than a stylesheet. */
:root{
  color-scheme:dark;
  --bg:#12141a; --surface:#1a1d25; --surface-2:#212734; --surface-3:#2b3240;
  --rail:#0d0f14; --rail-2:#1a1f2a;
  --line:#282e3a; --line-soft:#1f2530;
  --fg:#e8eaf0; --fg-2:#b4bbca; --dim:#9aa1b0;
  --ok:#3ecf6d; --warn:#f0a92c; --bad:#ff7771; --info:#5aa2e8;
  --ok-ink:#08210d; --warn-ink:#2a1c05; --bad-ink:#2a0b0b; --info-ink:#06131f;
  --shadow-1:0 1px 2px rgba(0,0,0,.45);
  --shadow-2:0 2px 6px rgba(0,0,0,.35),0 14px 30px -16px rgba(0,0,0,.8);
  --shadow-3:0 30px 70px -24px rgba(0,0,0,.85);
  --edge:inset 0 1px 0 rgba(255,255,255,.045);
  --art:#0b0d11;
}
:root[data-theme="light"]{
  color-scheme:light;
  --bg:#eef1f6; --surface:#fff; --surface-2:#f5f7fb; --surface-3:#e7ebf2;
  --rail:#fff; --rail-2:#eef1f7;
  --line:#dce2ec; --line-soft:#eaeef5;
  --fg:#161b24; --fg-2:#404859; --dim:#626a7a;
  --ok:#08783a; --warn:#765000; --bad:#b42318; --info:#255d99;
  --ok-ink:#fff; --warn-ink:#fff; --bad-ink:#fff; --info-ink:#fff;
  --shadow-1:0 1px 2px rgba(16,24,40,.06);
  --shadow-2:0 1px 3px rgba(16,24,40,.09),0 14px 30px -18px rgba(16,24,40,.32);
  --shadow-3:0 34px 70px -26px rgba(16,24,40,.38);
  --edge:inset 0 1px 0 rgba(255,255,255,.9);
  --art:#e3e8f0;
}
/* Easy on the eyes: warm paper and little blue, with the same readable text
   contrast as the other modes. Surfaces stay dimmer than light mode. */
:root[data-theme="sepia"]{
  color-scheme:light;
  --bg:#e6dbcb; --surface:#f3ebde; --surface-2:#ece2d2; --surface-3:#dfd2bd;
  --rail:#e0d4c0; --rail-2:#d5c6ae;
  --line:#d2c3ab; --line-soft:#ded0ba;
  --fg:#3d362c; --fg-2:#5e5446; --dim:#574c3c;
  --ok:#2c5c34; --warn:#6b4a0c; --bad:#88342c; --info:#2b5169;
  --ok-ink:#fff; --warn-ink:#fff; --bad-ink:#fff; --info-ink:#fff;
  --shadow-1:0 1px 2px rgba(74,58,36,.09);
  --shadow-2:0 1px 3px rgba(74,58,36,.10),0 12px 26px -16px rgba(74,58,36,.30);
  --shadow-3:0 28px 60px -24px rgba(74,58,36,.36);
  --edge:inset 0 1px 0 rgba(255,255,255,.5);
  --art:#d9cbb4;
}

/* Derived once, here, so no rule below ever names a colour twice. Declared
   after the modes on purpose: these read whatever the mode set, lazily. */
:root{
  --accent:#f2a33c; --accent-text:#f2a33c; --accent-ink:#141414;
  --accent-soft:color-mix(in srgb,var(--accent) 15%,transparent);
  --accent-softer:color-mix(in srgb,var(--accent) 8%,transparent);
  --accent-line:color-mix(in srgb,var(--accent) 42%,transparent);
  --accent-hi:color-mix(in srgb,var(--accent) 86%,#fff);
  --ring:0 0 0 3px color-mix(in srgb,var(--accent) 26%,transparent);
  --panel:var(--surface);
  --r-sm:7px; --r-md:11px; --r-lg:15px; --r-pill:999px;
  --t:.15s cubic-bezier(.4,0,.2,1);
}

html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--fg);
  font:14px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    "Noto Sans Arabic","Noto Sans CJK SC","Noto Sans CJK TC","Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
a{color:var(--accent-text);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:2px}
::selection{background:var(--accent-soft);color:var(--fg)}
:focus-visible{outline:2px solid var(--accent-text);outline-offset:2px}
*{scrollbar-width:thin;scrollbar-color:var(--surface-3) transparent}
::-webkit-scrollbar{width:11px;height:11px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--surface-3);border-radius:var(--r-pill);
  border:3px solid transparent;background-clip:padding-box}
::-webkit-scrollbar-thumb:hover{background:var(--dim);background-clip:padding-box}

/* ---- rail ---- */
#rail{position:fixed;inset-inline-start:0;top:0;bottom:0;width:222px;background:var(--rail);
  border-inline-end:1px solid var(--line);z-index:20;
  display:flex;flex-direction:column;overflow:hidden}
/* No gap: the brand is one word split into two nodes so that "arr" can
   carry the accent colour, and a flex gap renders it as "ROM arr". */
#brand{display:flex;align-items:center;gap:0;padding:17px 18px 16px;
  font-size:20px;font-weight:700;letter-spacing:-.025em;
  border-bottom:1px solid var(--line-soft);flex:none;overflow:hidden;
  white-space:nowrap}
#brand span{color:var(--accent-text)}
#navwrap{flex:1;overflow-y:auto;padding:6px 0 10px}
.navgroup{padding:8px 0 2px}
.navhead{padding:6px 20px;font-size:10.5px;font-weight:600;
  text-transform:uppercase;letter-spacing:.1em;color:var(--dim)}
.nav{display:flex;align-items:center;gap:10px;margin:1px 10px;
  width:calc(100% - 20px);min-height:40px;padding:8px 11px;
  color:var(--fg-2);background:transparent;border:0;text-align:start;
  font-family:inherit;cursor:pointer;font-size:13.5px;line-height:1.4;
  text-decoration:none;border-radius:var(--r-sm);position:relative;
  transition:background var(--t),color var(--t)}
.nav:hover{background:var(--rail-2);color:var(--fg);text-decoration:none}
.nav.on{background:var(--accent-soft);color:var(--accent-text);font-weight:600}
/* The active marker is a rounded bar rather than *arr's flat 3px border, and
   it lives on a pseudo-element so the row can keep its own radius. */
.nav.on::before{content:"";position:absolute;inset-inline-start:-6px;top:7px;bottom:7px;
  width:3px;border-radius:var(--r-pill);background:var(--accent)}
.nav .ct{margin-inline-start:auto;font-size:10.5px;font-weight:600;
  background:var(--surface-3);color:var(--dim);padding:1px 7px;
  border-radius:var(--r-pill)}
/* A zero is written as "" rather than "0", which left an empty pill sitting
   in the rail claiming to be a number. */
.nav .ct:empty{display:none}
.nav.on .ct{background:var(--accent);color:var(--accent-ink)}

/* ---- the theme control ----
   In the rail rather than under Settings: it is a comfort control, and a
   comfort control you have to navigate to is one you change once and then
   live with. */
#railfoot{flex:none;border-top:1px solid var(--line-soft);padding:12px 12px 14px;
  background:var(--rail)}
.thm-lbl{font-size:10.5px;font-weight:600;text-transform:uppercase;
  letter-spacing:.1em;color:var(--dim);margin:0 0 8px 2px}
.thm-modes{display:flex;gap:3px;background:var(--surface-2);padding:3px;
  border-radius:var(--r-sm);margin-bottom:10px}
/* Longhand, not the `font` shorthand: `inherit` is not a family name, so
   `font:600 11px/1.3 inherit` is invalid and the browser drops the whole
   declaration -- a button silently keeps the UA's own font instead. */
.thm{flex:1;padding:5px 4px;font-family:inherit;font-size:11px;
  font-weight:600;line-height:1.3;color:var(--dim);
  background:transparent;border:0;border-radius:5px;cursor:pointer;
  transition:background var(--t),color var(--t)}
.thm:hover{color:var(--fg)}
.thm.on{background:var(--surface);color:var(--fg);box-shadow:var(--shadow-1)}
.thm-accents{display:flex;flex-wrap:wrap;gap:6px}
.sw{width:24px;height:24px;padding:0;border-radius:var(--r-pill);
  border:1px solid rgba(128,128,128,.35);background:var(--sw,var(--accent));
  cursor:pointer;position:relative;transition:transform var(--t)}
.sw:hover{transform:scale(1.14)}
.sw.on{box-shadow:0 0 0 2px var(--rail),0 0 0 4px var(--accent-text)}
.sw.pick{display:grid;place-items:center;overflow:hidden;
  background:conic-gradient(#f2635f,#f2a33c,#7bd88f,#2dd4bf,#5aa2f0,#c084fc,#f2635f)}
.sw.pick input{position:absolute;inset:-4px;width:calc(100% + 8px);
  height:calc(100% + 8px);opacity:0;cursor:pointer;border:0;padding:0}

/* ---- main ---- */
#main-content{margin-inline-start:222px;min-height:100vh}
#top{position:sticky;top:0;display:flex;align-items:center;gap:14px;
  padding:13px 26px;z-index:10;border-bottom:1px solid var(--line);
  background:color-mix(in srgb,var(--bg) 80%,transparent);
  -webkit-backdrop-filter:saturate(1.6) blur(12px);
  backdrop-filter:saturate(1.6) blur(12px)}
#top h1{font-size:17px;font-weight:650;letter-spacing:-.02em;white-space:nowrap}
#top input{flex:1;max-width:420px;padding:8px 13px;background:var(--surface);
  color:var(--fg);border:1px solid var(--line);border-radius:var(--r-sm);
  outline:none;transition:border-color var(--t),box-shadow var(--t)}
#top input:focus{border-color:var(--accent-line);box-shadow:var(--ring)}
.page{padding:24px 26px 48px;max-width:1600px}
.sr-only{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.skip-link{position:fixed;inset-block-start:10px;inset-inline-start:10px;
  z-index:100;transform:translateY(-160%);padding:9px 13px;
  background:var(--surface);color:var(--fg);border:2px solid var(--accent-text);
  border-radius:var(--r-sm);font-weight:650;box-shadow:var(--shadow-2)}
.skip-link:focus{transform:translateY(0)}
.nav-toggle{display:none;align-items:center;justify-content:center;min-height:40px;
  padding:7px 12px;border:1px solid var(--line);border-radius:var(--r-sm);
  background:var(--surface);color:var(--fg);font-family:inherit;
  font-size:13px;font-weight:600;line-height:1.3;cursor:pointer}
.nav-backdrop{display:none;position:fixed;inset:0;z-index:19;padding:0;border:0;
  background:rgba(0,0,0,.56);cursor:pointer}
.nav-backdrop[hidden]{display:none}
.mapping-field{display:flex;flex-direction:column;gap:5px;min-width:0;margin:0;
  color:var(--fg-2);font-size:12px;font-weight:600}
.settings-group{min-width:0;padding:0;border:0;margin:8px 0 14px}
.settings-group legend{margin-bottom:5px;color:var(--fg);font-size:13px;font-weight:650}
.mapping-row{display:grid;gap:8px;margin:8px 0;align-items:end}
.mapping-row.platform-folder{grid-template-columns:minmax(140px,.8fr) minmax(190px,1fr) auto}
.mapping-row.path-map{grid-template-columns:minmax(140px,1fr) minmax(160px,1fr) minmax(160px,1fr) auto}
.mapping-row button{min-height:38px}

/* ---- plugin catalogue ---------------------------------------------------
   A card grid rather than a table. A plugin is a thing you decide to trust,
   and that decision needs the description and the permissions in view at the
   same time -- a table row makes you read across five columns to assemble
   what one card says at a glance. */
.cat-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
  padding:0 0 14px;border-bottom:1px solid var(--line-soft);margin-bottom:16px}
.cat-bar input{flex:1;min-width:220px;padding:9px 13px;background:var(--bg);
  color:var(--fg);border:1px solid var(--line);border-radius:var(--r-sm);
  outline:none;transition:border-color var(--t),box-shadow var(--t)}
.cat-bar input:focus{border-color:var(--accent-line);box-shadow:var(--ring)}
.chip{padding:5px 12px;border-radius:var(--r-pill);border:1px solid var(--line);
  background:var(--bg);color:var(--dim);cursor:pointer;font-family:inherit;
  font-size:12px;line-height:1.35;white-space:nowrap;transition:all var(--t)}
.chip:hover{border-color:var(--accent-line);color:var(--fg)}
.chip.on{background:var(--accent);border-color:var(--accent);
  color:var(--accent-ink);font-weight:600}
.chip .n{color:inherit;margin-inline-start:5px}

/* The scroll the catalogue needs once it is more than a screenful. Bounded
   so the page header and the add-your-own panel stay put while it moves. */
.cat-scroll{max-height:calc(100vh - 340px);min-height:220px;overflow-y:auto;
  padding-inline-end:6px;margin-inline-end:-6px}

.pgrid{display:grid;gap:12px;
  grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}
.pcard{background:var(--bg);border:1px solid var(--line);
  border-radius:var(--r-md);padding:15px 16px;display:flex;
  flex-direction:column;gap:9px;
  transition:border-color var(--t),transform var(--t),box-shadow var(--t)}
.pcard:hover{border-color:var(--accent-line);transform:translateY(-2px);
  box-shadow:var(--shadow-2)}
.pcard.installed{border-inline-start:3px solid var(--ok)}
.pcard h4{font-size:14px;font-weight:650;display:flex;align-items:center;
  gap:8px;margin:0;letter-spacing:-.01em}
.pcard .by{color:var(--dim);font-size:11px;font-weight:400}
.pcard .desc{color:var(--fg-2);font-size:12.5px;line-height:1.5;flex:1}
.pcard .meta{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.pcard .foot{display:flex;gap:8px;align-items:center;
  border-top:1px solid var(--line-soft);padding-top:10px;margin-top:2px}
.pcard .net{color:var(--dim);font-size:11px;margin-inline-start:auto;text-align:end}
.dot-ok{width:7px;height:7px;border-radius:50%;background:var(--ok);
  display:inline-block;flex:none}
.dot-off{width:7px;height:7px;border-radius:50%;background:var(--surface-3);
  display:inline-block;flex:none}

.panels{display:grid;gap:14px;grid-template-columns:1fr 1fr;margin-top:16px}
@media(max-width:900px){.panels{grid-template-columns:1fr}}
/* A callout, not a card: bordered on one edge so it reads as an aside even
   when it is the third one on the page. */
.panel-note{background:color-mix(in srgb,var(--info) 11%,transparent);
  border:1px solid color-mix(in srgb,var(--info) 32%,transparent);
  border-inline-start:3px solid var(--info);border-radius:var(--r-sm);
  padding:11px 13px;color:var(--fg-2);font-size:12px;line-height:1.55;
  margin-top:10px}
.panel-warn{background:color-mix(in srgb,var(--bad) 11%,transparent);
  border-color:color-mix(in srgb,var(--bad) 32%,transparent);
  border-inline-start-color:var(--bad)}
/* Used by Friends and Discover for an inline block of prose. It had no rule
   at all, so it rendered as loose text in the middle of a card. */
.panel{background:var(--bg);border:1px solid var(--line-soft);
  border-radius:var(--r-md);padding:12px 14px;color:var(--fg-2);
  font-size:12.5px;line-height:1.6}
.field{display:flex;flex-direction:column;gap:5px;margin-bottom:10px}
.field label{font-size:10.5px;font-weight:600;text-transform:uppercase;
  letter-spacing:.07em;color:var(--dim)}
.field input,.field textarea{padding:9px 12px;background:var(--bg);
  color:var(--fg);border:1px solid var(--line);border-radius:var(--r-sm);
  outline:none;font-family:inherit;font-size:13px;line-height:1.5;
  transition:border-color var(--t),box-shadow var(--t)}
.field input:focus,.field textarea:focus{border-color:var(--accent-line);
  box-shadow:var(--ring)}
.field textarea{resize:vertical;min-height:58px}
.field input:disabled{color:var(--dim);background:var(--surface-2);
  cursor:not-allowed}
.empty-cat{text-align:center;padding:48px 20px;color:var(--dim)}
.empty-cat b{display:block;color:var(--fg);margin-bottom:6px;font-size:15px}
.hide{display:none !important}

/* ---- shared ---- */
.btn{padding:8px 16px;background:var(--accent);color:var(--accent-ink);
  font-weight:600;border:0;border-radius:var(--r-sm);cursor:pointer;
  font-size:13px;line-height:1.35;
  transition:filter var(--t),box-shadow var(--t),transform var(--t)}
.btn:hover{filter:brightness(1.07);box-shadow:var(--shadow-1)}
.btn:active{transform:translateY(1px)}
.btn:disabled{opacity:.55;cursor:default;filter:none;transform:none}
.btn.ghost{background:var(--surface);color:var(--fg);
  border:1px solid var(--line);box-shadow:var(--edge)}
.btn.ghost:hover{background:var(--surface-2);border-color:var(--accent-line);
  filter:none}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.card{background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-lg);padding:18px 20px;margin-bottom:16px;
  box-shadow:var(--shadow-1),var(--edge)}
/* The accent tick. It is the one place the operator's chosen colour appears
   on every page, which is what makes the choice feel like it took. */
.card h3{font-size:14.5px;font-weight:650;letter-spacing:-.01em;
  margin-bottom:13px;color:var(--fg);display:flex;align-items:center;gap:9px}
.card h3::before{content:"";flex:none;width:3px;height:15px;border-radius:2px;
  background:var(--accent)}
.card p.help{color:var(--dim);font-size:12.5px;margin:-7px 0 13px}
.help{color:var(--dim);font-size:12.5px;line-height:1.6}
table{width:100%;border-collapse:collapse}
th,td{text-align:start;padding:10px 12px;border-bottom:1px solid var(--line-soft);
  vertical-align:top;font-size:13px}
th{color:var(--dim);font-size:10.5px;font-weight:600;text-transform:uppercase;
  letter-spacing:.07em;background:var(--surface-2)}
thead th:first-child{border-start-start-radius:var(--r-sm)}
thead th:last-child{border-start-end-radius:var(--r-sm)}
tbody tr{transition:background var(--t)}
tbody tr:hover td{background:var(--surface-2)}
tbody tr:last-child td{border-bottom:0}
/* Queue and History put a table straight on the page with no card around it,
   so the table has to carry its own chrome there. */
#page>table{background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-lg);box-shadow:var(--shadow-1),var(--edge);
  overflow:hidden}
.mini{padding:4px 12px;font-size:12px;border:1px solid var(--line);
  background:var(--surface);color:var(--fg);border-radius:var(--r-sm);
  cursor:pointer;margin-inline-start:6px;transition:all var(--t)}
.mini:hover{border-color:var(--accent-line)}
.mini.accent{background:var(--accent);color:var(--accent-ink);
  border-color:var(--accent)}
.okt{color:var(--ok);font-size:12px}
.pill{font-size:11px;padding:2px 10px;border-radius:var(--r-pill);
  border:1px solid var(--line);background:var(--surface-2);color:var(--fg-2);
  display:inline-block;white-space:nowrap;font-weight:500}
.pill.grabbed{color:var(--info-ink);border-color:var(--info);background:var(--info)}
.pill.imported{color:var(--ok-ink);border-color:var(--ok);background:var(--ok)}
.pill.failed{color:var(--bad-ink);border-color:var(--bad);background:var(--bad)}
.pill.queued{color:var(--warn-ink);border-color:var(--warn);background:var(--warn)}
/* An empty page is a state, not an accident. Given a dashed enclosure it
   reads as "there is a place for things here and it is empty" rather than as
   a page that failed to load. */
.empty{color:var(--dim);padding:40px 20px;text-align:center;font-size:13px;
  background:var(--surface-2);border:1px dashed var(--line);
  border-radius:var(--r-lg)}
label{display:block;font-size:12.5px;color:var(--dim);margin-bottom:5px}
/* `input:not([type])` is in here because most of this UI writes a bare
   <input>, and an attribute selector does not match an attribute that is not
   written -- which is how half the fields kept the browser default box. */
input:not([type]),input[type=text],input[type=number],input[type=password],
input[type=search],select,textarea{
  width:100%;padding:9px 12px;background:var(--bg);color:var(--fg);
  border:1px solid var(--line);border-radius:var(--r-sm);outline:none;
  font-size:13px;font-family:inherit;
  transition:border-color var(--t),box-shadow var(--t)}
input:focus,select:focus,textarea:focus{border-color:var(--accent-line);
  box-shadow:var(--ring)}
.field{margin-bottom:14px;max-width:420px}
.check{display:flex;align-items:center;gap:9px;margin-bottom:11px;
  color:var(--fg);font-size:13px;cursor:pointer}
.check input{width:16px;height:16px;accent-color:var(--accent);flex:none}
/* ---- Add New results and the game page ---- */
.rcgrid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(330px,1fr))}
.rc{display:flex;gap:12px;padding:10px;background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-md);cursor:pointer;transition:border-color var(--t)}
.rc:hover{border-color:var(--accent-line)}
.rc-art,.gh-art{flex:none;background:var(--art) center/cover no-repeat;border-radius:var(--r-sm)}
.rc-art{width:72px;height:96px}
.rc-body{min-width:0;flex:1}
.rc-t{font-weight:650;font-size:14px}
.rc-y{font-weight:400;color:var(--dim);font-size:12.5px}
.rc-g{color:var(--dim);font-size:11.5px;margin:1px 0 4px}
.rc-s{color:var(--fg-2);font-size:12px;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden;margin-bottom:6px}
.rc-p{display:flex;flex-wrap:wrap;gap:5px}
.rc-opt{font:inherit;font-size:11.5px;padding:3px 8px;border-radius:var(--r-pill);cursor:pointer;
  background:var(--bg);color:var(--fg);border:1px solid var(--line)}
.rc-opt:hover{border-color:var(--accent-line)}
.sb{display:inline-block;font-size:10.5px;font-weight:650;padding:1px 7px;border-radius:var(--r-pill);
  margin-inline-start:4px;background:var(--surface-3);color:var(--fg-2)}
.sb-library{background:color-mix(in srgb,var(--ok) 20%,transparent);color:var(--ok)}
.sb-monitored,.sb-downloading{background:var(--accent-soft);color:var(--accent-text)}
.sb-none{display:none}
.gh{display:flex;gap:20px;flex-wrap:wrap}
.gh-art{width:190px;height:260px;max-width:100%}
.gh-main{flex:1;min-width:260px}
.gh-main h2{font-size:22px;font-weight:650;letter-spacing:-.02em;margin:0 0 2px}
.gh-sub{color:var(--dim);margin-bottom:12px}
.gh-act{display:flex;flex-wrap:wrap;gap:8px}
.gh-facts{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:14px 0 0;font-size:13px}
.gh-facts dt{color:var(--dim)}
.gh-facts dd{margin:0}
.tablewrap{overflow-x:auto}
.swu-dlc{margin:6px 0 0;padding-inline-start:18px;font-size:13px}
.swu-dlc li{margin:3px 0}
.swu-dlc code{color:var(--dim);font-size:11.5px;margin:0 6px}
/* Searchable single-choice picker: stands in for a <select> when the list is
   long (49 platforms). The hidden input keeps the id and .value, so code that
   reads $('#id').value is unchanged. */
.pp{position:relative;display:inline-block;min-width:230px;max-width:100%}
.pp-btn{display:flex;align-items:center;justify-content:space-between;gap:10px;
  width:100%;padding:8px 12px;background:var(--bg);color:var(--fg);
  border:1px solid var(--line);border-radius:var(--r-sm);font:inherit;font-size:13px;
  cursor:pointer;text-align:start;transition:border-color var(--t),box-shadow var(--t)}
.pp-btn:hover{border-color:var(--accent-line)}
.pp.open .pp-btn,.pp-btn:focus-visible{border-color:var(--accent-line);box-shadow:var(--ring);outline:none}
.pp-btn::after{content:"";flex:none;width:7px;height:7px;margin-inline-start:4px;
  border-inline-end:2px solid var(--dim);border-bottom:2px solid var(--dim);
  transform:rotate(45deg) translateY(-2px)}
.pp-cur{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pp-cur i{font-style:normal;color:var(--dim);margin-inline-start:6px;font-size:12px}
.pp-panel{position:absolute;z-index:40;inset-inline-start:0;top:calc(100% + 6px);
  width:max(100%,340px);max-width:calc(100vw - 32px);background:var(--surface);
  border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--shadow-3);
  padding:8px}
.pp-panel[hidden]{display:none}
.pp-q{margin-bottom:6px}
.pp-list{list-style:none;margin:0;padding:0;max-height:min(320px,50vh);overflow-y:auto}
.pp-opt{display:flex;justify-content:space-between;gap:12px;align-items:baseline;
  padding:7px 10px;border-radius:var(--r-sm);cursor:pointer;font-size:13px}
.pp-opt small{color:var(--dim);font-size:11.5px;white-space:nowrap}
.pp-opt.act{background:var(--accent-soft)}
.pp-opt[aria-selected=true]{font-weight:650}
.pp-none{padding:10px;color:var(--dim);font-size:12.5px}
.libstats{display:flex;flex-wrap:wrap;gap:4px 18px;align-items:baseline;margin:0 0 10px}
.libstats b{font-size:18px;font-weight:650;letter-spacing:-.02em;margin-inline-end:5px}
.libstats span{font-size:12.5px;color:var(--dim)}
.libstats details{flex-basis:100%;font-size:12.5px;color:var(--dim)}
.libstats summary{cursor:pointer;width:max-content}
.lfrow{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;align-items:center}
.lfrow select{width:auto;max-width:100%;padding:6px 10px;font-size:12.5px}
#page-title:focus,#main-content:focus{outline:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));
  gap:16px}
.tile{background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-md);overflow:hidden;box-shadow:var(--shadow-1);
  transition:transform var(--t),box-shadow var(--t),border-color var(--t)}
.tile:hover{transform:translateY(-3px);box-shadow:var(--shadow-2);
  border-color:var(--accent-line)}
/* background-color only: the cover comes in as an inline background-image and
   a shorthand here would be overridden by it, taking the placeholder with it. */
.tile .art{aspect-ratio:3/4;background-color:var(--art);background-position:center;
  background-size:cover;background-repeat:no-repeat;display:block}
.tile .nm{padding:10px 10px 2px;font-size:12.5px;line-height:1.35;
  font-weight:500}
.tile .pf{padding:2px 10px 10px;font-size:11px;color:var(--dim)}
/* A month, seven columns wide. Squares carry a count, so an empty month is
   visibly empty rather than indistinguishable from a month that failed to
   load -- the failure mode the old Calendar page had permanently. */
.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:5px}
.cal .dow{font-size:10.5px;color:var(--dim);text-align:center;padding:2px 0;
  text-transform:uppercase;letter-spacing:.06em}
.cal button{background:var(--bg);border:1px solid var(--line-soft);
  border-radius:var(--r-sm);padding:6px 4px;min-height:52px;cursor:pointer;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:2px;color:var(--fg-2);font-size:12px;transition:border-color var(--t)}
.cal button:hover{border-color:var(--accent-line)}
.cal button.on{border-color:var(--accent);background:var(--surface);
  color:var(--fg)}
.cal button.none{opacity:.42;cursor:default}
.cal button.pad{background:none;border:none;cursor:default;min-height:0}
.cal button b{font-size:11px;font-weight:650;color:var(--accent)}
/* Stat blocks, as tiles rather than a row of loose numbers. */
.st{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
  gap:10px}
.st div{min-width:0;background:var(--bg);border:1px solid var(--line-soft);
  border-radius:var(--r-md);padding:12px 14px}
.st b{display:block;font-size:22px;font-weight:650;letter-spacing:-.02em;
  line-height:1.2}
.st span{font-size:11.5px;color:var(--dim)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;
  margin-inline-end:7px;background:var(--surface-3)}
.dot.up{background:var(--ok);box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 22%,transparent)}
.dot.down{background:var(--bad);box-shadow:0 0 0 3px color-mix(in srgb,var(--bad) 22%,transparent)}
.dot.warn{background:var(--warn);box-shadow:0 0 0 3px color-mix(in srgb,var(--warn) 22%,transparent)}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);
  margin-bottom:18px}
.tab{padding:9px 15px;cursor:pointer;color:var(--dim);font-size:13px;
  font-weight:500;border-bottom:2px solid transparent;margin-bottom:-1px;
  border-radius:var(--r-sm) var(--r-sm) 0 0;transition:all var(--t)}
.tab:hover{color:var(--fg);background:var(--surface-2)}
.tab.on{color:var(--accent-text);border-bottom-color:var(--accent)}
.modal{position:fixed;inset:0;background:color-mix(in srgb,#000 55%,transparent);
  -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);z-index:60;
  display:flex;align-items:flex-start;justify-content:center;
  padding:60px 20px;overflow-y:auto;animation:fade .16s ease}
.modal .box{background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-lg);width:100%;max-width:520px;padding:22px 24px;
  box-shadow:var(--shadow-3);animation:rise .2s cubic-bezier(.2,.8,.3,1)}
.modal h3{font-size:16px;font-weight:650;letter-spacing:-.01em;margin-bottom:4px}
.modal .sub{color:var(--dim);font-size:12.5px;margin-bottom:18px}
.modal .foot{display:flex;gap:8px;margin-top:20px;align-items:center;
  flex-wrap:wrap}
.modal .foot .sp{margin-inline-start:auto}
@keyframes fade{from{opacity:0}}
@keyframes rise{from{opacity:0;transform:translateY(10px) scale(.985)}}
.btn.danger{background:transparent;color:var(--bad);
  border:1px solid color-mix(in srgb,var(--bad) 50%,transparent)}
.btn.danger:hover{background:color-mix(in srgb,var(--bad) 12%,transparent);
  filter:none}
.pick{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pick button{padding:14px;background:var(--bg);border:1px solid var(--line);
  color:var(--fg);border-radius:var(--r-md);cursor:pointer;text-align:start;
  font-family:inherit;font-size:13px;font-weight:600;line-height:1.4;
  transition:all var(--t)}
.pick button:hover{border-color:var(--accent-line);background:var(--surface-2);
  transform:translateY(-1px)}
.pick small{display:block;color:var(--dim);font-size:11px;margin-top:3px;
  font-weight:400}
.rowact{display:flex;gap:6px;justify-content:flex-end}
.rowact button{padding:4px 11px;font-size:12px;background:transparent;
  color:var(--dim);border:1px solid var(--line);border-radius:var(--r-sm);
  cursor:pointer;transition:all var(--t)}
.rowact button:hover{color:var(--accent-text);border-color:var(--accent-line);
  background:var(--accent-softer)}
.testline{font-size:12.5px;margin-top:10px}
.testline.ok{color:var(--ok)}.testline.bad{color:var(--bad)}
.toast{position:fixed;inset-inline-end:22px;bottom:22px;background:var(--surface);
  border:1px solid var(--line);border-inline-start:3px solid var(--accent);
  border-radius:var(--r-md);padding:13px 17px;max-width:380px;z-index:50;
  font-size:13px;color:var(--fg);box-shadow:var(--shadow-2);
  animation:toastin .22s cubic-bezier(.2,.8,.3,1)}
@keyframes toastin{from{opacity:0;transform:translateY(10px)}}
details summary{list-style:none}
details summary::-webkit-details-marker{display:none}
details summary::before{content:"\\25B8 ";color:var(--accent-text)}
details[open] summary::before{content:"\\25BE "}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.92em;background:var(--surface-2);padding:1px 5px;
  border-radius:4px;color:var(--fg-2)}

/* Narrow, not collapsed. Every nav entry here is a word -- there is no icon
   set to fall back on -- so the old 56px rail hid the labels and left a
   column of blank clickable boxes. It gives up width instead. */
@media(max-width:820px){
  #rail{width:168px}
  #main-content{margin-inline-start:168px}
  #brand{font-size:17px;padding:14px 13px 13px}
  .navhead{padding:5px 14px}
  .nav{width:calc(100% - 14px);padding:7px 9px;margin:1px 7px;font-size:13px;gap:6px}
  .nav.on::before{inset-inline-start:-5px}
  #top{padding:11px 14px}
  .page{padding:16px 14px 40px}
  #railfoot{padding:10px 9px 12px}
  .thm{font-size:10px;padding:5px 2px}
  .sw{width:24px;height:24px}
  .grid{grid-template-columns:repeat(auto-fill,minmax(126px,1fr));gap:12px}
  .pgrid{grid-template-columns:1fr}
  .panels{grid-template-columns:1fr}
}
@media(max-width:540px){
  #rail{width:138px}
  #main-content{margin-inline-start:138px}
  #brand{font-size:15px;padding:13px 10px 12px}
  .nav{width:calc(100% - 10px);padding:7px 8px;margin:1px 5px;font-size:12.5px}
  .thm-modes{flex-direction:column;gap:2px}
  .thm-accents{justify-content:center;gap:5px}
  .page{padding:14px 12px 36px}
  .card{padding:15px 14px}
  th,td{padding:8px 8px}
}
@media(max-width:680px){
  #rail{width:min(282px,calc(100vw - 48px));transform:translateX(-105%);
    transition:transform var(--t);box-shadow:var(--shadow-3)}
  #rail.mobile-open{transform:translateX(0)}
  #main-content{margin-inline-start:0}
  .nav-toggle{display:inline-flex}
  #nav-backdrop:not([hidden]){display:block}
  #top{flex-wrap:wrap;gap:8px;padding:10px 12px}
  #top h1{flex:1;white-space:normal;font-size:16px}
  #top input{flex:1 1 100%;width:100%;max-width:none}
  .page{padding:16px 12px 36px}
  .mapping-row,.mapping-row.platform-folder,.mapping-row.path-map{
    grid-template-columns:minmax(0,1fr)}
  [dir=rtl] #rail{transform:translateX(105%)}
  [dir=rtl] #rail.mobile-open{transform:translateX(0)}
}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{transition:none !important;animation:none !important}
}
"""


# The accents offered as one click. Stated once, in Python, so the swatch row
# and the boot script's fallback cannot disagree about what "Amber" is.
ACCENTS = [
    ("#f2a33c", "Amber"),
    ("#f2635f", "Coral"),
    ("#c084fc", "Violet"),
    ("#5aa2f0", "Azure"),
    ("#2dd4bf", "Teal"),
    ("#7bd88f", "Fern"),
]

# Runs in <head>, before anything paints. Reading the stored choice from the
# body script instead would repaint the whole shell in front of the operator on
# every single load -- the white flash every themed app gets wrong once.
#
# The luminance maths is here rather than in CSS because CSS cannot do it. An
# accent the user picked has no guaranteed contrast against anything: navy on
# the dark mode is unreadable as link text, and white-on-yellow is unreadable
# as button text. So two colours are derived from the one that was picked --
# --accent-text, walked along its own lightness until it clears 4.5:1 against
# whatever the mode's background turned out to be, and --accent-ink, whichever
# of near-black or white sits better on the accent itself. The mode background
# is read back out of the cascade rather than restated here, because a copy of
# it in this file is a copy that drifts the first time a mode is retuned.
THEME_BOOT = r"""
(function(){
  var MODES=['dark','light','sepia'], KEY='romarr.theme', AKEY='romarr.accent',
      FALLBACK='ACCENT_FALLBACK', root=document.documentElement;

  function store(k,v){ try{ localStorage.setItem(k,v); }catch(e){} }
  function recall(k){ try{ return localStorage.getItem(k); }catch(e){ return null; } }

  function rgb(h){
    h=String(h||'').trim().replace('#','');
    if(h.length===3) h=h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    if(!/^[0-9a-fA-F]{6}$/.test(h)) return null;
    var n=parseInt(h,16); return [n>>16&255,n>>8&255,n&255];
  }
  function hex(c){ return '#'+c.map(function(v){
    return ('0'+Math.round(Math.max(0,Math.min(255,v))).toString(16)).slice(-2);
  }).join(''); }
  function lum(c){
    var a=c.map(function(v){ v/=255;
      return v<=.03928 ? v/12.92 : Math.pow((v+.055)/1.055,2.4); });
    return .2126*a[0]+.7152*a[1]+.0722*a[2];
  }
  function ratio(a,b){
    var x=lum(a), y=lum(b);
    return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
  }
  function toHsl(c){
    var r=c[0]/255,g=c[1]/255,b=c[2]/255,
        mx=Math.max(r,g,b),mn=Math.min(r,g,b),d=mx-mn,h=0,s=0,l=(mx+mn)/2;
    if(d){
      s=d/(1-Math.abs(2*l-1));
      h = mx===r ? ((g-b)/d)%6 : mx===g ? (b-r)/d+2 : (r-g)/d+4;
      h*=60; if(h<0) h+=360;
    }
    return [h,s,l];
  }
  function toRgb(h,s,l){
    var c=(1-Math.abs(2*l-1))*s, x=c*(1-Math.abs((h/60)%2-1)), m=l-c/2,
        t = h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]
           :h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x];
    return [(t[0]+m)*255,(t[1]+m)*255,(t[2]+m)*255];
  }
  /* Accent text appears on cards, the rail and the selected-nav tint. Walk
     its lightness until it clears every surface used by links and focus rings. */
  function legible(accent,backgrounds){
    var c=rgb(accent), list=(Array.isArray(backgrounds)?backgrounds:[backgrounds])
      .map(rgb).filter(Boolean);
    if(!c||!list.length) return accent;
    function worst(candidate){
      return Math.min.apply(null,list.map(function(bg){return ratio(candidate,bg)}));
    }
    var score=worst(c);
    if(score>=4.5)return accent;
    var average=list.reduce(function(sum,bg){return sum+lum(bg)},0)/list.length,
        hsl=toHsl(c),up=average<.5,best=accent;
    for(var i=1;i<=100;i++){
      var l=up?Math.min(1,hsl[2]+i/100):Math.max(0,hsl[2]-i/100),
          candidate=toRgb(hsl[0],hsl[1],l),r=worst(candidate);
      if(r>score){score=r;best=hex(candidate)}
      if(r>=4.5)return hex(candidate);
    }
    return best;
  }
  /* And the text drawn *on* the accent: no walking, just whichever of the two
     extremes wins, because a button label has to stay a flat legible block. */
  function ink(accent){
    var c=rgb(accent); if(!c) return '#141414';
    return ratio(c,[20,20,20])>=ratio(c,[255,255,255]) ? '#141414' : '#ffffff';
  }

  function apply(mode,accent){
    root.setAttribute('data-theme',mode);
    root.style.setProperty('--accent',accent);
    // Read back rather than remember: whatever the mode block just set is the
    // background this accent actually has to survive.
    var styles=getComputedStyle(root), backgrounds=['--bg','--surface','--surface-2','--surface-3','--rail','--rail-2']
      .map(function(token){return styles.getPropertyValue(token).trim()})
      .filter(Boolean);
    // The active nav sits on a 15% accent tint, which is its own text surface.
    var baseRail=rgb(styles.getPropertyValue('--rail').trim()),accentRgb=rgb(accent);
    if(baseRail&&accentRgb)backgrounds.push(hex(baseRail.map(function(channel,index){
      return channel*.85+accentRgb[index]*.15;
    })));
    root.style.setProperty('--accent-text',legible(accent,backgrounds));
    root.style.setProperty('--accent-ink',ink(accent));
    // Announced rather than pushed: this runs in <head>, so the rail's
    // controls do not exist yet and cannot be told directly. Whoever ends up
    // owning them subscribes, and then no caller of set() can leave the
    // buttons showing a mode the page is not in.
    try{ root.dispatchEvent(new CustomEvent('themechange')); }catch(e){}
  }

  var mode=recall(KEY);
  if(MODES.indexOf(mode)<0){
    // Nothing stored, so the operating system's answer is the best guess
    // available. It is a guess, not a subscription -- once a choice is stored
    // it wins, because somebody who picked light meant light.
    mode = (window.matchMedia
      && matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
  }
  var accent=recall(AKEY);
  if(!rgb(accent)) accent=FALLBACK;
  apply(mode,accent);

  window.ROMTHEME={
    modes:MODES,
    mode:function(){ return root.getAttribute('data-theme'); },
    accent:function(){ return root.style.getPropertyValue('--accent').trim()
                              || FALLBACK; },
    set:function(mode,accent){
      var m=MODES.indexOf(mode)>=0?mode:this.mode(),
          a=rgb(accent)?accent:this.accent();
      apply(m,a); store(KEY,m); store(AKEY,a);
    }
  };
})();
""".replace("ACCENT_FALLBACK", ACCENTS[0][0])


def _theme_control_html() -> str:
    """The mode switch and the accent swatches, for the rail's footer."""
    swatches = "".join(
        f'<button class="sw" type="button" data-accent="{value}" '
        f'style="--sw:{value}" data-i18n-title="{_ui_key(name + " accent")}" '
        f'data-i18n-aria-label="{_ui_key(name + " accent")}" title="{html.escape(name + " accent", quote=True)}" '
        f'aria-label="{html.escape(name + " accent", quote=True)}" aria-pressed="false"></button>'
        for value, name in ACCENTS
    )
    language_options = '<option value="system" data-i18n-key="ui.use-browser-settings.02d22d3f39">Use browser settings</option>' + ''.join(
        f'<option value="{code}" lang="{code}" dir="{item["direction"]}">{item["nativeName"]}</option>'
        for code in UI_AVAILABLE_LOCALES
        for item in (UI_LOCALE_OPTIONS[code],)
    )
    return (
        '<div id="railfoot">'
        '<label class="thm-lbl" for="interface-language" data-i18n-key="ui.interface-language.8027f432a7">Interface language</label>'
        f'<select id="interface-language" style="width:100%;margin:0 0 10px;padding:7px 8px;background:var(--surface);color:var(--fg);border:1px solid var(--line);border-radius:7px">{language_options}</select>'
        '<div class="thm-lbl" data-i18n-key="ui.theme.efb52e7172">Theme</div>'
        '<div class="thm-modes" role="group" data-i18n-aria-label="ui.colour-mode.1f2f41fcfe" aria-label="Colour mode">'
        '<button class="thm" type="button" data-theme-set="dark" '
        'data-i18n-key="ui.dark.60acc53f13" data-i18n-title="ui.dark.60acc53f13" title="Dark" aria-pressed="false">Dark</button>'
        '<button class="thm" type="button" data-theme-set="light" '
        'data-i18n-key="ui.light.dbcd5e7bb7" data-i18n-title="ui.light.dbcd5e7bb7" title="Light" aria-pressed="false">Light</button>'
        '<button class="thm" type="button" data-theme-set="sepia" '
        'data-i18n-key="ui.sepia.7464e26f38" data-i18n-title="ui.warm-sepia-theme.52e5d3d0e7" '
        'title="Warm sepia theme" aria-pressed="false">'
        'Sepia</button></div>'
        f'<div class="thm-accents">{swatches}'
        '<label class="sw pick" data-i18n-title="ui.custom-accent-colour.a37c3fad1a" title="Custom accent colour">'
        f'<input type="color" id="accent-pick" value="{ACCENTS[0][0]}" '
        'data-i18n-aria-label="ui.custom-accent-colour.a37c3fad1a" '
        'aria-label="Custom accent colour"></label>'
        '</div></div>'
    )

# The nav, in *arr order. `count` names a stat the badge reads.
NAV = [
    ("Library",  [("library", "Games", "games"),
                  ("organize", "Identify & Organize", None), ("add", "Add New", None),
                  ("discover", "Discover", None), ("patches", "Patches", None),
                  ("switchupdates", "Switch Updates & DLC", None)]),
    ("Wanted",   [("missing", "Missing", "missing"), ("lists", "Lists", None),
                  ("calendar", "Calendar", None)]),
    ("Activity", [("queue", "Queue", "queued"), ("history", "History", None),
                  ("blocklist", "Blocklist", None)]),
    ("Hub",      [("hub", "Plugins", None), ("peers", "Friends", None)]),
    ("Settings", [("media", "Media Management", None), ("profiles", "Profiles", None),
                  ("indexers", "Indexers", None), ("clients", "Download Clients", None),
                  ("libraries", "Libraries", None),
                  ("connections", "Connections", None),
                  ("metadata", "Metadata", None), ("general", "General", None)]),
    ("System",   [("status", "Status", None), ("stats", "Stats", None),
                  ("ecosystem", "Ecosystem", None),
                  ("platforms", "Platforms", None),
                  ("getstarted", "Get Started", None),
                  ("collections", "Collections", None),
                  ("manualimport", "Manual Import", None),
                  ("tasks", "Tasks", None), ("logs", "Logs", None)]),
]


def _nav_html() -> str:
    out = []
    for group_index, (group, items) in enumerate(NAV):
        heading_id = f'nav-heading-{group_index}'
        group_key = UI_SOURCE_TO_ID.get(group, group)
        out.append(f'<div class="navgroup" role="group" aria-labelledby="{heading_id}">'
                   f'<div class="navhead" id="{heading_id}" data-i18n-key="{html.escape(group_key, quote=True)}">{html.escape(group)}</div>')
        for key, label, count in items:
            badge = f'<b class="ct" data-ct="{count}"></b>' if count else ""
            label_key = UI_SOURCE_TO_ID.get(label, label)
            out.append(
                f'<a class="nav" href="#{key}" data-page="{key}">'
                f'<span class="lbl" data-i18n-key="{html.escape(label_key, quote=True)}">{html.escape(label)}</span>{badge}</a>'
            )
        out.append("</div>")
    return "".join(out)


JS = r"""
const UI_CATALOG=__UI_CATALOG__, UI_MESSAGES=UI_CATALOG.messages;
const UI_LABELS=Object.create(null), UI_SOURCE_TO_KEY=Object.create(null);
for(const [key,message] of Object.entries(UI_MESSAGES)){
  UI_LABELS[message.source]=message.translations;
  UI_SOURCE_TO_KEY[message.source]=key;
}
const $=s=>document.querySelector(s);
const INTERFACE_LANGUAGE_KEY='romarrng.interface-language';
const INTERFACE_LANGUAGES=__INTERFACE_LANGUAGES__;
let activeInterfaceLanguage=null;
const browserInterfaceLanguage=()=>ROMarrI18n.resolveLocale(
  navigator.languages&&navigator.languages.length?navigator.languages:[navigator.language],
  UI_CATALOG,INTERFACE_LANGUAGES);
const readInterfacePreference=()=>{
  try{const value=localStorage.getItem(INTERFACE_LANGUAGE_KEY);
    return value==='system'||!INTERFACE_LANGUAGES.includes(value)?'system':value;}
  catch(_){return 'system';}
};
const readInterfaceLanguage=()=>{
  if(INTERFACE_LANGUAGES.includes(activeInterfaceLanguage)) return activeInterfaceLanguage;
  const preference=readInterfacePreference();
  return preference==='system'?browserInterfaceLanguage():preference;
};
const stableLocalizationKey=source=>Object.hasOwn(UI_MESSAGES,source)?source:(UI_SOURCE_TO_KEY[source]||'');
const hasLabel=source=>Boolean(stableLocalizationKey(source));
const translationInfo=(source,language)=>ROMarrI18n.lookup(UI_CATALOG,source,language);
const isTranslated=(source,language)=>translationInfo(source,language).translated;
const translateLegacyLabel=(source,language)=>{
  const value=UI_LABELS[source]?.[language];
  return typeof value==='string'&&value?value:source;
};
const translateLabel=(source,language)=>{
  const legacy=translateLegacyLabel(source,language);
  return legacy!==source?legacy:ROMarrI18n.translate(UI_CATALOG,source,language);
};
const translateTemplate=(source,values,language=readInterfaceLanguage())=>
  ROMarrI18n.formatMessage(translationInfo(source,language).value,values,language,
    getRegionalLocale(),(nested,nestedValues)=>translateTemplate(nested,nestedValues,language));
const ACCOUNT_IMPORT_HELP=`Steam is a true one-click: Steam's own "Sign in through Steam", no key, no app registration — it comes straight back with your library connected. Epic, EA and Battle.net pull your owned library through the same web APIs Playnite uses — none of them issues an application key, so each opens the page your signed-in browser already has and takes one paste. GOG needs only your public profile name.`;
const GGR_WEBHOOK_HELP=`Restart GG Requestz after changing its environment. In GG Requestz 1.5+, the webhook fires when a request becomes approved; enable request.auto_approve or approve it manually. A successful delivery now receives HTTP 202. Rejected payloads receive HTTP 422 and are named in both applications' logs.`;
const ROMM_FRIEND_HELP=`Your friend does not need to run ROMarr. If they use RomM, ask them for an account and choose Add a RomM server. RomM publishes a hash for every ROM, so browsing and netplay matching work without installing anything on their server. The account gets the access their RomM grants; ROMarr cannot narrow it.`;
const NETPLAY_HELP=`Netplay matches each ROM by its SHA1, not by its title. “Super Mario Kart” can refer to four different ROMs; two incorrect matches may desync within seconds and look like lag. ROMarr can match only games whose hashes it knows.`;
const NO_HASHES_HELP=`No hashes have been recorded yet, so all netplay offers will show as missing. ROMarr reads each ROM's SHA1 from the library server automatically.`;
const GG_ADDRESS_HELP=`Use {url} on the same Docker network. Otherwise use ROMarr's LAN or HTTPS URL, reachable from GG Requestz.`;
const ROM_SITE_HELP=`ROM sites use plain HTTP through the Direct HTTP client. Some sites require a form that their own page submits, so those need the Headless Browser client to load the page and submit the form. Sites that require a CAPTCHA or bot-detection challenge are reported as unavailable instead of being bypassed.`;
const DOWNLOAD_STATE_LABELS={queued:'Queued',grabbed:'Grabbed',imported:'Imported',
  failed:'Failed','import-failed':'Import failed',cancelled:'Cancelled',
  available:'Available',downloading:'Downloading',importing:'Importing',done:'Done',
  pending:'Pending',running:'Running',paused:'Paused',ignored:'Ignored',
  wanted:'Wanted',decompress:'Decompress',playing:'Playing',completed:'Completed',
  shelved:'Shelved',verified:'Verified',bad:'Bad',unknown:'Unknown'};
const interfaceMarkup=source=>'<span data-i18n-key="'+esc(stableLocalizationKey(source)||source)+'">'
  +esc(translateLabel(source,readInterfaceLanguage()))+'</span>';
const interfaceTemplateMarkup=(source,values)=>'<span data-i18n-template-key="'+esc(stableLocalizationKey(source)||source)
  +'" data-i18n-values="'+esc(JSON.stringify(values))+'">'
  +esc(translateTemplate(source,values))+'</span>';
const interfaceTitleTemplate=(source,values)=>'title="'+esc(translateTemplate(source,values))
  +'" data-i18n-title-template-key="'+esc(stableLocalizationKey(source)||source)+'" data-i18n-title-values="'
  +esc(JSON.stringify(values))+'"';
const sniffedMessageTemplate=value=>{
  const source=String(value??'');
  if(hasLabel(source))return {source,values:{}};
  let match=source.match(/^Nintendo 64 magic, (.+)$/);
  if(match)return {source:'Nintendo 64 magic, {order}',values:{order:match[1]}};
  match=source.match(/^TMR SEGA signature at (0x[0-9a-f]+) \(Master System or Game Gear\)$/);
  if(match)return {source:'TMR SEGA signature at {offset} (Master System or Game Gear)',values:{offset:match[1]}};
  match=source.match(/^(CISO|RVZ|WIA|GCZ) compressed disc image \(GameCube or Wii\)$/);
  if(match)return {source:'{format} compressed disc image (GameCube or Wii)',values:{format:match[1]}};
  for(const [prefix,sourceKey] of [
    ['Sega CD boot header at ','Sega CD boot header at {offset}'],
    ['Saturn boot header at ','Saturn boot header at {offset}'],
    ['Dreamcast boot header at ','Dreamcast boot header at {offset}'],
  ]){
    if(source.startsWith(prefix)&&/^0x[0-9a-f]+$/.test(source.slice(prefix.length)))
      return {source:sourceKey,values:{offset:source.slice(prefix.length)}};
  }
  return null;
};
const manualDiagnosticTitle=value=>{
  const source=String(value??''),hollow=source.match(/^(\d+) of (\d+) sampled regions are empty, including the start — the file has its full size \((\d+) MB\) and almost no content, which is what an interrupted download leaves behind$/s);
  if(hollow)return interfaceTitleTemplate('ui.empty-of-sampled-sampled-regions-are.adfa41e739',
    {empty:fmt(Number(hollow[1])),sampled:fmt(Number(hollow[2])),size:fmt(Number(hollow[3]))});
  const parsed=sniffedMessageTemplate(source);
  return parsed?interfaceTitleTemplate(parsed.source,parsed.values)
    :'title="'+esc(source)+'" lang="und" dir="auto"';
};
const appMessageMarkup=value=>{
  const source=String(value??'');
  if(hasLabel(source)) return interfaceMarkup(source);
  let match=source.match(/^(.+) — confirmed by the header$/s);
  if(match){
    const reason=sniffedMessageTemplate(match[1]);
    if(reason)return interfaceTemplateMarkup('ui.reason-confirmed-by-the-header.28b2925292',{reason});
  }
  match=source.match(/^(.+) — chosen over (\d+) platforms sharing this extension$/s);
  if(match){
    const reason=sniffedMessageTemplate(match[1]);
    if(reason)return interfaceTemplateMarkup('ui.reason-chosen-over-count-platforms-s.b80ce37980',
      {reason,count:fmt(Number(match[2]))});
  }
  match=source.match(/^seeders: (\d+)$/);
  if(match)return interfaceTemplateMarkup('ui.seeders-count.c31e318db5',{count:fmt(Number(match[1]))});
  match=source.match(/^unknown platform: (.+)$/s);
  if(match)return interfaceTemplateMarkup('ui.unknown-platform-platform.489002d02a',{platform:match[1]});
  match=source.match(/^search failed: (.+)$/s);
  if(match)return interfaceTemplateMarkup('ui.search-failed-error.b8182b49a5',{error:match[1]});
  match=source.match(/^No usable release was found\. Checked results: (\d+)\.$/);
  if(match)return interfaceTemplateMarkup('ui.no-usable-release-was-found-checked.eef9a1aaab',
    {count:fmt(Number(match[1]))});
  match=source.match(/^no usable release among (\d+) result\(s\)$/);
  if(match)return interfaceTemplateMarkup('ui.no-usable-release-was-found-checked.eef9a1aaab',
    {count:fmt(Number(match[1]))});
  match=source.match(/^(.+) does not exist$/s);
  if(match)return interfaceTemplateMarkup('ui.path-does-not-exist.5fac9594c5',{path:match[1]});
  match=source.match(/^no (.+) ROM found; candidate count: (\d+)\.$/);
  if(match)return interfaceTemplateMarkup('ui.no-platform-rom-found-candidate-coun.5e7e52a86f',
    {platform:match[1],count:fmt(Number(match[2]))});
  match=source.match(/^no (.+) ROM among (\d+) file\(s\)$/);
  if(match)return interfaceTemplateMarkup('ui.no-platform-rom-found-candidate-coun.5e7e52a86f',
    {platform:match[1],count:fmt(Number(match[2]))});
  match=source.match(/^game import failed: (.+)$/s);
  if(match)return interfaceTemplateMarkup('ui.game-import-failed-error.8386b9617a',{error:match[1]});
  match=source.match(/^download path does not exist in this container: (.+)\. Mount the download client's completed directory at that exact path, or add a remote path mapping under Settings -> Media Management\.$/s);
  if(match)return interfaceTemplateMarkup('ui.download-path-does-not-exist-in-this.112b0d17bf',
    {path:match[1]});
  match=source.match(/^(.+) is a (\.[^ ]+) archive and bsdtar is not installed, so its contents cannot be read\. Install libarchive-tools \(Debian\/Alpine\) or use the official ROMarr image, which ships it\.$/s);
  if(match)return interfaceTemplateMarkup('ui.filename-is-a-extension-archive-and.140419113e',
    {filename:match[1],extension:match[2]});
  match=source.match(/^two files in this download are both called (.+) \((.+) and (.+)\); refusing to guess which one the game needs$/s);
  if(match)return interfaceTemplateMarkup('ui.two-files-in-this-download-are-both.344d3762f0',
    {name:match[1],first:match[2],second:match[3]});
  match=source.match(/^in a folder named (['"])(.*)\1$/s);
  if(match)return interfaceTemplateMarkup('ui.in-a-folder-named-folder.d46c20bd54',{folder:match[2]});
  match=source.match(/^(\.[^ ]+) is unique to it$/);
  if(match)return interfaceTemplateMarkup('ui.extension-is-unique-to-it.8c668c3c22',{extension:match[1]});
  match=source.match(/^(\.[^ ]+) is used by (.+) -- confirm before importing$/s);
  if(match)return interfaceTemplateMarkup('ui.extension-is-used-by-platforms-confi.7a1f227e3e',
    {extension:match[1],platforms:match[2]});
  match=source.match(/^(.+) is not a directory$/s);
  if(match)return interfaceTemplateMarkup('ui.path-is-not-a-directory.26fe0ef3e3',{path:match[1]});
  match=source.match(/^repository: (.+) is not an allowed source\. Allowed: (.+)\. Add it under Settings if you host your own forge\.$/s);
  if(match)return interfaceTemplateMarkup('ui.repository-host-is-not-an-allowed-so.5a31078d00',
    {host:match[1],allowed:match[2]});
  match=source.match(/^(.+) is not an allowed source\. Allowed: (.+)\. Add it under Settings if you host your own forge\.$/);
  if(match)return interfaceTemplateMarkup('ui.host-is-not-an-allowed-source-allowe.1727dfe88c',
    {host:match[1],allowed:match[2]});
  match=source.match(/^title does not match (['"])(.*)\1$/s);
  if(match)return interfaceTemplateMarkup('ui.title-does-not-match-title.ca6044dd1f',{title:match[2]});
  match=source.match(/^blocklisted: (.+)$/s);
  if(match)return interfaceTemplateMarkup('ui.blocklisted-reason.b9150b07d2',{
    reason:match[1]==='blocked by the operator'
      ?{source:'blocked by the operator',values:{}}:match[1]});
  match=source.match(/^release profile prefers (['"])(.*)\1$/s);
  if(match)return interfaceTemplateMarkup('ui.release-profile-prefers-term.180cc22f98',{term:match[2]});
  match=source.match(/^excluded by release profile \((['"])(.*)\1\)$/s);
  if(match)return interfaceTemplateMarkup('ui.excluded-by-release-profile-term.37468ce4d2',{term:match[2]});
  match=source.match(/^missing a required term \((['"])(.*)\1\)$/s);
  if(match)return interfaceTemplateMarkup('ui.missing-a-required-term-term.73761d6be6',{term:match[2]});
  match=source.match(/^looks like a hack, beta or repack \((.*)\)$/s);
  if(match)return interfaceTemplateMarkup('ui.looks-like-a-hack-beta-or-repack-mar.810e638d6c',{marker:match[1]});
  match=source.match(/^names another platform \((.+)\)$/);
  if(match)return interfaceTemplateMarkup('ui.names-another-platform-platform.35058a3537',{platform:match[1]});
  match=source.match(/^a PC release \((.+)\)$/);
  if(match)return interfaceTemplateMarkup('ui.a-pc-release-marker.a4d0405064',{marker:match[1]});
  match=source.match(/^trusted repacker \((.+)\)$/);
  if(match)return interfaceTemplateMarkup('ui.trusted-repacker-name.bc8c3237ca',{name:match[1]});
  match=source.match(/^a compilation, not a single game \((.+)\)$/);
  if(match)return interfaceTemplateMarkup('ui.a-compilation-not-a-single-game-mark.a15bc468ef',{marker:match[1]});
  match=source.match(/^a (.+) dump$/);
  if(match&&match[1]==='Redump')return interfaceTemplateMarkup('ui.a-project-dump.90fa1e1349',{project:match[1]});
  match=source.match(/^carries a (.+) ROM extension$/);
  if(match)return interfaceTemplateMarkup('ui.carries-a-platform-rom-extension.f9cc7e449e',{platform:match[1]});
  match=source.match(/^provider declares (.+)$/);
  if(match)return interfaceTemplateMarkup('ui.provider-declares-platform.cd233110a9',{platform:match[1]});
  match=source.match(/^names (.+)$/);
  if(match)return interfaceTemplateMarkup('ui.names-platform.13dd488b08',{platform:match[1]});
  match=source.match(/^region ranks lower \((.+)\)$/);
  if(match)return interfaceTemplateMarkup('ui.region-ranks-lower-region.983968b588',{region:match[1]});
  match=source.match(/^region (.+)$/);
  if(match&&/^(?:usa|world|europe|japan|[a-z]{1,3})$/.test(match[1]))
    return interfaceTemplateMarkup('ui.region-region.17e5cc0b09',{region:match[1]});
  match=source.match(/^(.+) translation, kept as a variant$/);
  if(match)return interfaceTemplateMarkup('ui.language-translation-kept-as-a-varia.a07ee0c96f',{language:match[1]});
  match=source.match(/^(.+) translation used because no dump exists in your preferred regions$/);
  if(match)return interfaceTemplateMarkup('ui.language-translation-used-because-no.aeb8345bd9',{language:match[1]});
  match=source.match(/^(.+) translation preferred over (.+)$/);
  if(match)return interfaceTemplateMarkup('ui.language-translation-preferred-over.af52539e78',{language:match[1],name:match[2]});
  match=source.match(/^(.+) translation added to the set$/);
  if(match)return interfaceTemplateMarkup('ui.language-translation-added-to-the-se.28bfcbdfa9',{language:match[1]});
  return '<span lang="und" dir="auto">'+esc(source)+'</span>';
};
const searchReasonMarkup=value=>{
  const source=String(value??''),scored=source.match(/^([+-])(\d+)\s+(.+)$/s);
  const score=scored?'<span lang="und" dir="ltr">'+scored[1]+fmt(Number(scored[2]))+'</span> ':'';
  const reason=scored?scored[3]:source;
  return score+appMessageMarkup(reason);
};
const collectionReasonMarkup=value=>{
  const source=String(value??'');
  let match=source.match(/^region (.+) is (\d+) of (\d+) in your preference(; it is the parent dump)?$/);
  if(match)return interfaceTemplateMarkup(
    match[4]
      ?'region {region} is {rank} of {count} in your preference; it is the parent dump'
      :'region {region} is {rank} of {count} in your preference',
    {region:match[1],rank:fmt(Number(match[2])),count:fmt(Number(match[3]))});
  if(source==='no dump matched your preferred regions, so the set keeps this one rather than losing the game')
    return interfaceMarkup(source);
  if(source==='no dump matched your preferred regions, so the set keeps this one rather than losing the game; it is the parent dump')
    return interfaceMarkup(source);
  return appMessageMarkup(source);
};
const statusMarkup=value=>{
  const raw=String(value??''),source=DOWNLOAD_STATE_LABELS[raw];
  return source
    ? interfaceMarkup(source)
    : '<span lang="und" dir="auto">'+esc(raw)+'</span>';
};
const applyTranslatedLabel=(el,language)=>{
  const source=el.dataset.i18nKey||el.dataset.i18n, translated=isTranslated(source,language);
  el.textContent=translateLabel(source,language);
  el.lang=translated?language:'en';
  el.dir=translated&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
};
const applyTranslatedLabels=(root,language)=>{
  const elements=[];
  if(root.nodeType===Node.ELEMENT_NODE&&root.matches?.('[data-i18n],[data-i18n-key]'))elements.push(root);
  if(root.querySelectorAll)elements.push(...root.querySelectorAll('[data-i18n],[data-i18n-key]'));
  for(const el of elements)applyTranslatedLabel(el,language);
};
const applyTranslatedTemplates=(root,language)=>{
  const elements=[];
  if(root.nodeType===Node.ELEMENT_NODE&&root.matches?.('[data-i18n-template],[data-i18n-template-key]'))elements.push(root);
  if(root.querySelectorAll)elements.push(...root.querySelectorAll('[data-i18n-template],[data-i18n-template-key]'));
  for(const el of elements){
    let values={};
    try{values=JSON.parse(el.dataset.i18nValues||'{}')}catch(_){continue}
    const source=el.dataset.i18nTemplateKey||el.dataset.i18nTemplate;
    const translated=isTranslated(source,language);
    el.textContent=translateTemplate(source,values,language);
    el.lang=translated?language:'en';
    el.dir=translated&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
  }
};
const applyTranslatedAttribute=(el,source,attribute,language)=>{
  const translated=isTranslated(source,language);
  el.setAttribute(attribute,translateLabel(source,language));
  el.lang=translated?language:'en';
  el.dir=translated&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
};
const translatedTextSources=new WeakMap();
const translatedAttributeSources=new WeakMap();
const applyTranslatedTextNode=(node,language)=>{
  const parent=node.parentElement;
  if(!parent||parent.closest('script,style,textarea,input,select,[contenteditable="true"],[lang="und"],[data-i18n],[data-i18n-key]'))return;
  const original=translatedTextSources.get(node)||node.data.trim().replace(/\s+/g,' ');
  if(!hasLabel(original))return;
  translatedTextSources.set(node,original);
  const leading=node.data.match(/^\s*/)?.[0]||'',trailing=node.data.match(/\s*$/)?.[0]||'';
  const value=leading+translateLabel(original,language)+trailing;
  if(node.data!==value)node.data=value;
  const translated=Boolean(isTranslated(original,language));
  parent.lang=translated?language:'en';
  parent.dir=translated&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
};
const applyTranslatedTextTree=(root,language)=>{
  if(root.nodeType===Node.TEXT_NODE){applyTranslatedTextNode(root,language);return;}
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  while(walker.nextNode())applyTranslatedTextNode(walker.currentNode,language);
};
const keepPlaceholderLiteral=source=>/^(?:https?:\/\/|[a-z]+\.[a-z.]+\/|[A-Z0-9_-]{5,}$|[a-z0-9_-]+(?:,\s*[a-z0-9_-]+)+$)/i.test(source)
  ||['Dave\'s RomM','K7RM-9TFQ','Phantasy Star IV','Super Mario World','Your Plugin','your-plugin','search, importer','snes, n64'].includes(source);
const applyTranslatedAttributes=(root,language)=>{
  const elements=[];
  if(root.nodeType===Node.ELEMENT_NODE)elements.push(root);
  if(root.querySelectorAll)elements.push(...root.querySelectorAll('[title],[aria-label],[placeholder],[data-i18n-title],[data-i18n-aria-label],[data-i18n-placeholder],[data-i18n-title-template],[data-i18n-title-template-key]'));
  for(const el of elements){
    for(const [attribute,marker] of [['title','data-i18n-title'],['aria-label','data-i18n-aria-label'],['placeholder','data-i18n-placeholder']]){
      const template=el.getAttribute(marker+'-template-key')??el.getAttribute(marker+'-template');
      if(template!==null){
        let values={};
        try{values=JSON.parse(el.getAttribute(marker+'-values')||'{}')}catch(_){continue}
        el.setAttribute(attribute,translateTemplate(template,values,language));
        const localized=Boolean(isTranslated(template,language));
        el.lang=localized?language:'en';
        el.dir=localized&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
        continue;
      }
      const explicit=el.getAttribute(marker),current=el.getAttribute(attribute);
      if(explicit===null&&current===null)continue;
      if(explicit===null&&el.closest('[lang="und"]'))continue;
      let source=explicit;
      if(source===null){
        if(attribute==='placeholder'&&keepPlaceholderLiteral(current))continue;
        let tracked=translatedAttributeSources.get(el);
        if(!tracked){tracked=new Map();translatedAttributeSources.set(el,tracked)}
        source=tracked.get(attribute)||current;
        tracked.set(attribute,source);
      }
      if(!hasLabel(source))continue;
      const localized=Boolean(isTranslated(source,language));
      el.setAttribute(attribute,translateLabel(source,language));
      el.lang=localized?language:'en';
      el.dir=localized&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
    }
  }
};
let interfaceTextObserver=null;
const observeInterfaceText=()=>{
  if(interfaceTextObserver||!document.body)return;
  interfaceTextObserver=new MutationObserver(records=>{
    for(const record of records){
      if(record.type==='characterData')applyTranslatedTextNode(record.target,readInterfaceLanguage());
      for(const node of record.addedNodes){
        enhanceFormLabels(node);
        applyTranslatedLabels(node,readInterfaceLanguage());
        applyTranslatedTemplates(node,readInterfaceLanguage());
        applyTranslatedTextTree(node,readInterfaceLanguage());
        applyTranslatedAttributes(node,readInterfaceLanguage());
      }
    }
  });
  interfaceTextObserver.observe(document.body,{subtree:true,childList:true,characterData:true});
};
let generatedControlId=0;
function enhanceFormLabels(root=document.body){
  if(!root)return;
  const labels=[];
  if(root.nodeType===Node.ELEMENT_NODE&&root.matches('label:not([for])'))labels.push(root);
  if(root.querySelectorAll)labels.push(...root.querySelectorAll('label:not([for])'));
  for(const label of labels){
    if(label.querySelector('input,select,textarea,button'))continue;
    const field=label.closest('.field,.mapping-field');
    if(!field)continue;
    const control=[...field.querySelectorAll('input,select,textarea')]
      .find(el=>!el.closest('label'));
    if(!control)continue;
    if(!control.id){
      let id;
      do{id='romarr-field-'+(++generatedControlId)}while(document.getElementById(id));
      control.id=id;
    }
    label.htmlFor=control.id;
    const help=field.querySelector(':scope > .help');
    if(help&&!control.hasAttribute('aria-describedby')){
      if(!help.id){
        let id;
        do{id='romarr-help-'+(++generatedControlId)}while(document.getElementById(id));
        help.id=id;
      }
      control.setAttribute('aria-describedby',help.id);
    }
  }
  const selectNames={genre:'Genre',region:'Region',decade:'Decade',origin:'Origin',source:'Source',sort:'Sort by'};
  const controls=[];
  if(root.nodeType===Node.ELEMENT_NODE&&root.matches('input,select,textarea'))controls.push(root);
  if(root.querySelectorAll)controls.push(...root.querySelectorAll('input,select,textarea'));
  for(const control of controls){
    if(control.hasAttribute('aria-label')||control.hasAttribute('aria-labelledby'))continue;
    if(control.id&&[...document.querySelectorAll('label[for]')].some(label=>label.htmlFor===control.id))continue;
    if(control.closest('label'))continue;
    const source=selectNames[control.dataset.lf];
    const fallback=source?translateLabel(source,readInterfaceLanguage()):
      (control.getAttribute('placeholder')||control.getAttribute('title'));
    if(fallback){
      control.setAttribute('aria-label',fallback);
      if(source)control.dataset.i18nAriaLabel=source;
    }
  }
}
const applyInterfaceLanguage=(language=readInterfaceLanguage())=>{
  document.documentElement.lang=language;
  document.documentElement.dir=ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
  applyTranslatedLabels(document,language);
  applyTranslatedTemplates(document,language);
  document.querySelectorAll('[data-i18n-aria-label]').forEach(el=>applyTranslatedAttribute(el,el.dataset.i18nAriaLabel,'aria-label',language));
  document.querySelectorAll('[data-i18n-title]').forEach(el=>applyTranslatedAttribute(el,el.dataset.i18nTitle,'title',language));
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{
    const source=el.dataset.i18nPlaceholder, translated=isTranslated(source,language);
    el.placeholder=translateLabel(source,language);
    el.lang=translated?language:'en';
    el.dir=translated&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr';
  });
  applyTranslatedTextTree(document.body,language);
  applyTranslatedAttributes(document.body,language);
  enhanceFormLabels(document.body);
  observeInterfaceText();
  const selector=$('#interface-language'); if(selector) selector.value=readInterfacePreference();
  const heading=$('#page-title');
  if(heading)document.title=heading.textContent.trim()+' · ROMarr';
};
const j=(u,o)=>fetch(u,o).then(r=>r.json());
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// Library counts here run to six figures; grouped, they are readable at a
// glance instead of a digit-counting exercise.
const REGIONAL_FORMAT_KEY='romarrng.regional-format';
const REGIONAL_FORMATS=[["system", "Use browser settings"],...__REGIONAL_FORMATS__];
const REGIONAL_LANGUAGE_TAGS=Object.fromEntries(REGIONAL_FORMATS.filter(([code])=>code!=='system').map(([code])=>[code,code]));
const readRegionalPreference=()=>{
  try{
    const value=localStorage.getItem(REGIONAL_FORMAT_KEY);
    return REGIONAL_FORMATS.some(([code])=>code===value)?value:'system';
  }catch(_){return 'system';}
};
let activeRegionalPreference=readRegionalPreference();
const getRegionalLocale=()=>activeRegionalPreference==='system'?undefined:activeRegionalPreference;
const refreshRegionalView=()=>{
  const current=location.hash.slice(1);
  const formattedPages=new Set(['library','add','search','missing','lists','calendar',
    'queue','history','blocklist','hub','peers','status','stats','ecosystem',
    'platforms','getstarted','collections','manualimport','tasks','logs',
    'organize','discover','patches']);
  if(document.querySelector('.modal[role="dialog"]'))return;
  if(formattedPages.has(current))go(current,false);
  else refreshCounts();
};
const setRegionalLocale=value=>{
  if(!REGIONAL_FORMATS.some(([code])=>code===value)) return false;
  activeRegionalPreference=value;
  try{
    if(value==='system') localStorage.removeItem(REGIONAL_FORMAT_KEY);
    else localStorage.setItem(REGIONAL_FORMAT_KEY,value);
  }catch(_){
    // Keep the chosen format active in this tab when browser storage is unavailable.
  }
  return true;
};
if(typeof window!=='undefined'){
  window.addEventListener('storage',event=>{
    if(event.key!==REGIONAL_FORMAT_KEY&&event.key!==null) return;
    activeRegionalPreference=readRegionalPreference();
    refreshRegionalView();
  });
}
const applyRegionalFormat=(value,control)=>{
  if(!setRegionalLocale(value)){
    if(control) control.value=getRegionalLocale()||'system';
    return false;
  }
  refreshRegionalView();
  return true;
};
const regionalFormatField=()=>{
  const current=activeRegionalPreference;
  const language=readInterfaceLanguage();
  const metadata=(source)=>{
    const translated=Boolean(isTranslated(source,language));
    return ' lang="'+(translated?language:'en')+'" dir="'+(translated&&ROMarrI18n.isRTL(language,UI_CATALOG)?'rtl':'ltr')+'"';
  };
  const options=REGIONAL_FORMATS.map(([code,label])=>{
    const text=code==='system'?translateLabel(label,language):label;
    const translation=code==='system'
      ? ' data-i18n-key="'+esc(stableLocalizationKey(label))+'"'+metadata(label)
      : '';
    const optionLanguage=REGIONAL_LANGUAGE_TAGS[code]||'en';
    const optionDirection=ROMarrI18n.isRTL(code,UI_CATALOG)?'rtl':'ltr';
    return '<option value="'+esc(code)+'" lang="'+optionLanguage+'" dir="'+optionDirection+'"'+translation+(code===current?' selected':'')+'>'+esc(text)+'</option>';
  }).join('');
  const formatLabel='Date, time, and number format';
  const formatHelp='This changes date and number formats only; it is separate from interface language.';
  return '<div class="field"><label for="g-regional-format" data-i18n-key="'+esc(stableLocalizationKey(formatLabel))+'"'+metadata(formatLabel)+'>'+esc(translateLabel(formatLabel,language))+'</label>'+
    '<select id="g-regional-format" aria-describedby="g-regional-format-help">'+options+'</select>'+
    '<div id="g-regional-format-help" data-i18n-key="'+esc(stableLocalizationKey(formatHelp))+'"'+metadata(formatHelp)+' style="color:var(--dim);font-size:11.5px;margin-top:4px">'+esc(translateLabel(formatHelp,language))+'</div></div>';
};
const fmt=n=>Number(n??0).toLocaleString(getRegionalLocale());
const num=n=>n===null||n===undefined?'—':fmt(n);
const utcCalendarDate=(year,month,day)=>{
  const date=new Date(0);
  date.setUTCFullYear(year,month-1,day);
  return date.getUTCFullYear()===year&&date.getUTCMonth()===month-1
    &&date.getUTCDate()===day?date:null;
};
const regionalDate=value=>{
  if(value===null||value===undefined||value==='') return '—';
  const source=String(value);
  const monthDay=/^(\d{2})-(\d{2})$/.exec(source);
  if(monthDay){
    const month=Number(monthDay[1]),day=Number(monthDay[2]);
    const date=utcCalendarDate(2000,month,day);
    if(!date) return source;
    return new Intl.DateTimeFormat(getRegionalLocale(),{
      month:'short',day:'numeric',timeZone:'UTC'}).format(date);
  }
  const dayOnly=/^(\d{4})-(\d{2})-(\d{2})$/.exec(source);
  if(dayOnly){
    const date=utcCalendarDate(Number(dayOnly[1]),Number(dayOnly[2]),Number(dayOnly[3]));
    return date?date.toLocaleDateString(getRegionalLocale(),{timeZone:'UTC'}):source;
  }
  const date=new Date(source);
  return Number.isNaN(date.getTime())?source:date.toLocaleDateString(getRegionalLocale());
};
const regionalDateTime=value=>{
  if(value===null||value===undefined||value==='') return '—';
  const source=String(value);
  const dayOnly=/^(\d{4})-(\d{2})-(\d{2})(?:T|$)/.exec(source);
  if(dayOnly&&!utcCalendarDate(Number(dayOnly[1]),Number(dayOnly[2]),Number(dayOnly[3])))
    return source;
  const date=value instanceof Date?value:new Date(value);
  return Number.isNaN(date.getTime())?String(value)
    :date.toLocaleString(getRegionalLocale());
};
const regionalEpochDateTime=value=>{
  if(value===null||value===undefined||value==='') return '—';
  return regionalDateTime(Number(value)*1000);
};
const regionalMonth=value=>{
  const match=/^(\d{4})-(\d{2})$/.exec(String(value||''));
  if(!match) return String(value||'');
  const date=utcCalendarDate(Number(match[1]),Number(match[2]),1);
  if(!date) return String(value||'');
  return new Intl.DateTimeFormat(getRegionalLocale(),{
    month:'long',year:'numeric',timeZone:'UTC'}).format(date);
};
const regionalYear=value=>{
  const year=Number(value);
  return Number.isFinite(year)?year.toLocaleString(getRegionalLocale(),{
    useGrouping:false}):String(value??'');
};
let PLATFORMS=[], SETTINGS={};
let CATALOG_VIEW={mode:'catalog',source:'igdb',platform:'',query:'',genre:'',
  year:'',offset:0,sort:'popular',view:'grid',hideOwned:true,selected:[],
  igdbPlatforms:[],datPlatforms:[],rows:[],next:null};
let PLATFORM_VIEW={group:'all',query:''};

function toast(msg,language='en',direction='ltr'){
  const t=document.createElement('div');
  t.className='toast'; t.lang=language; t.dir=direction; t.textContent=msg;
  t.setAttribute('aria-hidden','true');
  document.body.append(t);
  const live=$('#app-announcement');
  if(live){live.lang=language;live.dir=direction;live.textContent='';
    requestAnimationFrame(()=>{if(live.isConnected)live.textContent=msg;});}
  setTimeout(()=>t.remove(),4200);
}
function toastLabel(source){
  const language=readInterfaceLanguage(), translated=isTranslated(source,language);
  toast(translateLabel(source,language),translated?language:'en',translated&&language==='ar'?'rtl':'ltr');
}
function toastMessage(source,values={}){
  const language=readInterfaceLanguage(), translated=Boolean(isTranslated(source,language));
  toast(translateTemplate(source,values,language),translated?language:'en',translated&&language==='ar'?'rtl':'ltr');
}
function toastAppMessage(message){
  const source=String(message??'');
  if(hasLabel(source))toastLabel(source);
  else if(source)toast(source,'und','auto');
}
function confirmMessage(source,values={}){
  return window.confirm(translateTemplate(source,values,readInterfaceLanguage()));
}
function promptMessage(source,values={},defaultValue=''){
  return window.prompt(translateTemplate(source,values,readInterfaceLanguage()),defaultValue);
}

/* ---------------- routing ---------------- */
let mobileNavPreviousOverflow='', routeEpoch=0;
function setMobileNavOpen(open,restoreFocus=true){
  const rail=$('#rail'),main=$('#main-content'),toggle=$('#nav-toggle'),backdrop=$('#nav-backdrop');
  if(!rail||!toggle||!backdrop)return;
  if(open){
    if(rail.classList.contains('mobile-open'))return;
    mobileNavPreviousOverflow=document.body.style.overflow;
    rail.classList.add('mobile-open');
    toggle.setAttribute('aria-expanded','true');
    toggle.dataset.i18nAriaLabel='ui.close-navigation.99904db30d';
    toggle.setAttribute('aria-label',translateLabel('ui.close-navigation.99904db30d',readInterfaceLanguage()));
    toggle.dataset.i18nKey='ui.close.7d9eb7acb1';applyTranslatedLabel(toggle,readInterfaceLanguage());
    backdrop.hidden=false;
    if(main)main.inert=true;
    document.body.style.overflow='hidden';
    requestAnimationFrame(()=>rail.querySelector('.nav')?.focus({preventScroll:true}));
  }else{
    if(!rail.classList.contains('mobile-open'))return;
    rail.classList.remove('mobile-open');
    toggle.setAttribute('aria-expanded','false');
    toggle.dataset.i18nAriaLabel='ui.open-navigation.0ed77fd261';
    toggle.setAttribute('aria-label',translateLabel('ui.open-navigation.0ed77fd261',readInterfaceLanguage()));
    toggle.dataset.i18nKey='ui.menu.99af6606ff';applyTranslatedLabel(toggle,readInterfaceLanguage());
    backdrop.hidden=true;
    if(main)main.inert=false;
    document.body.style.overflow=mobileNavPreviousOverflow;
    if(restoreFocus)toggle.focus({preventScroll:true});
  }
}
let ROUTE_ARGS=[];
function go(pageSpec,focusHeading=false){
  const parts=String(pageSpec).split('/');
  let page=parts[0]; ROUTE_ARGS=parts.slice(1).map(x=>{try{return decodeURIComponent(x);}catch(e){return x;}});
  // Interactive Search was folded into Add New; old links still land there.
  if(page==='search'){page='add';pageSpec='add';ROUTE_ARGS=[];}
  if(page!=='game'&&!document.querySelector('.nav[data-page="'+CSS.escape(page)+'"]')){page='library';pageSpec='library';ROUTE_ARGS=[];}
  const renderEpoch=++routeEpoch;
  if(location.hash!=='#'+pageSpec)location.hash=pageSpec;
  const navPage=page==='game'?'library':page;
  document.querySelectorAll('.nav').forEach(n=>{
    const current=n.dataset.page===navPage;
    n.classList.toggle('on',current);
    if(current)n.setAttribute('aria-current','page');
    else n.removeAttribute('aria-current');
  });
  setMobileNavOpen(false,false);
  const titles={library:'Games',add:'Add New Game',game:'Game',switchupdates:'Switch Updates & DLC',search:'Add New Game',
    missing:'Wanted — Missing',lists:'Import Lists',stats:'Statistics',
    discover:'Discover',patches:'Patches — translations, hacks and improvements',ecosystem:'The Ecosystem',peers:'Friends',
    queue:'Queue',history:'History',media:'Media Management',profiles:'Profiles',
    indexers:'Indexers',clients:'Download Clients',libraries:'Libraries',
    general:'General',
    status:'System Status',platforms:'Platforms',tasks:'Tasks',logs:'Logs',
    blocklist:'Blocklist',connections:'Connections',metadata:'Metadata',
    calendar:'Release Calendar',manualimport:'Manual Import',
    organize:'Identify & Organize',
    collections:'Collections \u2014 full sets and 1G1R',
    getstarted:'Get Started',
    hub:'ROM Hub — Plugins'};
  const title=$('#top h1');
  const titleSource=titles[page]||'ROMarr';
  title.dataset.i18nKey=stableLocalizationKey(titleSource)||titleSource;
  applyTranslatedLabel(title,readInterfaceLanguage());
  document.title=title.textContent.trim()+' · ROMarr';
  $('#search').classList.toggle('hide', page!=='library');
  const main=$('#main-content'),content=$('#page');
  main.setAttribute('aria-busy','true');
  Promise.resolve().then(()=> (RENDER[page]||RENDER.library)(renderEpoch))
    .catch(()=>{
      if(renderEpoch!==routeEpoch)return;
      content.innerHTML='<div class="card" role="alert" aria-live="assertive">'
        +'<h2>Page could not be loaded</h2><p class="help">ROMarr could not finish loading this page. Check the connection and try again.</p>'
        +'<button class="btn" id="page-retry" type="button">Try again</button></div>';
      $('#page-retry').onclick=()=>go(page,true);
    })
    .finally(()=>{if(renderEpoch===routeEpoch)main.removeAttribute('aria-busy');});
  if(focusHeading)requestAnimationFrame(()=>title.focus({preventScroll:true}));
}
addEventListener('hashchange',()=>{
  const spec=location.hash.slice(1), page=spec.split('/')[0];
  if(page==='game'||page==='search'||document.querySelector('.nav[data-page="'+CSS.escape(page)+'"]'))go(spec,true);
});

/* ---------------- pages ---------------- */
const RENDER={};
RENDER.hub=async(renderEpoch=routeEpoch)=>{
  // Installing a plugin means running its author's code. Whether that code is
  // confined is the thing to know first, so it goes at the top of the page
  // rather than in a log the operator will never read.
  const hs=await j('/api/v1/hub/status').catch(()=>({}));
  if(renderEpoch!==routeEpoch||location.hash!=='#hub')return;
  const confined=hs.sandboxed===true;
  const sandboxNote=hs.available===false ? '' :
    (confined
      ? '<div class="panel-note" style="border-inline-start:3px solid var(--ok)">'
        +'<b>Plugins run confined.</b> Each runs as its own subprocess with no '
        +'library token or sockets of its own. '
        +(hs.isolation==='uid'
          ? 'This host has no Landlock, so plugins run as a separate unprivileged '
            +'user: they cannot read ROMarr’s settings file or any credential, and '
            +'cannot change user or regain privileges. Writes stay in bounded tmpfs '
            +'scratch. '
          : 'Landlock limits file access to plugin code, verified assets and '
            +'runtime files; writes stay in bounded tmpfs scratch. It cannot change '
            +'file permissions or spawn child processes. ')
        +'Network requests go through ROMarr and can reach only declared hosts.</div>'
      : '<div class="panel-note panel-warn"><b>Plugins run with no '
        +'confinement.</b> '+appMessageMarkup(hs.sandbox_detail||'')+' A plugin you install '
        +'may run without one or both boundaries if you explicitly override '
        +'this check; check the missing capability before allowing it.</div>');
  // What enabling a searchable plugin actually does now, said out loud:
  // its results join Interactive Search once the ROM Hub download client
  // is configured. Before that existed, the honest sentence was "CLI-only".
  const acq=hs.acquisition||'';
  const acqNote=hs.available===false ? '' :
    (acq==='ready'
      ? '<div class="panel-note" style="border-inline-start:3px solid var(--ok)">'
        +'<b>Enabled plugins join search.</b> '
        +interfaceTemplateMarkup('ui.every-enabled-plugin-that-declares-c.b262b12d91',
          {capability:'search',plugins:(hs.searchable_plugins||[]).join(', ')})
        +'</div>'
      : '<div class="panel-note panel-warn"><b>Plugins are installed but not '
        +'part of search yet.</b> '+appMessageMarkup(acq)
        +'. '+interfaceMarkup('ui.add-a-rom-hub-download-client-downlo.bf65f18682')
        +' '
        +'<code>rom-hub search</code> / <code>rom-hub import</code> '
        +'inside the container.</div>');

  const p=$('#page');
  p.innerHTML='<div class="empty">Reading the plugin catalogue…</div>';

  // State lives here rather than in the DOM: a filter that has to be read
  // back out of the markup drifts from what is actually displayed.
  let q='', cap='', inst='', actionError=null,catalogueRequest=0;

  const load=async()=>{
    const qs=new URLSearchParams();
    if(q) qs.set('q',q);
    if(cap) qs.set('capability',cap);
    if(inst) qs.set('installed',inst);
    const request=++catalogueRequest;
    const result=await j('/api/v1/hub/catalogue?'+qs.toString())
      .catch(()=>({items:[],facets:{capabilities:[],platforms:[]},error:'ROM Hub unreachable'}));
    return {...result,_catalogueRequest:request};
  };

  const card=pl=>{
    const caps=(pl.capabilities||[]).map(c=>'<span class="pill">'+esc(c)+'</span>').join(' ');
    const net=(pl.network||[]).slice(0,2).join(', ');
    const action = pl.installed
      ? '<span class="'+(pl.enabled?'dot-ok':'dot-off')+'"></span>'
        +'<span class="help" style="margin:0">'+interfaceMarkup(pl.enabled?'Enabled':'Disabled')+'</span>'
        +'<button class="mini" data-act="'+(pl.enabled?'disable':'enable')+'" '
        +'data-slug="'+esc(pl.slug)+'">'+interfaceMarkup(pl.enabled?'Disable':'Enable')+'</button>'
      : '<button class="mini accent" data-act="install" data-slug="'+esc(pl.slug)+'">'+interfaceMarkup('ui.install.569ca49f4a')
        +(pl.key_required?' · '+interfaceMarkup('ui.key-needed.896c85cfc6'):'')+'</button>';
    return '<div class="pcard'+(pl.installed?' installed':'')+'">'
      +'<h4>'+esc(pl.name)+(pl.author?'<span class="by">'
        +interfaceTemplateMarkup('ui.by-author.c63374c540',{author:pl.author})+'</span>':'')+'</h4>'
      +'<div class="desc">'+esc(pl.description||'No description supplied.')+'</div>'
      +'<div class="meta">'+(caps||'<span class="help" style="margin:0">no capabilities declared</span>')+'</div>'
      +'<div class="foot">'+action
      +(net?'<span class="net">'+interfaceTemplateMarkup('ui.reaches-hosts.ad1513043f',{hosts:net})+'</span>':'')+'</div></div>';
  };

  const render=d=>{
    if(renderEpoch!==routeEpoch||location.hash!=='#hub'||d._catalogueRequest!==catalogueRequest)return;
    const items=d.items||[];
    const facets=(d.facets&&d.facets.capabilities)||[];
    const chips=facets.map(([name,n])=>{
      const selected=cap===name;
      return '<button type="button" class="chip'+(selected?' on':'')
        +'" aria-pressed="'+String(selected)+'" data-cap="'+esc(name)+'">'
        +esc(name)+'<span class="n">'+fmt(n)+'</span></button>';
    }).join('');

    p.innerHTML=sandboxNote+acqNote+'<div class="card"><h3>Plugins'
      +'<span class="help" aria-live="polite" aria-atomic="true" style="margin-inline-start:10px">'
      +interfaceTemplateMarkup('ui.showing-shown-of-total-plugins.aed3cf2185',
        {shown:fmt(items.length),total:fmt(d.total||0)})+'</span></h3>'
      +'<div class="cat-bar">'
      +'<label class="sr-only" for="pq">Search plugins</label>'
      +'<input id="pq" placeholder="Search plugins by name, author or description…" value="'+esc(q)+'">'
      +'<button type="button" class="chip'+(inst==='1'?' on':'')+'" aria-pressed="'+String(inst==='1')+'" data-inst="1">Installed</button>'
      +'<button type="button" class="chip'+(inst==='0'?' on':'')+'" aria-pressed="'+String(inst==='0')+'" data-inst="0">Available</button>'
      +chips+'</div>' 
      +(d.error?'<div class="panel-note panel-warn" role="alert" aria-live="assertive">'+appMessageMarkup(d.error)+'</div>':'')
      +(actionError?'<div id="hub-action-error" class="panel-note panel-warn" role="alert" aria-live="assertive">'+(actionError.source
        ?interfaceTemplateMarkup(actionError.source,actionError.values)
        :'<span lang="und" dir="auto">'+esc(actionError.raw)+'</span>')+'</div>':'')
      +'<div class="cat-scroll">'
      +(items.length?'<div class="pgrid">'+items.map(card).join('')+'</div>'
        :'<div class="empty-cat"><b>Nothing matches</b>'
         +'Try a different search, or add your own plugin below.</div>')
      +'</div></div>'

      +'<div class="panels">'
      +'<div class="card"><h3>Add your own</h3>'
      +'<p class="help">Install a plugin straight from its repository — yours, '
      +'or somebody else\'s that is not in the catalogue yet.</p>'
      +'<div class="field"><label for="ownurl">Repository URL</label>'
      +'<input id="ownurl" placeholder="https://github.com/you/rom-hub-your-plugin"></div>'
      +'<button class="mini accent" id="ownadd">Check and install</button>'
      +'<div id="ownmsg" role="status" aria-live="polite" aria-atomic="true"></div>'
      +'<div class="panel-note">A plugin is code ROMarr runs. Only https, and only '
      +'from a forge where you can read the source first — the check tells you which '
      +'hosts are allowed.</div></div>'

      +'<div class="card"><h3>Submit to be featured</h3>'
      +'<p class="help">Propose your plugin for the shared catalogue so everyone '
      +'can find it.</p>'
      +'<div class="field"><label for="sslug">Slug</label><input id="sslug" placeholder="your-plugin"></div>'
      +'<div class="field"><label for="sname">Name</label><input id="sname" placeholder="Your Plugin"></div>'
      +'<div class="field"><label for="srepo">Repository</label><input id="srepo" placeholder="https://github.com/you/your-plugin"></div>'
      +'<div class="field"><label for="scaps">Capabilities</label><input id="scaps" placeholder="search, importer"></div>'
      +'<div class="field"><label for="sdesc">Description</label><textarea id="sdesc" '
      +'placeholder="What it does, and what somebody is trusting when they run it."></textarea></div>'
      +'<button class="mini accent" id="ssubmit">Prepare submission</button>'
      +'<div id="smsg" role="status" aria-live="polite" aria-atomic="true"></div>'
      +'<div class="panel-note">ROMarr does not post this for you. It prepares the '
      +'entry and hands you a link to review and submit yourself.</div></div>'
      +'</div>';

    const qi=$('#pq');
    let t=null;
    qi.oninput=()=>{clearTimeout(t);t=setTimeout(async()=>{
      q=qi.value.trim();
      const at=qi.selectionStart;
      render(await load());
      const n=$('#pq'); n.focus(); n.setSelectionRange(at,at);
    },220);};

    p.querySelectorAll('button.chip[data-cap]').forEach(c=>c.onclick=async()=>{
      const selected=c.dataset.cap;
      cap=cap===selected?'':selected;
      render(await load());
      Array.from(p.querySelectorAll('button.chip[data-cap]'))
        .find(button=>button.dataset.cap===selected)?.focus();
    });
    p.querySelectorAll('button.chip[data-inst]').forEach(c=>c.onclick=async()=>{
      const selected=c.dataset.inst;
      inst=inst===selected?'':selected;
      render(await load());
      p.querySelector(`button.chip[data-inst="${selected}"]`)?.focus();
    });

    p.querySelectorAll('button[data-act]').forEach(b=>b.onclick=async()=>{
      const slug=b.dataset.slug, action=b.dataset.act;
      b.disabled=true; b.textContent='Working…'; actionError=null;
      try{
        const r=await fetch('/api/v1/hub/plugin',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({slug,action})});
        let result={};
        try{result=await r.json();}catch(_){result={};}
        if(!r.ok||result.ok!==true){
          const detail=result.error||result.reason;
          actionError=detail?{raw:detail}:{
            source:`Could not ${action} {slug} (HTTP {status}).`,
            values:{slug,status:r.status}};
        }
      }catch(e){
        actionError={source:`Could not ${action} {slug}: {error}`,values:{
          slug,error:e&&e.message?e.message:
            translateLabel('ui.romarr-did-not-answer.350ec27a93',readInterfaceLanguage())}};
      }
      render(await load());
    });

    $('#ownadd').onclick=async()=>{
      const button=$('#ownadd'),msg=$('#ownmsg');button.disabled=true;
      try{
        const r=await fetch('/api/v1/hub/source/check',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({url:$('#ownurl').value.trim()})});
        const d=await r.json().catch(()=>({})),ok=r.ok&&d.ok===true;
        msg.setAttribute('role',ok?'status':'alert');
        msg.setAttribute('aria-live',ok?'polite':'assertive');
        msg.innerHTML='<div class="panel-note'+(ok?'':' panel-warn')+'">'
          +(ok?interfaceTemplateMarkup('ui.source-accepted-host-installing.06bc7327df',{host:d.host})
            :appMessageMarkup(d.reason||d.error||'Could not check this plugin source.'))+'</div>';
      }catch(_){
        msg.setAttribute('role','alert');msg.setAttribute('aria-live','assertive');
        msg.textContent='ROMarr could not check this source. Check the connection and try again.';
      }finally{button.disabled=false;}
    };

    $('#ssubmit').onclick=async()=>{
      const button=$('#ssubmit'),msg=$('#smsg');button.disabled=true;
      try{
        const r=await fetch('/api/v1/hub/submit',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            slug:$('#sslug').value.trim(), name:$('#sname').value.trim(),
            repository:$('#srepo').value.trim(),
            description:$('#sdesc').value.trim(),
            capabilities:$('#scaps').value.split(',').map(x=>x.trim()).filter(Boolean)})});
        const d=await r.json().catch(()=>({})),problems=d.problems||(!r.ok?[d.error||'Could not prepare this submission.']:[]);
        msg.setAttribute('role',problems.length?'alert':'status');
        msg.setAttribute('aria-live',problems.length?'assertive':'polite');
        if(problems.length){
          msg.innerHTML='<div class="panel-note panel-warn"><b>'+interfaceMarkup('ui.fix-these.e5c50d4696')+'</b><br>'
            +problems.map(appMessageMarkup).join('<br>')+'</div>';
        }else{
          msg.innerHTML='<div class="panel-note">'+interfaceMarkup('ui.ready.e20846d20b')+' '
            +'<a href="'+esc(d.submit_url)+'" target="_blank" rel="noopener noreferrer">'
            +interfaceMarkup('ui.open-the-submission.4a863bf1dd')+'</a> '
            +interfaceMarkup('ui.to-review-and-post-it-yourself.d6c59b1333')+'</div>';
        }
      }catch(_){
        msg.setAttribute('role','alert');msg.setAttribute('aria-live','assertive');
        msg.textContent='ROMarr could not prepare the submission. Check the connection and try again.';
      }finally{button.disabled=false;}
    };
  };

  render(await load());
};

// Searchable single-choice picker (see .pp in the stylesheet). `items` is
// [{value,label,meta}]; the caller puts the "any" row in front itself.
function pickerHtml(id,items,value,ariaLabel){
  const cur=items.find(x=>x.value===value)||items[0]||{value:'',label:''};
  return `<div class="pp" data-pp="${esc(id)}">
    <input type="hidden" id="${esc(id)}" value="${esc(cur.value)}">
    <button type="button" class="pp-btn" aria-haspopup="listbox" aria-expanded="false"
      aria-controls="${esc(id)}-list" aria-label="${esc(ariaLabel||'Choose')}">
      <span class="pp-cur">${esc(cur.label)}${cur.meta?`<i>${esc(cur.meta)}</i>`:''}</span></button>
    <div class="pp-panel" hidden>
      <input type="search" class="pp-q" placeholder="Search…" aria-label="Search the list"
        autocomplete="off" role="combobox" aria-expanded="true" aria-controls="${esc(id)}-list">
      <ul class="pp-list" id="${esc(id)}-list" role="listbox"></ul></div></div>`;
}
document.addEventListener('mousedown',e=>{
  document.querySelectorAll('.pp.open').forEach(b=>{
    if(!b.contains(e.target)) b.querySelector('.pp-btn').dispatchEvent(new CustomEvent('pp-close'));});
},true);
const platPickerItems=any=>(any?[{value:'',label:'Any platform'}]:[])
  .concat(PLATFORMS.map(p=>({value:p.slug,label:p.name})));
function bindPicker(root,id,items,onChange){
  const box=root.querySelector('[data-pp="'+CSS.escape(id)+'"]');
  if(!box) return;
  const btn=box.querySelector('.pp-btn'), panel=box.querySelector('.pp-panel');
  const q=box.querySelector('.pp-q'), list=box.querySelector('.pp-list');
  const hid=box.querySelector('input[type=hidden]'), cur=box.querySelector('.pp-cur');
  let shown=[], act=0;
  const paint=()=>{
    const f=q.value.trim().toLowerCase();
    shown=items.filter(x=>!f||x.label.toLowerCase().includes(f)||String(x.value).toLowerCase().includes(f));
    if(act>=shown.length) act=Math.max(0,shown.length-1);
    list.innerHTML=shown.length?shown.map((x,i)=>`<li class="pp-opt${i===act?' act':''}" role="option"
      id="${esc(id)}-o${i}" data-i="${i}" aria-selected="${x.value===hid.value}"><span>${esc(x.label)}</span>${
      x.meta?`<small>${esc(x.meta)}</small>`:''}</li>`).join('')
      :'<li class="pp-none">Nothing matches.</li>';
    q.setAttribute('aria-activedescendant',shown.length?`${id}-o${act}`:'');
    const a=list.querySelector('.act'); if(a&&a.scrollIntoView) a.scrollIntoView({block:'nearest'});
  };
  const close=(refocus)=>{
    panel.hidden=true; box.classList.remove('open'); btn.setAttribute('aria-expanded','false');
    if(refocus) btn.focus();
  };
  const open=()=>{
    panel.hidden=false; box.classList.add('open'); btn.setAttribute('aria-expanded','true');
    q.value=''; act=Math.max(0,items.findIndex(x=>x.value===hid.value)); paint(); q.focus();
  };
  const choose=i=>{
    const x=shown[i]; if(!x) return;
    hid.value=x.value; cur.innerHTML=esc(x.label)+(x.meta?`<i>${esc(x.meta)}</i>`:'');
    close(true);
    if(onChange) onChange(x.value,hid);
  };
  btn.onclick=()=>panel.hidden?open():close(true);
  btn.addEventListener('pp-close',()=>close(false));
  q.oninput=()=>{act=0;paint();};
  q.onkeydown=e=>{
    if(e.key==='ArrowDown'){e.preventDefault();act=Math.min(act+1,shown.length-1);paint();}
    else if(e.key==='ArrowUp'){e.preventDefault();act=Math.max(act-1,0);paint();}
    else if(e.key==='Enter'){e.preventDefault();choose(act);}
    else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}
    else if(e.key==='Tab') close(false);
  };
  list.onmousedown=e=>e.preventDefault();
  list.onclick=e=>{const li=e.target.closest('.pp-opt'); if(li) choose(Number(li.dataset.i));};
  list.onmousemove=e=>{const li=e.target.closest('.pp-opt');
    if(li&&Number(li.dataset.i)!==act){act=Number(li.dataset.i);
      list.querySelectorAll('.pp-opt').forEach((n,i)=>n.classList.toggle('act',i===act));}};
}

let LIB={platform:'',genre:'',region:'',decade:'',origin:'',source:'',sort:'',
         offset:0,limit:120};
// What each catalogue is called on screen. Spelled out rather than shown as
// the raw key, because "archive" and "flashpoint" mean nothing to somebody
// who did not set the indexers up, and "cloud" has to say plainly that
// ROMarr does not know where those came from.
const SOURCE_LABEL={
  local:'On disk here',
  archive:'Archive.org (streams)',
  flashpoint:'Flashpoint (streams)',
  cloud:'Catalogued, source unknown'};
let libraryRequest=0;
RENDER.library=async(renderEpoch=routeEpoch)=>{
  if(renderEpoch!==routeEpoch||location.hash!=='#library')return;
  const request=++libraryRequest;
  const p=$('#page');
  if(!p.querySelector('#lib-grid')){
    p.innerHTML='<div class="empty" data-i18n="ui.reading-the-library.fe68286704">Reading the library</div>';
    applyInterfaceLanguage();
  }
  const q=($('#search').value||'').trim();
  const d=await j(`/api/v1/game?platform=${encodeURIComponent(LIB.platform)}`
    +`&q=${encodeURIComponent(q)}&offset=${LIB.offset}&limit=${LIB.limit}`
    +`&genre=${encodeURIComponent(LIB.genre)}`
    +`&region=${encodeURIComponent(LIB.region)}`
    +`&decade=${encodeURIComponent(LIB.decade)}`
    +`&origin=${encodeURIComponent(LIB.origin)}`
    +`&source=${encodeURIComponent(LIB.source)}`
    +`&sort=${encodeURIComponent(LIB.sort)}`)
    .catch(()=>({items:[],error:'Unreachable'}));
  if(renderEpoch!==routeEpoch||request!==libraryRequest||location.hash!=='#library')return;

  if(d.loading){
    // The first fetch has not landed yet. Say so, rather than showing an
    // empty grid that reads as "your library is empty".
    p.innerHTML=`<div class="card"><h3 data-i18n="ui.reading-the-library.fe68286704">Reading the library</h3>
      <p class="help">${d.message?appMessageMarkup(d.message):'<span data-i18n="ui.fetching-from-romm.24384ccda6">Fetching from RomM…</span>'}
      ${d.error?` <span data-i18n="ui.last-attempt.3ec078252b">Last attempt:</span> <b>${appMessageMarkup(d.error)}</b>. <span data-i18n="ui.retrying-with-backoff.06028a831f">Retrying with backoff.</span>`:''}</p></div>`;
    applyInterfaceLanguage();
    return;
  }

  const items=d.items||[];
  const T=d.totals||{};
  // Every platform the library server holds, from the first second --
  // even ones the background walk has not reached. When a platform is only
  // partly cached the chip says so rather than under-reporting silently.
  //
  // The number on a chip is the platform's whole row count, and on its own
  // that was actively misleading: "Browser 94,415" sat beside "Nintendo DS
  // 8,112" looking like the same claim, when not one of those 94,415 is a
  // file on this disk. A chip whose contents are wholly or partly catalogued
  // now shows the split and says which is which on hover.
  // 49 platforms do not fit as a wall of buttons, so they live in a searchable
  // picker. The count is still the platform's whole row count; "N here" is the
  // part that is a file on this disk, and a partly-read platform says so.
  const platItems=[{value:'',label:'All platforms',meta:fmt(d.grand_total)}]
    .concat((d.platforms||[]).map(x=>{
      const part=x.cached!==undefined&&x.cached<x.count;
      const cat=x.catalogued||0, disk=x.on_disk||0;
      return {value:x.platform,label:x.platform,
        meta:(part?fmt(x.cached)+'/'+fmt(x.count):fmt(x.count))+(cat>0?' · '+fmt(disk)+' here':'')};
    }));
  const f=d.facets||{};
  const sel=(key,label,list,fmt)=>{
    if(!list||!list.length) return '';
    const filterName=({genre:'Genre',region:'Region',decade:'Decade',origin:'Origin',source:'Source',sort:'Sort by'})[key]||label;
    return `<select data-lf="${key}" aria-label="${esc(translateLabel(filterName,readInterfaceLanguage()))}" data-i18n-aria-label="${esc(stableLocalizationKey(filterName)||filterName)}" style="padding:4px 8px;font-size:12px">
      <option value="" data-i18n-key="${esc(stableLocalizationKey(label)||label)}">${esc(translateLabel(label,readInterfaceLanguage()))}</option>
      ${list.map(x=>`<option value="${esc(x.value)}"${LIB[key]===x.value?' selected':''}
        >${esc(fmt?fmt(x.value):x.value)} (${num(x.count)})</option>`).join('')}
    </select>`;
  };
  const coverage=f.identified&&d.grand_total
    ? Math.round(f.identified/d.grand_total*100) : 0;
  // The headline. Three numbers where there used to be one, because the one
  // was the other two added together and nothing said so: a shelf of 166,548
  // reads as a collection twice the size of the 72,120 files that are
  // actually here. The middle number is the interesting one -- it is what
  // would have to be fetched or streamed before anybody could play it.
  const srcRows=(f.sources||[]).filter(x=>x.value!=='local');
  const readNote=T.counted_from==='cached rows'
    ?`${interfaceTemplateMarkup('ui.read-count-rows-so-far-the-library-s.020b2c0f2b',{count:num(d.cached_total)})}${d.partial?' '+interfaceMarkup('ui.the-read-is-still-in-progress.cd7ca40347'):''}`
    :((T.total!==null&&T.total!==undefined&&d.cached_total<T.total)
      ?`${interfaceTemplateMarkup('ui.count-rows-are-loaded-and-browsable.7b49767919',{count:num(d.cached_total)})}${d.partial?' '+interfaceMarkup('ui.the-read-is-still-in-progress.cd7ca40347'):''}`:'');
  const banner=`<div class="libstats">
      <div><b>${num(T.on_disk)}</b><span data-i18n="ui.on-disk-here.6d4649d06e">On disk here</span></div>
      <div><b>${num(T.catalogued)}</b><span data-i18n="ui.catalogued-streams.31a406530a">Catalogued, streams</span></div>
      <div><b>${num(T.total)}</b><span data-i18n="ui.total-known.d0c9d103f3">Total known</span></div>
      ${readNote?`<p class="help" style="flex-basis:100%;margin:0">${readNote}</p>`:''}
      ${srcRows.length?`<details><summary>How these are counted</summary>
        <p class="help" style="margin:6px 0 0">Catalogued entries by source:
        ${srcRows.map(x=>`<b style="font-size:inherit">${num(x.count)}</b> ${esc(SOURCE_LABEL[x.value]||x.value)}`).join(' · ')}.
        Source is read from the filename each indexer writes, so anything ROMarr cannot place
        stays “source unknown” rather than being filed under a guess.</p></details>`:''}
    </div>`;
  const head=banner+`<div class="lfrow">
      ${pickerHtml('lib-plat',platItems,LIB.platform,'Platform')}
      ${sel('genre','Any genre',f.genres)}
      ${sel('region','Any region',f.regions)}
      ${sel('decade','Any decade',f.decades)}
      ${(f.origins||[]).length>1?sel('origin','On disk & catalogued',f.origins,
        v=>v==='local'?'On disk (plays now)':'Catalogued (needs fetching)'):''}
      ${(f.sources||[]).length>1?sel('source','Any source',f.sources,
        v=>SOURCE_LABEL[v]||v):''}
      <select data-lf="sort" aria-label="Sort by" data-i18n-aria-label="ui.sort-by.c9129025bd" style="padding:4px 8px;font-size:12px">
        <option value="" data-i18n="ui.platform-then-name.bb91fdb134"${LIB.sort?'':' selected'}>Platform, then name</option>
        <option value="name" data-i18n="ui.name-az.7ed9662907"${LIB.sort==='name'?' selected':''}>Name A–Z</option>
        <option value="rating" data-i18n="ui.top-rated.5f12603835"${LIB.sort==='rating'?' selected':''}>Top rated</option>
        <option value="year" data-i18n="ui.newest-first.ffb6f5764b"${LIB.sort==='year'?' selected':''}>Newest first</option>
      </select>
      ${(LIB.genre||LIB.region||LIB.decade||LIB.origin||LIB.source||LIB.sort)
        ?'<button class="btn ghost" id="lf-clear" data-i18n="ui.clear-filters.7179ea0035" style="padding:4px 10px;font-size:12px">Clear filters</button>':''}
      ${(f.genres||[]).length?`<span class="help" style="margin:0;font-size:11.5px;flex-basis:100%" data-i18n-template="genre/year known for {identified} of {total} ({coverage}%) — run a metadata scan in your library server to raise it"
        data-i18n-values="${esc(JSON.stringify({identified:fmt(f.identified),total:fmt(d.grand_total),coverage:fmt(coverage)}))}">${esc(translateTemplate('genre/year known for {identified} of {total} ({coverage}%) — run a metadata scan in your library server to raise it',{identified:fmt(f.identified),total:fmt(d.grand_total),coverage:fmt(coverage)}))}</span>`:''}
    </div>
    <p class="help" style="margin-bottom:10px">
      ${interfaceTemplateMarkup('ui.showing-start-end-of-total.64af6de234',{start:fmt(d.total?LIB.offset+1:0),end:fmt(Math.min(LIB.offset+items.length,d.total)),total:fmt(d.total)})}
      ${LIB.platform?` ${interfaceTemplateMarkup('ui.on-platform.351081c667',{platform:LIB.platform})}`:''}${q?` ${interfaceTemplateMarkup('ui.matching-query.12aacdc131',{query:q})}`:''}
      · ${interfaceTemplateMarkup('ui.cached-cached-across-platformcount-p.55b169ed05',{cached:fmt(d.grand_total),platformCount:fmt((d.platforms||[]).length)})}
      ${d.partial?` · <b>${interfaceMarkup('ui.still-loading-from-the-library-serve.4b07f1a4b9')}</b>`:''}
      ${d.error?` · ${interfaceMarkup('ui.last-refresh.519ad138a1')} ${appMessageMarkup(d.error)}`:''}</p>`;

  if(!items.length){
    p.innerHTML=head+`<div class="empty">
      ${q||LIB.platform?'<span data-i18n="ui.no-game-matches-that.0cda910221">No game matches that.</span>':'<span data-i18n="ui.no-games-returned-by-the-library.342cfd2c29">No games returned by the library.</span>'}</div>`;
    applyInterfaceLanguage(); bindLibraryChips(p,platItems); return;
  }
  // The shelf: status, rating and notes set by the operator, overlaid on the
  // grid. One fetch for the whole page -- the metadata is tiny.
  const meta=await j('/api/v1/game/meta').catch(()=>({items:[]}));
  const shelf={};
  (meta.items||[]).forEach(x=>{
    shelf[`${x.platform}/${(x.game||'').toLowerCase()}`]=x; });
  const mark=g=>{
    const x=shelf[`${g.platform||''}/${(g.name||'').toLowerCase()}`];
    if(!x) return '';
    const bits=[];
    if(x.status) bits.push(`<span class="pill">${statusMarkup(x.status)}</span>`);
    if(x.rating) bits.push(`<span class="pill">★ ${num(x.rating)}</span>`);
    return bits.length?`<div style="margin-top:2px">${bits.join(' ')}</div>`:'';
  };
  const grid=`<div class="grid" id="lib-grid">${items.map((g,i)=>`<div class="tile"
      data-shelf="${i}" style="cursor:pointer" title="Open game page">
      <div class="art" style="background-image:url('${esc(g.cover||'')}')"></div>
    <div class="nm" lang="und" dir="auto">${esc(g.name)}</div>
    <div class="pf" lang="und" dir="auto">${esc(g.platform||'')}</div>${mark(g)}</div>`).join('')}</div>`;
  const more=LIB.offset+items.length<d.total
    ?`<div class="row" style="justify-content:center;margin:16px 0">
       <button class="btn" id="lib-more">${interfaceTemplateMarkup('ui.show-more-count-left.e19d54d077',{count:fmt(d.total-LIB.offset-items.length)})}</button></div>`:'';
  p.innerHTML=head+grid+more;
  if(q||d.error){
    const live=$('#app-announcement');
    if(live)live.textContent=d.error?'Could not load the game library.':fmt(d.total||0)+' games found.';
  }
  applyInterfaceLanguage();
  bindLibraryChips(p,platItems);
  const moreBtn=p.querySelector('#lib-more');
  if(moreBtn) moreBtn.onclick=()=>{LIB.limit+=240;go('library');};
  document.querySelectorAll('[data-shelf]').forEach(t=>{
    const g=items[Number(t.dataset.shelf)];
    t.setAttribute('role','link'); t.tabIndex=0;
    const open=()=>{ location.hash='game/'+encodeURIComponent(g.platform_slug||'')+'/'+encodeURIComponent(g.id); };
    t.onclick=open; t.onkeydown=e=>{ if(e.key==='Enter') open(); };
  });
};

function bindLibraryChips(p,platItems){
  bindPicker(p,'lib-plat',platItems||[],v=>{
    LIB.platform=v; LIB.offset=0; LIB.limit=120;
    go('library');
  });
  p.querySelectorAll('[data-lf]').forEach(s=>s.onchange=()=>{
    LIB[s.dataset.lf]=s.value; LIB.offset=0; LIB.limit=120;
    go('library');
  });
  const clear=p.querySelector('#lf-clear');
  if(clear) clear.onclick=()=>{
    LIB.genre=LIB.region=LIB.decade=LIB.origin=LIB.source=LIB.sort='';
    LIB.offset=0; LIB.limit=120; go('library');
  };
}

function shelfEditor(g, meta){
  const m=document.createElement('div');
  m.className='modal';
  const opt=(v,label)=>{
    const source=String(label??'');
  const marker=hasLabel(source)?` data-i18n-key="${esc(stableLocalizationKey(source)||source)}"`:'';
    return `<option value="${esc(v)}"${(meta.status||'')===v?' selected':''}${marker}>${esc(translateLabel(source,readInterfaceLanguage()))}</option>`;
  };
  m.innerHTML=`<div class="box">
    <h3 lang="und" dir="auto">${esc(g.name)}</h3>
    <div class="sub">${esc(g.platform||'')} &mdash; ${interfaceMarkup('ui.your-shelf-status-rating-and-notes-f.beb2e14d15')}</div>
    <div class="field"><label>Status</label>
      <select data-f="status">${opt('','—')}${opt('playing','Playing')}
        ${opt('completed','Completed')}${opt('shelved','Shelved')}</select></div>
    <div class="field"><label>Rating</label>
      <select data-f="rating"><option value="0" data-i18n="ui.unrated.c1748608e8">unrated</option>
        ${[1,2,3,4,5,6,7,8,9,10].map(n=>`<option value="${n}"${
          meta.rating===n?' selected':''}>${'★'.repeat(Math.ceil(n/2))} ${fmt(n)}/10</option>`).join('')}
      </select></div>
    <div class="field"><label>Notes</label>
      <textarea data-f="notes" rows="4"
        style="width:100%;resize:vertical">${esc(meta.notes||'')}</textarea></div>
    <div class="foot">
      <button class="btn ghost sp" data-close>Cancel</button>
      <button class="btn" id="sh-save">Save</button>
    </div></div>`;
  openModal(m);
  m.onclick=e=>{ if(e.target===m||e.target.dataset.close!==undefined) closeModal(); };
  m.querySelector('#sh-save').onclick=async()=>{
    const f=readForm();
    const r=await j('/api/v1/game/meta',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({platform:g.platform||'',game:g.name,
        status:f.status,rating:Number(f.rating)||0,notes:f.notes})});
    closeModal();
    if(r.error)toastAppMessage(r.error);else toastLabel('ui.saved.b5c120b316'); if(!r.error) go(location.hash.slice(1)||'library');
  };
}

// ---- Releases: the scored list, with a Grab button on each row -----------
// One implementation for the Add New flow and the game page, so a release
// chosen by hand behaves identically wherever it was picked.
async function renderReleases(out,game,platform){
  const mb=n=>n>=1048576?(n/1048576).toLocaleString(getRegionalLocale(),{maximumFractionDigits:1})+' MB'
    :n>0?(n/1024).toLocaleString(getRegionalLocale(),{maximumFractionDigits:0})+' KB':'—';
  out.innerHTML='<div class="empty" data-i18n="ui.searching-indexers.ae3d974c9a">Searching indexers…</div>'; applyInterfaceLanguage();
  const d=await j(`/api/v1/release?game=${encodeURIComponent(game)}`
    +`&platform=${encodeURIComponent(platform)}`).catch(()=>({error:'Search failed'}));
  if(d.error){
    out.innerHTML=`<p class="help" style="color:var(--warn)">${appMessageMarkup(d.error)}</p>`;
    return;
  }
  if(!d.items.length){
    out.innerHTML='<div class="empty" data-i18n="ui.nothing-found-a-search-where-every-i.cf40aad291">Nothing found. A search where every indexer fails looks exactly like one that found nothing — check Indexers if this is unexpected.</div>';
    applyInterfaceLanguage();
    return;
  }
  const indexerTitle=r=>r.indexer
    ? `title="${esc(translateTemplate('Open on {indexer}',{indexer:r.indexer}))}"
       data-i18n-title-template-key="ui.open-on-indexer.202e1ad5f5"
       data-i18n-title-values="${esc(JSON.stringify({indexer:r.indexer}))}"`
    : `title="${esc(translateLabel('ui.open-on-the-indexer.4766c56d0d',readInterfaceLanguage()))}"
       data-i18n-title="ui.open-on-the-indexer.4766c56d0d"`;
  out.innerHTML=`
    <p class="help">${interfaceTemplateMarkup('ui.found-found-releases-accepted-match.65f542cd3e',{found:fmt(d.found),accepted:fmt(d.accepted)})}</p>
    <div class="tablewrap"><table><thead><tr><th data-i18n="ui.score.38e5a46cbc">Score</th><th data-i18n="ui.release.e020e3c67b">Release</th><th data-i18n="ui.size.1af8519073">Size</th>
      <th data-i18n="ui.seeders.40abd71e74">Seeders</th><th data-i18n="ui.indexer.4a8a73e215">Indexer</th><th data-i18n="ui.why.d3ae14a50b">Why</th><th></th></tr></thead><tbody>
    ${d.items.map(r=>`<tr>
      <td><span class="pill ${r.accepted?'imported':'failed'}">${num(r.score)}</span></td>
      <td><span lang="und" dir="auto">${esc(r.title)}</span>${r.info_url?` <a href="${esc(r.info_url)}" target="_blank"
          rel="noopener noreferrer"
          ${indexerTitle(r)} lang="und" dir="auto"
          style="text-decoration:none">&#8599;</a>`:''}
        ${r.private?' <span class="pill">private</span>':''}
        ${r.protocol==='usenet'?' <span class="pill">usenet</span>':''}</td>
      <td style="white-space:nowrap">${mb(r.size)}</td>
      <td>${num(r.seeders)}</td>
      <td style="color:var(--dim)" lang="und" dir="auto">${esc(r.indexer||'—')}</td>
      <td style="color:var(--dim);font-size:12px">${r.reasons.map(searchReasonMarkup).join('<br>')}</td>
      <td><div class="rowact">${r.grabbable
        ? `<button data-grab="${esc(r.id)}" data-i18n="ui.grab.7d935f2589">Grab</button>`
        : '<span style="color:var(--dim);font-size:12px">'+interfaceMarkup('ui.no-link.9563affc02')+'</span>'}</div></td>
      </tr>`).join('')}</tbody></table></div>`;
  applyInterfaceLanguage();
  out.querySelectorAll('[data-grab]').forEach(b=>b.onclick=async()=>{
    b.disabled=true; b.dataset.i18n='Grabbing…'; applyTranslatedLabel(b,readInterfaceLanguage());
    const r=await j('/api/v1/release/grab',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({id:b.dataset.grab})});
    b.dataset.i18n=r.ok?'Grabbed':'Failed'; applyTranslatedLabel(b,readInterfaceLanguage());
    if(r.ok)toastMessage('ui.grabbed-release.94cc8b2735',{release:r.release});
    else if(r.error)toastAppMessage(r.error);else toastLabel('ui.could-not-grab-that-release.8861451b16');
    refreshCounts();
  });
}

// ---- Add New: find a game, then add it the way Radarr's Add dialog does ----
const STATE_LABEL={library:'In library',downloading:'Downloading',monitored:'Monitored',
  unmonitored:'Not monitored','':'Not added'};
const stateBadge=st=>`<span class="sb sb-${esc(st||'none')}">${esc(STATE_LABEL[st||'']||'')}</span>`;
const gameHref=(slug,id,title)=>'#game/'+encodeURIComponent(slug)+'/'
  +(id?encodeURIComponent(id):'~'+encodeURIComponent(title));

// The Add dialog: platform, monitor, and what to do right now.
function addDialog({title,options,platform,afterAdd}){
  const m=document.createElement('div'); m.className='modal';
  const opts=(options&&options.length?options:PLATFORMS.map(p=>({slug:p.slug,name:p.name,state:''})));
  const start=opts.find(o=>o.slug===platform)||opts.find(o=>o.state!=='library')||opts[0]||{slug:'',name:'',state:''};
  m.innerHTML=`<div class="box" role="dialog" aria-modal="true" aria-label="Add game">
    <h3 lang="und" dir="auto">${esc(title||'Add a game')}</h3>
    <div class="sub">Add it to Wanted. ROMarr searches your indexers and watches new releases for it.</div>
    ${title?'':`<div class="field"><label>Title</label><input type="text" id="ad-title" lang="und" dir="auto"></div>`}
    <div class="field"><label>Platform</label>
      ${options&&options.length===1
        ? `<div>${esc(start.name)}</div><input type="hidden" id="ad-plat" value="${esc(start.slug)}">`
        : pickerHtml('ad-plat',opts.map(o=>({value:o.slug,label:o.name,meta:o.state?STATE_LABEL[o.state]:''})),start.slug,'Platform')}</div>
    <label class="check"><input type="checkbox" id="ad-mon" checked>
      <span>Monitor — keep searching and watching RSS until it is found. Uncheck to keep it on your wishlist without searching.</span></label>
    <div class="field"><label>When added</label>
      <select id="ad-search">
        <option value="auto">Search now and grab the best release</option>
        <option value="manual">Search now and let me choose the release</option>
        <option value="none">Only add it</option></select></div>
    <div class="foot"><button class="btn ghost sp" data-close>Cancel</button>
      <button class="btn" id="ad-go">Add game</button></div></div>`;
  openModal(m);
  if(!(options&&options.length===1)) bindPicker(m,'ad-plat',opts.map(o=>({value:o.slug,label:o.name,meta:o.state?STATE_LABEL[o.state]:''})));
  m.onclick=e=>{ if(e.target===m||e.target.dataset.close!==undefined) closeModal(); };
  const ti=m.querySelector('#ad-title'); if(ti) ti.focus();
  m.querySelector('#ad-go').onclick=async()=>{
    const game=(ti?ti.value:title).trim(), plat=m.querySelector('#ad-plat').value;
    if(!game){toastLabel('ui.enter-a-game-name.ea7e4635a4');return;}
    const mode=m.querySelector('#ad-search').value, monitored=m.querySelector('#ad-mon').checked;
    const btn=m.querySelector('#ad-go'); btn.disabled=true; btn.textContent='Adding…';
    const r=await j('/api/v1/wanted/add',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({game,platform:plat,monitored,search:mode==='auto'})}).catch(()=>({ok:false,error:'Request failed'}));
    closeModal();
    if(!r.ok){toastAppMessage(r.error||'Could not add that game');return;}
    refreshCounts();
    if(mode==='manual'){ location.hash='game/'+encodeURIComponent(plat)+'/~'+encodeURIComponent(game)+'/search'; return; }
    if(mode==='auto'){
      const s=r.search||{};
      toastAppMessage(s.ok?('Grabbed '+(s.release||game)):('Added'+(monitored?' and monitored':'')+' — no release yet, ROMarr will keep looking'));
    }else toastAppMessage('Added '+game+(monitored?' (monitored)':''));
    if(afterAdd) afterAdd();
  };
}

RENDER.add=async()=>{
  const page=$('#page');
  page.innerHTML=`<div class="card">
    <h3>Add New Game</h3>
    <p class="help">Search for a game, pick it, and ROMarr will find it — now or when a release turns up. Games already on your shelf are marked.</p>
    <div class="row">
      <div class="field" style="flex:1;min-width:220px;margin:0"><label>Game</label>
        <input type="search" id="a-q" placeholder="Search for a game…" lang="und" dir="auto" autocomplete="off"></div>
      <div class="field" style="width:230px;margin:0"><label>Platform</label>
        ${pickerHtml('a-plat',platPickerItems(true),'','Platform')}</div>
      <button class="btn" id="a-go" style="margin-top:20px">Search</button>
    </div>
    <div id="a-out" style="margin-top:16px"></div></div>`;
  bindPicker(page,'a-plat',platPickerItems(true),()=>{ if(($('#a-q').value||'').trim()) run(); });
  applyInterfaceLanguage();
  const out=$('#a-out'); let seq=0;
  const manualLink=()=>`<p class="help" style="margin-top:14px">Can’t find it? <a href="#" id="a-manual">Add it by exact title</a>.</p>`;
  const bindManual=()=>{ const a=$('#a-manual'); if(a) a.onclick=e=>{e.preventDefault();
    addDialog({title:'',options:null,platform:$('#a-plat').value||''});}; };
  const run=async()=>{
    const q=$('#a-q').value.trim();
    if(q.length<2){out.innerHTML='';return;}
    const mine=++seq;
    out.innerHTML='<div class="empty">Searching…</div>';
    const d=await j('/api/v1/lookup?q='+encodeURIComponent(q)+'&platform='+encodeURIComponent($('#a-plat').value||''))
      .catch(()=>({configured:true,items:[],error:'Search failed'}));
    if(mine!==seq) return;
    if(d.configured===false){
      out.innerHTML=`<p class="help" style="color:var(--warn)">Game search needs an IGDB connection (Metadata settings). You can still add a game by its exact title.</p>${manualLink()}`;
      bindManual(); return;
    }
    if(d.error){ out.innerHTML=`<p class="help" style="color:var(--warn)">${esc(d.error)}</p>${manualLink()}`; bindManual(); return; }
    if(!d.items.length){ out.innerHTML=`<div class="empty">No games found for “${esc(q)}”.</div>${manualLink()}`; bindManual(); return; }
    out.innerHTML=`<div class="rcgrid">${d.items.map((g,i)=>`<div class="rc" data-i="${i}">
        <div class="rc-art" style="background-image:url('${esc(g.cover||'')}')"></div>
        <div class="rc-body">
          <div class="rc-t" lang="und" dir="auto">${esc(g.title)}${g.year?` <span class="rc-y">${g.year}</span>`:''}</div>
          <div class="rc-g">${esc((g.genres||[]).slice(0,3).join(' · '))}</div>
          <div class="rc-s">${esc(g.summary||'')}</div>
          <div class="rc-p">${g.options.map(o=>`<button type="button" class="rc-opt" data-slug="${esc(o.slug)}"
            title="${esc(STATE_LABEL[o.state||'']||'')}">${esc(o.name)} ${stateBadge(o.state)}</button>`).join('')}</div>
        </div></div>`).join('')}</div>${manualLink()}`;
    bindManual();
    out.querySelectorAll('.rc-opt').forEach(b=>b.onclick=e=>{
      e.stopPropagation();
      const g=d.items[Number(b.closest('.rc').dataset.i)], slug=b.dataset.slug;
      const opt=g.options.find(o=>o.slug===slug)||{};
      if(opt.state==='library'){ location.hash='game/'+encodeURIComponent(slug)+'/~'+encodeURIComponent(g.title); return; }
      addDialog({title:g.title,options:g.options,platform:slug,afterAdd:run});
    });
    out.querySelectorAll('.rc').forEach(c=>c.onclick=()=>{
      const g=d.items[Number(c.dataset.i)];
      if(g.options.length===1){ c.querySelector('.rc-opt').click(); }
      else addDialog({title:g.title,options:g.options,platform:'',afterAdd:run});
    });
  };
  $('#a-go').onclick=run;
  let t=null; $('#a-q').oninput=()=>{clearTimeout(t);t=setTimeout(run,450);};
  $('#a-q').onkeydown=e=>{ if(e.key==='Enter'){clearTimeout(t);run();} };
  $('#a-q').focus();
};

// Old links and bookmarks to Interactive Search land on the merged page.
RENDER.search=async()=>RENDER.add();


// ---- Switch updates and DLC (switch-library-manager's report) --------------
const SWU_BADGE={current:['sb-library','Up to date'],outdated:['sb-monitored','Update available'],
  missing:['sb-monitored','No update installed'],unknown:['','Not in TitleDB']};
let SWU_GAPS=true;
RENDER.switchupdates=async(renderEpoch=routeEpoch,refresh=false)=>{
  const page=$('#page');
  page.innerHTML='<div class="empty">Reading your Switch folders and comparing with TitleDB…</div>';
  const d=await j('/api/v1/switch/updates'+(refresh?'?refresh=1':'')).catch(()=>null);
  if(renderEpoch!==routeEpoch) return;
  if(!d||!d.summary){ page.innerHTML='<div class="empty">Could not build the report.</div>'; return; }
  const S=d.summary;
  const rows=d.items.filter(i=>!SWU_GAPS||i.update==='missing'||i.update==='outdated'||(i.dlc_missing||[]).length)
    .sort((a,b)=>a.game.localeCompare(b.game));
  const v=n=>n==null?'—':('v'+fmt(n));
  page.innerHTML=`<div class="libstats">
      <div><b>${fmt(S.games)}</b><span>games scanned</span></div>
      <div><b>${fmt(S.update_gaps)}</b><span>need an update</span></div>
      <div><b>${fmt(S.dlc_gaps)}</b><span>DLC not on disk</span></div>
      <div><b>${fmt(S.unknown_to_titledb)}</b><span>unknown to TitleDB</span></div></div>
    ${S.dlc_lists_complete?'':'<p class="help" style="color:var(--warn)">DLC lists are incomplete: TitleDB’s names file is not loaded, so only DLC that has its own version history is checked. Updates are unaffected.</p>'}
    <div class="row" style="margin-bottom:12px">
      <button class="btn ${SWU_GAPS?'':'ghost'}" id="swu-gaps">${SWU_GAPS?'Showing only games with gaps':'Showing every game'}</button>
      <button class="btn ghost" id="swu-scan">Rescan</button>
      <span class="help" style="margin:0">Switch 2 titles are mostly missing from TitleDB, so they show as unknown rather than current.</span></div>
    ${rows.length?`<div class="tablewrap"><table><thead><tr><th>Game</th><th>Platform</th><th>Installed</th><th>Latest</th><th>Update</th><th>DLC</th><th></th></tr></thead><tbody>
      ${rows.map(i=>{const b=SWU_BADGE[i.update]||['',i.update];return `<tr>
        <td lang="und" dir="auto"><a href="${esc(gameHref(i.platform,i.rom_id,i.game))}">${esc(i.game)}</a></td>
        <td>${esc(i.platform)}</td><td>${v(i.installed_version)}</td><td>${v(i.latest_version)}</td>
        <td><span class="sb ${b[0]}" style="margin:0">${esc(b[1])}</span></td>
        <td>${i.dlc_total==null?'—':fmt(i.dlc_installed)+' / '+fmt(i.dlc_total)}${(i.dlc_missing||[]).length?` <span class="sb sb-monitored">${fmt(i.dlc_missing.length)} missing</span>`:''}</td>
        <td><a class="btn ghost" style="padding:3px 10px;font-size:12px;text-decoration:none" href="${esc(gameHref(i.platform,i.rom_id,i.game))}">Open</a></td></tr>`;}).join('')}
      </tbody></table></div>`:'<div class="empty">Nothing to update. Every scanned game is current.</div>'}
    <p class="help" style="margin-top:10px">Read from the file names in your library (title ID and version). Report generated ${esc(regionalDate(d.generated||''))}.</p>`;
  $('#swu-gaps').onclick=()=>{SWU_GAPS=!SWU_GAPS; RENDER.switchupdates(routeEpoch);};
  $('#swu-scan').onclick=()=>RENDER.switchupdates(routeEpoch,true);
};

// ---- The game page ---------------------------------------------------------
RENDER.game=async(renderEpoch=routeEpoch)=>{
  const [slug,idOrTitle,flag]=ROUTE_ARGS;
  const page=$('#page');
  const isTitle=(idOrTitle||'').startsWith('~');
  const d=await j('/api/v1/game/detail?platform='+encodeURIComponent(slug||'')
    +(isTitle?'&title='+encodeURIComponent(idOrTitle.slice(1)):'&id='+encodeURIComponent(idOrTitle||''))
    ).catch(()=>null);
  if(renderEpoch!==routeEpoch) return;
  if(!d||!d.title){ page.innerHTML='<div class="empty">Game not found.</div>'; return; }
  const it=d.item||{}, w=d.wanted, q=d.queue||[], h=d.history||[];
  const state=d.in_library?'library':(q.some(x=>['grabbed','downloading','queued'].includes(x.state))?'downloading'
    :(w?(w.monitored?'monitored':'unmonitored'):''));
  const facts=[['Released',it.released],['Rating',it.rating?('★ '+num(it.rating)):''],
    ['Genres',(it.genres||[]).join(', ')],['Franchise',(it.franchises||[]).join(', ')],
    ['Developer / publisher',(it.companies||[]).join(', ')],['Modes',(it.modes||[]).join(', ')],
    ['Players',it.players],['In RomM since',it.added]].filter(x=>x[1]);
  page.innerHTML=`<div class="card gh">
      <div class="gh-art" style="background-image:url('${esc(it.cover||'')}')"></div>
      <div class="gh-main">
        <h2 lang="und" dir="auto">${esc(d.title)} ${it.year?`<span class="rc-y">${it.year}</span>`:''}</h2>
        <div class="gh-sub">${esc(d.platform_name)} ${stateBadge(state)}</div>
        <div class="gh-act">
          ${d.romm_url?`<a class="btn" href="${esc(d.romm_url)}" target="_blank" rel="noopener noreferrer">Open in RomM ↗</a>`:''}
          ${!d.in_library?`<button class="btn" id="g-add">${w?'Search now':'Add to Wanted'}</button>`:''}
          ${w?`<button class="btn ghost" id="g-mon" aria-pressed="${w.monitored}">${w.monitored?'Monitored ✓':'Not monitored'}</button>`:''}
          <button class="btn ghost" id="g-int">Interactive search</button>
          <button class="btn ghost" id="g-shelf">Shelf: status, rating, notes</button>
        </div>
        ${d.in_library?`<p class="help" style="margin-top:10px">Metadata, covers and files are managed in RomM — use “Open in RomM” to change them.</p>`:''}
        ${facts.length?`<dl class="gh-facts">${facts.map(([k,v])=>`<dt>${esc(k)}</dt><dd lang="und" dir="auto">${esc(v)}</dd>`).join('')}</dl>`:''}
        ${(d.meta&&(d.meta.status||d.meta.rating||d.meta.notes))?`<p class="help" style="margin-top:10px">
          ${d.meta.status?`<span class="pill">${esc(d.meta.status)}</span> `:''}${d.meta.rating?`<span class="pill">★ ${num(d.meta.rating)}/10</span> `:''}
          ${esc(d.meta.notes||'')}</p>`:''}
      </div></div>
    <div id="g-swu"></div>
    <div class="card" id="g-rel" ${flag==='search'?'':'hidden'}><h3>Interactive search</h3><div id="g-relout"></div></div>
    ${q.length?`<div class="card"><h3>Downloads</h3><div class="tablewrap"><table><thead><tr><th>Release</th><th>State</th><th>Detail</th></tr></thead><tbody>
      ${q.map(x=>`<tr><td lang="und" dir="auto">${esc(x.release||'—')}</td><td>${esc(x.state)}</td><td style="color:var(--dim)">${esc(x.detail||'')}</td></tr>`).join('')}</tbody></table></div></div>`:''}
    ${h.length?`<div class="card"><h3>History</h3><div class="tablewrap"><table><thead><tr><th>When</th><th>Event</th><th>Release</th><th>Detail</th></tr></thead><tbody>
      ${h.map(x=>`<tr><td>${esc(regionalDate(x.at||x.time||''))}</td><td>${esc(x.kind)}</td><td lang="und" dir="auto">${esc(x.release||'')}</td><td style="color:var(--dim)">${esc(x.detail||'')}</td></tr>`).join('')}</tbody></table></div></div>`:''}
    ${(!d.in_library&&w&&w.last_error)?`<p class="help">Last search: ${esc(w.last_error)} (${fmt(w.attempts)} attempt${w.attempts===1?'':'s'})</p>`:''}`;
  applyInterfaceLanguage();
  const relBox=$('#g-rel'), relOut=$('#g-relout');
  if(d.in_library&&(d.platform==='switch'||d.platform==='switch-2')){
    j('/api/v1/switch/updates?game='+encodeURIComponent(d.title)).then(r=>{
      if(renderEpoch!==routeEpoch||!r.items||!r.items.length) return;
      const box=$('#g-swu'); if(!box) return;
      box.innerHTML=`<div class="card"><h3>Updates &amp; DLC</h3>${r.items.map(i=>{const b=SWU_BADGE[i.update]||['',i.update];return `
        <p>Installed <b>${i.installed_version!=null?'v'+fmt(i.installed_version):'—'}</b> ·
          latest known <b>${i.latest_version!=null?'v'+fmt(i.latest_version):'—'}</b>
          <span class="sb ${b[0]}">${esc(b[1])}</span>
          ${(i.update==='missing'||i.update==='outdated')?`<button class="btn ghost swu-find" data-q="${esc(d.title+' update')}" style="margin-inline-start:8px;padding:3px 10px;font-size:12px">Search for the update</button>`:''}</p>
        <p class="help">DLC: ${i.dlc_total==null?'not checked':fmt(i.dlc_installed)+' of '+fmt(i.dlc_total)+' on disk'}${i.dlc_complete_list?'':' (list may be incomplete)'}</p>
        ${(i.dlc_missing||[]).length?`<ul class="swu-dlc">${i.dlc_missing.map(x=>`<li><span lang="und" dir="auto">${esc(x.name||x.tid)}</span>
          <code>${esc(x.tid)}</code> <button class="btn ghost swu-find" data-q="${esc(d.title+' '+(x.name||'DLC'))}" style="padding:2px 9px;font-size:11.5px">Search</button></li>`).join('')}</ul>`:''}`;}).join('')}</div>`;
      box.querySelectorAll('.swu-find').forEach(b=>b.onclick=()=>{
        relBox.hidden=false; renderReleases(relOut,b.dataset.q,d.platform); relBox.scrollIntoView({behavior:'smooth',block:'start'}); });
    }).catch(()=>{});
  }
  const openRel=()=>{ relBox.hidden=false; renderReleases(relOut,d.title,d.platform); relBox.scrollIntoView({behavior:'smooth',block:'start'}); };
  if(flag==='search') renderReleases(relOut,d.title,d.platform);
  $('#g-int').onclick=openRel;
  $('#g-shelf').onclick=()=>shelfEditor({name:d.title,platform:(it.platform||d.platform)},d.meta||{});
  const mon=$('#g-mon'); if(mon) mon.onclick=async()=>{
    const r=await j('/api/v1/wanted/monitor',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({game:d.title,platform:d.platform,monitored:!w.monitored})});
    if(r.ok) go('game/'+ROUTE_ARGS.map(encodeURIComponent).join('/'));
  };
  const add=$('#g-add'); if(add) add.onclick=async()=>{
    add.disabled=true; add.textContent='Searching…';
    const r=await j('/api/v1/wanted/add',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({game:d.title,platform:d.platform,monitored:true,search:true})}).catch(()=>({ok:false}));
    const s=r.search||{};
    toastAppMessage(s.ok?('Grabbed '+(s.release||d.title)):'No release yet — still monitored');
    refreshCounts(); go('game/'+ROUTE_ARGS.map(encodeURIComponent).join('/'));
  };
};

let MISSING_VIEW='all';
RENDER.missing=async()=>{
  const all=await j('/api/v1/wanted/missing');
  const nMon=all.items.filter(w=>w.monitored!==false).length, nWish=all.items.length-nMon;
  const d={items:all.items.filter(w=>MISSING_VIEW==='all'||(MISSING_VIEW==='wishlist')===(w.monitored===false))};
  const seg=(k,l,n)=>`<button class="btn ${MISSING_VIEW===k?'':'ghost'}" data-mview="${k}" style="padding:4px 12px;font-size:12.5px">${l} ${n}</button>`;
  $('#page').innerHTML=`<div class="row" style="margin-bottom:10px">
      ${seg('all','All',all.items.length)}${seg('monitored','Monitored',nMon)}${seg('wishlist','Wishlist',nWish)}
      <span class="help" style="margin:0">Wishlist = on your list but not monitored, so ROMarr never searches for it.</span></div>
    <div class="row" style="margin-bottom:14px">
      <button class="btn" id="w-all" data-i18n="ui.search-all.01b4b1de28">Search All</button>
      <span style="color:var(--dim);font-size:12.5px">
        ${interfaceTemplateMarkup('ui.requested-not-yet-imported-count.25dbb4afe4',
          {count:fmt(d.items.length)})}</span></div>
    ${d.items.length?`<table><thead><tr><th data-i18n="ui.game.5c412a2620">Game</th><th data-i18n="ui.platform.c78ffe1957">Platform</th>
      <th>Monitored</th><th data-i18n="ui.added.6b02e0d363">Added</th><th data-i18n="ui.attempts.06e70139fc">Attempts</th><th data-i18n="ui.last-error.5488d837f5">Last error</th><th></th></tr></thead><tbody>
      ${d.items.map(w=>`<tr${w.monitored===false?' style="opacity:.62"':''}><td lang="und" dir="auto"><a href="${esc(gameHref(w.platform,'',w.game))}">${esc(w.game)}</a></td><td lang="und" dir="auto">${esc(w.platform)}</td>
        <td><button class="mini" data-mon-game="${esc(w.game)}" data-mon-platform="${esc(w.platform)}"
          data-mon="${w.monitored===false?'0':'1'}" aria-pressed="${w.monitored!==false}"
          title="Monitored games are searched by the sweep and watched in RSS">${w.monitored===false?'Off':'On'}</button></td>
        <td>${esc(regionalDate(w.added))}</td><td>${fmt(w.attempts)}</td>
        <td style="color:var(--dim)" lang="und" dir="auto">${esc(w.last_error||'—')}</td>
        <td><button class="mini" data-drop-game="${esc(w.game)}"
          data-drop-platform="${esc(w.platform)}"
          data-i18n-title="ui.stop-looking-for-this-it-stays-out-o.f77eab9336"
          title="Stop looking for this. It stays out of Wanted until you ask for it again."
          data-i18n="ui.remove.c3812fc4ac">Remove</button></td></tr>`).join('')}
      </tbody></table>`:'<div class="empty" data-i18n="ui.nothing-missing.ec939b22fd">Nothing missing.</div>'}`;
  applyInterfaceLanguage();
  $('#page').querySelectorAll('[data-mview]').forEach(x=>x.onclick=()=>{MISSING_VIEW=x.dataset.mview; go('missing');});
  const b=$('#w-all'); if(b) b.onclick=async()=>{
    b.disabled=true; b.dataset.i18n='Searching…'; applyTranslatedLabel(b,readInterfaceLanguage());
    const r=await j('/api/v1/command',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({name:'MissingGameSearch'})});
    toastMessage('ui.searched-searched-releases-grabbed-g.bf337411f2',{
      searched:fmt(r.searched??0),grabbed:fmt(r.grabbed??0)});
    go('missing'); refreshCounts();
  };
  $('#page').querySelectorAll('button[data-mon-game]').forEach(x=>x.onclick=async()=>{
    x.disabled=true;
    const r=await j('/api/v1/wanted/monitor',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({game:x.dataset.monGame,platform:x.dataset.monPlatform,monitored:x.dataset.mon!=='1'})});
    if(r.ok) go('missing'); else {x.disabled=false; toastAppMessage('Could not change monitoring');}
  });
  // Dropping a request, which Wanted could not do at all: the list was only
  // ever emptied by an import, so a typo went on being searched for forever.
  $('#page').querySelectorAll('button[data-drop-game]').forEach(x=>x.onclick=async()=>{
    const game=x.dataset.dropGame, platform=x.dataset.dropPlatform;
    if(!confirmMessage('ui.stop-looking-for-game-on-platform.e7761b183a',{game,platform})) return;
    x.disabled=true;
    const r=await fetch('/api/v1/wanted/missing?game='+encodeURIComponent(game)
      +'&platform='+encodeURIComponent(platform),{method:'DELETE'});
    if(r.ok){ toastMessage('ui.removed-game.ea342bb833',{game}); go('missing'); refreshCounts(); }
    else { x.disabled=false; toastLabel('ui.could-not-remove-that-request.faff872227'); }
  });
};


function listsNav(active){
  return '<div class="row" style="margin-bottom:12px">'
    +'<button class="btn '+(active==='catalog'?'':'ghost')+'" data-list-mode="catalog">Browse catalog</button>'
    +'<button class="btn '+(active==='imports'?'':'ghost')+'" data-list-mode="imports">Import lists</button>'
    +'<span style="flex:1"></span>'
    +'<a class="btn ghost" style="text-decoration:none" href="https://github.com/snapetech-org/seerrng" target="_blank" rel="noopener noreferrer">SeerrNG discovery</a>'
    +'<a class="help" href="https://github.com/snapetech-org/ROMarrNG/blob/main/docs/SEERRNG-INTEGRATION.md" target="_blank" rel="noopener noreferrer">Integration guide</a>'
    +'</div>';
}
function wireListNav(){
  document.querySelectorAll('[data-list-mode]').forEach(b=>b.onclick=()=>{
    CATALOG_VIEW.mode=b.dataset.listMode; go('lists');
  });
}
function catalogNorm(value){
  return String(value||'').normalize('NFKD').toLowerCase().replace(/[^a-z0-9]/g,'');
}
function catalogPlatform(value){
  const needle=catalogNorm(value);
  return PLATFORMS.find(p=>[p.name,p.slug].concat(p.aliases||[])
    .some(name=>catalogNorm(name)===needle))||null;
}
function catalogImage(value){
  try{
    const u=new URL(String(value||''),location.href);
    return u.protocol==='https:'&&u.hostname==='images.igdb.com'?u.href:'';
  }catch(_){return '';}
}
function catalogPlatformsForGame(game){
  const names=(game.platformOptions||[]).map(p=>p.name||p.key||'')
    .concat(game.platforms||[]);
  const out=[],seen=new Set();
  names.forEach(name=>{
    const local=catalogPlatform(name);
    if(local&&!seen.has(local.slug)){seen.add(local.slug);out.push(local);}
  });
  (game.platformOptions||[]).forEach(p=>{
    const local=PLATFORMS.find(x=>x.slug===p.key);
    if(local&&!seen.has(local.slug)){seen.add(local.slug);out.push(local);}
  });
  return out;
}
function catalogAspect(slug){
  if(['psx','ps2','ps3','ps4','ps5','xbox','xbox360','xboxone','series-x-s'].includes(slug))return '1 / 1';
  if(['genesis-slash-megadrive','sms','gamegear','gb','gbc','gba','nds','3ds','psp','psvita'].includes(slug))return '2 / 3';
  if(['nes','snes','n64','ngc','wii','wiiu','switch'].includes(slug))return '4 / 3';
  return '3 / 4';
}
async function catalogOwnedRows(rows){
  const targets=[];
  rows.forEach((game,index)=>{
    let platforms=CATALOG_VIEW.platform
      ? [PLATFORMS.find(p=>p.slug===CATALOG_VIEW.platform)].filter(Boolean)
      : catalogPlatformsForGame(game);
    if(game.catalogProvider==='dat'&&game.platformOptions&&game.platformOptions[0]){
      const key=game.platformOptions[0].key;
      const exact=PLATFORMS.find(p=>p.slug===key);
      if(exact)platforms=[exact];
    }
    platforms.forEach(platform=>targets.push({
      title:String(game.title||'').slice(0,200),platform:platform.slug,index
    }));
  });
  const owned=new Set();
  for(let at=0;at<targets.length;at+=50){
    const batch=targets.slice(at,at+50);
    const result=await j('/api/v1/catalog/ownership',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({games:batch.map(x=>({title:x.title,platform:x.platform}))})
    }).catch(error=>({error:error.message||'ownership lookup failed'}));
    if(result.error)throw new Error(result.error);
    (result.owned||[]).forEach(i=>{
      if(batch[i])owned.add(batch[i].index);
    });
  }
  return owned;
}
function catalogRequestPlatform(game){
  if(CATALOG_VIEW.platform){
    return PLATFORMS.find(p=>p.slug===CATALOG_VIEW.platform)||null;
  }
  const matches=catalogPlatformsForGame(game);
  if(game.catalogProvider==='dat'&&game.platformOptions&&game.platformOptions[0]){
    const exact=PLATFORMS.find(p=>p.slug===game.platformOptions[0].key);
    if(exact)return exact;
  }
  if(matches.length===1)return matches[0];
  const available=matches.length?matches:PLATFORMS;
  const choice=promptMessage('ui.choose-a-platform-for-game-available.b011a6614c',{
    game:game.title,platforms:available.map(p=>p.name+' ('+p.slug+')').join(', ')
  });
  const normalized=catalogNorm(choice);
  return available.find(p=>catalogNorm(p.slug)===normalized
    ||catalogNorm(p.name)===normalized)||null;
}
async function sendCatalogRequest(game){
  const platform=catalogRequestPlatform(game);
  if(!platform){toastLabel('ui.need-a-known-platform.730519de98');return null;}
  return j('/api/request',{method:'POST',
    headers:{'content-type':'application/json'},
    body:JSON.stringify({game:game.title,platform:platform.slug})
  });
}
const CATALOG_GENRES=['Action','Adventure','Arcade','Card & Board Game','Fighting',
  'Hack and slash/Beat \'em up','Indie','Music','Pinball','Platform','Puzzle',
  'Racing','Role-playing (RPG)','Shooter','Simulator','Sport','Strategy',
  'Tactical','Turn-based strategy (TBS)','Quiz/Trivia','Visual Novel'];
async function renderGameCatalog(){
  const queuedPlatform=sessionStorage.getItem('romarr.catalogPlatform');
  if(queuedPlatform){
    CATALOG_VIEW.platform=queuedPlatform;
    sessionStorage.removeItem('romarr.catalogPlatform');
  }
  let [igdb,dat]=await Promise.all([
    j('/api/v1/catalog/platforms').catch(error=>({error:error.message||'IGDB unavailable'})),
    j('/api/v1/catalog/dat/platforms').catch(error=>({error:error.message||'DAT catalog unavailable'}))
  ]);
  CATALOG_VIEW.igdbPlatforms=Array.isArray(igdb)?igdb:[];
  CATALOG_VIEW.datPlatforms=(dat&&dat.results)||[];
  const igdbChoices=CATALOG_VIEW.igdbPlatforms.map(row=>({
    row,local:catalogPlatform(row.name)
  })).filter(x=>x.local);
  const hasIgdb=CATALOG_VIEW.igdbPlatforms.length>0;
  const hasDat=CATALOG_VIEW.datPlatforms.length>0;
  if(!hasIgdb&&hasDat)CATALOG_VIEW.source='dat';
  if(CATALOG_VIEW.source==='dat'&&!hasDat&&hasIgdb)CATALOG_VIEW.source='igdb';
  if(!hasIgdb&&!hasDat){
    CATALOG_VIEW.rows=[];
    $('#page').innerHTML=listsNav('catalog')
      +'<div class="card"><h3>Browse games</h3>'
      +'<p class="help">Connect an IGDB metadata provider under <a href="#metadata">Metadata</a>, or load No-Intro / Redump DATs under <a href="#collections">Collections</a>, to browse a catalog here.</p>'
      +'<p class="help">For a guided discovery and user request queue, pair ROMarrNG with <a href="https://github.com/snapetech-org/seerrng" target="_blank" rel="noopener noreferrer">SeerrNG</a>. ROMarr handles release search, verification and filing; see the <a href="https://github.com/snapetech-org/ROMarrNG/blob/main/docs/SEERRNG-INTEGRATION.md" target="_blank" rel="noopener noreferrer">integration guide</a>.</p></div>';
    wireListNav();
    return;
  }
  if(CATALOG_VIEW.source==='igdb'&&!hasIgdb)CATALOG_VIEW.source='dat';
  if(CATALOG_VIEW.source==='dat'&&!hasDat)CATALOG_VIEW.source='igdb';
  const source=CATALOG_VIEW.source;
  const platformOptions=source==='dat'
    ?CATALOG_VIEW.datPlatforms.map(x=>({slug:x.slug,name:x.name}))
    :igdbChoices.filter((x,i,a)=>a.findIndex(y=>y.local.slug===x.local.slug)===i)
      .map(x=>({slug:x.local.slug,name:x.local.name,id:x.row.id}));
  if(CATALOG_VIEW.platform&&!platformOptions.some(p=>p.slug===CATALOG_VIEW.platform))
    CATALOG_VIEW.platform='';
  let endpoint,params=[];
  const pageSize=24;
  if(source==='dat'){
    params=['limit='+pageSize,'cursor='+encodeURIComponent(String(CATALOG_VIEW.offset))];
    if(CATALOG_VIEW.platform)params.push('platformSlugs='+encodeURIComponent(CATALOG_VIEW.platform));
    if(CATALOG_VIEW.query.trim()){
      endpoint='/api/v1/catalog/dat/search-page';
      params.push('q='+encodeURIComponent(CATALOG_VIEW.query.trim()));
    }else endpoint='/api/v1/catalog/dat/browse-page';
  }else{
    const selected=platformOptions.find(p=>p.slug===CATALOG_VIEW.platform);
    params=['limit='+pageSize];
    if(selected)params.push('platformIds='+encodeURIComponent(String(selected.id)));
    if(CATALOG_VIEW.genre)params.push('genre='+encodeURIComponent(CATALOG_VIEW.genre));
    if(CATALOG_VIEW.year)params.push('releaseYear='+encodeURIComponent(CATALOG_VIEW.year));
    if(CATALOG_VIEW.query.trim()){
      endpoint='/api/v1/catalog/search-page';
      params.push('q='+encodeURIComponent(CATALOG_VIEW.query.trim()));
      params.push('cursor='+encodeURIComponent(String(CATALOG_VIEW.offset)));
    }else{
      endpoint='/api/v1/catalog/popular-page';
      params.push('offset='+encodeURIComponent(String(CATALOG_VIEW.offset)));
    }
  }
  const data=await j(endpoint+'?'+params.join('&'))
    .catch(error=>({error:error.message||'Catalog could not be loaded'}));
  const rows=data.results||[];
  CATALOG_VIEW.rows=rows;
  CATALOG_VIEW.next=data.nextOffset??data.nextCursor??null;
  CATALOG_VIEW.selected=[];
  let owned=new Set(),ownedError='';
  if(CATALOG_VIEW.hideOwned&&rows.length){
    try{owned=await catalogOwnedRows(rows);}
    catch(error){owned=new Set();ownedError=error.message||'library ownership is unavailable';}
  }
  let visible=rows.map((game,index)=>({game,index}))
    .filter(x=>!owned.has(x.index));
  if(source==='igdb'&&CATALOG_VIEW.sort==='name')
    visible.sort((a,b)=>String(a.game.title).localeCompare(String(b.game.title)));
  if(source==='igdb'&&CATALOG_VIEW.sort==='rating')
    visible.sort((a,b)=>(Number(b.game.rating)||0)-(Number(a.game.rating)||0));
  if(source==='igdb'&&CATALOG_VIEW.sort==='year')
    visible.sort((a,b)=>String(b.game.releaseDate||'').localeCompare(String(a.game.releaseDate||'')));
  const sourcePlatforms=platformOptions.map(p=>'<option value="'+esc(p.slug)+'"'
    +(p.slug===CATALOG_VIEW.platform?' selected':'')+'>'+esc(p.name)+'</option>').join('');
  const genreOptions=CATALOG_GENRES.map(g=>'<option value="'+esc(g)+'"'
    +(g===CATALOG_VIEW.genre?' selected':'')+'>'+esc(g)+'</option>').join('');
  const coverMarkup=(game,index)=>{
    const image=catalogImage(game.coverUrl);
    const platform=CATALOG_VIEW.platform
      ?PLATFORMS.find(p=>p.slug===CATALOG_VIEW.platform)
      :catalogPlatformsForGame(game)[0];
    const ratio=catalogAspect(platform&&platform.slug);
    const boxWidth=CATALOG_VIEW.view==='list'?'width:62px;':'';
    return image?'<div class="art" style="aspect-ratio:'+ratio+';'+boxWidth+'"><img loading="lazy" referrerpolicy="no-referrer" alt="" src="'+esc(image)+'" style="width:100%;height:100%;object-fit:contain"></div>'
      :'<div class="art" style="aspect-ratio:'+ratio+';'+boxWidth+'display:flex;align-items:center;justify-content:center;color:var(--dim);font-size:12px">No cover</div>';
  };
  let resultsMarkup='';
  if(visible.length&&CATALOG_VIEW.view==='grid'){
    resultsMarkup='<div class="grid">'+visible.map(({game,index})=>{
      const tags=(game.genres||[]).slice(0,3).map(x=>'<button class="mini" data-c-similar="'+esc(x)+'" title="Explore more games in this genre">'+esc(x)+'</button>').join(' ');
      const rating=Number(game.rating)||0;
      const ratingLine=rating?'<span>★ '+(source==='igdb'?num(rating/20):num(rating))+'</span>':'';
      const release=game.releaseDate||'';
      const platforms=(game.platforms||[]).slice(0,2).join(' · ');
      const provider=game.source||source.toUpperCase();
      return '<div class="tile">'+coverMarkup(game,index)
        +'<div class="nm" lang="und" dir="auto">'+esc(game.title||'Untitled')+'</div>'
        +'<div class="pf">'+[release,ratingLine,provider].filter(Boolean).join(' · ')+'</div>'
        +'<div class="pf" style="padding-top:0">'+esc(platforms)+'</div>'
        +(tags?'<div class="pf" style="display:flex;gap:4px;flex-wrap:wrap">'+tags+'</div>':'')
        +'<div class="rowact" style="padding:0 8px 9px"><label class="check" style="margin:0;flex:1"><input type="checkbox" data-c-select="'+index+'"> Select</label><button data-c-request="'+index+'">Request</button></div></div>';
    }).join('')+'</div>';
  }else if(visible.length){
    resultsMarkup='<div style="overflow-x:auto"><table><thead><tr><th>Select</th><th>Cover</th><th>Game</th><th>Platform</th><th>Genres</th><th>Released</th><th>Rating</th><th></th></tr></thead><tbody>'
      +visible.map(({game,index})=>'<tr><td><input type="checkbox" data-c-select="'+index+'"></td><td>'+coverMarkup(game,index)+'</td>'
        +'<td lang="und" dir="auto"><b>'+esc(game.title||'Untitled')+'</b><div class="help">'+esc(game.source||source.toUpperCase())+'</div></td>'
        +'<td>'+esc((game.platforms||[]).slice(0,3).join(', ')||'—')+'</td>'
        +'<td>'+esc((game.genres||[]).slice(0,3).join(', ')||'—')+'</td>'
        +'<td>'+esc(game.releaseDate||'—')+'</td>'
        +'<td>'+(Number(game.rating)?'★ '+num(Number(game.rating)/20):'—')+'</td>'
        +'<td><button data-c-request="'+index+'">Request</button></td></tr>').join('')+'</tbody></table></div>';
  }else{
    resultsMarkup='<div class="empty">'+(data.error?appMessageMarkup(data.error):'No titles match these filters.')+'</div>';
  }
  const sources='<div class="row" style="margin-bottom:10px">'
    +(hasIgdb?'<button class="btn '+(source==='igdb'?'':'ghost')+'" data-c-source="igdb">IGDB · covers, genres and ratings</button>':'')
    +(hasDat?'<button class="btn '+(source==='dat'?'':'ghost')+'" data-c-source="dat">Loaded DATs · verified dump names</button>':'')
    +'<span style="flex:1"></span><button class="btn ghost" id="c-grid">Cover view</button><button class="btn ghost" id="c-list">List view</button></div>';
  const filters='<div class="row" style="align-items:end;margin-bottom:12px">'
    +'<div style="flex:2;min-width:210px"><label for="c-query">Search titles</label><input id="c-query" type="search" value="'+esc(CATALOG_VIEW.query)+'" placeholder="Search this catalog"></div>'
    +'<div style="flex:1;min-width:190px"><label for="c-platform">Platform</label><select id="c-platform"><option value="">All supported platforms</option>'+sourcePlatforms+'</select></div>'
    +(source==='igdb'?'<div style="flex:1;min-width:150px"><label for="c-genre">Genre</label><select id="c-genre"><option value="">All genres</option>'+genreOptions+'</select></div><div style="width:115px"><label for="c-year">Release year</label><input id="c-year" type="number" min="1950" max="2200" value="'+esc(CATALOG_VIEW.year)+'" placeholder="Any"></div><div style="width:190px"><label for="c-sort">Sort this page</label><select id="c-sort"><option value="popular">Recommended · IGDB popular</option><option value="name"'+(CATALOG_VIEW.sort==='name'?' selected':'')+'>Title A–Z</option><option value="rating"'+(CATALOG_VIEW.sort==='rating'?' selected':'')+'>Highest rated</option><option value="year"'+(CATALOG_VIEW.sort==='year'?' selected':'')+'>Newest release</option></select></div>':'')
    +'<label class="check" style="margin:0 0 8px"><input id="c-hide-owned" type="checkbox"'+(CATALOG_VIEW.hideOwned?' checked':'')+'> Hide owned</label>'
    +'<button class="btn" id="c-search">Search</button></div>';
  const pageInfo='<div class="row" style="margin:12px 0"><span class="help">'
    +(source==='dat'?'Loaded DAT titles are verified dump references; this source has no covers, genre, release date or rating metadata.'
      :'IGDB results are metadata catalog matches. Ratings and artwork are supplied by IGDB.')
    +'</span><span style="flex:1"></span><button class="btn ghost" id="c-request-selected">Request selected (max 5)</button>'
    +'<button class="btn ghost" id="c-prev"'+(CATALOG_VIEW.offset?'':' disabled')+'>Previous</button>'
    +'<button class="btn ghost" id="c-next"'+(CATALOG_VIEW.next===null?' disabled':'')+'>Next</button></div>';
  const status='<p class="help">'+visible.length+' shown on this page'
    +(owned.size?' · '+owned.size+' already in your library hidden':'')
    +(ownedError?' · owned check unavailable: '+esc(ownedError):'')
    +(CATALOG_VIEW.platform?' · '+esc((PLATFORMS.find(p=>p.slug===CATALOG_VIEW.platform)||{}).name||''):'')
    +'</p>';
  $('#page').innerHTML=listsNav('catalog')+sources
    +'<div class="card"><h3>Discoverable games</h3>'
    +'<p class="help">Request searches your configured sources and hands a usable release to your download client. If no usable release is found, ROMarr keeps the title on Wanted.</p>'
    +filters+status+resultsMarkup+pageInfo
    +'<p class="help">For a household catalog and request queue, use <a href="https://github.com/snapetech-org/seerrng" target="_blank" rel="noopener noreferrer">SeerrNG</a>. ROMarrNG handles acquiring, verifying and filing. <a href="https://github.com/snapetech-org/ROMarrNG/blob/main/docs/SEERRNG-INTEGRATION.md" target="_blank" rel="noopener noreferrer">See how they connect</a>.</p></div>';
  wireListNav();
  document.querySelectorAll('[data-c-source]').forEach(b=>b.onclick=()=>{
    CATALOG_VIEW.source=b.dataset.cSource;CATALOG_VIEW.platform='';CATALOG_VIEW.offset=0;go('lists');
  });
  const update=()=>{
    CATALOG_VIEW.query=$('#c-query').value.trim();
    CATALOG_VIEW.platform=$('#c-platform').value;
    CATALOG_VIEW.genre=$('#c-genre')?$('#c-genre').value:'';
    CATALOG_VIEW.year=$('#c-year')?$('#c-year').value:'';
    CATALOG_VIEW.sort=$('#c-sort')?$('#c-sort').value:'popular';
    CATALOG_VIEW.hideOwned=$('#c-hide-owned').checked;
    CATALOG_VIEW.offset=0;go('lists');
  };
  $('#c-search').onclick=update;
  $('#c-query').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();update();}};
  $('#c-platform').onchange=update;
  if($('#c-genre'))$('#c-genre').onchange=update;
  if($('#c-year'))$('#c-year').onchange=update;
  if($('#c-sort'))$('#c-sort').onchange=update;
  $('#c-hide-owned').onchange=update;
  $('#c-grid').onclick=()=>{CATALOG_VIEW.view='grid';go('lists');};
  $('#c-list').onclick=()=>{CATALOG_VIEW.view='list';go('lists');};
  $('#c-prev').onclick=()=>{CATALOG_VIEW.offset=Math.max(0,CATALOG_VIEW.offset-pageSize);go('lists');};
  $('#c-next').onclick=()=>{CATALOG_VIEW.offset=Number(CATALOG_VIEW.next)||0;go('lists');};
  document.querySelectorAll('[data-c-similar]').forEach(b=>b.onclick=()=>{
    CATALOG_VIEW.source='igdb';CATALOG_VIEW.genre=b.dataset.cSimilar;
    CATALOG_VIEW.query='';CATALOG_VIEW.offset=0;go('lists');
  });
  document.querySelectorAll('[data-c-request]').forEach(b=>b.onclick=async()=>{
    b.disabled=true;b.textContent='Searching…';
    const result=await sendCatalogRequest(rows[Number(b.dataset.cRequest)]);
    if(result&&result.ok)toastMessage('ui.grabbed-release.94cc8b2735',{release:result.release||'release'});
    else if(result&&result.error)toastAppMessage(result.error);
    refreshCounts();go('lists');
  });
  document.querySelectorAll('[data-c-select]').forEach(b=>b.onchange=()=>{
    const index=Number(b.dataset.cSelect);
    if(b.checked&&!CATALOG_VIEW.selected.includes(index))CATALOG_VIEW.selected.push(index);
    if(!b.checked)CATALOG_VIEW.selected=CATALOG_VIEW.selected.filter(x=>x!==index);
  });
  $('#c-request-selected').onclick=async()=>{
    const chosen=CATALOG_VIEW.selected.slice();
    if(!chosen.length){toastLabel('ui.select-at-least-one.49b538bd75');return;}
    if(chosen.length>5){toastLabel('ui.request-up-to-5-titles-at-a-time.0634c13c83');return;}
    if(!confirmMessage('ui.search-and-request-count-selected-ti.1cb3cad5ab',{count:chosen.length}))return;
    const button=$('#c-request-selected');button.disabled=true;
    for(const index of chosen){
      const game=rows[index];
      const result=await sendCatalogRequest(game);
      if(result&&result.error)toastAppMessage(result.error);
    }
    refreshCounts();go('lists');
  };
}

RENDER.lists=async()=>{
  if(CATALOG_VIEW.mode==='catalog')return renderGameCatalog();
  const d=await j('/api/v1/importlist').catch(()=>({items:[]}));
  $('#page').innerHTML=listsNav('imports')+`<div class="row" style="margin-bottom:14px">
      <button class="btn" id="l-add" data-i18n="ui.add-list.474ffc6a82">Add List</button>
      <button class="btn ghost" id="l-sync" data-i18n="ui.sync-now.b5060fd171">Sync Now</button>
      <span style="color:var(--dim);font-size:12.5px">Feed Wanted from a
        list &mdash; a top-100 article, a homebrew catalogue, a friend's
        spreadsheet. Each title is added once, ever; full sets and 1G1R live
        under Collections.</span></div>
    ${d.items.length?`<table><thead><tr><th data-i18n="ui.name.dcd1d5223f">Name</th><th data-i18n="ui.type.baaddf70fb">Type</th>
      <th data-i18n="ui.platform.c78ffe1957">Platform</th><th data-i18n="ui.added-so-far.cde559d068">Added so far</th><th data-i18n="ui.enabled.92c1cdfdf4">Enabled</th><th></th></tr></thead><tbody>
      ${d.items.map((l,i)=>`<tr><td><b lang="und" dir="auto">${esc(l.name||'—')}</b>${
          l.type==='url'?`<div style="color:var(--dim);font-size:11.5px">${esc(l.url||'')}</div>`:''}</td>
        <td lang="und" dir="auto">${esc(l.type)}</td><td>${l.platform
          ?`<span lang="und" dir="auto">${esc(l.platform)}</span>`
          :interfaceMarkup('ui.per-line.141de1d29e')}</td>
        <td>${fmt(l.added_count||0)}${l.unmatched_count
          ?` <span class="pill" title="Titles with no ROM platform — modern store games. Open Edit to see them.">${interfaceTemplateMarkup('ui.count-kept-aside.c7b4f9ae4d',{count:fmt(l.unmatched_count)})}</span>`:''}
          ${l.last_sync?`<div style="font-size:11px;color:${l.last_sync.error?'var(--warn)':'var(--dim)'}">
            ${l.last_sync.error?`<span lang="und" dir="auto">${esc(l.last_sync.error.slice(0,90))}</span>`
              :interfaceTemplateMarkup('ui.fetched-count-at-date.82745b0bd9',
                {count:fmt(l.last_sync.fetched),date:regionalDateTime(l.last_sync.at)})}</div>`:''}</td>
        <td><span class="dot ${l.enable!==false?'up':'down'}"></span></td>
        <td style="text-align:end"><div class="rowact">
          <button data-ledit="${i}" data-i18n="ui.edit.464c4ffd01">Edit</button></div></td></tr>`).join('')}
      </tbody></table>`
      :'<div class="empty" data-i18n="ui.no-lists-yet-paste-one-or-connect-an.944f40a607">No lists yet. Paste one, or connect an account, and let the clock do the asking.</div>'}
    <div class="card" style="margin-top:14px"><h3 data-i18n="ui.connect-an-account.efeac437f9">Connect an account</h3>
      <p class="help">You are already signed in to these services in your browser, so each
        connection takes one click.</p>
      <div class="row" style="flex-wrap:wrap;gap:10px;margin:10px 0">
        <a class="btn" href="/api/v1/connect/steam"
           style="text-decoration:none" data-i18n="ui.sign-in-through-steam.4a6d9aa3c8">Sign in through Steam</a>
        <button class="btn ghost" data-token="gog" data-i18n="ui.connect-gog.eaff8de9d5">Connect GOG</button>
        <button class="btn ghost" data-token="epic" data-i18n="ui.connect-epic.4014de6278">Connect Epic</button>
        <button class="btn ghost" data-token="ea" data-i18n="ui.connect-ea.7a1bcc619b">Connect EA</button>
        <button class="btn ghost" data-token="battlenet" data-i18n="ui.connect-battle-net.bd65ad2073">Connect Battle.net</button>
        <button class="btn ghost" data-token="psn" data-i18n="ui.connect-playstation.79b59e6bd5">Connect PlayStation</button>
        <button class="btn ghost" data-token="xbox" data-i18n="ui.connect-xbox.47bd370b36">Connect Xbox</button>
        <button class="btn ghost" data-token="itchio" data-i18n="ui.connect-itch-io.dda4ddc747">Connect itch.io</button>
        <button class="btn ghost" data-token="humble" data-i18n="ui.connect-humble.2e9076ceca">Connect Humble</button>
        <button class="btn ghost" data-paste="amazon">Amazon / Prime</button>
        <button class="btn ghost" data-paste="ubisoft">Ubisoft</button>
      </div>
      <p class="help">${interfaceTemplateMarkup(ACCOUNT_IMPORT_HELP,{})}</p>
      <div id="l-token"></div>
      <h3 style="margin-top:18px">Games installed on your gaming PC</h3>
      <p class="help">A second route, useful alongside the above: every
        launcher writes what it installed to disk, so this needs no
        credential of any kind &mdash; and it catches anything a store's
        API misses. Run it <b>on the PC you play on</b>:</p>
      <pre style="font:12px/1.6 ui-monospace,Menlo,monospace;color:var(--dim);
        background:var(--bg);border:1px solid var(--line);border-radius:6px;
        padding:10px;white-space:pre-wrap">python scripts/connect_launchers.py --url ${location.origin} --key &lt;your API key&gt;</pre>
      <div class="row" style="margin:8px 0">
        <button class="btn ghost" id="l-scan">Scan the ROMarr server</button>
        <span class="help" style="margin:0">Only useful if ROMarr runs on
          the machine you play on &mdash; it scans wherever ROMarr itself
          lives, which is usually a server with no launchers.</span></div>
      <div id="l-noapi" style="color:var(--dim);font-size:12.5px"></div></div>`;

  wireListNav();
  applyInterfaceLanguage();
  document.querySelectorAll('[data-paste]').forEach(b=>b.onclick=async()=>{
    const s=await j('/api/v1/connect/sources').catch(()=>({paste_sources:{}}));
    const spec=(s.paste_sources||{})[b.dataset.paste];
    if(!spec){toastLabel('ui.unknown-store.e7ff0236d5');return;}
    window.open(spec.open,'_blank','noopener');
    toastAppMessage(spec.how);
    editList({type:'paste',name:spec.label+' library'});
  });
  document.querySelectorAll('[data-token]').forEach(b=>b.onclick=async()=>{
    const s=await j('/api/v1/connect/sources').catch(()=>({token_sources:{}}));
    const spec=(s.token_sources||{})[b.dataset.token];
    if(!spec){toastLabel('ui.unknown-store.e7ff0236d5');return;}
    window.open(spec.open,'_blank','noopener');
    // A modal, not an inline panel: window.open moves the person to another
    // tab, and when they come back a box further down the page is a box
    // they never see. This one is in front of them and focused.
    const m=document.createElement('div');
    m.className='modal';
    m.innerHTML=`<div class="box">
      <h3>${interfaceTemplateMarkup('ui.connect-to-service.bb9d648886',{service:spec.label})}</h3>
      <div class="sub">${interfaceTemplateMarkup('ui.a-tab-just-opened-how.e4de8fcadf',
        {how:spec.how||''})}</div>
      <div class="field"><label>Paste it here</label>
        <textarea id="tok-v" rows="4" autocomplete="off" spellcheck="false"
          placeholder='paste the whole thing — {"npsso":"..."} is fine'
          style="width:100%;resize:vertical;font:12px/1.5 ui-monospace,
          Menlo,monospace"></textarea>
        <div style="color:var(--dim);font-size:11.5px;margin-top:4px">
          Paste the entire page if you like — ROMarr pulls the value out.</div>
      </div>
      <div id="testline" role="status" aria-live="polite" aria-atomic="true"></div>
      <div class="foot">
        <button class="btn ghost sp" data-close>Cancel</button>
        <button class="btn" id="tok-save">Connect</button>
      </div></div>`;
    openModal(m);
    m.onclick=e=>{ if(e.target===m||e.target.dataset.close!==undefined) closeModal(); };
    setTimeout(()=>m.querySelector('#tok-v')?.focus(),50);
    $('#tok-save').onclick=async()=>{
      const value=$('#tok-v').value.trim();
      if(!value){toastLabel('ui.paste-the-value-first.51526abffc');return;}
      const button=$('#tok-save');button.disabled=true;
      const body={name:spec.label+' library',type:b.dataset.token,
                  platform:'',enable:true};
      body[spec.field]=value;
      const line=(ok,msg)=>{
        const el=m.querySelector('#testline');
        el.className='testline '+(ok?'ok':'bad');
        el.setAttribute('role',ok?'status':'alert');el.setAttribute('aria-live',ok?'polite':'assertive');
        el.innerHTML=appMessageMarkup(msg);
      };
      line(true,'Connecting…');
      try{
        const saved=await j('/api/v1/importlist',{method:'POST',
          headers:{'content-type':'application/json'},body:JSON.stringify(body)});
        if(saved.error){line(false,saved.error);return;}
        const r=await j('/api/v1/command',{method:'POST',
          headers:{'content-type':'application/json'},
          body:JSON.stringify({name:'ListSync'})});
        // The failure reason belongs here, in front of the person who just
        // pasted, not in a toast that vanishes.
        const failed=(r.failures||[]).find(f=>f.id===saved.id);
        if(failed){line(false,failed.reason);return;}
        closeModal(); if(r.message)toastAppMessage(r.message);else toastLabel('ui.connected.22965568d2'); go('lists',true);
      }catch(_){line(false,'ROMarr could not complete this connection. Check the server and try again.');}
      finally{if(button.isConnected)button.disabled=false;}
    };
  });
  j('/api/v1/importlist/schema').then(s=>{
    const el=$('#l-noapi'); if(!el) return;   // page may have changed
    const rows=Object.entries(s.no_api||{});
    el.innerHTML=rows.map(([store,why])=>
      `<p style="margin:6px 0"><b>${esc(store)}</b> — ${esc(why)}</p>`).join('');
  }).catch(()=>{});
  const scanBtn=$('#l-scan');
  if(scanBtn) scanBtn.onclick=async()=>{
    scanBtn.disabled=true; scanBtn.textContent='Scanning…';
    const r=await j('/api/v1/launchers/connect',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({name:'Local launchers'})}).catch(()=>({error:'scan failed'}));
    if(r.error)toastAppMessage(r.error);else if(r.message)toastAppMessage(r.message);else toastLabel('ui.done.11a6767d56');
    if(r.ok) go('lists'); else { scanBtn.disabled=false; scanBtn.textContent='Scan this machine'; }
  };
  $('#l-add').onclick=()=>editList({type:'paste'});
  $('#l-sync').onclick=async e=>{
    e.target.disabled=true; e.target.textContent='Syncing…';
    const r=await j('/api/v1/command',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({name:'ListSync'})});
    if(r.message)toastAppMessage(r.message);else toastLabel('ui.synced.5da22fe4f7'); go('lists'); refreshCounts();
  };
  document.querySelectorAll('[data-ledit]').forEach(b=>b.onclick=()=>
    editList(d.items[Number(b.dataset.ledit)]));
};

function editList(item){
  const isNew=!item.id;
  const modalTitle=isNew?'Add Import List':'Edit Import List';
  const m=document.createElement('div');
  m.className='modal';
  m.innerHTML=`<div class="box">
    <h3 data-i18n-key="${esc(stableLocalizationKey(modalTitle)||modalTitle)}">${modalTitle}</h3>
    <div class="sub" data-i18n="ui.one-title-per-line-comments-ranking.8c54c86102">One title per line. '# comments', ranking numbers and
      'Title&nbsp;&rarr;tab&larr;&nbsp;platform' lines are understood.</div>
    <div class="field"><label data-i18n="ui.name.dcd1d5223f">Name</label>
      <input type="text" data-f="name" value="${esc(item.name||'')}" lang="und" dir="auto"></div>
    <div class="field"><label data-i18n="ui.type.baaddf70fb">Type</label>
      <select data-f="type">
        <option value="paste" data-i18n="ui.pasted-list.80a83ed456"${!['url','steam','gog'].includes(item.type)?' selected':''}>Pasted list</option>
        <option value="url" data-i18n="ui.list-at-a-url.68f171a9c9"${item.type==='url'?' selected':''}>List at a URL</option>
        <option value="steam" data-i18n="ui.steam-library-wishlist.c069045626"${item.type==='steam'?' selected':''}>Steam library / wishlist</option>
        <option value="gog" data-i18n="ui.gog-profile.866a5318ca"${item.type==='gog'?' selected':''}>GOG profile</option>
        <option value="xbox" data-i18n="ui.xbox-openxbl.3d330a7abd"${item.type==='xbox'?' selected':''}>Xbox (OpenXBL)</option>
        <option value="psn" data-i18n="ui.playstation-npsso.0b1c050f2f"${item.type==='psn'?' selected':''}>PlayStation (NPSSO)</option>
        <option value="itchio" data-i18n="ui.itch-io-purchases.a37be13870"${item.type==='itchio'?' selected':''}>itch.io purchases</option>
      </select></div>
    <div class="field"><label data-i18n="ui.default-platform.34b2ad1a9c">Default platform</label>
      <select data-f="platform"><option value="" data-i18n="ui.named-per-line.7a0401d477">Named per line</option>
        ${PLATFORMS.map(p=>`<option value="${esc(p.slug)}"${
          item.platform===p.slug?' selected':''}>${esc(p.name)}</option>`).join('')}
      </select></div>
    <div class="field" data-lt="url" style="${item.type==='url'?'':'display:none'}">
      <label data-i18n="ui.url.e7a241deba">URL</label>
      <input type="text" data-f="url" value="${esc(item.url||'')}"
        placeholder="https://example.org/top-100.txt"></div>
    <div data-lt="steam" style="${item.type==='steam'?'':'display:none'}">
      <div class="field"><label>SteamID (64-bit)</label>
        <input type="text" data-f="steam_id" value="${esc(item.steam_id||'')}"
          placeholder="76561198000000000"></div>
      <div class="field"><label>Web API key</label>
        <input type="password" data-f="api_key" autocomplete="new-password"
          value="${esc(item.api_key||'')}"
          placeholder="steamcommunity.com/dev/apikey"></div>
      <div class="field"><label data-i18n="ui.source.0e570ca6fa">Source</label>
        <select data-f="source">
          <option value="owned" data-i18n="ui.owned-games.6092613ad5"${item.source!=='wishlist'?' selected':''}>Owned games</option>
          <option value="wishlist" data-i18n="ui.wishlist.edc279c643"${item.source==='wishlist'?' selected':''}>Wishlist</option>
        </select></div>
      <p class="help">The profile's game details must be public. Imported titles are matched
        to the default platform above, which helps ROMarr identify each game.</p></div>
    <div class="field" data-lt="gog" style="${item.type==='gog'?'':'display:none'}">
      <label>GOG username</label>
      <input type="text" data-f="gog_username" value="${esc(item.gog_username||'')}"
        placeholder="a public gog.com profile name"></div>
    <div data-lt="xbox" style="${item.type==='xbox'?'':'display:none'}">
      <div class="field"><label>OpenXBL API key</label>
        <input type="password" data-f="openxbl_key" autocomplete="new-password"
          value="${esc(item.openxbl_key||'')}" placeholder="sign in once at xbl.io"></div>
      <p class="help" data-i18n="ui.imports-your-play-history-every-game.1ff20c8ccd">Imports your play history — every game the account has played. Microsoft does not provide a purchase list, so play history is the practical way to build a library.</p></div>
    <div data-lt="psn" style="${item.type==='psn'?'':'display:none'}">
      <div class="field"><label>NPSSO token</label>
        <input type="password" data-f="npsso" autocomplete="new-password"
          value="${esc(item.npsso||'')}"
          placeholder="from ca.account.sony.com/api/authz/v3/ssocookie"></div>
      <p class="help">Sign in at playstation.com, then open the ssocookie URL
        above and copy the token. It expires every couple of months; when a
        sync fails, grab a fresh one.</p></div>
    <div class="field" data-lt="itchio" style="${item.type==='itchio'?'':'display:none'}">
      <label>itch.io API key</label>
      <input type="password" data-f="itchio_key" autocomplete="new-password"
        value="${esc(item.itchio_key||'')}"
        placeholder="itch.io/user/settings/api-keys"></div>
    <div class="field" data-lt="paste" style="${['url','steam','gog'].includes(item.type)?'display:none':''}">
      <label data-i18n="ui.titles.3b23a123fa">Titles</label>
      <textarea data-f="content" rows="10"
        style="width:100%;resize:vertical">${esc(item.content||'')}</textarea></div>
    <label class="check"><input type="checkbox" data-f="enable"
      ${item.enable!==false?'checked':''}><span data-i18n="ui.enabled.92c1cdfdf4">Enabled</span></label>
    ${(item.unmatched||[]).length?`<details style="margin-top:10px">
      <summary class="help" style="margin:0;cursor:pointer">
        ${interfaceTemplateMarkup('ui.count-titles-kept-aside-no-rom-platf.a06162e141',
          {count:fmt(item.unmatched.length)})}
        These are your modern store games; ROMarr acquires ROMs, so they
        wait here rather than pretending to be cartridges.</summary>
      <div style="color:var(--dim);font-size:12px;max-height:180px;
        overflow:auto;margin-top:6px">${item.unmatched.map(esc).join('<br>')}
      </div></details>`:''}
    <div id="testline"></div>
    <div class="foot">
      <button class="btn ghost" id="l-preview" data-i18n="ui.preview.324b134f57">Preview</button>
      ${isNew?'':'<button class="btn danger" id="l-del" data-i18n="ui.delete.e2d0a54968">Delete</button>'}
      <button class="btn ghost sp" data-close data-i18n="ui.cancel.19766ed6cc">Cancel</button>
      <button class="btn" id="l-save" data-i18n="ui.save.1509f561f2">Save</button>
    </div></div>`;
  openModal(m);
  applyInterfaceLanguage();
  m.onclick=e=>{ if(e.target===m||e.target.dataset.close!==undefined) closeModal(); };
  m.querySelector('[data-f=type]').onchange=e=>{
    const kind=['url','steam','gog','xbox','psn','itchio'].includes(e.target.value)
      ?e.target.value:'paste';
    m.querySelectorAll('[data-lt]').forEach(el=>
      el.style.display=el.dataset.lt===kind?'':'none');
  };
  const payload=()=>({...readForm(), id:item.id});
  const line=(ok,markup)=>{
    m.querySelector('#testline').className='testline '+(ok?'ok':'bad');
    m.querySelector('#testline').setAttribute('role',ok?'status':'alert');
    m.querySelector('#testline').setAttribute('aria-live',ok?'polite':'assertive');
    m.querySelector('#testline').innerHTML=markup;
  };
  m.querySelector('#l-preview').onclick=async e=>{
    e.target.disabled=true; line(true,interfaceMarkup('ui.reading.874bfa5bed'));
    const r=await j('/api/v1/importlist/preview',{method:'POST',
      headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
    if(r.error){ line(false,appMessageMarkup(r.error)); }
    else{
      const unresolved=r.items.filter(x=>x.unresolved).length;
      const summary=unresolved
        ?interfaceTemplateMarkup('ui.found-count-titles-unresolved-have-n.c72ecee544',
          {count:fmt(r.total),unresolved:fmt(unresolved)})
        :interfaceTemplateMarkup('ui.found-count-titles.4c3d13d187',{count:fmt(r.total)});
      const first=r.total&&r.items[0]?.game
        ?' '+interfaceMarkup('ui.first.e7b9cb3d54')+' <span lang="und" dir="auto">'
          +esc(r.items[0].game)+'</span>':'';
      line(!unresolved,summary+first);
    }
    e.target.disabled=false;
  };
  m.querySelector('#l-save').onclick=async()=>{
    const button=m.querySelector('#l-save');button.disabled=true;
    try{
      const saved=await j('/api/v1/importlist',{method:'POST',
        headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
      if(saved.error){line(false,appMessageMarkup(saved.error));button.disabled=false;return;}
      closeModal(); toastLabel('ui.saved.b5c120b316'); go('lists',true);
    }catch(_){
      line(false,appMessageMarkup('Could not save this list. Check the connection and try again.'));
      button.disabled=false;
    }
  };
  const del=m.querySelector('#l-del');
  if(del) del.onclick=async()=>{
    if(!confirmMessage('ui.remove-name.01c1f02508',{name:item.name
      ||translateLabel('ui.this-list.15ec1309e5',readInterfaceLanguage())})) return;
    del.disabled=true;
    try{
      const response=await fetch(`/api/v1/importlist/${item.id}`,{method:'DELETE'});
      const result=await response.json().catch(()=>({}));
      if(!response.ok||result.error)throw new Error(result.error||`Could not remove this list (HTTP ${response.status}).`);
      closeModal(); toastLabel('ui.removed.4118fb4fed'); go('lists',true);
    }catch(error){line(false,appMessageMarkup(error.message||'Could not remove this list.'));del.disabled=false;}
  };
}

let DISC={mode:'library',shelf:'top-rated',genre:''};
RENDER.discover=async()=>{
  // Two sources, and the local one is the default because it works with
  // nothing configured: your own library already carries genres, ratings
  // and years. The storefront shelves need a metadata API key.
  const mine=DISC.mode==='library';
  const libTabs=[['top-rated','Top rated'],['recent','Newest'],
                 ['recently-added','Just added'],['hidden-gems','Hidden gems'],
                 ['multiplayer','Multiplayer'],['anniversary','On this day'],
                 ['by-genre','Genre'],['by-franchise','Franchise'],
                 ['by-company','Company']];
  const webTabs=[['popular','Popular'],['new','New releases'],['upcoming','Upcoming']];
  const tabs=mine?libTabs:webTabs;
  if(mine&&!libTabs.some(t=>t[0]===DISC.shelf)) DISC.shelf='top-rated';
  if(!mine&&!webTabs.some(t=>t[0]===DISC.shelf)) DISC.shelf='popular';
  $('#page').innerHTML=`<div class="row" style="margin-bottom:10px;gap:6px;flex-wrap:wrap">
      <button class="btn ${mine?'':'ghost'}" data-mode="library">My library</button>
      <button class="btn ${mine?'ghost':''}" data-mode="web">New releases (web)</button>
      <span style="flex:1"></span>
      ${tabs.map(([k,l])=>`<button class="btn ${k===DISC.shelf?'':'ghost'}"
        data-shelf="${k}" style="padding:4px 10px;font-size:12px">${l}</button>`).join('')}
    </div>
    <div id="d-genres" style="margin-bottom:10px"></div>
    <div id="d-out"><div class="empty">Browsing…</div></div>`;
  document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{
    DISC.mode=b.dataset.mode; go('discover');});
  document.querySelectorAll('[data-shelf]').forEach(b=>b.onclick=()=>{
    DISC.shelf=b.dataset.shelf; go('discover');});

  if(mine){
    const d=await j(`/api/v1/discover/library?shelf=${encodeURIComponent(DISC.shelf)}`
      +`&value=${encodeURIComponent(DISC.genre)}&limit=60`)
      .catch(()=>({items:[]}));
    // The chip row belongs to the shelf being browsed — genres while you are
    // browsing franchises is a row of buttons that do nothing.
    const facet={'by-genre':['genre','a metadata scan'],
                 'by-franchise':['franchise','a metadata scan'],
                 'by-company':['company','a metadata scan']}[DISC.shelf];
    if(facet){
      $('#d-genres').innerHTML=(d.facet||[]).map(g=>
        `<button class="btn ${DISC.genre===g?'':'ghost'}" data-dgenre="${esc(g)}"
          style="padding:3px 9px;font-size:12px;margin:0 4px 4px 0">${esc(g)}</button>`).join('')
        ||`<span class="help" style="margin:0">${interfaceMarkup('ui.no-results-yet-your-library-server-f.6082732618')}</span>`;
      document.querySelectorAll('[data-dgenre]').forEach(b=>b.onclick=()=>{
        DISC.genre=b.dataset.dgenre; go('discover');});
    }
    const items=d.items||[];
    if(!items.length){
      const facetNames={genre:'Genre',franchise:'Franchise',company:'Company'};
      const emptyCopy=d.error?appMessageMarkup(d.error)
        :facet&&!DISC.genre?interfaceTemplateMarkup('ui.pick-a-facet-above.95ff025720',{
          facet:translateLabel(facetNames[facet[0]]||facet[0],readInterfaceLanguage())})
        :interfaceMarkup('ui.nothing-on-this-shelf-yet.337c41f2eb');
      $('#d-out').innerHTML=`<div class="empty">${emptyCopy}</div>`;
      return;
    }
    // Whatever the shelf is sorted on is what the subtitle leads with, so a
    // "Just added" grid is not a wall of tiles with no dates on them.
    const sub=g=>DISC.shelf==='recently-added'?regionalDate(g.added)
      :DISC.shelf==='anniversary'?regionalDate(g.released)
      :(g.year?regionalYear(g.year):'');
    $('#d-out').innerHTML=`<p class="help">${interfaceTemplateMarkup('ui.this-shelf-has-count-games-from-your.ffbe793830',
        {count:fmt(d.total)})}</p>
      <div class="grid">${items.map(g=>`<div class="tile">
        <div class="art" style="background-image:url('${esc(g.cover_url||'')}')"></div>
        <div class="nm">${esc(g.title)}</div>
        <div class="pf">${esc(g.platform||'')}${sub(g)?' · '+esc(sub(g)):''}${
          g.rating?' · ★'+num(g.rating):''}${
          g.players&&g.players!=='1'?' · '+esc(g.players)+'p':''}</div>
        <div class="pf" style="padding-top:0;color:var(--dim)">${esc(
          (g.franchises||[]).concat(g.genres||[]).slice(0,2).join(' · '))}</div>
        </div>`).join('')}</div>`;
    return;
  }

  const d=await j('/api/v1/discover?shelf='+DISC.shelf).catch(()=>({items:[]}));
  const shelf=DISC.shelf;
  if(!d.items||!d.items.length){
    // Whatever the server says is missing, verbatim. It knows which
    // providers are configured and which credential is blank; a fixed line
    // here naming one provider is how somebody with a working IGDB setup
    // gets told to go and register for RAWG.
    $('#d-out').innerHTML=`<div class="empty">${appMessageMarkup(d.error||'Nothing to show.')}</div>`;
    return;
  }
  const src=d.provider_label||'';
  const requestable=g=>(g.platforms||[]).filter(p=>
    PLATFORMS.some(x=>x.name.toLowerCase()===String(p).toLowerCase()
      ||x.slug===String(p).toLowerCase()));
  // Every tile carries where it came from. These sit one button away from
  // the library grid, which looks identical, and a shelf that lets a
  // catalogue entry pass for a game you own is worse than an empty page.
  const catalogueLine=src
    ?interfaceTemplateMarkup('ui.count-titles-from-provider-s-catalog.6aa04d7dfc',
      {count:fmt(d.items.length),provider:src})
    :interfaceTemplateMarkup('ui.count-titles-from-the-metadata-provi.c9caa2fedf',
      {count:fmt(d.items.length)});
  $('#d-out').innerHTML=`<p class="help">${catalogueLine}</p>
    <div class="grid">${d.items.map((g,i)=>{
    const plats=requestable(g);
    return `<div class="tile">
      <div class="art" style="background-image:url('${esc(g.cover_url||'')}')"></div>
      <div class="nm">${esc(g.title)}</div>
      <div class="pf">${esc(regionalDate(g.released))}${g.rating?' · ★'+num(g.rating):''}</div>
      <div class="pf" style="padding-top:0;color:var(--dim)">${g.source||src
        ?interfaceTemplateMarkup('ui.source-source.9f9d70c6e9',{source:g.source||src})
        :interfaceMarkup('ui.source-metadata-provider.cb5f04257e')}</div>
      ${plats.length?`<div class="rowact" style="margin-top:4px">
        <button data-dreq="${i}">Request</button></div>`
        :`<div class="pf" style="color:var(--dim)">${interfaceMarkup('ui.no-rom-platform.cfcbe9e79b')}</div>`}</div>`;
  }).join('')}</div>
  <p class="help" style="margin-top:10px">Request shows only for games on a
    platform ROMarr models — the scorer takes it from there, DAT
    verification included.</p>`;
  document.querySelectorAll('[data-dreq]').forEach(b=>b.onclick=async()=>{
    const g=d.items[Number(b.dataset.dreq)];
    const plats=requestable(g);
    const pick=plats.length===1?plats[0]
      :promptMessage('ui.which-platform-available-platforms.9323c837c4',{platforms:plats.join(', ')},plats[0]);
    if(!pick) return;
    const match=PLATFORMS.find(x=>x.name.toLowerCase()===String(pick).toLowerCase()
      ||x.slug===String(pick).toLowerCase());
    if(!match){toastLabel('ui.unknown-platform.9e67415d4c');return;}
    b.disabled=true; b.textContent='Requesting…';
    const r=await j('/api/request',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({game:g.title,platform:match.slug})});
    b.textContent=r.ok?'Grabbed':'Wanted';
    if(r.ok)toastMessage('ui.grabbed-release.94cc8b2735',{release:r.release});
    else if(r.error)toastAppMessage(r.error);else toastLabel('ui.added-to-wanted.bacfe35baa');
    refreshCounts();
  });
};

RENDER.peers=async()=>{
  const d=await j('/api/v1/peer').catch(()=>({peers:[]}));
  const list=d.peers||[];
  const hx=await j('/api/v1/hashes').catch(()=>({count:0}));
  const scopeLabel={none:'Nothing',platforms:'Named platforms only',
    verified:'Verified dumps only',all:'Everything'};
  const accessLabel={catalogue:'See titles only',stream:'Play here',
    fetch:'Download from me'};
  $('#page').innerHTML=`<div class="card"><h3>Friends</h3>
      <p class="help">${interfaceMarkup('ui.share-a-library-with-someone-running.81db6ce026')}
        <b>Peering shares nothing by itself</b> — ${interfaceMarkup('ui.you-choose-what-each-friend-sees-and.b14fcf4cf5')}</p>
      <div class="row" style="flex-wrap:wrap;gap:8px">
        <button class="btn" id="p-invite">Invite a friend</button>
        <button class="btn ghost" id="p-redeem">I have an invitation</button>
        <button class="btn ghost" id="p-romm">Add a RomM server</button>
      </div>
      <p class="help" style="margin-top:10px">${interfaceMarkup(ROMM_FRIEND_HELP)}</p>
      <div id="p-out" style="margin-top:12px"></div></div>
    <div class="card"><h3>What netplay can prove</h3>
      <p class="help">${interfaceMarkup(NETPLAY_HELP)}</p>
      ${hx.count
        ? `<div class="panel"><b>${fmt(hx.count)}</b> dump(s) can be
             matched, across ${fmt(Object.keys(hx.platforms||{}).length)} platform(s).</div>`
        : `<div class="panel panel-warn">${interfaceMarkup(NO_HASHES_HELP)}</div>`}
      <div id="p-seedlive"></div>
      <div class="row" style="gap:8px;margin-top:10px">
        <button class="btn ghost" id="p-seed">Read them again now</button>
      </div>
      <div id="p-seedout"></div></div>
    ${list.length?`<div class="card"><h3>Your friends</h3>
      <table><thead><tr><th>Name</th><th>They see</th><th>They may</th>
        <th>State</th><th></th></tr></thead><tbody>
      ${list.map((p,i)=>`<tr><td><b>${esc(p.name)}</b>
        ${p.kind==='romm'?' <span class="pill">RomM</span>':''}
        <div style="color:var(--dim);font-size:11.5px">${esc(p.url||'')}</div></td>
        <td>${esc(scopeLabel[p.scope]||p.scope)}${
          p.scope==='platforms'&&(p.platforms||[]).length
            ?`<div style="color:var(--dim);font-size:11.5px">${esc(p.platforms.join(', '))}</div>`:''}</td>
        <td>${esc(accessLabel[p.access]||p.access)}${
          p.delegate_users?' <span class="pill">their users too</span>':''}</td>
        <td>${p.confirmed?'<span class="pill imported">confirmed</span>'
          :'<span class="pill failed">awaiting your confirmation</span>'}</td>
        <td style="text-align:end"><div class="rowact">
          ${p.confirmed?`<button data-pbrowse="${esc(p.peer_id)}"${
             p.url?'':' disabled data-i18n-title="ui.their-invitation-carried-no-address.e69f21b5aa" title="Their invitation carried no address, '
                     +'so there is nowhere to call. Ask them to set their '
                     +'public URL and send a fresh invitation." title="Their invitation carried no address, '
                     +'so there is nowhere to call. Ask them to set their '
                     +'public URL and send a fresh invitation."'}
             >Browse library</button>
            <button data-pedit="${i}">Sharing</button>`
            :`<button data-pconfirm="${esc(p.peer_id)}">Confirm</button>`}
          <button data-prevoke="${esc(p.peer_id)}">Remove</button>
        </div></td></tr>`).join('')}</tbody></table>
      <div id="p-shelf"></div></div>`
      :'<div class="empty">No friends yet. Invite someone, or paste an invitation they sent you.</div>'}`;

  //: Two halves, shown as two halves. The link is safe to paste anywhere a
  //: link goes because it authorises nothing; the code is the credential and
  //: is never in it. Presenting them side by side with the reason written
  //: down is the only thing that stops somebody pasting both into the same
  //: message and wondering why we bothered.
  $('#p-invite').onclick=async()=>{
    const r=await j('/api/v1/peer/invite',{method:'POST',
      headers:{'content-type':'application/json'},body:'{}'});
    const claimCodeMessage='This claim code is a secret. Send it separately from the link, for example by saying it aloud, texting it, or using another app. It works once and expires in {minutes} minutes.';
    $('#p-out').innerHTML=`<div class="card" style="margin:0">
      <h3>Send your friend two things</h3>
      ${r.note?`<p class="help">${appMessageMarkup(r.note)}</p>`:''}
      ${r.warning?`<div class="panel panel-warn">${appMessageMarkup(r.warning)}</div>`:''}
      ${r.link?`<div class="field"><label>1. The link — send it anywhere</label>
        <input type="text" id="p-link" readonly value="${esc(r.link)}"
          style="width:100%;font:12px/1.5 ui-monospace,Menlo,monospace">
        <p class="help" style="margin-top:6px">Carries no secret. Chat, mail,
          a preview card in someone's group thread — none of it matters,
          because on its own this opens nothing.</p></div>`:''}
      <div class="field"><label>2. The claim code — send it separately</label>
        <div id="p-code" style="font:700 26px/1.2 ui-monospace,Menlo,monospace;
          letter-spacing:.12em;padding:12px 0">${esc(r.code||'')}</div>
        <p id="p-code-help" class="help">${interfaceTemplateMarkup(claimCodeMessage,{minutes:fmt(Math.max(0,Math.round((r.code_expires_in||0)/60)))})}</p></div>
      <div class="row" style="gap:8px">
        <button class="btn ghost" id="p-copy">Copy the link</button>
        <button class="btn ghost" id="p-copycode">Copy the code</button></div>
      <details style="margin-top:14px"><summary class="help"
        style="cursor:pointer">Your friend's ROMarr is older than invitation
        links</summary>
        <p class="help" data-i18n="ui.the-full-invitation-contains-a-long.562a19df47">The full invitation contains a long secret. Treat it like a password. Use the link and code above instead; they are shorter-lived and easier to share.</p>
        <textarea rows="4" readonly style="width:100%;font:12px/1.5
          ui-monospace,Menlo,monospace">${esc(JSON.stringify(r.invite||{}))}</textarea>
      </details></div>`;
    const copy=async(text,said)=>{
      try{await navigator.clipboard.writeText(text); toastLabel(said);}
      catch{toastLabel('ui.select-it-and-copy-it.f7c4294028');}
    };
    $('#p-copy').onclick=()=>copy(r.link||'','Link copied');
    $('#p-copycode').onclick=()=>copy(r.code||'','Code copied');
    //: Counting down rather than showing a timestamp: the operator is deciding
    //: right now whether to resend, and "4 min" answers that where "expires at
    //: 19:42" makes them do arithmetic.
    let left=r.code_expires_in||0;
    const tick=setInterval(()=>{
      const help=$('#p-code-help');
      if(!help){ clearInterval(tick); return; }
      left-=10;
      if(left<=0){
        clearInterval(tick);
        help.innerHTML=interfaceMarkup('ui.expired.843a037ea1');
        const code=$('#p-code');
        if(code) code.removeAttribute('aria-label');
      } else help.innerHTML=interfaceTemplateMarkup(claimCodeMessage,{minutes:fmt(Math.max(1,Math.round(left/60)))});
    },10000);
  };

  //: Prefilled from the /link landing page, which stashes the invitation in
  //: sessionStorage rather than the URL. Read once and cleared: an invitation
  //: sitting in a tab's storage after it has been used is a thing to explain
  //: later rather than a feature.
  const claimForm=(pre)=>{
    $('#p-out').innerHTML=`<div class="card" style="margin:0">
      <h3>Redeem an invitation</h3>
      <div class="field"><label>The link your friend sent</label>
        <input type="text" id="p-link-in" value="${esc(pre&&pre.link||'')}"
          placeholder="https://their-server.example/link#i=…"
          style="width:100%;font:12px/1.5 ui-monospace,Menlo,monospace"></div>
      <div class="field"><label>The claim code they sent separately</label>
        <input type="text" id="p-code-in" autocomplete="off" maxlength="12"
          placeholder="K7RM-9TFQ" style="max-width:220px;
          font:700 18px/1.2 ui-monospace,Menlo,monospace;letter-spacing:.1em">
        <p class="help" style="margin-top:6px">The code has eight characters. Letter case, spaces, and hyphens are ignored.</p></div>
      <div id="p-claim-target"></div>
      <button class="btn" id="p-claim-go">Become friends</button>
      <details style="margin-top:14px"><summary class="help"
        style="cursor:pointer">They sent one long block of JSON instead</summary>
        <p class="help">An older ROMarr, or an invitation minted before this
          version. Paste the whole block.</p>
        <textarea id="p-blob" rows="4" style="width:100%;font:12px/1.5
          ui-monospace,Menlo,monospace"
          placeholder='{"peer_id":"...","secret":"..."}'></textarea>
        <button class="btn ghost" id="p-go" style="margin-top:8px">Redeem the
          pasted invitation</button></details></div>`;
    if(pre&&pre.link) $('#p-code-in').focus();
    //: The address is shown before anything is sent to it. A link is a thing
    //: somebody else wrote, and the one fact worth reading off it is whose
    //: server it points at.
    const showTarget=()=>{
      const el=$('#p-claim-target');
      let host='';
      try{ host=new URL($('#p-link-in').value.trim()).origin; }catch{}
      const frag=($('#p-link-in').value.match(/[#&]u=([^&]*)/)||[])[1];
      if(frag){ try{ host=new URL(decodeURIComponent(frag)).origin; }catch{} }
      el.innerHTML=host?`<div class="panel" style="margin-bottom:12px">${interfaceTemplateMarkup('ui.romarr-will-send-this-code-to-host.3540c472bb',{host})}</div>`:'';
    };
    $('#p-link-in').oninput=showTarget; showTarget();
    $('#p-claim-go').onclick=async()=>{
      const b=$('#p-claim-go');
      b.disabled=true; b.textContent='Talking to their server…';
      const r=await j('/api/v1/peer/claim',{method:'POST',
        headers:{'content-type':'application/json'},
        body:JSON.stringify({link:$('#p-link-in').value.trim(),
                             code:$('#p-code-in').value.trim()})});
      b.disabled=false; b.textContent='Become friends';
      if(!r.ok){ if(r.error)toastAppMessage(r.error);else toastLabel('ui.that-invitation-was-refused.dbe525c91c'); return; }
      if(r.warning) toastAppMessage(r.warning);
      if(r.name&&r.detail)toastMessage('ui.connected-to-friend-they-confirm-you.d27741887e',
        {friend:r.name});
      else if(r.detail)toastAppMessage(r.detail);
      else toastLabel('ui.your-friend-request-was-sent-they-st.123ded17ef');
      go('peers');
    };
    $('#p-go').onclick=async()=>{
      let blob;
      try{ blob=JSON.parse($('#p-blob').value); }
      catch{ toastLabel('ui.that-is-not-a-valid-invitation.f57618f0cb'); return; }
      const r=await j('/api/v1/peer/redeem',{method:'POST',
        headers:{'content-type':'application/json'},
        body:JSON.stringify({invite:blob})});
      if(r.error){toastAppMessage(r.error);return;}
      toastLabel('ui.your-friend-request-was-sent-they-st.123ded17ef');
      go('peers');
    };
  };
  $('#p-redeem').onclick=()=>claimForm(null);

  let waiting=null;
  try{ waiting=JSON.parse(sessionStorage.getItem('romarr-invite')||'null'); }
  catch{}
  if(waiting&&waiting.peer_id&&waiting.url){
    try{ sessionStorage.removeItem('romarr-invite'); }catch{}
    claimForm({link:waiting.url.replace(/\/+$/,'')+'/link#i='
      +encodeURIComponent(waiting.peer_id)
      +'&u='+encodeURIComponent(waiting.url)});
    $('#p-out').scrollIntoView({block:'nearest'});
  }

  document.querySelectorAll('[data-pconfirm]').forEach(b=>b.onclick=async()=>{
    await j('/api/v1/peer/confirm',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({peer_id:b.dataset.pconfirm})});
    toastLabel('ui.confirmed.fe00b67b6d'); go('peers');
  });
  document.querySelectorAll('[data-prevoke]').forEach(b=>b.onclick=async()=>{
    if(!confirmMessage('ui.remove-this-friend-they-lose-access.6c1fc6cefa')) return;
    await fetch('/api/v1/peer/'+b.dataset.prevoke,{method:'DELETE'});
    toastLabel('ui.removed.4118fb4fed'); go('peers');
  });
  document.querySelectorAll('[data-pedit]').forEach(b=>b.onclick=()=>
    sharingEditor(list[Number(b.dataset.pedit)]));
  document.querySelectorAll('[data-pbrowse]').forEach(b=>b.onclick=()=>
    friendShelf(b.dataset.pbrowse));

  //: Poll while the background read is running, so the page shows it moving
  //: rather than looking stuck. Stops itself when the page changes.
  const seedPoll=async()=>{
    if(location.hash.replace('#','')!=='peers') return;
    const s=await j('/api/v1/hashes').catch(()=>null);
    if(!s) return;
    const st=s.seed||{};
    const live=$('#p-seedlive');
    if(!live) return;
    if(st.running){
      live.innerHTML=`<div class="panel" style="margin-top:10px">${interfaceTemplateMarkup('ui.reading-your-library-seen-entries-ch.17d1ca60ec',
        {seen:fmt(st.seen||0),added:fmt(st.added||0)})}</div>`;
      setTimeout(seedPoll,2000);
    } else if(st.status==='done'&&st.seen){
      live.innerHTML=`<div class="panel" style="margin-top:10px">${
      appMessageMarkup(st.detail||'')}</div>`;
    } else if(st.status==='failed'){
      live.innerHTML=`<div class="panel panel-warn" style="margin-top:10px">${
        appMessageMarkup(st.error||'The library read failed.')}</div>`;
    }
  };
  seedPoll();

  $('#p-seed').onclick=async()=>{
    const b=$('#p-seed');
    b.disabled=true; b.textContent='Starting…';
    const r=await j('/api/v1/hashes/seed',{method:'POST',
      headers:{'content-type':'application/json'},body:'{}'});
    b.disabled=false; b.textContent='Read them again now';
    toastAppMessage(r.detail||r.error||'');
    seedPoll();
  };

  $('#p-romm').onclick=()=>{
    const m=document.createElement('div');
    m.className='modal';
    m.innerHTML=`<div class="box">
      <h3>Add a friend who runs RomM</h3>
      <div class="sub">They do not need ROMarr, and nothing has to be
        installed on their server. Ask them to make you an account on their
        RomM — read-only is enough.</div>
      <div class="field"><label>Their RomM address</label>
        <input type="text" data-f="url" placeholder="https://romm.their-server.com"></div>
      <div class="field"><label>Username they gave you</label>
        <input type="text" data-f="username" autocomplete="off"></div>
      <div class="field"><label>Password</label>
        <input type="password" data-f="password" autocomplete="off"></div>
      <div class="field"><label>Call them (optional)</label>
        <input type="text" data-f="name"></div>
      <div class="panel" data-i18n="ui.romarr-reads-the-library-through-rom.b4a9f1ba95">ROMarr reads the library through RomM’s API, including the SHA1 hash RomM stores for each ROM. Netplay uses that hash to match the same file across servers, even if the other server does not know this protocol.</div>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:14px">
        <button class="btn ghost" data-close="1">Cancel</button>
        <button class="btn" id="rm-go">Connect</button></div></div>`;
    openModal(m);
    const close=()=>closeModal();
    m.querySelector('[data-close]').onclick=close;
    m.onclick=e=>{ if(e.target===m) close(); };
    m.querySelector('#rm-go').onclick=async()=>{
      const val=f=>m.querySelector(`[data-f="${f}"]`).value.trim();
      const btn=m.querySelector('#rm-go');
      btn.disabled=true; btn.textContent='Connecting…';
      const r=await j('/api/v1/peer/romm',{method:'POST',
        headers:{'content-type':'application/json'},
        body:JSON.stringify({url:val('url'),username:val('username'),
          password:val('password'),name:val('name')})});
      btn.disabled=false; btn.textContent='Connect';
      if(r.error){ toastAppMessage(r.error); return; }
      close();
      if(r.name&&Number.isFinite(Number(r.titles))){
        const source='Connected to {friend}: {count} title with hashes ROMarr can match on.';
        toastMessage(source,{friend:r.name,count:Number(r.titles)});
      } else if(r.detail)toastAppMessage(r.detail);
      else toastLabel('ui.connected.22965568d2');
      go('peers');
    };
  };
};

//: Browsing a friend's library. Their shelf is fetched once and filtered
//: here, so typing in the search box does not bill somebody else's server
//: for every keystroke.
const FSHELF={peer:'',q:'',platform:'',offset:0};

async function friendShelf(peerId, opts){
  Object.assign(FSHELF, {peer:peerId}, opts||{});
  const out=$('#p-shelf');
  if(!out) return;
  out.innerHTML='<div class="empty">Asking your friend’s server…</div>';
  const p=new URLSearchParams({peer_id:FSHELF.peer, q:FSHELF.q,
    platform:FSHELF.platform, offset:FSHELF.offset, limit:100});
  const r=await j('/api/v1/friends/shelf?'+p.toString()).catch(()=>({}));
  if(!r.ok){
    out.innerHTML=`<div class="panel panel-warn" style="margin-top:14px">${
      appMessageMarkup(r.error||'Could not reach that friend.')}</div>`;
    return;
  }
  const rows=r.items||[];
  const pages=Math.ceil((r.total||0)/100);
  const page=Math.floor(FSHELF.offset/100)+1;
  const friendName=String(r.friend||'');
  const friendTitle=friendName
    ?interfaceTemplateMarkup('ui.friend-s-library.11aef5ed10',{friend:friendName})
    :interfaceMarkup('ui.your-friends-library.53c2cbe5df');
  const accessLabels={catalogue:'See titles only',stream:'Play here',fetch:'Download from me'};
  const accessMarkup=r.access==='catalogue'
    ?interfaceMarkup('ui.you-can-add-anything-here-to-your-ow.3972ab31c3')
    :interfaceMarkup('ui.they-allow.293deba9f6')+' '+(accessLabels[r.access]
      ?interfaceMarkup(accessLabels[r.access]):appMessageMarkup(r.access||'—'));
  out.innerHTML=`<div style="margin-top:18px;border-top:1px solid var(--line);
      padding-top:16px">
    <h3 style="margin:0 0 4px">${friendTitle}</h3>
    <p class="help">${interfaceTemplateMarkup('ui.count-of-total-shared-titles.0920f3bc8f',
      {count:fmt(r.total||0),total:fmt(r.shelf_total||0)})}
      ${accessMarkup}
      ${r.stale?`<b>${interfaceMarkup('ui.showing-the-last-copy-their-server-d.ca1eb552a5')}</b>`:''}</p>
    <div class="row" style="flex-wrap:wrap;gap:8px;margin-bottom:10px">
      <input type="text" id="fs-q" placeholder="Search their library"
        value="${esc(FSHELF.q)}" style="flex:1;min-width:200px">
      <select id="fs-plat"><option value="" data-i18n="ui.all-platforms.6d46bb346f">All platforms</option>
        ${(r.platforms||[]).map(pl=>`<option value="${esc(pl)}"${
          pl===FSHELF.platform?' selected':''}>${esc(pl)}</option>`).join('')}
      </select>
      <button class="btn ghost" id="fs-refresh">Refresh from them</button>
    </div>
    ${rows.length?`<table><thead><tr><th>Title</th><th>Platform</th>
      <th>Year</th><th>Verified</th><th></th></tr></thead><tbody>
      ${rows.map(g=>`<tr>
        <td>${esc(g.title||'')}</td>
        <td>${esc(g.platform||'')}</td>
        <td>${g.year?regionalYear(g.year):''}</td>
        <td>${g.verified?'<span class="pill imported">verified</span>':''}</td>
        <td style="text-align:end"><div class="rowact">
          <button data-fwant="${esc(g.title||'')}"
            data-fplat="${esc(g.platform||'')}">Add to Wanted</button>
          <button data-fplay="${esc(g.title||'')}"
            data-fpplat="${esc(g.platform||'')}">Play together</button>
        </div></td></tr>`).join('')}</tbody></table>
      ${pages>1?`<div class="row" style="gap:8px;margin-top:10px">
        <button class="btn ghost" id="fs-prev"${page<=1?' disabled':''}>Previous</button>
        <span style="color:var(--dim);font-size:12px;align-self:center"
          >${interfaceTemplateMarkup('ui.page-page-of-pages.240ab6d8dc',
            {page:fmt(page),pages:fmt(pages)})}</span>
        <button class="btn ghost" id="fs-next"${page>=pages?' disabled':''}>Next</button>
      </div>`:''}`
      :'<div class="empty">Nothing matches. They may not share this platform.</div>'}
    <div id="fs-out"></div></div>`;

  const reload=o=>friendShelf(FSHELF.peer,o);
  $('#fs-q').onchange=e=>reload({q:e.target.value,offset:0});
  $('#fs-plat').onchange=e=>reload({platform:e.target.value,offset:0});
  $('#fs-refresh').onclick=async()=>{
    const rp=new URLSearchParams({peer_id:FSHELF.peer,refresh:'1',limit:1});
    await j('/api/v1/friends/shelf?'+rp.toString()).catch(()=>({}));
    reload({});
  };
  if($('#fs-prev')) $('#fs-prev').onclick=()=>reload({offset:Math.max(0,FSHELF.offset-100)});
  if($('#fs-next')) $('#fs-next').onclick=()=>reload({offset:FSHELF.offset+100});

  document.querySelectorAll('[data-fwant]').forEach(b=>b.onclick=async()=>{
    const r=await j('/api/v1/friends/want',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({peer_id:FSHELF.peer,title:b.dataset.fwant,
        platform:b.dataset.fplat})});
    if(r.ok)toastMessage('ui.added-detail.96268cbde3',{detail:r.detail||''});
    else if(r.error)toastAppMessage(r.error);else toastLabel('ui.could-not-add.4c45a2e67f');
  });
  document.querySelectorAll('[data-fplay]').forEach(b=>b.onclick=async()=>{
    $('#fs-out').innerHTML='<div class="empty">Comparing dumps…</div>';
    const r=await j('/api/v1/friends/netplay',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({peer_id:FSHELF.peer,title:b.dataset.fplay,
        platform:b.dataset.fpplat})});
    $('#fs-out').innerHTML=netplayVerdict(r);
  });
}

//: Netplay never reports a bare success. Each verdict says what was compared
//: and what it means, because "mismatch" is the one people otherwise spend an
//: evening blaming on their connection.
function netplayVerdict(r){
  const cls=r.ok?'panel':'panel panel-warn';
  const head={
    ready:'Ready — you both have the same dump',
    unverified:'Playable, with a caveat',
    mismatch:'Same game, different dumps',
    missing:'They do not have this dump',
    unhashed:'ROMarr has not hashed your copy yet',
    error:'Could not ask'
  }[r.status]||r.status||'No answer';
  const headMarkup=appMessageMarkup(head);
  let extra='';
  if(r.room){
    extra=`<div style="margin-top:8px">${interfaceMarkup('ui.room.911ea89c43')} <code>${esc(r.room)}</code>
      — ${interfaceTemplateMarkup('ui.both-servers-derive-this-independent.98f26e4e94',
        {friend:r.friend||translateLabel('ui.your-friend.ac3a0c1979',readInterfaceLanguage())})}</div>`;
  }
  if(r.sha1){
    extra+=`<div style="margin-top:6px;color:var(--dim);font-size:11.5px">
      ${interfaceTemplateMarkup('ui.compared-on-sha1-sha1-not-the-title.5935055754',{sha1:r.sha1})}</div>`;
  }
  return `<div class="${cls}" style="margin-top:12px"><b>${headMarkup}</b>
    ${r.detail?`<div style="margin-top:6px">${appMessageMarkup(r.detail)}</div>`:''}
    ${extra}</div>`;
}

function sharingEditor(peer){
  const m=document.createElement('div');
  m.className='modal';
  const opt=(v,cur,label)=>`<option value="${v}"${v===cur?' selected':''}>${label}</option>`;
  m.innerHTML=`<div class="box">
    <h3>${interfaceTemplateMarkup('ui.what-friend-can-see.22410cd2df',{friend:peer.name})}</h3>
    <div class="sub">Visibility and downloading are separate permissions.</div>
    <div class="field"><label>They see</label>
      <select data-f="scope">
        ${opt('none',peer.scope,'Nothing (peered for netplay only)')}
        ${opt('platforms',peer.scope,'Only the platforms I name')}
        ${opt('verified',peer.scope,'Only DAT-verified dumps')}
        ${opt('all',peer.scope,'Everything in my library')}
      </select></div>
    <div class="field"><label>Platforms (comma separated, for the option above)</label>
      <input type="text" data-f="platforms" data-list="1"
        value="${esc((peer.platforms||[]).join(', '))}" placeholder="snes, n64"></div>
    <div class="field"><label>They may</label>
      <select data-f="access">
        ${opt('catalogue',peer.access,'See titles only — they acquire it themselves')}
        ${opt('stream',peer.access,'Play it here, no file transfer')}
        ${opt('fetch',peer.access,'Download the file from me')}
      </select>
      <div style="color:var(--dim);font-size:11.5px;margin-top:4px">
        Allowing downloads lets this person fetch files from your server.
        Enable it only if you intend to share those files.</div></div>
    <label class="check"><input type="checkbox" data-f="delegate_users"
      ${peer.delegate_users?'checked':''}><span>Their users get this too,
      not just them</span></label>
    <div class="foot">
      <button class="btn ghost sp" data-close>Cancel</button>
      <button class="btn" id="p-save">Save</button></div></div>`;
  openModal(m);
  m.onclick=e=>{ if(e.target===m||e.target.dataset.close!==undefined) closeModal(); };
  m.querySelector('#p-save').onclick=async()=>{
    const f=readForm();
    const r=await j('/api/v1/peer/policy',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({peer_id:peer.peer_id,scope:f.scope,
        access:f.access,platforms:f.platforms,
        delegate_users:f.delegate_users})});
    closeModal(); if(r.error)toastAppMessage(r.error);else toastLabel('ui.saved.b5c120b316'); go('peers',true);
  };
}

RENDER.ecosystem=async()=>{
  const d=await j('/api/v1/ecosystem').catch(()=>({categories:{}}));
  const cats=d.categories||{};
  const card=p=>`<div class="pcard"${p.is_self?' style="border-color:var(--accent)"':''}>
    <h4>${esc(p.name)}${p.is_self?' <span class="pill">you are here</span>':''}</h4>
    <div class="desc">${esc(p.blurb)}</div>
    <div class="rowact" style="margin-top:8px;flex-wrap:wrap;gap:6px">
      ${p.repo?`<a class="btn ghost" href="${esc(p.repo)}" target="_blank"
        rel="noopener noreferrer" style="text-decoration:none">GitHub</a>`:''}
      ${p.site?`<a class="btn ghost" href="${esc(p.site)}" target="_blank"
        rel="noopener noreferrer" style="text-decoration:none">Website</a>`:''}
      ${p.install?`<button class="btn ghost" data-copy="${esc(p.install)}"
        title="${esc(p.install)}">Copy install</button>`:''}
    </div></div>`;
  $('#page').innerHTML=`<div class="card"><h3>The ecosystem ROMarr stands on</h3>
      <p class="help">${interfaceMarkup('ui.romarr-acquires-roms-and-files-them.dc74906ba8')}</p></div>`
    +Object.entries(cats).map(([name,projects])=>
      `<div class="card"><h3>${esc(name)}</h3>
        <div class="pgrid">${projects.map(card).join('')}</div></div>`).join('');
  document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{
    try{ await navigator.clipboard.writeText(b.dataset.copy);
      toastMessage('ui.copied-value.f8fce2fbf6',{value:b.dataset.copy}); }
    catch{ toastAppMessage(b.dataset.copy); }
  });
};

RENDER.stats=async()=>{
  const s=await j('/api/v1/stats');
  const hours=Math.floor((s.uptime_seconds||0)/3600);
  const bar=(entries)=>{
    const rows=Object.entries(entries||{});
    if(!rows.length) return '<div class="empty">Nothing yet.</div>';
    const max=Math.max(...rows.map(([,v])=>v));
    return rows.map(([k,v])=>`<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
      <span style="width:180px;color:var(--dim);font-size:12.5px;text-align:end">${esc(k)}</span>
      <div style="flex:1;background:var(--line);border-radius:3px;height:14px">
        <div style="width:${Math.max(4,Math.round(v/max*100))}%;height:14px;
          background:var(--accent);border-radius:3px"></div></div>
      <b style="width:48px">${fmt(v)}</b></div>`).join('');
  };
  $('#page').innerHTML=`
    ${s.update_available?`<div class="card" style="border-color:var(--warn)">
      <h3>Update available</h3><p class="help">${interfaceTemplateMarkup('ui.romarr-latest-is-out-this-install-is.46b0565005',
        {latest:s.latest_version,current:s.version})}</p></div>`:''}
    <div class="card"><h3>This install</h3><div class="st">
      <div><b>${esc(s.version)}</b><span>Version</span></div>
      <div><b>${num(s.library_on_disk)}</b><span>On disk here</span></div>
      <div><b>${num(s.library_catalogued)}</b><span>Catalogued, streams</span></div>
      <div><b>${num(s.library_games)}</b><span>Total known</span></div>
      <div><b>${fmt(s.wanted)}</b><span>Wanted</span></div>
      <div><b>${fmt(hours)}h</b><span>Uptime</span></div>
      <div><b>${fmt((s.events||{}).grabbed||0)}</b><span>Total grabs</span></div>
      <div><b>${fmt((s.events||{}).imported||0)}</b><span>Total imports</span></div>
      <div><b>${fmt((s.events||{}).failed||0)}</b><span>Failures</span></div>
      <div><b>${num(s.average_rating)}</b><span>${interfaceTemplateMarkup('ui.avg-rating-count-rated.23dce76dcd',{count:fmt(s.rated||0)})}</span></div>
    </div>
    <p class="help" style="margin:10px 0 0">“Total known” is the sum of the other two values and includes every row stored by your library server. Only the first number is bytes you already have; the second counts items that would need to be streamed or fetched first.</p></div>
    ${Object.keys(s.library_sources||{}).length>1?`<div class="card">
      <h3>Where the library comes from</h3>
      ${bar(Object.fromEntries(Object.entries(s.library_sources)
        .sort((a,b)=>b[1]-a[1])
        .map(([k,v])=>[SOURCE_LABEL[k]||k,v])))}
      <p class="help">These counts come from rows ROMarr read. Each catalogue is identified by the filename written by its indexer. Rows that match neither are labeled “source unknown” instead of being assigned to the larger catalogue.</p></div>`:''}
    <div class="card"><h3>Imports by platform</h3>${bar(s.imported_by_platform)}</div>
    <div class="card"><h3>Grabs by indexer</h3>${bar(s.grabbed_by_indexer)}</div>
    <div class="card"><h3>Library audit</h3>
      <p class="help" data-i18n="ui.this-audit-compares-file-hashes-with.237e4ab782">This audit compares file hashes with your DATs to find bad dumps (the right size but wrong bytes, from bit rot or tampering) and byte-identical duplicates. Run one platform at a time; it works in the background.</p>
      <div class="row">
        <select id="au-plat">${PLATFORMS.map(p=>
          `<option value="${esc(p.slug)}">${esc(p.name)}</option>`).join('')}</select>
        <button class="btn" id="au-go">Audit</button></div>
      <div id="au-out" style="margin-top:10px"></div></div>
    <div class="card"><h3>Shelf</h3><div class="st">
      <div><b>${fmt((s.statuses||{}).playing||0)}</b><span>Playing</span></div>
      <div><b>${fmt((s.statuses||{}).completed||0)}</b><span>Completed</span></div>
      <div><b>${fmt((s.statuses||{}).shelved||0)}</b><span>Shelved</span></div>
    </div><p class="help">Set from any game tile in the Library.</p></div>`;

  const paintAudit=a=>{
    // Guard the node: this is called from a fetch .then() and a poll timer,
    // both of which can resolve after the user has left the Stats page.
    // Writing to a #au-out that no longer exists is the "Cannot set
    // innerHTML of null" a late audit response used to throw.
    const out=$('#au-out'); if(!out) return;
    if(!a||!a.status||a.status==='never run'){out.innerHTML='';return;}
    out.innerHTML=`<p class="help">
      <b>${esc(a.platform||'')}</b> — ${statusMarkup(a.status)} ·
      ${interfaceTemplateMarkup('ui.scanned-scanned-verified-verified-ba.a7fc60c549',
        {scanned:fmt(a.scanned||0),verified:fmt(a.verified||0),bad:fmt(a.bad||0),
         unknown:fmt(a.unknown||0),duplicates:fmt((a.duplicates||[]).length)})}</p>
      ${(a.bad_files||[]).length?`<details><summary class="help"
        style="cursor:pointer;margin:0">Bad dumps</summary>
        <div style="color:var(--dim);font-size:12px">${a.bad_files.map(f=>
          esc(f.file)+' — '+esc(f.detail)).join('<br>')}</div></details>`:''}
      ${(a.duplicates||[]).length?`<details><summary class="help"
        style="cursor:pointer;margin:0">Duplicates (byte-identical)</summary>
        <div style="color:var(--dim);font-size:12px">${a.duplicates.map(d=>
          esc(d.file)+' = '+esc(d.same_as)).join('<br>')}</div></details>`:''}`;
  };
  j('/api/v1/audit').then(paintAudit).catch(()=>{});
  let auditTimer=null;
  $('#au-go').onclick=async()=>{
    const a=await j('/api/v1/audit',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({platform:$('#au-plat').value})});
    if(a.error){toastAppMessage(a.error);return;}
    paintAudit(a);
    clearInterval(auditTimer);
    auditTimer=setInterval(async()=>{
      if(!$('#au-out')){clearInterval(auditTimer);return;}
      const s=await j('/api/v1/audit').catch(()=>null);
      if(s) paintAudit(s);
      if(s&&s.status!=='running') clearInterval(auditTimer);
    },2000);
  };
};

RENDER.queue=async()=>{
  const d=await j('/api/v1/queue');
  const failed=(d.items||[]).filter(i=>i.state==='failed').length;
  $('#page').innerHTML=`<div class="row" style="margin-bottom:12px">
      <button class="btn ghost" id="q-import">Import completed now</button>
      ${failed?`<button class="btn ghost" id="q-clearfail">${interfaceTemplateMarkup('ui.clear-count-failed.ae1c7a9e34',{count:fmt(failed)})}</button>`:''}
      <span class="help" style="margin:0">${interfaceTemplateMarkup('ui.in-queue-count.205a6471b6', {count:fmt((d.items||[]).length)})}</span>
    </div>`+(d.items.length?`<table><thead><tr><th>Game</th>
    <th>Platform</th><th>Release</th><th>Seeders</th><th>State</th><th></th></tr></thead><tbody>
    ${d.items.map((i,n)=>`<tr><td>${esc(i.game)}</td><td>${esc(i.platform)}</td>
      <td>${esc(i.release||'—')}</td><td>${num(i.seeders)}</td>
      <td><span class="pill ${esc(i.state)}">${statusMarkup(i.state)}</span>
      ${i.detail?`<div style="color:var(--dim);font-size:11.5px">${appMessageMarkup(i.detail)}</div>`:''}
      </td><td style="text-align:end"><div class="rowact">
        ${i.state==='failed'?`<button data-qretry="${n}">Retry</button>`:''}
        <button data-qremove="${n}">Remove</button></div></td></tr>`).join('')}
      </tbody></table>`
    :`<div class="empty">${interfaceMarkup('ui.the-queue-is-empty-active-requests-w.2e39b56365')}</div>`);

  $('#q-import').onclick=async e=>{
    e.target.disabled=true; e.target.textContent='Importing…';
    const r=await j('/api/v1/command',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({name:'ImportCompleted'})});
    if(r.message)toastAppMessage(r.message);else toastLabel('ui.done.11a6767d56'); go('queue'); refreshCounts();
  };
  const cf=$('#q-clearfail');
  if(cf) cf.onclick=async()=>{
    await j('/api/v1/queue/clear',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({state:'failed'})});
    go('queue'); refreshCounts();
  };
  const act=async(index,action)=>{
    const r=await j('/api/v1/queue/action',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({index:Number(index),action})});
    if(r.error)toastAppMessage(r.error);
    else toastLabel(action==='retry'?(r.ok?'Grabbed':'Still no luck'):'Removed');
    go('queue'); refreshCounts();
  };
  document.querySelectorAll('[data-qretry]').forEach(b=>b.onclick=()=>act(b.dataset.qretry,'retry'));
  document.querySelectorAll('[data-qremove]').forEach(b=>b.onclick=()=>act(b.dataset.qremove,'remove'));
};

RENDER.patches=async()=>{
  const state={q:'',kind:'',complete:false};
  const load=async()=>{
    const qs=new URLSearchParams({limit:'48'});
    if(state.q) qs.set('q',state.q);
    if(state.kind) qs.set('kind',state.kind);
    if(state.complete) qs.set('completeOnly','true');
    const d=await j('/api/v1/patches/search?'+qs);
    const rows=d.results||[];
    $('#patch-results').innerHTML=rows.length?`<table><thead><tr><th>Project</th>
      <th>Game</th><th>Platform</th><th>Kind</th><th>Version</th><th>Status</th>
      <th>Base game</th></tr></thead><tbody>${rows.map(p=>{
        const v=(p.versions||[])[0]||{};
        return `<tr><td>${esc(p.name||p.title||p.id)}</td>
          <td>${esc((p.game||{}).title||'')}</td>
          <td>${esc((p.game||{}).platformSlug||'')}</td>
          <td>${esc(p.kind||'')}</td>
          <td>${esc(v.label||v.version||'—')}</td>
          <td>${esc(p.status||'')}${p.completeness?' · '+esc(p.completeness):''}</td>
          <td>${(v.base||{}).available?'In library':'<span style="color:var(--dim)">Not in library</span>'}</td></tr>`;
      }).join('')}</tbody></table>`
      :'<div class="empty">No patch projects match. Add a catalogue in Media Management or drop JSON files into the patch-catalog.d folder.</div>';
  };
  $('#page').innerHTML=`<div style="color:var(--dim);font-size:11.5px;margin-bottom:10px">
      Projects come from your own catalogue only. Completeness is what a project
      states, never a guess. Requests come from SeerrNG.</div>
    <div class="field" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <input type="search" id="patch-q" aria-label="Search patch projects" placeholder="Search">
      <select id="patch-kind" aria-label="Kind"><option value="">All kinds</option>
        <option value="translation">Translations</option><option value="hack">Hacks</option>
        <option value="improvement">Improvements</option></select>
      <label class="check"><input type="checkbox" id="patch-complete"><span>Complete only</span></label>
    </div>
    <div id="patch-results" aria-live="polite"></div>`;
  $('#patch-q').addEventListener('input',e=>{state.q=e.target.value;load();});
  $('#patch-kind').addEventListener('change',e=>{state.kind=e.target.value;load();});
  $('#patch-complete').addEventListener('change',e=>{state.complete=e.target.checked;load();});
  load();
};

RENDER.history=async()=>{
  const d=await j('/api/v1/history?limit=100');
  $('#page').innerHTML=d.items.length?`<table><thead><tr><th>When</th><th>Event</th>
    <th>Game</th><th>Platform</th><th>Release</th><th>Indexer</th></tr></thead><tbody>
    ${d.items.map(e=>`<tr><td style="color:var(--dim)">${esc(regionalDateTime(e.at))}</td>
      <td><span class="pill ${esc(e.kind)}">${statusMarkup(e.kind)}</span></td>
      <td>${esc(e.game)}</td><td>${esc(e.platform)}</td>
      <td style="color:var(--dim)">${esc(e.release||'—')}</td>
      <td style="color:var(--dim)">${esc(e.indexer||'—')}</td></tr>`).join('')}</tbody></table>`
    :'<div class="empty">No history yet.</div>';
};


/* ---------------- schema-driven editor ---------------- */
/* The form is built from the server's field list, so a new client or indexer
   type needs no change here -- the same thing the *arrs do with their schema
   endpoints. */
let SCHEMA = { downloadclient: {}, indexer: {}, library: {},
               metadataprovider: {}, connection: {} };

async function loadSchema(kind){
  if(Object.keys(SCHEMA[kind]).length) return SCHEMA[kind];
  const d = await j(`/api/v1/${kind}/schema`);
  SCHEMA[kind] = d.types || {};
  return SCHEMA[kind];
}

function fieldHtml(f, value){
  const v=value===undefined||value===null?f.default:value;
  const fieldName=String(f.name||'field');
  const fieldId='schema-'+fieldName.replace(/[^A-Za-z0-9_-]/g,'-');
  const fieldData=esc(fieldName);
  const required=f.required===true;
  const requiredAttr=required?' required aria-required="true"':'';
  const helpId=fieldId+'-help';
  const described=f.help?` aria-describedby="${helpId}"`:'';
  const help=f.help?`<div id="${helpId}" class="help" style="font-size:11.5px;margin-top:4px">${esc(f.help)}</div>`:'';
  if(f.type==='bool')
    return `<label class="check"><input id="${fieldId}" type="checkbox" data-f="${fieldData}"${requiredAttr}${described}
      ${v?'checked':''}><span>${esc(f.label)}</span></label>${help}`;
  // Lists stay comma-separated in settings, with the same parsing on save.
  if(f.type==='list')
    return `<div class="field"><label for="${fieldId}">${esc(f.label)}</label>
      <input id="${fieldId}" type="text" data-f="${fieldData}" data-list="1"${requiredAttr}${described}
        value="${esc(Array.isArray(v)?v.join(', '):(v??''))}">${help}</div>`;
  if(f.type==='select')
    return `<div class="field"><label for="${fieldId}">${esc(f.label)}</label>
      <select id="${fieldId}" data-f="${fieldData}"${requiredAttr}${described}>${(f.options||[]).map(o=>{
        const [ov,ot]=Array.isArray(o)?o:[o,o];
        const source=String(ot??'');
        const marker=hasLabel(source)?` data-i18n-key="${esc(stableLocalizationKey(source)||source)}"`:'';
        return `<option value="${esc(ov)}"${String(v??'')===String(ov)?' selected':''}${marker}>${esc(translateLabel(source,readInterfaceLanguage()))}</option>`;
      }).join('')}</select>${help}</div>`;
  const type=f.type==='int'?'number':(f.type==='secret'?'password':'text');
  return `<div class="field"><label for="${fieldId}">${esc(f.label)}</label>
    <input id="${fieldId}" type="${type}" data-f="${fieldData}" value="${esc(v??'')}"${requiredAttr}${described}
      ${f.type==='secret'?'autocomplete="new-password"':''}>${help}</div>`;
}

function readForm(){
  const out = {};
  document.querySelectorAll('[data-f]').forEach(el => {
    out[el.dataset.f] = el.type === 'checkbox' ? el.checked
      : el.type === 'number' ? (el.value === '' ? null : Number(el.value))
      : el.dataset.list ? el.value.split(',').map(x => x.trim()).filter(Boolean)
      : el.value;
  });
  return out;
}

let activeDialog=null, dialogReturnFocus=null, dialogPreviousState=null, dialogSequence=0;
const dialogFocusableSelector='a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
function dialogFocusables(dialog){
  return Array.from(dialog.querySelectorAll(dialogFocusableSelector))
    .filter(el=>el.getClientRects().length>0&&!el.closest('[hidden],[inert]'));
}
function openModal(modal){
  if(activeDialog&&activeDialog!==modal)closeModal();
  if($('#rail')?.classList.contains('mobile-open'))setMobileNavOpen(false,false);
  const heading=modal.querySelector('.box h1,.box h2,.box h3,[data-dialog-title]');
  const description=modal.querySelector('.box .sub');
  if(heading){
    if(!heading.id)heading.id='romarr-dialog-title-'+(++dialogSequence);
    modal.setAttribute('aria-labelledby',heading.id);
  }else{
    modal.setAttribute('aria-label','ROMarr dialog');
  }
  if(description){
    if(!description.id)description.id='romarr-dialog-description-'+dialogSequence;
    modal.setAttribute('aria-describedby',description.id);
  }
  modal.setAttribute('role','dialog');
  modal.setAttribute('aria-modal','true');
  modal.setAttribute('tabindex','-1');
  dialogReturnFocus=document.activeElement;
  const main=$('#main-content'),rail=$('#rail');
  dialogPreviousState={overflow:document.body.style.overflow,
    mainInert:main?.inert||false,railInert:rail?.inert||false};
  if(main)main.inert=true;
  if(rail)rail.inert=true;
  document.body.style.overflow='hidden';
  document.body.append(modal);
  activeDialog=modal;
  requestAnimationFrame(()=>{
    if(activeDialog!==modal)return;
    const target=dialogFocusables(modal)[0]||modal;
    target.focus({preventScroll:true});
  });
}
function closeModal(){
  const modal=activeDialog||document.querySelector('.modal');
  if(!modal)return;
  modal.remove();
  activeDialog=null;
  if(dialogPreviousState){
    document.body.style.overflow=dialogPreviousState.overflow;
    const main=$('#main-content'),rail=$('#rail');
    if(main)main.inert=dialogPreviousState.mainInert;
    if(rail)rail.inert=dialogPreviousState.railInert;
  }
  dialogPreviousState=null;
  const target=dialogReturnFocus;
  dialogReturnFocus=null;
  requestAnimationFrame(()=>{
    if(target?.isConnected)target.focus({preventScroll:true});
    else $('#page-title')?.focus({preventScroll:true});
  });
}
document.addEventListener('keydown',event=>{
  if(activeDialog){
    if(event.key==='Escape'){
      event.preventDefault();
      closeModal();
      return;
    }
    if(event.key==='Tab'){
      const focusables=dialogFocusables(activeDialog);
      if(!focusables.length){event.preventDefault();activeDialog.focus();return;}
      const first=focusables[0],last=focusables[focusables.length-1];
      if(event.shiftKey&&(document.activeElement===first||!activeDialog.contains(document.activeElement))){
        event.preventDefault();last.focus();
      }else if(!event.shiftKey&&(document.activeElement===last||!activeDialog.contains(document.activeElement))){
        event.preventDefault();first.focus();
      }
    }
    return;
  }
  if($('#rail')?.classList.contains('mobile-open')){
    if(event.key==='Escape'){event.preventDefault();setMobileNavOpen(false);return;}
    if(event.key==='Tab'){
      const focusables=Array.from($('#rail').querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled])'))
        .filter(el=>el.getClientRects().length>0);
      if(!focusables.length){event.preventDefault();return;}
      const first=focusables[0],last=focusables[focusables.length-1];
      if(event.shiftKey&&(document.activeElement===first||!$('#rail').contains(document.activeElement))){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&(document.activeElement===last||!$('#rail').contains(document.activeElement))){event.preventDefault();first.focus();}
    }
  }
});

/* What each editable kind is called, and which page lists it. Stated once so a
   fourth kind does not mean hunting for three ternaries. */
const KINDS = {
  downloadclient: { label: 'Download Client', page: 'clients' },
  indexer:        { label: 'Indexer',         page: 'indexers' },
  library:        { label: 'Library',         page: 'libraries' },
  metadataprovider: { label: 'Metadata Provider', page: 'metadata' },
  connection: { label: 'Connection', page: 'connections' },
};

/** Choose a type, then edit it. */
async function addItem(kind){
  const types = await loadSchema(kind);
  const m = document.createElement('div');
  m.className = 'modal';
  m.innerHTML = `<div class="box"><h3>Add ${esc((KINDS[kind]||{}).label || kind)}</h3>
    <div class="sub">Pick a type.</div>
    <div class="pick">${Object.entries(types).map(([k, t]) =>
      `<button data-t="${k}">${esc(t.label)}<small>${esc(t.protocol || k)}</small></button>`).join('')}</div>
    <div class="foot"><button class="btn ghost sp" data-close>Cancel</button></div></div>`;
  openModal(m);
  m.onclick = e => { if(e.target === m || e.target.dataset.close !== undefined) closeModal(); };
  m.querySelectorAll('[data-t]').forEach(b => b.onclick = () => {
    closeModal();
    editItem(kind, { type: b.dataset.t });
  });
}

async function editItem(kind, item){
  const types = await loadSchema(kind);
  const spec = types[item.type];
  if(!spec){ toastMessage('ui.unknown-type-type.668ca2388a',{type:item.type}); return; }
  const isNew = !item.id;
  // A new entry gets the type's sensible defaults rather than an empty form.
  if(isNew){
    if(spec.default_port && item.port === undefined) item.port = spec.default_port;
    if(item.name === undefined) item.name = spec.label;
  }

  const m = document.createElement('div');
  m.className = 'modal';
  const clientPathContext = kind === 'downloadclient'
    ? `<div class="panel-note"><b>Container path check</b><br>
      ROMarr library destination: <code>${esc(SETTINGS.library_path||'not configured')}</code>.<br>
      ${item.save_path
        ? `Configured client save path: <code>${esc(item.save_path)}</code>.`
        : 'This client reports the completed path for each download.'}
      ROMarr checks the actual completed path during import. If that path is not
      visible inside ROMarr, use the remote path mapping on Media Management;
      keep the download path and library destination distinct.</div>`
    : '';
  m.innerHTML = `<div class="box">
    <h3>${isNew ? 'Add' : 'Edit'} ${esc(spec.label)}</h3>
    <div class="sub">${esc(spec.protocol || (KINDS[kind]||{}).label || '')}${spec.managed ? ' · manages its own indexers' : ''}</div>
    ${clientPathContext}
    <div id="fields">${spec.fields.map(f => fieldHtml(f, item[f.name])).join('')}</div>
    <div id="testline"></div>
    <div class="foot">
      <button class="btn ghost" id="m-test">Test</button>
      ${isNew ? '' : '<button class="btn danger" id="m-del">Delete</button>'}
      <button class="btn ghost sp" data-close>Cancel</button>
      <button class="btn" id="m-save">Save</button>
    </div></div>`;
  openModal(m);
  m.onclick = e => { if(e.target === m || e.target.dataset.close !== undefined) closeModal(); };

  const payload = () => ({ ...readForm(), type: item.type, id: item.id });
  const line = (ok, msg) => {
    const status=m.querySelector('#testline');
    status.className = 'testline ' + (ok ? 'ok' : 'bad');
    status.setAttribute('role',ok?'status':'alert');
    status.setAttribute('aria-live',ok?'polite':'assertive');
    status.innerHTML = appMessageMarkup(msg);
  };

  m.querySelector('#m-test').onclick = async (e) => {
    e.target.disabled = true; line(true, 'Testing…');
    try{
      const r = await j(`/api/v1/${kind}/test`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload()) });
      line(r.ok, r.message || (r.ok ? 'Connected' : 'Failed'));
    }catch(_){line(false,'Could not reach ROMarr. Check the connection and try again.');}
    e.target.disabled = false;
  };

  m.querySelector('#m-save').onclick = async (e) => {
    e.target.disabled = true;
    try{
      const saved=await j(`/api/v1/${kind}`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload()) });
      if(saved.error){line(false,saved.error);e.target.disabled=false;return;}
      closeModal(); toastLabel('ui.saved.b5c120b316'); go((KINDS[kind] || {}).page || 'clients',true);
    }catch(_){
      line(false,'Could not save this connection. Check the connection and try again.');
      e.target.disabled=false;
    }
  };

  const del = m.querySelector('#m-del');
  if(del) del.onclick = async () => {
    if(!confirmMessage('ui.remove-name.01c1f02508',{name:item.name||spec.label})) return;
    del.disabled=true;
    try{
      const response=await fetch(`/api/v1/${kind}/${item.id}`, { method: 'DELETE' });
      const result=await response.json().catch(()=>({}));
      if(!response.ok||result.error)throw new Error(result.error||`Could not remove this entry (HTTP ${response.status}).`);
      closeModal(); toastLabel('ui.removed.4118fb4fed'); go((KINDS[kind] || {}).page || 'clients',true);
    }catch(error){line(false,error.message||'Could not remove this entry.');del.disabled=false;}
  };
}

/* ---------------- settings ---------------- */
function settingsPage(title, help, body, after){
  $('#page').innerHTML=`<div class="card"><h3>${title}</h3>
    <p class="help">${help}</p>${body}
    <div id="settings-save-status" class="help" role="status" aria-live="polite" aria-atomic="true"></div>
    <button class="btn" id="s-save">Save</button></div>`;
  if(after)after();
  const reportSettingsError=(message,control)=>{
    const status=$('#settings-save-status');
    status.setAttribute('role','alert');status.setAttribute('aria-live','assertive');
    status.textContent=message;
    control?.setAttribute('aria-invalid','true');
    control?.focus({preventScroll:false});
  };
  $('#s-save').onclick=async()=>{
    const patch={};
    document.querySelectorAll('[aria-invalid="true"]').forEach(el=>el.removeAttribute('aria-invalid'));
    document.querySelectorAll('[data-k]').forEach(el=>{
      patch[el.dataset.k]=el.type==='checkbox'?el.checked
        :el.type==='number'?(el.value===''?null:Number(el.value))
        :el.dataset.list?el.value.split(',').map(s=>s.trim()).filter(Boolean)
        :el.value;
    });
    const mappings=$('#remote-path-mappings');
    if(mappings)patch.remote_path_mappings=[...mappings.querySelectorAll('[data-mapping-row]')]
      .map(row=>({
        client_id:row.querySelector('[data-map-client]').value,
        remote:row.querySelector('[data-map-remote]').value.trim(),
        local:row.querySelector('[data-map-local]').value.trim(),
      })).filter(m=>m.remote&&m.local);
    const folders=$('#platform-folder-mappings');
    if(folders){
      const mapped={};
      for(const row of folders.querySelectorAll('[data-platform-folder-row]')){
        const name=row.querySelector('[data-platform-folder-name]').value.trim();
        const slug=row.querySelector('[data-platform-folder-slug]').value;
        if(!name&&!slug)continue;
        const invalidFolderName=!name||name==='.'||name==='..'||name.includes('/')
          ||name.includes(String.fromCharCode(92))||name.includes(String.fromCharCode(0));
        if(invalidFolderName||!slug){
          reportSettingsError('Enter one folder name and choose its platform.',
            row.querySelector(invalidFolderName?'[data-platform-folder-name]':'[data-platform-folder-slug]'));
          return;
        }
        const key=name.normalize('NFKC').toLocaleLowerCase();
        if(Object.keys(mapped).some(existing=>existing.normalize('NFKC').toLocaleLowerCase()===key)){
          reportSettingsError('Each platform folder name can be mapped only once.',
            row.querySelector('[data-platform-folder-name]'));
          return;
        }
        mapped[name]=slug;
      }
      patch.platform_folder_mappings=mapped;
    }
    const button=$('#s-save'),status=$('#settings-save-status');
    button.disabled=true;status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    status.textContent='Saving settings…';
    try{
      const response=await fetch('/api/v1/config',{method:'PUT',
        headers:{'content-type':'application/json'},body:JSON.stringify(patch)});
      const saved=await response.json().catch(()=>({}));
      if(!response.ok||!saved||typeof saved!=='object'||saved.error)
        throw new Error(saved.error||`Settings could not be saved (HTTP ${response.status}).`);
      SETTINGS=saved;status.textContent='Settings saved.';toastLabel('ui.saved.b5c120b316');
    }catch(error){
      status.setAttribute('role','alert');status.setAttribute('aria-live','assertive');
      status.textContent=String(error&&error.message||'Settings could not be saved. Try again.');
    }finally{button.disabled=false;}
  };
}
const fld=(k,label,val,type='text',extra='')=>`<div class="field"><label for="s-${k}">${label}</label>
  <input type="${type}" id="s-${k}" data-k="${k}" ${extra} value="${esc(val)}"></div>`;
const chk=(k,label,val)=>`<label class="check"><input type="checkbox" data-k="${k}"
  ${val?'checked':''}><span>${label}</span></label>`;

const sel=(k,label,options,val,help='')=>`<div class="field"><label for="s-${k}">${label}</label>
  <select id="s-${k}" data-k="${k}">${options.map(([v,t])=>{
    const source=String(t??''),marker=hasLabel(source)?` data-i18n-key="${esc(stableLocalizationKey(source)||source)}"`:'';
    return `<option value="${esc(v)}"${String(val)===v?' selected':''}${marker}>${esc(translateLabel(source,readInterfaceLanguage()))}</option>`;
  }).join('')}</select>
  ${help?`<div style="color:var(--dim);font-size:11.5px;margin-top:4px">${help}</div>`:''}</div>`;

const pathMappingRow=m=>{
  m=m||{};
  const clientId=m.client_id==null?'':String(m.client_id);
  const clients=SETTINGS.download_clients||[];
  const options=[['','All download clients'],...clients.map(c=>[
    String(c.id||''),`${c.name||c.type||'Download client'} · ${c.type||'client'} · ${c.host||'local'}${c.port?':'+c.port:''}`])];
  if(clientId&&!clients.some(c=>String(c.id||'')===clientId))
    options.push([clientId,`Unavailable download client · ${clientId}`]);
  const rowName=m.remote?`Path mapping for ${m.remote}`:'New path mapping';
  return `<div data-mapping-row class="mapping-row path-map" role="group" aria-label="${esc(rowName)}">
    <label class="mapping-field">Download client
      <select data-map-client>${options.map(([value,label])=>{
        const unavailable=value===clientId&&!clients.some(c=>String(c.id||'')===clientId);
        const marker=value===''?' data-i18n="ui.all-download-clients.7a29531f8e"'
          :unavailable?' data-i18n-template="Unavailable download client · {id}" data-i18n-values="'+esc(JSON.stringify({id:clientId}))+'"':'';
        const text=value===''?translateLabel('ui.all-download-clients.7a29531f8e',readInterfaceLanguage())
          :unavailable?translateTemplate('Unavailable download client · {id}',{id:clientId}):label;
        return `<option value="${esc(value)}"${value===clientId?' selected':''}${marker}>${esc(text)}</option>`;
      }).join('')}</select>
    </label>
    <label class="mapping-field">Remote path
      <input data-map-remote value="${esc(m.remote||'')}" placeholder="Path reported by client">
    </label>
    <label class="mapping-field">Local path
      <input data-map-local value="${esc(m.local||'')}" placeholder="Path visible to ROMarr">
    </label>
    <button class="btn ghost" type="button" data-mapping-remove aria-label="Remove ${esc(rowName)}">Remove</button>
  </div>`;
};
const pathMappingRows=m=>(Array.isArray(m)&&m.length?m:[{}]).map(pathMappingRow).join('');
const platformFolderRow=m=>{
  m=m||{};
  const folder=String(m.folder||'');
  const rowName=folder?`Platform folder mapping for ${folder}`:'New platform folder mapping';
  const options=(PLATFORMS||[]).map(p=>`<option value="${esc(p.slug)}"${String(m.platform||'')===String(p.slug)?' selected':''}>${esc(p.name||p.slug)}</option>`).join('');
  return `<div data-platform-folder-row class="mapping-row platform-folder" role="group" aria-label="${esc(rowName)}">
    <label class="mapping-field">Folder name
      <input data-platform-folder-name value="${esc(folder)}" placeholder="e.g. PS2 Games">
    </label>
    <label class="mapping-field">Platform
      <select data-platform-folder-slug><option value="">Choose a platform</option>${options}</select>
    </label>
    <button class="btn ghost" type="button" data-platform-folder-remove aria-label="Remove ${esc(rowName)}">Remove</button>
  </div>`;
};
const platformFolderRows=m=>Object.entries(m&&typeof m==='object'&&!Array.isArray(m)?m:{}).map(([folder,platform])=>platformFolderRow({folder,platform})).join('');
RENDER.media=()=>settingsPage('Media Management',
  'Where imported ROMs and the shared metadata catalog live. The ROM path must be the path your library server scans. Completed-download paths are reported by the client per item; compare that exact path before import and add a remote path mapping below when ROMarr sees it somewhere else.',
  fld('library_path','ROM library root',SETTINGS.library_path)
  +fld('metadata_path','Shared metadata root',SETTINGS.metadata_path||'')
  +`<div class="help" style="margin:-6px 0 14px">Use one ROM root with one folder per platform, such as <code>Emulation/roms/ps2</code> and <code>Emulation/roms/snes</code>; you do not need a separate library entry for each system. With EmuDeck, point this at its <code>Emulation/roms</code> folder, not the wider <code>Emulation</code> directory. Keep shared metadata alongside it at <code>Emulation/metadata</code>, outside the ROM root, and mount that folder on each client. ROMarr keeps one catalog per platform and deduplicated artwork here, so a rename or path change does not trigger another provider lookup.</div>`
  +`<fieldset class="settings-group"><legend>Platform folder names</legend>
    <p class="help" style="margin:4px 0 8px">ROMarr recognizes platform slugs and unambiguous ES-DE system names automatically. Add a mapping only when your existing folder uses another name, such as <code>PS2 Games</code>. Folder names are matched only at the library root.</p>
    <div id="platform-folder-mappings">${platformFolderRows(SETTINGS.platform_folder_mappings)}</div>
    <button class="btn ghost" id="platform-folder-mapping-add" type="button">Add folder mapping</button></fieldset>`
  +fld('esde_gamelists_path','Existing ES-DE gamelists folder (optional)',SETTINGS.esde_gamelists_path||'')
  +fld('esde_media_path','Existing ES-DE media folder (optional)',SETTINGS.esde_media_path||'')
  +`<div class="help" style="margin:-6px 0 14px">Set these only when you want ROMarr to import an existing ES-DE setup visible inside this server. ROMarr publishes shared output to <code>metadata/esde/gamelists</code> and <code>metadata/esde/downloaded_media</code>. Link or configure ES-DE's gamelist directory to the shared <code>gamelists</code> folder and set its Game media directory to <code>downloaded_media</code>. Media files follow ROM names and folders, so artwork remains matched when clients mount the same library at different paths.</div>`
  +fld('dat_path','DAT directory',SETTINGS.dat_path||'')
  +`<fieldset class="settings-group"><legend>Remote path mappings</legend>
     <p class="help" style="margin:4px 0 8px">
       Map the path a download client reports to the path ROMarr can see. Choose
       a client to keep SABnzbd and torrent paths separate, or use All download
       clients for a shared path. Client-specific mappings take precedence;
       within a scope, the longest matching prefix wins.</p>
     <div id="remote-path-mappings">${pathMappingRows(SETTINGS.remote_path_mappings)}</div>
     <button class="btn ghost" id="remote-path-mapping-add" type="button">Add path mapping</button></fieldset>`
  +sel('library_layout','Folder structure',
     [['flat','Structure A — platform/rom'],['nested','Structure B — platform/roms/rom']],
     SETTINGS.library_layout||'flat',
     'Match your library server. RomM Structure A files as '
     +'&lt;root&gt;/&lt;platform&gt;/&lt;rom&gt;; Structure B adds a roms/ level. '
     +'Per-library overrides live on the Libraries page.')
  +chk('rename_on_import','Rename on import',SETTINGS.rename_on_import)
  +chk('switch_auto_route','Route Switch updates and DLC by TitleDB filename ID',SETTINGS.switch_auto_route)
  +`<div class="help" style="margin:-6px 0 12px">Switch IDs and version numbers come from the filename and TitleDB. They classify a likely base game, update or DLC; they do not verify the package bytes. When enabled, only TitleDB identified updates and DLC are routed to the folders below.</div>`
  +fld('switch_updates_dir','Switch updates folder',SETTINGS.switch_updates_dir||'Updates')
  +fld('switch_dlc_dir','Switch DLC folder',SETTINGS.switch_dlc_dir||'DLC')
  +chk('overwrite_existing','Overwrite an existing file',SETTINGS.overwrite_existing)
  +chk('rescan_after_import','Tell your library server to rescan after an import',SETTINGS.rescan_after_import)
  +sel('translation_policy','Fan translations in 1G1R sets',
     [['exclude','Exclude — published dumps only'],
      ['fill','Fill gaps — use a translation only when no preferred-region dump exists'],
      ['prefer','Prefer — take a translation over the region winner when one exists'],
      ['keep_both','Keep both — original plus the translation in a Translations subfolder']],
     SETTINGS.translation_policy||'exclude',
     'What Collections does with a fan translation in a language you selected '
     +'below. The Digimon-only-in-Japan case: "Fill" downloads the translation '
     +'instead of leaving the game Japanese-only; "Keep both" files it under '
     +'Translations/ so your library shows it as a variant.')
  +fld('patch_catalog_url','Patch catalogue URL (optional)',SETTINGS.patch_catalog_url||'')
  +`<div style="color:var(--dim);font-size:11.5px;margin:-6px 0 12px">
     An https address of a JSON catalogue of translation, ROM-hack and
     improvement projects, refreshed every 12 hours. Projects in a
     <code>patch-catalog.d</code> folder next to your data file are always
     read. Nothing is bundled, and completeness is only what a project states.
     See <code>docs/patch-catalogue.md</code>.</div>`
  +`<div class="field"><label for="s-translation_langs">Fan-translation languages</label>
     <input type="text" id="s-translation_langs" data-k="translation_langs" data-list="1"
       value="${esc((SETTINGS.translation_langs||['en']).join(', '))}">
     <div style="color:var(--dim);font-size:11.5px;margin-top:4px">
       Comma-separated codes, e.g. <code>de, en</code>. Matches scene markers
       like <code>[T-De]</code> / <code>[T+Eng]</code>; an unmarked
       <code>(Translation)</code> counts as English.</div></div>`
  +sel('region_mode','Region list in 1G1R sets',
     [['prefer','Prefer selected regions — keep a title even when no dump matches'],
      ['strict','Only selected regions — omit a title when no dump matches']],
     SETTINGS.region_mode||'prefer',
     '"Prefer" is the historical fallback: a game with only Japan dumps stays '
     +'in the set rather than being lost. "Strict" treats the region list as '
     +'an allowlist — the plan counts every title omitted for having no dump '
     +'in your regions.'),
  ()=>{
    const rows=$('#remote-path-mappings');
    const addPath=$('#remote-path-mapping-add');
    addPath.onclick=()=>{
      rows.insertAdjacentHTML('beforeend',pathMappingRow({}));
      rows.lastElementChild?.querySelector('[data-map-remote]')?.focus();
    };
    rows.onclick=e=>{
      const remove=e.target.closest('[data-mapping-remove]');
      if(!remove)return;
      const row=remove.closest('[data-mapping-row]');
      const siblings=[...rows.querySelectorAll('[data-mapping-row]')];
      const next=siblings[siblings.indexOf(row)+1]||siblings[siblings.indexOf(row)-1];
      row.remove();
      (next?.querySelector('[data-map-remote]')||addPath).focus();
    };
    const folders=$('#platform-folder-mappings');
    const addFolder=$('#platform-folder-mapping-add');
    addFolder.onclick=()=>{
      folders.insertAdjacentHTML('beforeend',platformFolderRow({}));
      folders.lastElementChild?.querySelector('[data-platform-folder-name]')?.focus();
    };
    folders.onclick=e=>{
      const remove=e.target.closest('[data-platform-folder-remove]');
      if(!remove)return;
      const row=remove.closest('[data-platform-folder-row]');
      const siblings=[...folders.querySelectorAll('[data-platform-folder-row]')];
      const next=siblings[siblings.indexOf(row)+1]||siblings[siblings.indexOf(row)-1];
      row.remove();
      (next?.querySelector('[data-platform-folder-name]')||addFolder).focus();
    };
  });

RENDER.profiles=()=>settingsPage('Release Profile',
  'A quality profile means nothing for a cartridge dump — there is no bitrate. '
  +'What separates two dumps of one game is region, revision and whether it is a '
  +'hack or a beta, so that is what is ranked here. Earlier regions win.',
  `<div class="field"><label>Preferred regions, best first</label>
     <input type="text" data-k="preferred_regions" data-list="1"
       value="${esc((SETTINGS.preferred_regions||[]).join(', '))}"></div>`
  +`<div class="field"><label>Video standard</label>
     <select data-k="video_standard">
       <option value=""${!SETTINGS.video_standard?' selected':''}>No preference</option>
       <option value="ntsc"${SETTINGS.video_standard==='ntsc'?' selected':''}>NTSC — North America, Japan</option>
       <option value="pal"${SETTINGS.video_standard==='pal'?' selected':''}>PAL — Europe, Australia</option></select>
     <div style="color:var(--dim);font-size:11.5px;margin-top:4px">Releases naming your standard rank higher (+30); the other standard ranks lower (−30). A release naming both, such as USA + Europe, is left alone. The Why column on search results shows the adjustment.</div></div>`
  +chk('video_standard_strict','Refuse the other standard instead of only ranking it lower',SETTINGS.video_standard_strict)
  +chk('allow_beta','Accept betas and prototypes',SETTINGS.allow_beta)
  +chk('allow_rom_hacks','Accept ROM hacks',SETTINGS.allow_rom_hacks)
  +fld('min_seeders','Minimum seeders',SETTINGS.min_seeders,'number')
  +fld('max_size_mb','Maximum size (MB)',SETTINGS.max_size_mb,'number'));

RENDER.clients=async()=>{
  const d=await j('/api/v1/downloadclient');
  // Reported separately because "not installed" is a legitimate state here,
  // not a fault: an install that only fetches plain URLs is finished. Without
  // this line a site plugin needing a click fails with nothing on screen
  // saying the browser lane was never set up.
  const br=await j('/api/v1/downloadclient/browser').catch(()=>null);
  const state=c=>!c.configured?'<span class="dot"></span>'+interfaceMarkup('ui.not-configured.9f33f06843')
    :c.ok?'<span class="dot up"></span>'+interfaceMarkup('ui.connected.22965568d2')
    :'<span class="dot down"></span>'+interfaceMarkup('ui.unreachable.abaa46adb4');
  const gaps=['torrent','usenet'].filter(p=>
    !d.items.some(c=>c.protocol===p&&c.configured));
  $('#page').innerHTML=`<div class="card">
    <div class="row" style="margin-bottom:12px">
      <h3 style="margin:0">Download Clients</h3>
      <button class="btn sp" id="c-add" style="margin-inline-start:auto">Add</button>
    </div>
    <p class="help">ROMarr sends each release to a download client based on its protocol. An indexer type cannot be downloaded until a client for that protocol is configured, so unconfigured clients are listed instead of hidden.</p>
    ${gaps.length?`<p class="help" style="color:var(--warn)">${interfaceTemplateMarkup('ui.no-client-configured-for-protocols-t.b8c34cba49',
      {protocols:gaps.join(', ')})}</p>`:''}
    ${br?`<p class="help">${interfaceMarkup(ROM_SITE_HELP)}
      ${br.available
        ?`<span style="color:var(--ok)">${interfaceTemplateMarkup('ui.browser-mode-is-available-reason-whe.e7fc844058',{reason:br.reason,where:br.where})}</span>`
        :`<span style="color:var(--warn)">${interfaceTemplateMarkup('ui.browser-mode-is-not-configured-reaso.b2e3ab05c5',{reason:br.reason})}</span>`}</p>`:''}
    ${d.items.length?`<table><thead><tr><th>Client</th><th>Protocol</th><th>Address</th>
      <th>Category</th><th>Status</th><th></th></tr></thead><tbody>
      ${d.items.map((c,i)=>`<tr><td>${esc(c.name)}
        ${c.detail?`<div class="help" style="margin:2px 0 0">${esc(c.detail)}</div>`:''}</td>
        <td><span class="pill">${esc(c.protocol)}</span></td>
        <td style="color:var(--dim)">${esc(c.url||'—')}</td>
        <td>${esc(c.category||'—')}</td>
        <td>${state(c)}</td>
        <td><div class="rowact"><button data-edit="${i}">Edit</button></div></td>
        </tr>`).join('')}</tbody></table>`
    :`<div class="empty">${interfaceMarkup('ui.romarr-cannot-send-release-grabs-wit.692f2ececf')}<br><button class="btn" id="c-add-empty" data-i18n="ui.add.9fd728c66c">Add</button></div>`}
  </div>`;
  $('#c-add').onclick=()=>addItem('downloadclient');
  const emptyAdd=$('#c-add-empty');
  if(emptyAdd)emptyAdd.onclick=()=>addItem('downloadclient');
  document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=async()=>{
    const row=d.items[Number(b.dataset.edit)];
    // The table is a status view; the editor needs the stored configuration.
    const all=await j('/api/v1/config');
    const cfg=(all.download_clients||[]).find(x=>x.id===row.id);
    if(cfg) editItem('downloadclient', cfg);
    else toastLabel('ui.that-client-has-no-stored-configurat.c6086fd1b8');
  });
};

RENDER.libraries=async()=>{
  const d=await j('/api/v1/library');
  // Answering is not the same as usable. A RomM whose credentials had
  // expired answered its heartbeat and rejected every read, so this said
  // "connected" while nothing could be read out of it.
  const stateLabel=l=>!l.ok?'Unreachable'
    :l.readable===false?'Cannot read'
    :!l.path_exists?'Path missing':'Connected';
  const state=l=>'<span class="dot '+(!l.ok||l.readable===false?'down':!l.path_exists?'warn':'up')
    +'"></span>'+interfaceMarkup(stateLabel(l));
  const rules=l=>(l.platforms&&l.platforms.length)
    ? l.platforms.map(p=>`<span class="pill">${esc(p)}</span>`).join(' ')
    : (l.is_default?'<span style="color:var(--dim)">any platform</span>'
                   :'<span style="color:var(--warn)">nothing routes here</span>');
  const noDefault=d.items.length>1&&!d.items.some(l=>l.is_default);
  const unmounted=d.items.filter(l=>l.ok&&!l.path_exists);
  $('#page').innerHTML=`<div class="card">
    <div class="row" style="margin-bottom:12px">
      <h3 style="margin:0">Libraries</h3>
      <button class="btn sp" id="l-add" style="margin-inline-start:auto">Add</button>
    </div>
    <p class="help">${interfaceMarkup('ui.where-finished-roms-are-filed-add-mo.86401d5786')}</p>
    ${noDefault?`<p class="help" style="color:var(--warn)">${interfaceMarkup('ui.no-library-is-marked-default-so-anyt.60146a85ac')}</p>`:''}
    ${unmounted.map(l=>`<p class="help" style="color:var(--warn)">
      ${interfaceTemplateMarkup('ui.name-answers-but-nothing-can-be-impo.2992263c10',
        {name:l.name||''})} ${esc(l.path_hint||'')}</p>
      ${l.readable===false?`<p class="panel-note panel-warn">${esc(l.detail||'')}</p>`:''}`).join('')}
    ${d.items.length?`<table><thead><tr><th>Library</th><th>Type</th>
      <th>Address</th><th>Path</th><th>Platforms</th><th>Status</th><th></th></tr>
      </thead><tbody>
      ${d.items.map((l,i)=>`<tr><td>${esc(l.name)}
        ${l.is_default?'<span class="pill">default</span>':''}</td>
        <td><span class="pill">${esc(l.type)}</span></td>
        <td style="color:var(--dim)">${esc(l.url||'—')}</td>
        <td style="color:var(--dim)">${esc(l.path||'—')}</td>
        <td>${rules(l)}</td>
        <td>${state(l)}</td>
        <td><div class="rowact"><button data-ledit="${i}">Edit</button></div></td>
        </tr>`).join('')}</tbody></table>`
    :'<div class="empty">No library yet. Add one, or nothing can be imported.</div>'}
  </div>`;
  $('#l-add').onclick=()=>addItem('library');
  document.querySelectorAll('[data-ledit]').forEach(b=>b.onclick=async()=>{
    const row=d.items[Number(b.dataset.ledit)];
    // The table is a status view; the editor needs the stored configuration.
    const all=await j('/api/v1/library/config');
    const cfg=(all.items||[]).find(x=>x.id===row.id);
    if(cfg) editItem('library', cfg);
    else toastLabel('ui.that-library-has-no-stored-configura.ef130fd54c');
  });
};

RENDER.indexers=async()=>{
  const [d,types]=await Promise.all([
    j('/api/v1/indexer'), loadSchema('indexer')
  ]);
  const hasEnabledSource=(d.items||[]).some(i=>i.enable)
    ||(d.proxied||[]).some(i=>i.enable);
  $('#page').innerHTML=`<div class="card">
    <div class="row" style="margin-bottom:12px">
      <h3 style="margin:0">Indexers</h3>
      <button class="btn" id="i-add" style="margin-inline-start:auto">Add</button>
    </div>
    <p class="help">Add a Newznab or Torznab indexer, search public Internet
      Archive software records through Direct HTTP, or connect Prowlarr.
      Internet Archive grabs need the Direct HTTP client configured.</p>
    ${d.items.length&&!hasEnabledSource?`<p class="panel-note panel-warn">${interfaceMarkup('ui.release-search-is-unavailable-until.6240f4b5a8')}</p>`:''}
    ${d.items.length?`<table><thead><tr><th>Name</th><th>Type</th><th>URL</th>
      <th>Enabled</th><th></th></tr></thead><tbody>
      ${d.items.map((it,i)=>`<tr><td>${esc(it.name||'—')}</td>
        <td><span class="pill">${esc((types[it.type]||{}).label||it.type)}</span></td>
        <td style="color:var(--dim)">${esc(it.url||'—')}</td>
        <td><span class="dot ${it.enable?'up':'down'}"></span>${it.enable?'yes':'no'}</td>
        <td><div class="rowact"><button data-iedit="${i}">Edit</button></div></td>
        </tr>`).join('')}</tbody></table>`
    :`<div class="empty">${interfaceMarkup(hasEnabledSource
      ?'No direct indexers are configured. Enabled Prowlarr indexers are listed below.'
      :'Release search is unavailable until an enabled indexer is configured. ROM browsing and local-library features still work.')}<br><button class="btn" id="i-add-empty" data-i18n="ui.add.9fd728c66c">Add</button></div>`}
  </div>
  ${(d.proxied||[]).length?`<div class="card"><h3>Via Prowlarr</h3>
    <p class="help">Managed in Prowlarr, shown here read-only. Add or remove
      them there and they appear or disappear from this list.</p>
    <div class="row" style="justify-content:flex-end;margin-bottom:10px">
      <button class="btn ghost" id="i-diagnose">Test indexers</button></div>
    <table><thead><tr><th>Indexer</th><th>Protocol</th><th>Categories</th>
      <th>Enabled</th></tr></thead><tbody>
      ${d.proxied.map(i=>`<tr><td>${esc(i.name)}</td><td>${esc(i.protocol)}</td>
        <td style="color:var(--dim)">${esc((i.categories||[]).join(', ')||'—')}</td>
        <td><span class="dot ${i.enable?'up':'down'}"></span>${i.enable?'yes':'no'}</td>
        </tr>`).join('')}</tbody></table></div><div id="i-diagnostics"></div>`
    :(d.error?`<div class="card"><h3>Via Prowlarr</h3>
        <p class="help" style="color:var(--warn)">${appMessageMarkup(d.error)}</p>
        <div class="row" style="justify-content:flex-end">
          <button class="btn ghost" id="i-diagnose">Test indexers</button></div>
        </div><div id="i-diagnostics"></div>`:'')}`;
  $('#i-add').onclick=()=>addItem('indexer');
  const emptyAdd=$('#i-add-empty');
  if(emptyAdd)emptyAdd.onclick=()=>addItem('indexer');
  const test=$('#i-diagnose');
  if(test)test.onclick=async()=>{
    test.disabled=true;test.textContent='Testing…';
    try{
      const report=await j('/api/v1/indexer/diagnose',{method:'POST',
        headers:{'Content-Type':'application/json'},body:'{}'});
      const management=report.management||{};
      const rows=Array.isArray(report.indexers)?report.indexers:[];
      $('#i-diagnostics').innerHTML=`<div class="card"><h3>Prowlarr diagnostics</h3>
        <p class="help">Management API and indexer feeds are checked separately.</p>
        <p><span class="dot ${management.success?'up':'down'}"></span>
          <b>Management API</b> — ${interfaceMarkup(management.success?'Connected':'Failed')}
          ${management.status?' · HTTP '+esc(management.status):''}
          ${management.version?' · '+esc(management.version):''}</p>
    ${management.error?`<p class="help" style="color:var(--warn)">${appMessageMarkup(management.error)}</p>`:''}
        ${rows.length?`<table><thead><tr><th>Indexer</th><th>Feed</th><th>Details</th>
          </tr></thead><tbody>${rows.map(item=>`<tr>
            <td>${esc(item.name||'Indexer')}</td>
            <td><span class="dot ${item.success?'up':'down'}"></span>
              ${interfaceMarkup(item.success?'Connected':'Failed')}${item.status?' · HTTP '+esc(item.status):''}</td>
            <td style="color:var(--dim)">${appMessageMarkup(item.error||item.recentFailure||'—')}
              ${item.disabledUntil?`<br>${interfaceTemplateMarkup('ui.disabled-until-date.9bb80884d5',{date:regionalDateTime(item.disabledUntil)})}`:''}</td>
            </tr>`).join('')}</tbody></table>`
          :'<p class="help">No enabled torrent or usenet indexers were found.</p>'}
        </div>`;
    }catch(e){
      $('#i-diagnostics').innerHTML=`<div class="card"><p class="help" style="color:var(--warn)">${appMessageMarkup(e.message||'Diagnostics failed')}</p></div>`;
    }finally{test.disabled=false;test.textContent='Test indexers';}
  };
  document.querySelectorAll('[data-iedit]').forEach(b=>b.onclick=()=>
    editItem('indexer', d.items[Number(b.dataset.iedit)]));
};

RENDER.general=()=>settingsPage('General',
  'Optional connections to the rest of the stack. Credentials live in the environment '
  +'file, not here — this page never shows or stores a secret. Indexers and download '
  +'clients have their own Settings pages; notifications and metadata connections '
  +'can be added only when you choose to use them.',
  `<div class="field"><label>Prowlarr</label>
     <input type="text" value="${esc(SETTINGS._prowlarr_url||'')}" disabled></div>
   <div class="field"><label>qBittorrent</label>
     <input type="text" value="${esc(SETTINGS._qbit_url||'')}" disabled></div>
   <div class="field"><label>RomM</label>
     <input type="text" value="${esc(SETTINGS._romm_url||'')}" disabled></div>
   <div class="field"><label>RomM address for links</label>
     <input type="text" data-k="romm_public_url"
       value="${esc(SETTINGS.romm_public_url||'')}"
       placeholder="http://timnode:8337">
     <div style="color:var(--dim);font-size:11.5px;margin-top:4px">Where your browser reaches RomM. Used by “Open in RomM” on the game page.</div></div>
   ${regionalFormatField()}
   <div class="field"><label>Your public URL (for Friends)</label>
     <input type="text" data-k="public_url"
       value="${esc(SETTINGS.public_url||'')}"
       placeholder="https://romarr.example.com">
     <div data-i18n="ui.this-is-how-a-friends-server-reaches.f78fde54a6" style="color:var(--dim);font-size:11.5px;margin-top:4px">This is how a friend’s server reaches yours. Invitations include this address. Without it, the person redeeming an invitation has nowhere to connect. Peering is the only feature that needs ROMarr to know its own address.</div></div>`
  +chk('auto_import','Import completed downloads automatically',SETTINGS.auto_import)
  +`<div class="field"><label>Protocol</label>
     <select data-k="protocol">
       <option value="torrent" data-i18n="ui.torrent.3814901724"${SETTINGS.protocol==='torrent'?' selected':''}>Torrent</option>
       <option value="usenet" data-i18n="ui.usenet.e0a4531fbf"${SETTINGS.protocol==='usenet'?' selected':''}>Usenet</option>
     </select></div>
   <h3 style="margin-top:18px">The clock</h3>
   <p class="help">How often the scheduled jobs run. Zero turns a job off;
     changes apply at the next tick, no restart.</p>`
  +fld('auto_import_interval_minutes','Import check (minutes)',
       SETTINGS.auto_import_interval_minutes,'number')
  +fld('search_missing_interval_hours','Wanted search (hours)',
       SETTINGS.search_missing_interval_hours,'number')
  +fld('rss_sync_interval_minutes','RSS sync (minutes)',
       SETTINGS.rss_sync_interval_minutes,'number')
  +fld('list_sync_interval_hours','List sync (hours)',
       SETTINGS.list_sync_interval_hours,'number')
  +chk('update_check','Check github.com daily for a newer ROMarr (never auto-updates)',
       SETTINGS.update_check)
  +`<h3 style="margin-top:18px">Security</h3>
    <div class="row" style="gap:8px;align-items:center;margin:8px 0">
      <button class="btn ghost" id="g-key" type="button">Reveal API key</button>
      <code id="g-keyout" style="font-size:12px;color:var(--dim)"></code></div>
    <h3>SeerrNG provider key</h3>
    <p class="help">Give this key to SeerrNG. It can use the SeerrNG
      integration routes, while your main API key keeps full administrator
      access.</p>
    <div class="row" style="gap:8px;align-items:center;margin:8px 0">
      <button class="btn ghost" id="g-seerrng-key" type="button">Reveal provider key</button>
      <button class="btn ghost" id="g-seerrng-rotate" type="button">Rotate provider key</button>
      <code id="g-seerrng-keyout" style="font-size:12px;color:var(--dim)"></code>
    </div>
    <div class="row" style="gap:8px;align-items:center;margin:8px 0">
      <button class="btn ghost" id="g-totp" type="button">Enable two-factor (TOTP)</button>
      <button class="btn ghost" id="g-totpoff" type="button">Disable</button>
      <span class="help" style="margin:0">Two-factor authentication protects sign-in only. The API key is already a high-entropy secret, so it does not require two-factor authentication.</span></div>
    <pre id="g-totpout" style="display:none;font:12px/1.6 ui-monospace,Menlo,monospace;color:var(--dim);white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px"></pre>`,
  ()=>{
    const regionalFormat=$('#g-regional-format');
    if(regionalFormat) regionalFormat.onchange=()=>{
      applyRegionalFormat(regionalFormat.value,regionalFormat);
    };
    $('#g-key').onclick=async()=>{
      const d=await j('/api/v1/system/apikey').catch(()=>({}));
      $('#g-keyout').innerHTML=d.api_key
        ?'<span lang="und" dir="auto">'+esc(d.api_key)+'</span>'
        :interfaceMarkup('ui.could-not-read-it.baf6cf1a0d');
    };
    $('#g-seerrng-key').onclick=async()=>{
      const d=await j('/api/v1/system/seerrng-key').catch(()=>({}));
      $('#g-seerrng-keyout').innerHTML=d.api_key
        ?'<span lang="und" dir="auto">'+esc(d.api_key)+'</span>'
        :interfaceMarkup('ui.could-not-read-it.baf6cf1a0d');
      if(d.managed_by_env) toastLabel('ui.this-key-is-managed-by-romarr-seerrn.ec5f333983');
    };
    $('#g-seerrng-rotate').onclick=async()=>{
      if(!confirmMessage('ui.rotate-the-seerrng-provider-key-seer.e8ff0c0718')) return;
      const d=await j('/api/v1/system/seerrng-key/rotate',{method:'POST',
        headers:{'content-type':'application/json'},body:'{}'}).catch(()=>({}));
      if(d.api_key){
        $('#g-seerrng-keyout').textContent=d.api_key;
        toastLabel('ui.provider-key-rotated.f34467b1b5');
      }else if(d.error)toastAppMessage(d.error);else toastLabel('ui.could-not-rotate-provider-key.02c09c9a71');
    };
    $('#g-totp').onclick=async()=>{
      if(!confirmMessage('ui.enable-two-factor-sign-in-you-will-n.5fa605c62e')) return;
      const d=await j('/api/v1/totp/enroll',{method:'POST',
        headers:{'content-type':'application/json'},body:'{}'}).catch(()=>({}));
      const out=$('#g-totpout'); out.style.display='block';
      out.textContent='Secret:  '+(d.secret||'?')
        +'\nURI:     '+(d.uri||'?')
        +'\n\nBackup codes (single use, save them now):\n  '
        +((d.backup_codes||[]).join('\n  '))
        +'\n\n'+(d.note||'');
    };
    $('#g-totpoff').onclick=async()=>{
      const d=await j('/api/v1/totp/disable',{method:'POST',
        headers:{'content-type':'application/json'},body:'{}'}).catch(()=>({}));
      toastLabel(d.ok?'Two-factor disabled':'Failed');
      $('#g-totpout').style.display='none';
    };
  });

/* ---------------- system ---------------- */
RENDER.status=async()=>{
  const h=await j('/api/v1/system/status');
  const row=(l,ok,extra='')=>`<tr><td>${l}</td>
    <td><span class="dot ${ok?'up':'down'}"></span>${ok?'OK':'Not available'}</td>
    <td style="color:var(--dim)">${esc(extra)}</td></tr>`;
  const g=h.ggrequestz||{};
  $('#page').innerHTML=`<div class="card"><h3>Health</h3><table><tbody>
      ${row('Prowlarr',h.prowlarr,h.prowlarr_url)}
      ${(h.clients||[]).map(c=>row(
        `${c.name} <span class="pill">${esc(c.protocol)}</span>`,
        c.ok, c.configured?c.url:'not configured')).join('')}
      ${(h.libraries||[]).length
        ? (h.libraries||[]).map(l=>row(
            `${esc(l.name)} <span class="pill">${esc(l.type)}</span>${
              l.is_default?' <span class="pill">default</span>':''}`,
            l.ok && l.path_exists,
            !l.ok ? (l.url||'unreachable')
                  : (l.path_exists ? l.path : (l.path_hint||l.path)))).join('')
        : row('RomM',h.romm,h.romm_url)
          +row('ROM library',h.library,h.library?h.library_path:(h.library_path_hint||h.library_path))}
      ${g.configured?row('GG Requestz page',g.ok,
          g.url+' (reachability only; request delivery is configured below)')
        :`<tr><td>GG Requestz page</td><td><span class="dot"></span>not configured</td>
          <td style="color:var(--dim)">GGREQUESTZ_URL only adds and checks the
          front-end link; it does not deliver requests</td></tr>`}
      ${h.stream_url
        ? row('Stream server',(h.play_routes||{}).stream>0,h.stream_url)
        : `<tr><td>Stream server</td><td><span class="dot"></span>not configured</td>
           <td style="color:var(--dim)">set STREAM_SERVER_URL to play PS2, GameCube,
           Wii, Dreamcast and 3DS here</td></tr>`}
      ${(h.moonlight||{}).configured
        ? row(esc((h.moonlight||{}).kind_label||'Moonlight host'),
              (h.moonlight||{}).ok,
              (h.moonlight||{}).ok?(h.moonlight||{}).label
                                  :((h.moonlight||{}).problem||''))
        : `<tr><td>Moonlight host</td><td><span class="dot"></span>not configured</td>
           <td style="color:var(--dim)">set MOONLIGHT_HOST to a Wolf, Sunshine or
           Steam Headless machine</td></tr>`}
    </tbody></table></div>
    ${ggrequestzCard(g)}
    ${playCard(h.play_routes||{})}
    ${moonlightCard(h.moonlight||{})}
    <div class="card"><h3>About</h3><div class="st">
      <div><b>${esc(h.version)}</b><span>Version</span></div>
      <div><b>${fmt(h.platforms)}</b><span>Platforms</span></div>
      <div><b>${fmt(h.dats||0)}</b><span>DATs loaded</span></div>
      <div><b>${fmt(h.dat_games||0)}</b><span>Known dumps</span></div>
      <div><b>${fmt(h.events)}</b><span>History events</span></div>
      <div><b>${esc(h.uptime)}</b><span>Uptime</span></div>
      <div><b><a href="https://ko-fi.com/snapetech" target="_blank" rel="noopener noreferrer">Support ROMarrNG</a></b><span>Ko-fi</span></div>
    </div></div>

    <div class="card"><h3>Backup and export</h3>
    <p class="help">A snapshot restores an install: settings, libraries,
    indexers, clients, history and the wanted list. Credentials are stripped
    unless you ask for them. Use the encrypted export to carry credentials
    between installs without storing them as plain text.</p>
    <div class="row" style="flex-wrap:wrap;gap:8px">
      <button class="btn" id="bk-dl">Download backup</button>
      <button class="btn ghost" id="bk-dle">Download encrypted backup with credentials</button>
      <button class="btn ghost" id="bk-dls">Download with credentials (plain JSON)</button>
      <button class="btn ghost" id="bk-rs">Restore from file…</button>
      <input type="file" id="bk-file" accept="application/json" style="display:none">
    </div>
    <div id="bk-msg" class="testline"></div>
    <p class="help" style="margin-top:16px">Export the library itself, for a
    spreadsheet or another tool:</p>
    <div class="row" style="flex-wrap:wrap;gap:8px">
      <select id="ex-what">
        <option value="library" data-i18n="ui.library.dc20b3d5d2">Library</option>
        <option value="wanted" data-i18n="ui.wanted.c296832656">Wanted</option>
        <option value="blocklist" data-i18n="ui.blocklist.f8019af406">Blocklist</option>
      </select>
      <select id="ex-fmt"><option value="json">JSON</option>
        <option value="csv">CSV</option></select>
      <button class="btn ghost" id="ex-go">Export</button>
    </div>
    <p class="help" style="margin-top:16px">Or as a frontend's own format:</p>
    <div class="row" style="flex-wrap:wrap;gap:8px" id="fe-row"></div>
    </div>`;

  wireGGRequestz();
  wireMoonlight(h.moonlight||{});

  const msg=(ok,markup)=>{const m=$('#bk-msg');
    m.className='testline '+(ok?'ok':'bad'); m.innerHTML=markup;};
  const save=(url,name)=>{const a=document.createElement('a');
    a.href=url; a.download=name; document.body.append(a); a.click(); a.remove();};

  $('#bk-dl').onclick=()=>save('/api/v1/backup','romarr-backup.json');
  $('#bk-dle').onclick=async()=>{
    const pass=promptMessage('ui.choose-a-passphrase-with-at-least-16.0fb257a193');
    if(pass===null) return;
    const confirmPass=promptMessage('ui.re-enter-the-backup-passphrase.f0593fb279');
    if(confirmPass===null) return;
    if(pass!==confirmPass){ msg(false,interfaceMarkup('ui.the-passphrases-do-not-match.4d3fc2c44f')); return; }
    if([...pass].filter(c=>!(/\\s/.test(c))).length<16){ msg(false,interfaceMarkup('ui.use-at-least-16-non-whitespace-chara.bc53cad408')); return; }
    msg(true,interfaceMarkup('ui.encrypting-backup.8fc8833aba'));
    try{
      const encrypted=await j('/api/v1/backup/encrypted',{headers:{'X-ROMarr-Backup-Passphrase':pass}});
      if(encrypted.error) throw new Error(encrypted.error);
      const blob=new Blob([JSON.stringify(encrypted,null,2)],{type:'application/json'});
      const url=URL.createObjectURL(blob); save(url,'romarr-backup-encrypted.json');
      setTimeout(()=>URL.revokeObjectURL(url),1000); msg(true,interfaceMarkup('ui.encrypted-backup-downloaded.d15118586e'));
    }catch(err){ msg(false,appMessageMarkup(err.message||'Could not encrypt backup.')); }
  };
  $('#bk-dls').onclick=()=>{
    if(confirmMessage('ui.this-file-will-contain-your-api-key.bfeea73fc6'))
      save('/api/v1/backup?secrets=1','romarr-backup-with-credentials.json');
  };
  $('#bk-rs').onclick=()=>$('#bk-file').click();
  $('#bk-file').onchange=async e=>{
    const file=e.target.files[0]; if(!file) return;
    if(!confirmMessage('ui.restore-from-filename-this-replaces.c49fa7352c',{filename:file.name})) { e.target.value=''; return; }
    msg(true,interfaceMarkup('ui.restoring.5a4918e020'));
    try{
      const backup=JSON.parse(await file.text());
      const headers={'Content-Type':'application/json'};
      if(backup.kind==='romarr-encrypted-backup'){
        const pass=promptMessage('ui.enter-the-passphrase-used-to-encrypt.5eb0ff3860');
        if(pass===null){ e.target.value=''; return; }
        headers['X-ROMarr-Backup-Passphrase']=pass;
      }
      const r=await j('/api/v1/restore',{method:'POST',headers,body:JSON.stringify(backup)});
      msg(!r.error,r.error?appMessageMarkup(r.error)
        :(r.warning?appMessageMarkup(r.warning):interfaceMarkup('ui.restored.54fb6e453c'))
          +' '+interfaceMarkup('ui.reloading.ea456dcf3d'));
      if(!r.error) setTimeout(()=>location.reload(),1200);
    }catch(_){ msg(false,interfaceMarkup('ui.that-file-is-not-a-romarr-backup.4e556a59e7')); }
    e.target.value='';
  };
  $('#ex-go').onclick=()=>save('/api/v1/export?what='+$('#ex-what').value
    +'&format='+$('#ex-fmt').value,
    'romarr-'+$('#ex-what').value+'.'+$('#ex-fmt').value);

  const fe=await j('/api/v1/frontend/formats').catch(()=>({formats:[]}));
  const feRow=$('#fe-row'); if(!feRow) return;   // navigated away mid-fetch
  feRow.innerHTML=(fe.formats||[]).map(f=>
    '<button class="btn ghost fe-btn" data-f="'+esc(f.name||f)+'" data-filename="'+esc(f.filename||('romarr-'+(f.name||f)+'.export'))+'">'
    +esc(f.label||f.name||f)+'</button>').join('')
    ||'<span class="help" style="margin:0">No frontend formats available.</span>';
  feRow.querySelectorAll('.fe-btn').forEach(b=>b.onclick=()=>
    save('/api/v1/frontend/export?format='+encodeURIComponent(b.dataset.f),
         b.dataset.filename||'romarr-export.export'));
};

// GG Requestz pushes to ROMarr; the reachability probe above is deliberately
// labelled as the opposite direction. The API key is revealed only after a
// deliberate click, just like Settings -> General, because the finished URL
// is itself a credential and should not sit in the page by default.
const ggrequestzCard=g=>`<div class="card"><h3>GG Requestz requests</h3>
  <p class="help">${interfaceMarkup('ui.configure-the-webhook-in-gg-requestz.5bd9cf4d98')}</p>
  <label>ROMarr URL as the GG Requestz container reaches it</label>
  <input id="ggr-base" placeholder="http://romarr:6868">
  <p class="help">${interfaceTemplateMarkup(GG_ADDRESS_HELP,{url:'http://romarr:6868'})}</p>
  <div class="row" style="flex-wrap:wrap;gap:8px;align-items:center">
    <button class="btn" id="ggr-build" type="button">Reveal setup value</button>
    <button class="btn ghost" id="ggr-copy" type="button" disabled>Copy</button>
  </div>
  <pre id="ggr-value" style="display:none;font:12px/1.6 ui-monospace,Menlo,monospace;
    color:var(--dim);white-space:pre-wrap;overflow-wrap:anywhere;background:var(--bg);
    border:1px solid var(--line);border-radius:6px;padding:10px"></pre>
  <p class="help">${interfaceTemplateMarkup(GGR_WEBHOOK_HELP,{})}</p>
  <p class="help" data-i18n="ui.treat-the-finished-url-like-a-passwo.e875376f5b">Treat the finished URL like a password: it contains ROMarr’s API key. Keep it on a trusted Docker network or HTTPS and do not paste it in public logs.</p></div>`;

const wireGGRequestz=()=>{
  const base=$('#ggr-base'), build=$('#ggr-build'), copy=$('#ggr-copy');
  const value=$('#ggr-value'); if(!base||!build||!copy||!value) return;
  // Do not assume the browser-facing origin works from another container.
  // `localhost` here would mean the GG Requestz container itself there.
  base.value='';
  base.oninput=()=>{
    value.textContent=''; value.style.display='none'; copy.disabled=true;
  };
  build.onclick=async()=>{
    build.disabled=true;
    try{
      if(!base.value.trim()) throw new Error(
        'Enter the ROMarr URL reachable from inside GG Requestz');
      const d=await j('/api/v1/system/apikey');
      if(!d.api_key) throw new Error('ROMarr did not return an API key');
      const target=new URL('/api/v1/webhook/ggrequestz',base.value.trim());
      target.searchParams.set('apikey',d.api_key);
      value.textContent='REQUEST_WEBHOOK_URL='+target.href;
      value.style.display='block'; copy.disabled=false;
    }catch(e){
      value.innerHTML=interfaceTemplateMarkup('ui.could-not-build-the-url-error.d5a21525de',
        {error:String(e.message||e)});
      value.style.display='block'; copy.disabled=true;
    }finally{build.disabled=false;}
  };
  copy.onclick=async()=>{
    try{await navigator.clipboard.writeText(value.textContent); toastLabel('ui.copied.8d525e5f15');}
    catch(_){toastLabel('ui.copy-failed-select-the-value-manuall.cf743f3384');}
  };
};

// The Moonlight host: what it is, what it proves, and the one step that is
// still a human's.
//
// The card is written to be readable when the answer is "nothing", because
// that is the common case and the interesting one. A host that answers
// /serverinfo but whose app list ROMarr cannot read is working perfectly and
// grants no platform anything -- if this card rendered a green dot and
// stopped, an operator would reasonably conclude their PS2 games were now
// playable, and they would not be.
//
// The pairing section never says "Pair" on its own. Moonlight's PIN is
// generated by the client on the user's device; ROMarr can only be the box it
// is typed into, and the copy says so before the input rather than after a
// failure.
const moonlightCard=m=>{
  if(!m.configured) return `<div class="card"><h3>Game streaming host</h3>
    <p class="help">${esc(m.hint||'')}. A Moonlight host renders a real
    desktop emulator on the host's GPU and sends video &mdash; which is how
    machines with no browser core get played. ROMarr reports what it can
    verify about one and never guesses the rest.</p>
    <p class="help">${esc(m.manual||'')}</p></div>`;

  if(!m.ok) return `<div class="card"><h3>${esc(m.kind_label||'Moonlight')}</h3>
    <p class="testline bad">${interfaceTemplateMarkup('ui.no-answer-from-host-port.d291802598',
      {host:m.host||'',port:String(m.port||'')})}
    &mdash; ${m.problem?appMessageMarkup(m.problem):interfaceMarkup('ui.unreachable.abaa46adb4')}</p>
    <p class="help">${interfaceTemplateMarkup('ui.romarr-checks-path-on-the-moonlight.e63082c6ce',{path:'/serverinfo'})}</p></div>`;

  const slugs=Object.keys(m.platforms||{});
  const pend=(m.pairing||{}).pending||[];
  const canList=(m.pairing||{}).can_list_pending;

  return `<div class="card"><h3>${esc(m.kind_label||'Moonlight')}</h3>
    <div class="st">
      <div><b>${esc(m.hostname||m.host||'?')}</b><span>Host</span></div>
      <div><b>${esc(m.appversion||'?')}</b><span>Version</span></div>
      <div><b>${m.busy?'In a game':'Idle'}</b><span>State</span></div>
      <div><b>${fmt((m.paired||[]).length)}</b><span>Paired clients</span></div>
    </div>

    <h4 style="margin:18px 0 6px">What this host adds</h4>
    ${m.apps_read
      ? (slugs.length
          ? `<p class="help">${interfaceTemplateMarkup(
              slugs.length===1
                ? '{count} platform gains a stream route here, each because a named single-machine emulator is on this host’s app list:'
                : '{count} platforms gain a stream route here, each because a named single-machine emulator is on this host’s app list:',
              {count:fmt(slugs.length)})}</p>
             <table><tbody>${slugs.map(s=>`<tr><td>${esc(s)}</td>
               <td style="color:var(--dim)">${esc(m.platforms[s])}</td></tr>`).join('')}
             </tbody></table>`
          : `<p class="help">${interfaceTemplateMarkup(
              (m.apps||[]).length===1
                ? 'Its app list was read ({count} app) and no platform gains a route from it. ROMarr only counts an app whose name is an emulator for exactly one machine — PCSX2, Dolphin, flycast. A RetroArch or a Steam proves nothing, because nothing in the API says which cores or games are inside it.'
                : 'Its app list was read ({count} apps) and no platform gains a route from it. ROMarr only counts an app whose name is an emulator for exactly one machine — PCSX2, Dolphin, flycast. A RetroArch or a Steam proves nothing, because nothing in the API says which cores or games are inside it.',
              {count:fmt((m.apps||[]).length)})}</p>`)
      : `<p class="help"><b>Reachable, but its app list could not be read</b>,
         so ROMarr cannot say which platforms it plays and does not guess.
         ${esc(m.apps_problem||'')}</p>`}
    ${(m.apps||[]).length?`<p class="help">Apps: ${
      (m.apps||[]).map(a=>'<span class="pill">'+esc(a)+'</span>').join(' ')}</p>`:''}

    <h4 style="margin:18px 0 6px">Pairing</h4>
    <p class="help">${esc((m.pairing||{}).manual||'')}</p>
    ${canList
      ? (pend.length
          ? `<p class="help">${interfaceTemplateMarkup(
              pend.length===1?'{count} client waiting:':'{count} clients waiting:',
              {count:fmt(pend.length)})}</p>`
          : `<p class="help">${interfaceTemplateMarkup('ui.no-moonlight-client-is-waiting-to-pa.baaa9b58a1',{host:m.host||''})}</p>`)
      : `<p class="help">${esc((m.pairing||{}).detail||'')}</p>`}
    <div class="row" style="flex-wrap:wrap;gap:8px;align-items:center">
      ${canList&&pend.length
        ? `<select id="ml-secret">${pend.map(p=>
            `<option value="${esc(p.pair_secret)}">${esc(p.client_ip||p.pair_secret)}</option>`
          ).join('')}</select>`
        : ''}
      <input id="ml-pin" placeholder="PIN from your Moonlight client"
             maxlength="8" style="max-width:230px" ${canList&&!pend.length?'disabled':''}>
      <button class="btn" id="ml-send" ${canList&&!pend.length?'disabled':''}>Send PIN to host</button>
    </div>
    <div id="ml-msg" class="testline"></div>

    <h4 style="margin:18px 0 6px">Connecting</h4>
    <p class="help">${interfaceMarkup('ui.romarr-cannot-launch-moonlight-sessi.58b4495498')}</p>
    <p class="help">${interfaceTemplateMarkup('ui.add-host-in-moonlight-or-run-command.a3ea2277be',{host:m.host||'',command:m.connect_hint||''})}</p>
    ${m.desktop_url?`<p class="help">${interfaceMarkup('ui.this-host-also-serves-a-browser-desk.1ee6961387')}
      <a href="${esc(m.desktop_url)}" target="_blank" rel="noreferrer noopener"
      >${esc(m.desktop_url)}</a></p>`:''}
    </div>`;
};

// Wired after every status render, and defensive about the card being absent:
// it is not drawn at all when no host is configured, and this runs regardless.
const wireMoonlight=m=>{
  const send=$('#ml-send'); if(!send) return;
  send.onclick=async()=>{
    const out=$('#ml-msg');
    const pin=($('#ml-pin')||{}).value||'';
    const sec=($('#ml-secret')||{}).value||'';
    out.className='testline'; out.innerHTML=interfaceMarkup('ui.sending.b8ed5279e8');
    const r=await j('/api/v1/moonlight/pin',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({pin:pin,pair_secret:sec})}).catch(()=>({ok:false,
        detail:'ROMarr could not reach the host'}));
    // Never "Paired". Neither Wolf nor Sunshine reports whether the PIN was
    // right on this call -- Sunshine returns true for a wrong PIN whenever a
    // request is outstanding (LizardByte/Sunshine#3944) -- so the strongest
    // honest word is "accepted", and the check is the paired-client count.
    out.className='testline '+(r.ok?'ok':'bad');
    out.innerHTML=appMessageMarkup(r.detail||(r.ok?'Accepted.':'Refused.'));
    if(r.ok) setTimeout(()=>RENDER.status(),1500);
  };
};

// How the supported platforms can actually be played, on THIS install.
//
// It belongs on the status page rather than in the docs because the answer
// depends on the operator's own setup: configuring a stream server moves five
// platforms out of "download only", and nothing else in the UI would show
// that it had worked.
const playCard=r=>`<div class="card"><h3>How platforms play here</h3>
  <div class="st">
    <div><b>${fmt(r.local||0)}</b><span>In the browser (EmulatorJS)</span></div>
    <div><b>${fmt(r.stream||0)}</b><span>Streamed server-side</span></div>
    <div><b>${fmt(r.archive||0)}</b><span>On Archive.org</span></div>
    <div><b>${fmt(r.download_only||0)}</b><span>Download only</span></div>
  </div>
  <p class="help">Every platform can be downloaded. ${
    (r.download_only||0)>0
      ? `${fmt(r.download_only)} have no player on this install &mdash; a stream
         server is what plays PS2, GameCube, Wii, Dreamcast and 3DS.`
      : 'Every supported platform also plays here without downloading.'}
    See <a href="#platforms">Platforms</a> for the per-platform answer.</p></div>`;

RENDER.platforms=async()=>{
  const [rows,igdb,dat]=await Promise.all([
    j('/api/platforms').catch(()=>[]),
    j('/api/v1/catalog/platforms').catch(()=>[]),
    j('/api/v1/catalog/dat/platforms').catch(()=>({results:[]}))
  ]);
  CATALOG_VIEW.igdbPlatforms=Array.isArray(igdb)?igdb:[];
  CATALOG_VIEW.datPlatforms=(dat&&dat.results)||[];
  const eras=[
    {id:'early',label:'1970s–early 80s',slugs:['atari2600','atari5200','atari7800','colecovision','intellivision','vectrex','odyssey-2-slash-videopac-g7000','sg1000']},
    {id:'8bit',label:'8 & 16-bit · 1980s–90s',slugs:['nes','famicom','fds','snes','sfam','genesis-slash-megadrive','sms','gamegear','gb','gbc','gba','lynx','turbografx16--1','sega32','neo-geo-pocket','neo-geo-pocket-color','virtualboy','wonderswan','wonderswan-color','atari-jaguar','supergrafx']},
    {id:'disc',label:'3D & discs · 1990s–2000s',slugs:['n64','psx','saturn','segacd','dc','3do','ps2','ngc','psp','nds','xbox','philips-cd-i','pc-fx','turbografx-16-slash-pc-engine-cd','amiga-cd32','neo-geo-cd','atari-jaguar-cd']},
    {id:'hd',label:'HD era · 2000s–2010s',slugs:['ps3','xbox360','wii','wiiu','3ds','psvita']},
    {id:'modern',label:'Modern · 2010s+',slugs:['ps4','ps5','xboxone','series-x-s','switch']},
    {id:'computer',label:'Computers',media:'computer'},
    {id:'arcade',label:'Arcade',slugs:['arcade','neogeoaes','neogeomvs']},
    {id:'other',label:'Other systems',slugs:[]}
  ];
  const groupFor=p=>{
    if(p.media==='computer')return 'computer';
    const found=eras.find(g=>g.slugs.includes(p.slug));
    return found?found.id:(p.slug==='arcade'?'arcade':'other');
  };
  const countFor=id=>rows.filter(p=>groupFor(p)===id).length;
  const search=String(PLATFORM_VIEW.query||'').toLowerCase();
  const filtered=rows.filter(p=>(PLATFORM_VIEW.group==='all'||groupFor(p)===PLATFORM_VIEW.group)
    &&(!search||(p.name+' '+p.slug+' '+p.media).toLowerCase().includes(search)));
  const eraButtons=[{id:'all',label:'All platforms'}].concat(eras)
    .filter(g=>g.id==='all'||countFor(g.id)>0)
    .map(g=>'<button class="btn '+(PLATFORM_VIEW.group===g.id?'':'ghost')+'" data-platform-group="'+esc(g.id)+'" style="padding:5px 10px;font-size:12px">'+esc(g.label)+' <span class="pill">'+fmt(g.id==='all'?rows.length:countFor(g.id))+'</span></button>').join('');
  const cards=filtered.map(p=>{
    const match=CATALOG_VIEW.igdbPlatforms.find(x=>{
      const local=catalogPlatform(x.name);return local&&local.slug===p.slug;
    });
    const logo=catalogImage(match&&match.logoUrl);
    const datCount=CATALOG_VIEW.datPlatforms.find(x=>x.slug===p.slug);
    const canBrowse=Boolean(match||datCount);
    const generation=match&&match.generation?'Generation '+esc(match.generation):'';
    const logoMarkup=logo
      ?'<img loading="lazy" referrerpolicy="no-referrer" alt="" src="'+esc(logo)+'" style="max-width:100%;max-height:58px;object-fit:contain">'
      :'<span style="font-size:19px;font-weight:700;color:var(--accent-text)">'+esc(p.name.split(/\s+/).map(x=>x[0]||'').slice(0,3).join('').toUpperCase())+'</span>';
    const routeBadges=(p.play_routes||[]).map(x=>'<span class="pill">'+esc(x)+'</span>').join(' ');
    const max=p.max_size_mb>=1024?fmt(p.max_size_mb/1024)+' GB':fmt(p.max_size_mb)+' MB';
    return '<article class="tile" style="padding:12px;display:flex;flex-direction:column;min-height:224px">'
      +'<div style="height:62px;display:flex;align-items:center;justify-content:center;background:var(--surface-2);border-radius:var(--r-sm);margin-bottom:8px">'+logoMarkup+'</div>'
      +'<div class="nm" style="padding:2px 0 4px"><b>'+esc(p.name)+'</b></div>'
      +'<div class="pf" style="padding:0 0 6px">'+esc(p.media)+(generation?' · '+generation:'')+'</div>'
      +'<div class="pf" style="padding:0 0 6px">'+routeBadges+'</div>'
      +'<div class="pf" style="padding:0 0 8px">'+esc((p.extensions||[]).slice(0,5).join(' '))+' · '+esc(max)
        +(datCount?' · '+fmt(datCount.gameCount)+' DAT titles':'')+'</div>'
      +'<div style="margin-top:auto"><button class="btn ghost" data-platform-browse="'+esc(p.slug)+'"'+(canBrowse?'':' disabled')+' style="width:100%">'+(canBrowse?'Browse games':'Catalog unavailable')+'</button></div>'
      +'</article>';
  }).join('');
  $('#page').innerHTML='<div class="card"><h3>Platforms, by era</h3>'
    +'<p class="help">Choose a generation you remember, search by name, then open its catalog. The playback label shows how this install handles each system.</p>'
    +'<p class="help">ROMarr acquires, verifies and files games. For household discovery, covers and a request queue, pair it with <a href="https://github.com/snapetech-org/seerrng" target="_blank" rel="noopener noreferrer">SeerrNG</a>; see the <a href="https://github.com/snapetech-org/ROMarrNG/blob/main/docs/SEERRNG-INTEGRATION.md" target="_blank" rel="noopener noreferrer">integration guide</a>.</p>'
    +'<div class="row" style="gap:6px;margin-bottom:12px;flex-wrap:wrap">'+eraButtons+'</div>'
    +'<div class="row" style="margin-bottom:14px"><input id="platform-filter" type="search" value="'+esc(PLATFORM_VIEW.query)+'" placeholder="Search platforms" style="max-width:340px"><span class="help">'+fmt(filtered.length)+' platforms</span></div>'
    +(cards?'<div class="grid">'+cards+'</div>':'<div class="empty">No platforms match this filter.</div>')
    +'<details class="card" style="margin-top:14px"><summary>Technical details</summary>'
    +'<table style="margin-top:10px"><thead><tr><th>Platform</th><th>Media</th><th>Plays</th><th>Size ceiling</th><th>Extensions</th></tr></thead><tbody>'
    +filtered.map(p=>'<tr><td><b>'+esc(p.name)+'</b><div class="help">'+esc(p.slug)+'</div></td>'
      +'<td><span class="pill">'+esc(p.media)+'</span></td>'
      +'<td>'+((p.play_routes||[]).map(x=>'<span class="pill">'+esc(x)+'</span>').join(' '))+'</td>'
      +'<td>'+esc(p.max_size_mb>=1024?fmt(p.max_size_mb/1024)+' GB':fmt(p.max_size_mb)+' MB')+'</td>'
      +'<td class="help">'+esc((p.extensions||[]).join(' '))+'</td></tr>').join('')
    +'</tbody></table></details></div>';
  document.querySelectorAll('[data-platform-group]').forEach(b=>b.onclick=()=>{
    PLATFORM_VIEW.group=b.dataset.platformGroup;RENDER.platforms();
  });
  $('#platform-filter').onchange=()=>{
    PLATFORM_VIEW.query=$('#platform-filter').value;RENDER.platforms();
  };
  document.querySelectorAll('[data-platform-browse]').forEach(b=>b.onclick=()=>{
    const slug=b.dataset.platformBrowse;
    const igdbMatch=CATALOG_VIEW.igdbPlatforms.some(x=>{
      const local=catalogPlatform(x.name);return local&&local.slug===slug;
    });
    const datMatch=CATALOG_VIEW.datPlatforms.some(x=>x.slug===slug);
    CATALOG_VIEW.platform=slug;CATALOG_VIEW.mode='catalog';
    CATALOG_VIEW.source=igdbMatch?'igdb':(datMatch?'dat':'igdb');
    CATALOG_VIEW.offset=0;go('lists');
  });
};

// --- Blocklist -------------------------------------------------------------
// Every other *arr shows you a list of blocked releases. This shows why each
// one is blocked, which is the only form of the answer anybody can act on.
RENDER.blocklist=async()=>{
  const d=await j('/api/v1/blocklist').catch(()=>({items:[]}));
  const items=d.items||[];
  const when=regionalEpochDateTime;
  $('#page').innerHTML='<div class="card"><h3>Blocklist '
    +'<span class="help" style="margin-inline-start:8px">'+fmt(items.length)+'</span></h3>'
    +'<p class="help">Releases ROMarr will never take again. Each carries the '
    +'reason it was blocked, so lifting one is a decision rather than a guess.</p>'
    +(items.length
      ?'<table><thead><tr><th>Release</th><th>Indexer</th><th>Reason</th>'
       +'<th>Blocked</th><th></th></tr></thead><tbody>'
       +items.map(i=>'<tr><td><b>'+esc(i.title||'(untitled)')+'</b>'
         +'<div class="help" style="margin:2px 0 0;font-size:11px">'+esc(i.id)+'</div></td>'
         +'<td>'+esc(i.indexer||'—')+'</td>'
         +'<td>'+esc(i.reason||'—')+'</td>'
         +'<td style="white-space:nowrap">'+esc(when(i.blocked_at))+'</td>'
         +'<td><button class="mini" data-un="'+esc(i.id)+'">Unblock</button></td></tr>').join('')
       +'</tbody></table>'
      :'<div class="empty-cat"><b>Nothing blocked</b>'
       +interfaceMarkup('ui.a-release-lands-here-when-a-download.82ab780403')+'</div>')
    +'</div>';
  $('#page').querySelectorAll('button[data-un]').forEach(b=>b.onclick=async()=>{
    await fetch('/api/v1/blocklist/'+encodeURIComponent(b.dataset.un),{method:'DELETE'});
    RENDER.blocklist();
  });
};

// --- Connections -----------------------------------------------------------
RENDER.connections=async()=>{
  const [schema,cfg]=await Promise.all([
    j('/api/v1/connection/schema').catch(()=>({types:[]})),
    j('/api/v1/config').catch(()=>({}))]);
  const conns=await j('/api/v1/connection').catch(()=>({items:[]}));
  const have=conns.items||[];
  const types=schema.list||schema.types||[];
  $('#page').innerHTML='<div class="card"><h3>Connections</h3>'
    +'<p class="help">Where ROMarr tells you what it did. A grab notification '
    +'carries the reasons the release was chosen, not just its name.</p>'
    +(have.length
      ?'<table><thead><tr><th>Name</th><th>Type</th><th>Events</th><th></th></tr></thead><tbody>'
       +have.map((c,i)=>'<tr><td><b>'+esc(c.name||c.type)+'</b></td>'
         +'<td><span class="pill">'+esc(c.type)+'</span></td>'
         +'<td>'+esc((c.events||['all']).join(', '))+'</td>'
         +'<td style="text-align:end"><div class="rowact">'
         +'<button data-cedit="'+i+'">Edit</button></div></td></tr>').join('')
       +'</tbody></table>'
      :'<div class="empty-cat"><b>No connections yet</b>Add one — this is '
       +'where the Discord webhook goes.</div>')
    +'<div class="row" style="margin-top:14px">'
    +'<button class="btn" id="c-add">Add Connection</button>'
    +'<button class="btn ghost" id="ctest">Send a test notification</button>'
    +'<span id="ctestmsg" class="help" style="margin:0"></span></div></div>'

    +'<div class="card"><h3>Available providers</h3>'
    +'<div class="pgrid">'+types.map(t=>
      '<div class="pcard"><h4>'+esc(t.label)+'</h4>'
      +'<div class="desc">'+esc(t.help)+'</div>'
      +'<div class="meta">'+(t.fields||[]).map(f=>'<span class="pill">'+esc(f)+'</span>').join(' ')+'</div>'
      +'</div>').join('')+'</div></div>';

  $('#c-add').onclick=()=>addItem('connection');
  document.querySelectorAll('[data-cedit]').forEach(b=>b.onclick=()=>
    editItem('connection', have[Number(b.dataset.cedit)]));
  $('#ctest').onclick=async()=>{
    const m=$('#ctestmsg'); m.textContent='Sending…';
    const r=await fetch('/api/v1/connection/test',{method:'POST',
      headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json();
    const res=d.results||[];
    m.innerHTML = res.length
      ? res.map(x=>'<span lang="und" dir="auto">'+esc(x.name)+':</span> '
          +interfaceMarkup(x.ok?'Delivered':'Failed')).join(' · ')
      : interfaceMarkup('ui.no-connections-configured.0132bcd2e2');
  };
};

// --- Metadata --------------------------------------------------------------
RENDER.metadata=async()=>{
  const mine=await j('/api/v1/metadataprovider').catch(()=>({items:[]}));
  const schema=await j('/api/v1/metadata/schema').catch(()=>({providers:[]}));
  const probe=await j('/api/v1/metadata/lookup?filename='
    +encodeURIComponent('Chrono.Trigger.USA.v1.1.smc')).catch(()=>({}));
  $('#page').innerHTML='<div class="card"><h3>Configured providers</h3>'
    +'<p class="help"><b>This is where the keys go.</b> Add RAWG (a free key) '
    +'or IGDB (a Twitch client id + bearer token) and lookups, Discover and '
    +'the Calendar light up.</p>'
    +'<div class="row" style="margin-bottom:10px">'
    +'<button class="btn" id="mp-add">Add Provider</button></div>'
    +((mine.items||[]).length
      ?'<table><thead><tr><th>Name</th><th>Type</th><th>Enabled</th><th></th></tr></thead><tbody>'
        +mine.items.map((m,i)=>'<tr><td><b>'+esc(m.name||m.type)+'</b></td>'
          +'<td>'+esc(m.type)+'</td>'
          +'<td><span class="dot '+(m.enable!==false?'up':'down')+'"></span></td>'
          +'<td style="text-align:end"><div class="rowact">'
          +'<button data-mpedit="'+i+'">Edit</button></div></td></tr>').join('')
        +'</tbody></table>'
      :'<div class="empty">No provider configured yet — covers, Discover and '
       +'the Calendar stay dark until one is.</div>')
    +'</div>'
    +'<div class="card"><h3>What each provider needs</h3>'
    +'<p class="help">ROMarr looks a game up by its <b>DAT-verified name</b> when it '
    +'has one, and only falls back to parsing the filename when it does not. '
    +'Every result says which was used, because a cover matched from a guess '
    +'deserves less trust than one matched from a hash.</p>'
    +'<table><thead><tr><th>Provider</th><th>Needs</th><th>Notes</th></tr></thead><tbody>'
    +(schema.providers||[]).map(p=>'<tr><td><b>'+esc(p.label)+'</b></td>'
      +'<td>'+(p.fields||[]).map(f=>'<span class="pill">'+esc(f)+'</span>').join(' ')+'</td>'
      +'<td class="help" style="margin:0">'+esc(p.help)+'</td></tr>').join('')
    +'</tbody></table></div>'

    +'<div class="card"><h3>Try it</h3>'
    +'<p class="help">A live lookup against whatever you have configured.</p>'
    +'<div class="field"><label>Filename</label>'
    +'<input id="mfn" value="Chrono.Trigger.USA.v1.1.smc"></div>'
    +'<button class="mini accent" id="mgo">Identify</button>'
    +'<div id="mout" style="margin-top:12px">'+metaResult(probe)+'</div></div>';

  $('#mgo').onclick=async()=>{
    const d=await j('/api/v1/metadata/lookup?filename='
      +encodeURIComponent($('#mfn').value)).catch(()=>({}));
    $('#mout').innerHTML=metaResult(d);
  };
  $('#mp-add').onclick=()=>addItem('metadataprovider');
  document.querySelectorAll('[data-mpedit]').forEach(b=>b.onclick=()=>
    editItem('metadataprovider', mine.items[Number(b.dataset.mpedit)]));
};

const metaResult=d=>{
  if(!d||!d.matched_by) return '<div class="help">No answer.</div>';
  const badge = d.matched_by==='dat'
    ? '<span class="pill" style="background:var(--ok);color:var(--ok-ink)">matched by DAT — exact</span>'
    : '<span class="pill">matched by filename — a guess</span>';
  return '<div class="pcard"><h4>'+esc(d.title||'Not identified')+'</h4>'
    +'<div class="meta">'+badge+(d.source?'<span class="pill">'+esc(d.source)+'</span>':'')+'</div>'
    +(d.summary?'<div class="desc">'+esc(d.summary)+'</div>':'')
    +(d.found?'':'<div class="help" style="margin:0">Configure a provider above to '
      +'turn this into a title, cover and description.</div>')+'</div>';
};

// --- Calendar --------------------------------------------------------------
// The Calendar reads YOUR library. It used to ask a metadata provider for a
// release schedule, which meant a fully-catalogued 166k-game install rendered
// "add a metadata provider with an API key" and nothing else, forever — while
// the library server sat there holding a release date, an added date and an
// updated date for every row. The provider calendar is still here, below the
// real one, for whoever has a key.
let CAL={view:'releases',month:'',day:''};

RENDER.calendar=async()=>{
  const q=new URLSearchParams({view:CAL.view,limit:'120'});
  if(CAL.month) q.set('month',CAL.month);
  if(CAL.day) q.set('day',CAL.day);
  const d=await j('/api/v1/calendar/library?'+q)
    .catch(()=>({items:[],days:[],error:'The library read failed.'}));
  const views=[['releases','Anniversaries'],['added','Added'],
               ['updated','Updated'],['upcoming','Upcoming']];
  const items=d.items||[], days=d.days||[];
  const cov=d.coverage||{};
  // The share of the shelf this view can place at all. A calendar drawn over
  // 39% of a library that presents itself as the whole library is how
  // somebody concludes they own nothing from 1993.
  const coverageSource={
    released:'{dated} of {total} games have a release date — the rest were never identified, so they cannot be placed on a day.',
    added:'{dated} of {total} games have a date added — the rest were never identified, so they cannot be placed on a day.',
    updated:'{dated} of {total} games have a date updated — the rest were never identified, so they cannot be placed on a day.',
  }[cov.field]||'{dated} of {total} games have a date — the rest were never identified, so they cannot be placed on a day.';
  const covLine=cov.total
    ? interfaceTemplateMarkup(coverageSource,{dated:fmt(cov.dated),total:fmt(cov.total)})
    :'';
  const step=n=>{
    const [y,m]=(d.month||'').split('-').map(Number);
    if(!y) return '';
    const t=new Date(Date.UTC(y,m-1+n,1));
    return t.getUTCFullYear()+'-'+String(t.getUTCMonth()+1).padStart(2,'0');
  };
  const busiest=days.reduce((a,x)=>Math.max(a,x.count),0);

  $('#page').innerHTML='<div class="card">'
    +'<div class="row" style="margin-bottom:10px;gap:6px;flex-wrap:wrap">'
    +views.map(([k,l])=>'<button class="btn '+(k===d.view?'':'ghost')+'"'
      +' data-calview="'+k+'" style="padding:4px 10px;font-size:12px">'
      +l+'</button>').join('')
    +'</div>'
      +(d.error?'<div class="panel-note panel-warn">'+appMessageMarkup(d.error)+'</div>':'')
    +(d.note?'<p class="help">'+esc(d.note)+'</p>':'')
    +(d.view!=='upcoming'&&d.month
      ?'<div class="row" style="align-items:center;gap:8px;margin:4px 0 8px">'
        +'<button class="btn ghost" data-calmonth="'+step(-1)+'">‹</button>'
        +'<b style="font-size:14px">'+esc(regionalMonth(d.month))+'</b>'
        +'<button class="btn ghost" data-calmonth="'+step(1)+'">›</button>'
        +'<span style="flex:1"></span>'
        +'<span class="help" style="margin:0">'+covLine+'</span></div>'
      +'<div class="cal">'
      +['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
        .map(n=>'<div class="dow">'+n+'</div>').join('')
      +Array.from({length:d.first_weekday||0},
                  ()=>'<button class="pad" disabled></button>').join('')
      +days.map(x=>'<button data-calday="'+x.day+'" '
        +(x.count?'':'disabled ')
        +'class="'+(x.count?'':'none ')
        +(x.day===d.selected_day?'on':'')+'">'
        +'<span>'+fmt(x.day)+'</span>'
        +(x.count?'<b>'+fmt(x.count)+'</b>':'')+'</button>').join('')
      +'</div>'
      +(busiest?'':'<p class="help">Nothing in this month. Page back — a '
        +'library imported in one batch has its dates where the imports were.</p>')
      :'')
    +'<h3 style="margin-top:14px">'
    +(d.view==='upcoming'?interfaceMarkup('ui.releasing-soon.3c88ed9466')
        :interfaceTemplateMarkup(d.view==='releases'?'Released on {date}'
          :d.view==='added'?'Added {date}':'Updated {date}',
          {date:regionalDate(d.day)}))
    +'</h3>'
    +(items.length
      ?'<p class="help">'+interfaceTemplateMarkup('ui.count-from-your-own-library.91b7e1cd52',
          {count:fmt(d.items.length)})+'</p>'
       +'<div class="grid">'+items.map(g=>'<div class="tile">'
        +'<div class="art" style="background-image:url(\''+esc(g.cover_url||'')+'\')"></div>'
        +'<div class="nm">'+esc(g.title)+'</div>'
        +'<div class="pf">'+esc(g.platform||'')
        +(g.year?' · '+regionalYear(g.year):'')+(g.rating?' · ★'+num(g.rating):'')
        +'</div></div>').join('')+'</div>'
      :'<div class="empty">'+esc(d.view==='upcoming'
        ?'Nothing dated in the future.'
        :'Nothing on this day.')+'</div>')
    +'</div>'
    +'<div class="card" style="margin-top:14px"><h3>Elsewhere</h3>'
    +'<p class="help" id="cal-web-note">A metadata provider can answer about '
    +'games nobody here owns — everything above needs nothing at all.</p>'
    +'<div id="cal-web"><div class="empty">Checking…</div></div>'
    +'</div>';

  document.querySelectorAll('[data-calview]').forEach(b=>b.onclick=()=>{
    CAL.view=b.dataset.calview; CAL.month=''; CAL.day=''; go('calendar');});
  document.querySelectorAll('[data-calmonth]').forEach(b=>b.onclick=()=>{
    CAL.month=b.dataset.calmonth; CAL.day=''; go('calendar');});
  document.querySelectorAll('[data-calday]').forEach(b=>b.onclick=()=>{
    CAL.day=b.dataset.calday; go('calendar');});

  // Second, and separately: a provider calendar shows a request button
  // because those are games you do not have. Nothing above does — you
  // already own everything on it.
  //
  // On the Upcoming view the window loses its backward half. The library
  // half of that view can only ever say "you own nothing unreleased", which
  // is true and is the point; pairing it with a provider list that is mostly
  // last month's releases answers a question nobody asked.
  //
  // back=-1 rather than back=0, because a window that opens today opens on
  // today's releases — forty of them on a busy day, every one of them
  // already out, filling a shelf headed "still to come".
  const w=await j('/api/v1/calendar'+(d.view==='upcoming'?'?back=-1':''))
    .catch(()=>({items:[],error:'Unreachable'}));
  const web=w.items||[];
  const wsrc=w.provider_label||'';
  if(web.length){
    const upcoming=d.view==='upcoming';
    const source=wsrc
      ?(upcoming
        ?'{count} titles from {provider}\'s catalogue, still to come — none are in your library, so they have a Request button.'
        :'{count} titles from {provider}\'s catalogue, either side of today — none are in your library, so they have a Request button.')
      :(upcoming
        ?'{count} titles from the metadata provider catalogue, still to come — none are in your library, so they have a Request button.'
        :'{count} titles from the metadata provider catalogue, either side of today — none are in your library, so they have a Request button.');
    const values={count:fmt(web.length)};
    if(wsrc) values.provider=wsrc;
    $('#cal-web-note').innerHTML=interfaceTemplateMarkup(source,values);
  }
  $('#cal-web').innerHTML=web.length
    ?'<div class="pgrid">'+web.map((g,n)=>'<div class="pcard">'
      +'<h4>'+esc(g.title)+'</h4>'
      +'<div class="meta"><span class="pill">'+(g.released
        ?esc(regionalDate(g.released)):interfaceMarkup('ui.not-announced.b40572aafd'))+'</span>'
      +(g.upcoming?'<span class="pill" style="background:var(--info);color:var(--info-ink)">upcoming</span>':'')
      +(g.source||wsrc?'<span class="pill">'+esc(g.source||wsrc)+'</span>'
        :interfaceMarkup('ui.metadata-provider.fe3de0c7fb'))
      +'</div>'
      +'<div class="desc">'+esc((g.platforms||[]).slice(0,4).join(', '))+'</div>'
      +'<div class="rowact" style="margin-top:6px"><button data-calreq="'+n+'">Request</button></div>'
      +'</div>').join('')+'</div>'
    :'<div class="empty">'+appMessageMarkup(w.error||'No provider configured.')+'</div>';
  document.querySelectorAll('[data-calreq]').forEach(b=>b.onclick=()=>
    requestGame(web[Number(b.dataset.calreq)]));
};

// Shared by Calendar and Discover: turn a metadata title into a Wanted
// request, resolving the store's platform names to a ROMarr platform.
async function requestGame(g){
  const names=(g.platforms||[]);
  const match=PLATFORMS.find(p=>names.some(n=>
    p.name.toLowerCase()===String(n).toLowerCase()||p.slug===String(n).toLowerCase()));
  let slug=match?match.slug:'';
  if(!slug){
    const pick=promptMessage('ui.platform-for-game-available-platform.afd580990f',{
      game:g.title,platforms:PLATFORMS.map(p=>p.slug).join(', ')});
    const m=PLATFORMS.find(p=>p.slug===(pick||'').toLowerCase()
      ||p.name.toLowerCase()===(pick||'').toLowerCase());
    if(!m){toastLabel('ui.need-a-known-platform.730519de98');return;}
    slug=m.slug;
  }
  const r=await j('/api/request',{method:'POST',
    headers:{'content-type':'application/json'},
    body:JSON.stringify({game:g.title,platform:slug})});
  if(r.ok)toastMessage('ui.grabbed-release.94cc8b2735',{release:r.release||g.title});
  else if(r.error)toastAppMessage(r.error);else toastLabel('ui.added-to-wanted.bacfe35baa');
  refreshCounts();
}

// --- Manual Import ---------------------------------------------------------
// Radarr calls this Manual Import and it exists for the same reason: somebody
// arrives with a library already on disk, and telling them to re-download
// everything ROMarr could have adopted is absurd.
RENDER.getstarted=async()=>{
  // The question a capable new self-hoster actually asked: "if I host ROMs,
  // where do I play them?" ROMarr acquires and files; something else plays.
  // Saying so plainly beats implying ROMarr is a frontend it is not.
  const [status,libs,plat]=await Promise.all([
    j('/api/v1/system/status').catch(()=>({})),
    j('/api/v1/library').catch(()=>({items:[]})),
    j('/api/platforms').catch(()=>({platforms:[]}))
  ]);
  const items=libs.items||[];
  const platforms=plat.platforms||[];
  const ok=x=>x?'<span class="pill" style="background:var(--ok);color:var(--ok-ink)">ready</span>'
                :'<span class="pill" style="background:var(--warn);color:var(--warn-ink)">not set up</span>';

  const indexerOk=!!(status.prowlarr||(status.indexers||0)>0);
  // /api/v1/system/status reports configured clients in `clients`. The
  // legacy per-client fields and `download_clients` count are not returned
  // by that endpoint, so checking them left this step permanently unset.
  const clientOk=(status.clients||[]).some(c=>c&&c.configured);
  const libOk=items.some(l=>l.ok);
  const datOk=(status.dats||0)>0||!!status.dat_games;

  const step=(n,title,done,body)=>'<div style="display:flex;gap:14px;'
    +'padding:14px 0;border-bottom:1px solid var(--line)">'
    +'<div style="flex:0 0 30px;height:30px;border-radius:50%;display:flex;'
    +'align-items:center;justify-content:center;font-weight:600;'
    +'background:'+(done?'var(--ok)':'var(--rail-2)')+';'
    +'color:'+(done?'#08210d':'var(--dim)')+'">'+(done?'✓':n)+'</div>'
    +'<div style="flex:1"><div style="font-weight:600;margin-bottom:3px">'
    +title+' '+ok(done)+'</div>'
    +'<div class="help" style="margin:0">'+body+'</div></div></div>';

  const counts={};
  platforms.forEach(p=>{const r=(p.play&&p.play.route)||'unknown';
    counts[r]=(counts[r]||0)+1;});
  const routeRow=(k,label,what)=>counts[k]
    ?'<tr><td>'+interfaceTemplateMarkup('ui.count-platforms.1b77a69ab6',{count:fmt(counts[k])})+'</td><td>'+esc(label)+'</td>'
     +'<td class="help" style="margin:0">'+what+'</td></tr>':'';

  $('#page').innerHTML=
    '<div class="card"><h3>What ROMarr is</h3>'
    +'<p class="help">'+interfaceMarkup('ui.romarr-is-the-acquisition-and-automa.5568f4a4ea')
    +' <b>'+interfaceMarkup('ui.it-is-not-an-emulator-and-not-a-game.ee0cdf4dd9')+'</b> '
    +interfaceMarkup('ui.something-else-plays-the-rom-romarr.96515488d1')+'</p>'
    +'<div style="font-family:ui-monospace,monospace;font-size:12.5px;'
    +'background:var(--bg);border:1px solid var(--line);border-radius:6px;'
    +'padding:14px;overflow-x:auto;line-height:1.9">'
    +'<b>Acquire</b> → <b>Verify</b> → <b>File</b> → <b>Scan</b> → <b>Play</b><br>'
    +'<span style="color:var(--dim)">'+interfaceMarkup('ui.indexers-dat-hashes-library-root-lib.6a5d3af601')+'</span><br>'
    +'<span style="color:var(--dim)">'+interfaceMarkup('ui.romarr-does-the-first-four-you-choos.88f6a36ef9')+'</span>'
    +'</div></div>'

    +'<div class="card" style="margin-top:16px"><h3>Choose a starting point</h3>'
    +'<p class="help">Pick one route. You can return here and add the other pieces later.</p>'
    +'<div class="grid">'
    +'<a class="tile" href="#platforms" style="text-decoration:none;color:inherit;padding:12px"><div class="nm">Choose a system or era</div><div class="pf">Browse supported platforms, see how they play, and open the matching catalog.</div></a>'
    +'<a class="tile" href="#manualimport" style="text-decoration:none;color:inherit;padding:12px"><div class="nm">I already have ROMs</div><div class="pf">Import a folder you own and let ROMarr identify and file what is there.</div></a>'
    +'<a class="tile" href="#organize" style="text-decoration:none;color:inherit;padding:12px"><div class="nm">Organize a library you already have</div><div class="pf">Match DATs, cache shared metadata and artwork, and preview safe renames.</div></a>'
    +'<a class="tile" href="#lists" style="text-decoration:none;color:inherit;padding:12px"><div class="nm">Build a request list</div><div class="pf">Browse catalog titles or connect an import list. Requests use your configured sources and client.</div></a>'
    +'<a class="tile" href="#collections" style="text-decoration:none;color:inherit;padding:12px"><div class="nm">Work toward a complete set</div><div class="pf">Load a DAT and see verified titles and collection progress.</div></a>'
    +'</div>'
    +'<p class="help" style="margin-top:12px">For a shared catalog and household request queue, use <a href="https://github.com/snapetech-org/seerrng" target="_blank" rel="noopener noreferrer">SeerrNG</a>. ROMarr handles release search, verification and filing; the <a href="https://github.com/snapetech-org/ROMarrNG/blob/main/docs/SEERRNG-INTEGRATION.md" target="_blank" rel="noopener noreferrer">integration guide</a> explains the connection.</p></div>'
    +'<div class="card" style="margin-top:16px"><h3>Your setup</h3>'
    +step(1,'An indexer',indexerOk,
       interfaceMarkup('ui.prowlarr-or-torznab-newznab-indexers.529ec79be7')
       +' <a href="#indexers">'+interfaceMarkup('ui.indexers.97f45bfb2b')+'</a>'
       +interfaceMarkup('ui.this-is-where-releases-are-found.84ac1c1f8c'))
    +step(2,'A download client',clientOk,
       interfaceMarkup('ui.qbittorrent-for-torrents-sabnzbd-or.1ebb11a5a2')
       +' <a href="#clients">'+interfaceMarkup('ui.download-clients.aea530a371')+'</a>.')
    +step(3,'A library',libOk,
       interfaceMarkup('ui.where-roms-are-filed-and-what-serves.0630ddfedf')
       +' <a href="#libraries">'+interfaceMarkup('ui.libraries.62ef6fd92e')+'</a>.')
    +step(4,'DATs (optional, recommended)',datOk,
       interfaceMarkup('ui.no-intro-and-redump-checksums-with-t.df6cd186de')
       +' <a href="#collections">'+interfaceMarkup('ui.collections.9f9feade76')+'</a> '
       +interfaceMarkup('ui.can-tell-you-what-a-complete-set-is.3fe1fc5db0'))
    +'</div>'

    +'<div class="card" style="margin-top:16px"><h3>Optional follow-ups</h3>'
    +'<p class="help">'+interfaceMarkup('ui.core-search-grabbing-and-filing-do-n.d6115a1a9e')+'</p>'
    +'<ul class="help">'
    +'<li>'+interfaceMarkup('ui.dat-checks-and-complete-set-progress.73302e5ba1')+' <a href="#collections">'+interfaceMarkup('ui.collections.9f9feade76')+'</a></li>'
    +'<li>'+interfaceMarkup('ui.import-lists-are-optional-and-can-ad.e9dbc2c00d')+' <a href="#lists">'+interfaceMarkup('ui.lists.308d5a0903')+'</a></li>'
    +'<li>'+interfaceMarkup('ui.plugins-are-optional-acquisition-sou.d59910357b')+' <a href="#hub">'+interfaceMarkup('ui.plugins.9514b7ff48')+'</a></li>'
    +'<li>'+interfaceMarkup('ui.streaming-hosts-and-browser-players.16b5157dac')+' <a href="#platforms">'+interfaceMarkup('ui.platforms.ab9bd7584a')+'</a> · <a href="#status">'+interfaceMarkup('ui.system.6725e7bbcd')+'</a></li>'
    +'</ul></div>'

    +'<div class="card" style="margin-top:16px"><h3>Where you actually play</h3>'
    +'<p class="help">'+interfaceMarkup('ui.romarr-files-the-rom-one-of-these-ru.2b6fa916bb')+'</p>'
    +'<table><thead><tr><th>If your library is</th><th>You play in</th></tr></thead><tbody>'
    +'<tr><td>RomM</td><td>RomM\'s built-in EmulatorJS, in the browser</td></tr>'
    +'<tr><td>Gaseous or Retrom</td><td>Their own web players and clients</td></tr>'
    +'<tr><td>'+interfaceMarkup('ui.a-folder.3305da5c6c')+'</td><td>'+interfaceMarkup('ui.batocera-retropie-recalbox-es-de-emu.860dbeb92f')+'</td></tr>'
    +'</tbody></table>'
    +'<div class="panel-note" style="margin-top:12px"><b>'+interfaceMarkup('ui.set-up-a-play-device.fe3981d1fa')+'</b><br>'
    +interfaceMarkup('ui.for-an-emudeck-style-layout-set-the.917f18c4e8')+' <code>Emulation/roms</code> '+interfaceMarkup('ui.folder-and-keep.011b3ce5f5')+' <code>Emulation/metadata</code> '+interfaceMarkup('ui.beside-it-add-a-platform-folder-mapp.6425999b49')
    +' <a href="https://emudeck.github.io/" target="_blank" rel="noopener noreferrer">'+interfaceMarkup('ui.emudeck-setup-guide.17a61d9db9')+'</a>'
    +' · <a href="https://es-de.org/" target="_blank" rel="noopener noreferrer">'+interfaceMarkup('ui.es-de.da1edb39f3')+'</a>'
    +' · <a href="#ecosystem">'+interfaceMarkup('ui.more-player-options.20bb9a4a10')+'</a></div>'
    +'<p class="help">'+interfaceMarkup('ui.romarr-can-also-export-your-library.6d7122989e')
    +' <a href="#status">'+interfaceMarkup('ui.system.6725e7bbcd')+'</a>.</p>'
    +(Object.keys(counts).length
      ?'<h3 style="margin-top:18px">On this install</h3>'
       +'<table><thead><tr><th></th><th>Route</th><th>What that means</th>'
       +'</tr></thead><tbody>'
       +routeRow('browser','Browser emulator',
          interfaceMarkup('ui.playable-in-the-browser-through-your.ff04c20c87'))
       +routeRow('stream','Streamed',
          interfaceMarkup('ui.too-heavy-for-the-browser-rendered-b.76692077eb'))
       +routeRow('download','Download only',
          interfaceMarkup('ui.romarr-fetches-and-verifies-it-you-p.38dbf2d368'))
       +'</tbody></table>':'')
    +'</div>'

    +'<div class="card" style="margin-top:16px"><h3>Next</h3>'
    +'<p class="help">'
    +'<a href="#add">'+interfaceMarkup('ui.request-a-game.027797e16d')+'</a> '+interfaceMarkup('ui.to-watch-the-whole-chain-run-once-or.f4cffe7beb')+' '
    +'<a href="#organize">'+interfaceMarkup('ui.identify-organize.e2a72a6310')+'</a> '+interfaceMarkup('ui.to-build-a-shared-inventory-from-an.690cadc93e')+' '
    +'<a href="#manualimport">'+interfaceMarkup('ui.manual-import.3b797ce5ae')+'</a> '+interfaceMarkup('ui.to-adopt-roms-you-already-have-if-yo.6aa6a69c8f')+' '
    +'<a href="#collections">'+interfaceMarkup('ui.collections.9f9feade76')+'</a> '
    +interfaceMarkup('ui.compares-a-dat-against-your-shelf-an.d52fa37f6b')
    +'</p></div>';
};

RENDER.collections=async()=>{
  const st=await j('/api/v1/collection').catch(()=>({dats:[],batches:[]}));
  const dats=st.dats||[];
  $('#page').innerHTML='<div class="card"><h3>Plan a set</h3>'
    +(dats.length
      ?'<p class="help">Compare a DAT against your library. Nothing is '
       +'requested until you say so.</p>'
       +'<div class="row" style="flex-wrap:wrap;gap:10px">'
       +'<select id="cdat">'+dats.map(d=>'<option>'+esc(d)+'</option>').join('')+'</select>'
       +'<select id="cplat"><option value="" data-i18n="ui.platform-match-on-disk.ff6c13f329">platform (match on disk)</option>'
       +PLATFORMS.map(p=>'<option value="'+esc(p.slug)+'">'+esc(p.name)+'</option>').join('')
       +'</select>'
       +'<label class="help" style="margin:0"><input type="checkbox" id="c1g1r" checked> '
       +interfaceMarkup('ui.one-game-one-rom.3372b0856c')+'</label>'
       +'<input id="cregions" placeholder="usa,world,europe,japan" '
       +'style="flex:1;min-width:180px;padding:7px 10px;background:var(--bg);'
       +'color:var(--fg);border:1px solid var(--line);border-radius:6px">'
       +'<label class="help" style="margin:0" title="Treat the region list as an allowlist: omit a title when no dump matches one of your regions">'
       +'<input type="checkbox" id="cstrict"'+((SETTINGS.region_mode||'prefer')==='strict'?' checked':'')+'> '
       +interfaceMarkup('ui.only-selected-regions.e257690d2c')+'</label>'
       +'<button class="btn" id="cplan">Preview plan</button></div>'
       +'<div class="row" style="flex-wrap:wrap;gap:14px;margin-top:10px">'
       +[['proto','Exclude prototypes'],['beta','Exclude beta versions'],
         ['demo','Exclude demos'],['hack','Exclude ROM hacks'],
         ['unlicensed','Exclude unlicensed ROMs']].map(([kind,label])=>
          '<label class="help" style="margin:0"><input type="checkbox" class="cex" '
          +'value="'+kind+'" checked> '+interfaceMarkup(label)+'</label>').join('')
       +'</div>'
       +'<div class="row" style="gap:8px;margin-top:10px;align-items:center">'
       +'<label class="help" style="margin:0" for="ctrans">Fan translations</label>'
       +'<select id="ctrans">'
       +[['exclude','Exclude — published dumps only'],
         ['fill','Fill gaps — use a translation only when no preferred-region dump exists'],
         ['prefer','Prefer — take a translation over the region winner when one exists'],
         ['keep_both','Keep both — original plus the translation in a Translations subfolder']].map(o=>
          '<option value="'+o[0]+'" data-i18n-key="'+esc(stableLocalizationKey(o[1])||o[1])+'"'+((SETTINGS.translation_policy||'exclude')===o[0]?' selected':'')
          +'>'+esc(o[1])+'</option>').join('')
       +'</select>'
       +'<label class="help" style="margin:0" for="ctranslangs">languages</label>'
       +'<input id="ctranslangs" placeholder="'+esc((SETTINGS.translation_langs||['en']).join(', '))+'" '
       +'value="'+esc((SETTINGS.translation_langs||['en']).join(', '))+'" '
       +'style="width:110px;padding:6px 8px;background:var(--bg);color:var(--fg);'
       +'border:1px solid var(--line);border-radius:6px" title="Comma-separated codes, e.g. de, en">'
       +'</div>'
      :'<div class="empty-cat"><b>No DAT loaded</b>'
       +'Point DAT_PATH at a directory of No-Intro or Redump DATs. Without one '
       +'there is no list of what a complete set contains.</div>')
    +'<div id="cswitch" hidden><p class="help">Switch uses catalogue IDs and filename versions, not checksum verification. DAT region and translation controls do not apply. Name searches need TITLED_NAMES=1.</p>'
    +'<label>Switch title name or ID <input id="csquery" placeholder="Title name or ID"></label>'
    +'<label> Include <select id="cskinds"><option value="base" data-i18n="ui.base-games.6462a63d20">Base games</option><option value="update" data-i18n="ui.updates.22e2bada8f">Updates</option><option value="dlc">DLC</option><option value="base,update,dlc" data-i18n="ui.all-three.10243133c1">All three</option></select></label>'
    +'<label><input type="checkbox" id="cslatest" checked> Latest listed version only</label></div>'
    +'<div id="cres" style="margin-top:16px"></div></div>'
    +'<div class="card" style="margin-top:16px"><h3>Batches</h3>'
    +'<div id="cbatch"></div></div>';

  const drawBatches=async()=>{
    const s=await j('/api/v1/collection').catch(()=>({batches:[]}));
    const cb=$('#cbatch'); if(!cb) return;   // left the Collections page
    const b=s.batches||[];
    cb.innerHTML=b.length
      ?'<table><thead><tr><th>Set</th><th>Progress</th><th>Done</th>'
       +'<th>Failed</th><th>Left</th><th></th></tr></thead><tbody>'
       +b.map(x=>'<tr data-id="'+esc(x.id)+'"><td>'+esc(x.dat||x.platform||x.id)+'</td>'
         +'<td style="min-width:150px"><div style="background:var(--bg);'
         +'border:1px solid var(--line);border-radius:4px;height:16px;overflow:hidden">'
         +'<div style="height:100%;width:'+x.percent+'%;background:var(--accent)"></div>'
         +'</div><span class="help" style="margin:0">'+fmt(x.percent)+'% — '+statusMarkup(x.status)+'</span></td>'
         +'<td>'+fmt(x.done)+'</td><td>'+fmt(x.failed)+'</td><td>'+fmt(x.remaining)+'</td>'
         +'<td class="row" style="gap:6px">'
         +'<button class="btn ghost cstep">Run next</button>'
         +'<button class="btn ghost cact" data-a="'+(x.status==='paused'?'resume':'pause')+'">'
         +(x.status==='paused'?'Resume':'Pause')+'</button>'
         +(x.failed?'<button class="btn ghost cact" data-a="retry">Retry failed</button>':'')
         +'<button class="btn ghost cact" data-a="cancel">Cancel</button></td></tr>').join('')
       +'</tbody></table>'
      :'<div class="empty">No set is being acquired.</div>';

    cb.querySelectorAll('.cstep').forEach(el=>el.onclick=async e=>{
      const id=e.target.closest('tr').dataset.id;
      e.target.disabled=true; e.target.textContent='Running…';
      await j('/api/v1/collection/step',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
      drawBatches();
    });
    cb.querySelectorAll('.cact').forEach(el=>el.onclick=async e=>{
      const id=e.target.closest('tr').dataset.id, action=e.target.dataset.a;
      if(action==='cancel'&&!confirmMessage('ui.cancel-this-set-titles-already-reque.00b722d3cd')) return;
      await j('/api/v1/collection/control',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:id,action:action})});
      drawBatches();
    });
  };
  drawBatches();

  const planBtn=$('#cplan');
  if(!planBtn) return;
  const switchControls=()=>{
    const enabled=$('#cdat').value==='TitleDB (Switch)';
    $('#cswitch').hidden=!enabled;
    if(enabled) $('#cplat').value='switch';
  };
  $('#cdat').onchange=switchControls;
  switchControls();
  planBtn.onclick=async()=>{
    const out=$('#cres');
    out.innerHTML='<div class="empty">Planning…</div>';
    const ex=[...document.querySelectorAll('.cex')].filter(c=>c.checked)
      .map(c=>c.value).join(',');
    const q='dat='+encodeURIComponent($('#cdat').value)
      +'&platform='+encodeURIComponent($('#cplat').value)
      +'&onegame='+($('#c1g1r').checked?'1':'0')
      +'&regions='+encodeURIComponent($('#cregions').value.trim())
      +'&region_mode='+($('#cstrict').checked?'strict':'prefer')
      +'&translation_policy='+encodeURIComponent($('#ctrans').value)
      +'&translation_langs='+encodeURIComponent($('#ctranslangs').value.trim())
      +'&query='+encodeURIComponent($('#csquery').value.trim())
      +'&kinds='+encodeURIComponent($('#cskinds').value)
      +'&latest_only='+($('#cslatest').checked?'1':'0')
      +'&exclude='+encodeURIComponent(ex);
    const planned={dat:$('#cdat').value,
          platform:$('#cplat').value,
          one_game_one_rom:$('#c1g1r').checked,
          regions:($('#cregions').value.trim()||'').split(',').filter(Boolean),
          region_mode:$('#cstrict').checked?'strict':'prefer',
          translation_policy:$('#ctrans').value,
          query:$('#csquery').value.trim(), kinds:$('#cskinds').value,
          latest_only:$('#cslatest').checked,
          translation_langs:($('#ctranslangs').value.trim()||'').split(',').map(s=>s.trim()).filter(Boolean),
          exclude:ex.split(',').filter(Boolean)};
    const d=await j('/api/v1/collection/plan?'+q).catch(()=>({error:'plan failed'}));
    if(d.error){out.innerHTML='<div class="panel-note panel-warn">'+appMessageMarkup(d.error)+'</div>';return;}
    const c=d.counts;
    const tile=(n,label,colour)=>'<div style="flex:1;min-width:110px;padding:10px 12px;'
      +'background:var(--bg);border:1px solid var(--line);border-radius:6px">'
      +'<div style="font-size:22px;font-weight:600;color:'+colour+'">'+fmt(n)+'</div>'
      +'<div class="help" style="margin:0">'+label+'</div></div>';
    const datMarkup='<span lang="und" dir="auto">'+esc(d.dat)
      +(d.dat_version?' ('+esc(d.dat_version)+')':'')+'</span>';
    const policyMarkup=d.dat==='TitleDB (Switch)'
      ? '<span lang="und" dir="auto">'+esc((d.policy.kinds||[]).join(', '))+'</span> — '
        +interfaceMarkup(d.policy.latest_only?'Latest listed versions':'All listed versions')
      : interfaceTemplateMarkup('ui.region-order-regions.a28b347637',
          {regions:(d.policy.regions||[]).join(' → ')});
    const strictMarkup=d.policy.region_mode==='strict'
      ? ' '+interfaceMarkup('ui.strict-titles-without-a-matching-reg.ce5799c1e8')
      : '';
    out.innerHTML='<div class="row" style="gap:10px;flex-wrap:wrap">'
      +tile(c.expected,interfaceMarkup('ui.in-the-set.6ac2ef8855'),'var(--fg)')
      +tile(c.have,interfaceMarkup('ui.you-have.af3f12e161'),'var(--ok)')
      +tile(c.missing,interfaceMarkup('ui.missing.6be36ca49e'),'var(--warn)')
      +tile(c.bad,interfaceMarkup('ui.bad-dumps.6dc55bd292'),'var(--bad)')
      +tile(c.excluded,interfaceMarkup('ui.excluded-by-policy.fee2bad0b3'),'var(--dim)')
      +((c.region_omitted||0)?tile(c.region_omitted,interfaceMarkup('ui.omitted-no-dump-in-your-regions.73a042f723'),'var(--dim)'):'')
      +'</div>'
      +'<p class="help">'+datMarkup+' — '+policyMarkup+strictMarkup+'.</p>'
      +'<div class="row"><button class="btn" id="cstart">'
      +interfaceTemplateMarkup('ui.request-count-missing.fbb85426ea',{count:fmt(c.missing)})+'</button>'
      +'<label class="help" style="margin:0">at <input id="cpp" type="number" '
      +'min="1" max="50" value="5" style="width:60px;padding:5px;background:var(--bg);'
      +'color:var(--fg);border:1px solid var(--line);border-radius:4px"> per pass</label></div>'
      +'<table style="margin-top:14px"><thead><tr><th>Title</th><th>Status</th>'
      +'<th>Why this dump</th></tr></thead><tbody>'
      +d.titles.slice(0,300).map(t=>{
        const pill=t.status==='verified'
          ?'<span class="pill" style="background:var(--ok);color:var(--ok-ink)">verified</span>'
          :t.status==='bad'
            ?'<span class="pill" style="background:var(--bad);color:var(--bad-ink)">bad dump</span>'
            :t.status==='missing'
              ?'<span class="pill" style="background:var(--warn);color:var(--warn-ink)">missing</span>'
              :'<span class="pill">present</span>';
        const clones=(t.discarded||[]).length
          ?'<details><summary class="help" style="margin:0;cursor:pointer">'
           +interfaceTemplateMarkup(t.discarded.length===1
             ?'One other dump':'{count} other dumps',{count:fmt(t.discarded.length)})+'</summary>'
           +'<ul style="margin:6px 0 0 16px">'+t.discarded.map(x=>
             '<li class="help" style="margin:0">'+esc(x.name)+' — '+collectionReasonMarkup(x.why)+'</li>').join('')
           +'</ul></details>':'';
        return '<tr><td>'+esc(t.name)
          +(t.outside_preference?' <span class="pill" title="No dump in your preferred regions; kept so the game is not lost">outside regions</span>':'')
          +'</td><td>'+pill+'</td><td class="help" style="margin:0">'+collectionReasonMarkup(t.why)
          +clones+'</td></tr>';
      }).join('')+'</tbody></table>'
      +(d.titles.length>300?'<p class="help">'+interfaceTemplateMarkup('ui.showing-the-first-limit-of-count.94b5cbae9f',{limit:fmt(300),count:fmt(d.titles.length)})+'</p>':'');

    $('#cstart').onclick=async e=>{
      e.target.disabled=true; e.target.textContent='Queueing…';
      const r=await j('/api/v1/collection/start',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...planned, per_pass:parseInt($('#cpp').value,10)||5})});
      if(r.error)toastAppMessage(r.error);else toastMessage('ui.queued-count-titles.ad804479d7',{count:fmt(r.queued||0)});
      e.target.disabled=false; e.target.innerHTML=interfaceMarkup('ui.request-missing.e21b6bbf1f');
      drawBatches();
    };
  };
};

RENDER.organize=async()=>{
  const p=$('#page');
  const token=(window._organizeViewToken||0)+1;
  window._organizeViewToken=token;
  const limit=80;
  let offset=0;
  let reviewOnly=false;
  let currentPlan=null;
  let nextPlanOffset=0;
  const planLimit=200;
  const platformOptions='<option value="">All platforms</option>'
    +PLATFORMS.map(x=>'<option value="'+esc(x.slug)+'">'+esc(x.name)+'</option>').join('');
  p.innerHTML=
    '<div class="card"><div class="row" style="align-items:flex-start;gap:12px">'
    +'<div style="flex:1"><h3>Identify &amp; Organize</h3>'
    +'<p class="help">Build a portable inventory, reuse existing ES-DE metadata, match exact DAT dumps, and review safe name changes. Scanning is read only. ROMarr changes files only after you preview and apply a plan.</p></div>'
    +'<a class="btn ghost" href="https://github.com/snapetech-org/seerrng" target="_blank" rel="noopener noreferrer">Requests in SeerrNG ↗</a></div>'
    +'<p class="help" style="margin:0">Use <a href="https://github.com/snapetech-org/seerrng" target="_blank" rel="noopener noreferrer">SeerrNG</a> for the shared household request queue; see the <a href="https://github.com/snapetech-org/ROMarrNG/blob/main/docs/SEERRNG-INTEGRATION.md" target="_blank" rel="noopener noreferrer">integration guide</a> to connect the services.</p>'
    +'<div class="st" style="margin-top:12px">'
    +'<div><b>ROM root</b><span lang="und" dir="auto">'+esc(SETTINGS.library_path||'not configured')+'</span></div>'
    +'<div><b>Shared metadata</b><span lang="und" dir="auto">'+esc(SETTINGS.metadata_path||'not configured')+'</span></div></div>'
    +(!SETTINGS.metadata_path
      ?'<div class="panel-note panel-warn" style="margin-top:12px">Set a shared metadata root in <a href="#media">Media Management</a>. Mount it on each client and point ES-DE at its shared gamelists and media folders.</div>'
      :'')
    +'<p class="help" style="margin:12px 0 8px">Switch title IDs and versions are read from filenames and TitleDB. They help group base games, updates and DLC, but do not verify the package bytes. Exact DAT checksums or a manual confirmation are required before ROMarr offers a rename.</p>'
    +'<div class="row" style="flex-wrap:wrap;gap:8px;align-items:center">'
    +'<select id="org-platform" aria-label="Platform">'+platformOptions+'</select>'
    +'<label class="help" style="margin:0"><input type="checkbox" id="org-review"> Needs review</label>'
    +'<button class="btn" id="org-scan" '+(!SETTINGS.metadata_path?'disabled':'')+'>Scan library</button>'
    +'<button class="btn ghost" id="org-refresh" '+(!SETTINGS.metadata_path?'disabled':'')+'>Refresh metadata</button>'
    +'<button class="btn ghost" id="org-plan" '+(!SETTINGS.metadata_path?'disabled':'')+'>Preview safe renames</button>'
    +'<button class="btn ghost" id="org-undo" '+(!SETTINGS.metadata_path?'disabled':'')+'>Undo last rename</button>'
    +'<button class="btn ghost" id="org-esde" '+(!SETTINGS.metadata_path?'disabled':'')+'>Publish ES-DE data</button></div>'
    +'<p class="help" style="margin:8px 0 0">ROMarr reads ES-DE gamelists and matching local media before online lookup. Publishing writes a shared gamelist and matching covers under the metadata root, using paths relative to the ROM root and matching ES-DE media names. Provider lookups are capped at 200 per scan. Export the portable catalog from <a href="#status">System → Backup &amp; Export</a>; see the <a href="https://github.com/snapetech-org/ROMarrNG/blob/main/docs/features/shared-library-identification.md#portable-metadata" target="_blank" rel="noopener noreferrer">format and schema</a>.</p></div>'
    +'<div id="org-message"></div><div id="org-status"></div><div id="org-plan-result"></div>'
    +'<div id="org-announcement" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>'
    +'<div class="card"><div class="row" style="align-items:center">'
    +'<h3 style="margin:0;flex:1">Library inventory</h3><span id="org-page-label" class="help" style="margin:0"></span></div>'
    +'<div id="org-items" style="margin-top:12px"><div class="empty">Loading inventory…</div></div>'
    +'<div class="row" style="justify-content:flex-end;gap:8px;margin-top:12px">'
    +'<button class="btn ghost" id="org-prev" disabled>Previous</button><button class="btn ghost" id="org-next" disabled>Next</button></div></div>';
  applyInterfaceLanguage();

  const message=(text,bad)=>{
    const box=$('#org-message');
    if(!box)return;
    if(text){
      box.setAttribute('role',bad?'alert':'status');
      box.setAttribute('aria-live',bad?'assertive':'polite');
      box.setAttribute('aria-atomic','true');
    }else{
      box.removeAttribute('role');box.removeAttribute('aria-live');
    }
    box.innerHTML=text?'<div class="panel-note '+(bad?'panel-warn':'')+'" style="margin:12px 0">'+esc(text)+'</div>':'';
  };
  let lastAnnouncedOrganizerState='';
  const platform=()=>($('#org-platform')||{}).value||'';
  const loadInventory=async()=>{
    if(token!==window._organizeViewToken||location.hash!=='#organize')return null;
    const query=new URLSearchParams({limit:String(limit),offset:String(offset)});
    if(platform())query.set('platform',platform());
    if(reviewOnly)query.set('review','1');
    const [status,data]=await Promise.all([
      j('/api/v1/organizer/status').catch(()=>({state:'unavailable'})),
      j('/api/v1/organizer/items?'+query.toString()).catch(()=>({items:[],total:0,error:'Could not load the inventory.'}))
    ]);
    if(token!==window._organizeViewToken||location.hash!=='#organize')return null;
    const stateLabel={idle:'Ready to scan',scanning:'Scanning',complete:'Scan complete',partial:'Scan reached its safety limit',failed:'Scan failed',unavailable:'Status unavailable'}[status.state]||status.state||'Unknown';
    if(['complete','partial','failed'].includes(status.state)&&lastAnnouncedOrganizerState!==status.state){
      const announcement=$('#org-announcement');
      if(announcement)announcement.textContent=stateLabel+'. '+fmt(status.processed||0)+' of '+fmt(status.total||0)+' files checked.';
    }
    lastAnnouncedOrganizerState=status.state||'';
    $('#org-status').innerHTML='<div class="card"><div class="row" style="align-items:center">'
      +'<b>'+esc(stateLabel)+'</b><span class="help" style="margin:0">'+fmt(status.processed||0)+' / '+fmt(status.total||0)+' files checked</span>'
      +'<span class="help" style="margin:0">DAT verified '+fmt(status.verified||0)+'</span>'
      +'<span class="help" style="margin:0">TitleDB catalogued '+fmt(status.catalogued||0)+'</span>'
      +'<span class="help" style="margin:0">Suggestions '+fmt(status.suggested||0)+'</span>'
      +'<span class="help" style="margin:0">Local ES-DE records reused '+fmt(status.local_metadata_imported||0)+'</span>'
      +'<span class="help" style="margin:0">Unmatched '+fmt(status.unmatched||0)+'</span>'
      +'<span class="help" style="margin:0">Switch versions behind catalog '+fmt(status.switch_outdated||0)+'</span></div>'
      +(status.truncated?'<p class="help" style="margin:8px 0 0">This scan was bounded at 50,000 entries. Filter to a platform and scan again to continue.</p>':'')
      +(status.error?'<p class="help" style="margin:8px 0 0;color:var(--warn)">'+esc(status.error)+'</p>':'')
      +'</div>';
    const items=data.items||[];
    const start=data.total?offset+1:0;
    const end=Math.min(data.total||0,offset+items.length);
    $('#org-page-label').textContent=fmt(start)+'–'+fmt(end)+' of '+fmt(data.total||0);
    $('#org-prev').disabled=offset<=0;
    $('#org-next').disabled=offset+limit>=(data.total||0);
    const target=$('#org-items');
    if(data.error){
      target.innerHTML='<div class="panel-note panel-warn">'+esc(data.error)+'</div>';
    }else if(!items.length){
      target.innerHTML='<div class="empty">No inventory entries yet. Scan a configured ROM library to begin.</div>';
    }else{
      const confidenceLabel={
        dat_verified:'DAT checksum verified',
        title_id_catalog:'TitleDB ID match · bytes unverified',
        provider_suggestion:'Provider suggestion · review',
        local_metadata:'Imported local metadata · review title',
        ambiguous_name:'Ambiguous title · review',
        manual:'Manually confirmed',
        filename_only:'Filename only · review',
        multi_disc:'Likely multi-disc set · review'
      };
      target.innerHTML='<div style="overflow-x:auto"><table><thead><tr>'
        +'<th>Game / evidence</th><th>ROM path</th><th>Switch family</th><th>Metadata</th><th></th>'
        +'</tr></thead><tbody>'+items.map(row=>{
          const sw=row.switch||{};
          const metadata=row.metadata||{};
          const ver=sw.file_version===null||sw.file_version===undefined?'':'v'+esc(sw.file_version)+' / latest '+esc(sw.latest_version||0);
          const switchLine=sw.title_id
            ?'<div lang="und" dir="ltr">'+esc(sw.kind||'title')+' · '+esc(sw.title_id)+'</div>'
              +(sw.base_title?'<div>'+esc(sw.base_title)+'</div>':'')
              +(ver?'<div class="help" style="margin:3px 0">'+ver+' · '+esc(sw.version_status||'unknown')+'</div>':'')
            :'<span class="help">No TitleDB ID</span>';
          const art=row.cover_path
            ?'<img src="/api/v1/organizer/art?identity_id='+encodeURIComponent(row.identity_id||'')+'" alt="" loading="lazy" style="width:42px;height:58px;object-fit:cover;border-radius:4px;vertical-align:middle;margin-inline-end:8px">'
            :'';
          const title=row.canonical_title||row.filename||'Untitled';
          const canMap=row.confidence!=='dat_verified';
          const discGroup=row.disc_group||{};
          const manifestInfo=(row.manifests||[]).map(manifest=>
            '<details style="margin-top:5px"><summary class="help" style="cursor:pointer">'
              +'Manifest '+esc(manifest.path||'')+' · '+fmt((manifest.references||[]).length)+' linked file(s)'
              +'</summary><div class="help" style="margin:4px 0">'+(manifest.references||[]).map(path=>
                '<div lang="und" dir="auto">'+esc(path)+'</div>').join('')+'</div></details>'
          ).join('');
          const pathCell=discGroup.id
            ?'<span class="pill">Likely '+fmt(discGroup.disc_count||0)+'-disc set</span>'
              +(discGroup.manifest_path?'<div class="help" style="margin:4px 0">Playlist: <span lang="und" dir="auto">'+esc(discGroup.manifest_path)+'</span></div>':'')
              +'<div class="help" style="margin:4px 0">'+(discGroup.members||[]).map(member=>
                '<div lang="und" dir="auto">'+esc(member.relative_path||'')+'</div>').join('')+'</div>'
              +manifestInfo
            :'<span lang="und" dir="auto">'+esc(row.relative_path||'')+'</span>'+manifestInfo;
          return '<tr data-identity="'+esc(row.identity_id||'')+'"><td>'+art+'<b>'+esc(title)+'</b>'
            +'<div class="help" style="margin:4px 0">'+esc(confidenceLabel[row.confidence]||row.confidence||'Unknown')+'</div>'
            +'<div class="help" style="margin:0">'+esc(row.match_details||'')+'</div>'
            +(canMap?'<button type="button" class="btn ghost org-map" style="margin-top:7px">Confirm or edit title</button>':'')
            +'</td><td>'+pathCell+'</td><td>'+switchLine+'</td>'
            +'<td>'+esc(metadata.source||'')+(metadata.released?'<div>'+esc(metadata.released)+'</div>':'')
            +(metadata.genres&&metadata.genres.length?'<div>'+esc(metadata.genres.join(', '))+'</div>':'')
            +(metadata.summary?'<div class="help" style="margin:4px 0;max-width:360px">'+esc(String(metadata.summary).slice(0,220))+'</div>':'')
            +(row.metadata_sidecar?'<div class="help" style="margin:4px 0" lang="und" dir="auto">'+esc(row.metadata_sidecar)+'</div>':'')
            +'</td><td>'+(row.cover_path?'<span class="pill">Artwork cached</span>':'')+'</td></tr>';
        }).join('')+'</tbody></table></div>';
      target.querySelectorAll('.org-map').forEach(button=>button.onclick=async()=>{
        const row=button.closest('tr');
        const identity=row&&row.dataset.identity;
        const item=items.find(x=>x.identity_id===identity);
        const title=promptMessage('ui.canonical-game-title.035a3372bf',{},item&&item.canonical_title||'');
        if(title===null)return;
        const result=await j('/api/v1/organizer/map',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({identity_id:identity,title:title,platform:platform()})})
          .catch(()=>({error:'Could not save this mapping.'}));
        if(result.error){message(result.error,true);return;}
        message('Title mapping saved. This game is now eligible for a safe rename preview.',false);
        await loadInventory();
      });
    }
    if(status.state==='scanning'){
      setTimeout(()=>{if(token===window._organizeViewToken&&location.hash==='#organize')loadInventory();},1300);
    }
    return status;
  };

  const startScan=async(force)=>{
    offset=0;
    currentPlan=null;
    nextPlanOffset=0;
    $('#org-plan-result').innerHTML='';
    message(force?'Refreshing provider metadata…':'Starting a read-only library scan…',false);
    const result=await j('/api/v1/organizer/scan',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({platform:platform(),force:!!force})})
      .catch(()=>({error:'Could not start the library scan.'}));
    if(result.error){message(result.error,true);return;}
    await loadInventory();
  };
  $('#org-scan').onclick=()=>startScan(false);
  $('#org-refresh').onclick=()=>startScan(true);
  $('#org-platform').onchange=()=>{offset=0;currentPlan=null;nextPlanOffset=0;$('#org-plan-result').innerHTML='';loadInventory();};
  $('#org-review').onchange=event=>{reviewOnly=event.target.checked;offset=0;loadInventory();};
  $('#org-prev').onclick=()=>{offset=Math.max(0,offset-limit);loadInventory();};
  $('#org-next').onclick=()=>{offset+=limit;loadInventory();};
  const previewPlan=async(planOffset)=>{
    const query=new URLSearchParams({offset:String(planOffset),limit:String(planLimit)});
    if(platform())query.set('platform',platform());
    const plan=await j('/api/v1/organizer/rename-plan?'+query.toString())
      .catch(()=>({error:'Could not create a rename preview.'}));
    currentPlan=plan;
    if(plan.error){message(plan.error,true);$('#org-plan-result').innerHTML='';return;}
    const batch=plan.batch||{offset:planOffset,limit:planLimit,total:0,count:0,has_more:false};
    const first=batch.count?batch.offset+1:0;
    const last=batch.offset+batch.count;
    const rows=(plan.operations||[]).map(op=>'<tr><td lang="und" dir="auto">'+esc(op.from)+'</td><td lang="und" dir="auto">'+esc(op.to)+'</td><td>'+esc(op.reason)+'</td></tr>').join('');
    const blocked=(plan.blocked||[]).map(op=>'<tr><td>'+esc(op.identity_id||'')+'</td><td>'+esc(op.reason||'')+'</td></tr>').join('');
    const safeCount=(plan.operations||[]).length,blockedCount=(plan.blocked||[]).length;
    const planAnnouncement=$('#org-announcement');
    if(planAnnouncement)planAnnouncement.textContent='Rename preview ready. '+fmt(safeCount)+' safe renames in this batch; '+fmt(blockedCount)+' entries left alone.';
    $('#org-plan-result').innerHTML='<div class="card"><h3>Rename preview · '+fmt(first)+'–'+fmt(last)+' of '+fmt(batch.total||0)+'</h3><p class="help">'
      +fmt(safeCount)+' safe rename(s) in this batch. '+fmt(blockedCount)+' matching entries were left alone.'
      +(batch.has_more?' More entries will be reviewed in the next batch.':'')+'</p>'
      +(rows?'<div style="overflow-x:auto"><table><thead><tr><th>Current path</th><th>Proposed path</th><th>Evidence</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'<p class="empty">No safe renames are ready in this batch.</p>')
      +(blocked?'<details style="margin-top:10px"><summary>See blocked items</summary><div style="overflow-x:auto"><table><thead><tr><th>Game</th><th>Reason</th></tr></thead><tbody>'+blocked+'</tbody></table></div></details>':'')
      +(rows?'<button class="btn" id="org-apply" style="margin-top:12px">Apply this batch · '+fmt((plan.operations||[]).length)+'</button>':'')
      +(batch.has_more?'<button class="btn ghost" id="org-next-plan" style="margin:12px 0 0 8px">Preview next batch</button>':'')+'</div>';
    const next=$('#org-next-plan');
    if(next)next.onclick=()=>{
      nextPlanOffset=batch.next_offset;
      previewPlan(nextPlanOffset);
    };
    const apply=$('#org-apply');
    if(apply)apply.onclick=async()=>{
      if(!currentPlan||!confirmMessage('ui.apply-count-safe-file-renames.0f6a5be597',{count:(currentPlan.operations||[]).length}))return;
      const appliedPlan=currentPlan;
      const result=await j('/api/v1/organizer/rename/apply',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({plan_id:appliedPlan.plan_id,platform:platform(),
          offset:batch.offset,limit:batch.limit})})
        .catch(()=>({error:'Could not apply the rename plan.'}));
      if(result.error){message(result.error,true);return;}
      message(result.message||'Rename batch applied.',false);
      currentPlan=null;
      nextPlanOffset=batch.has_more?batch.next_offset:0;
      $('#org-plan-result').innerHTML=batch.has_more
        ?'<div class="card"><span class="help">Batch applied. Continue when ready.</span> <button class="btn ghost" id="org-continue-plan">Preview next batch</button></div>':'';
      const continueButton=$('#org-continue-plan');
      if(continueButton)continueButton.onclick=()=>previewPlan(nextPlanOffset);
      await loadInventory();
    };
  };
  $('#org-plan').onclick=()=>{
    currentPlan=null;
    previewPlan(nextPlanOffset);
  };
  $('#org-undo').onclick=async()=>{
    if(!confirmMessage('ui.undo-the-last-romarr-rename-batch-fi.45e19a3d56'))return;
    const result=await j('/api/v1/organizer/rename/undo',{method:'POST',
      headers:{'Content-Type':'application/json'},body:'{}'})
      .catch(()=>({error:'Could not undo the last rename batch.'}));
    if(result.error){message(result.error,true);return;}
    message('Undid '+fmt(result.undone||0)+' rename(s).',false);
    await loadInventory();
  };
  $('#org-esde').onclick=async()=>{
    if(!platform()){message('Choose one platform before publishing its ES-DE gamelist.',true);return;}
    const result=await j('/api/v1/organizer/publish/esde',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({platform:platform()})})
      .catch(()=>({error:'Could not publish the ES-DE gamelist.'}));
    if(result.error){message(result.error,true);return;}
    message(result.message||('Published '+fmt(result.games||0)+' ES-DE entries.'),!result.written);
  };
  await loadInventory();
};

RENDER.manualimport=async()=>{
  $('#page').innerHTML='<div class="card"><h3>'+interfaceMarkup('ui.manual-import.3b797ce5ae')+'</h3>'
    +'<p class="help">'+interfaceMarkup('ui.point-romarr-at-a-directory-you-alre.d86d82c97a')+'</p>'
    +'<label for="mipath">'+interfaceMarkup('ui.path.62fa5a5b0d')+'</label>'
    +'<div class="row"><input id="mipath" lang="und" dir="auto" placeholder="/downloads/roms" '
    +'style="flex:1;padding:8px 12px;background:var(--bg);color:var(--fg);'
    +'border:1px solid var(--line);border-radius:6px">'
    +'<button class="btn" id="miscan">'+interfaceMarkup('ui.scan.ea1c510d1d')+'</button></div>'
    +'<div id="mires" style="margin-top:14px"></div></div>';

  const opts=sel=>PLATFORMS.map(p=>'<option value="'+esc(p.slug)+'"'
      +(p.slug===sel?' selected':'')+' lang="und" dir="auto">'+esc(p.name)+'</option>').join('');

  // The distinction the whole page turns on. UNKNOWN means "not in the DAT you
  // loaded" -- normal for homebrew, translations and anything newer than your
  // DAT -- and must never be presented as a problem. Only a bad dump is.
  const verdict=v=>v==='verified'
    ? '<span class="pill" style="background:var(--ok);color:var(--ok-ink)">'+interfaceMarkup('ui.verified.1c34f88707')+'</span>'
    : v==='bad-dump'
      ? '<span class="pill" style="background:var(--bad);color:var(--bad-ink)">'+interfaceMarkup('ui.bad-dump.f6b69d9a48')+'</span>'
      : '<span class="pill" data-i18n-title="ui.not-in-your-dat-often-perfectly-fine.d3400979d9" title="'+esc(translateLabel('ui.not-in-your-dat-often-perfectly-fine.d3400979d9',readInterfaceLanguage()))+'">'+interfaceMarkup('ui.unknown.b23a6a8439')+'</span>';

  async function adopt(row, force){
    const btn=row.querySelector('.mi-go');
    const st=row.querySelector('.mi-st');
    btn.disabled=true; st.innerHTML=interfaceMarkup('ui.importing.c01c4324f1');
    const d=await j('/api/v1/manualimport',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:row.dataset.path,
        platform:row.querySelector('.mi-pf').value, force:!!force})})
      .catch(()=>({ok:false,refused:[{reason:'Could not reach ROMarr.'}]}));

    if(d.ok){
      const one=d.imported[0]||{};
      st.innerHTML=one.forced
        ? '<span style="color:var(--warn)">'+interfaceMarkup('ui.imported-forced.7aa8747d10')+'</span>'
        : '<span style="color:var(--ok)">'+interfaceMarkup('ui.imported.5f54227b74')+'</span>';
      btn.remove();
      row.querySelector('.mi-pf').disabled=true;
      return;
    }
    const bad=(d.refused||[])[0]||{};
    st.innerHTML='<span style="color:var(--bad)">'+appMessageMarkup(bad.reason||'refused')+'</span>';
    btn.disabled=false;
    if(bad.needs_force){
      // Never a silent reinterpretation: forcing is a second, separate act,
      // and the button says exactly what it does.
      btn.innerHTML=interfaceMarkup('ui.import-anyway.e06eac7e79');
      btn.style.background='var(--bad)';
      btn.onclick=()=>{
        if(confirmMessage('ui.this-file-did-not-match-a-known-dump.b8f424cb01')) adopt(row,true);
      };
    }
  }

  $('#miscan').onclick=async()=>{
    const out=$('#mires');
    out.innerHTML='<div class="empty">'+interfaceMarkup('ui.scanning.38d96da6e8')+'</div>';
    const d=await j('/api/v1/manualimport?path='
      +encodeURIComponent($('#mipath').value)).catch(()=>({error:'scan failed'}));
    if(d.error){out.innerHTML='<div class="panel-note panel-warn">'+appMessageMarkup(d.error)+'</div>';return;}
    const c=d.candidates||[];
    out.innerHTML='<p class="help">'+interfaceTemplateMarkup('ui.importable-importable-skipped-skippe.7567d58f0d',
      {importable:fmt(c.length),skipped:fmt(d.skipped||0)})+'</p>'
      +(c.length
        ?'<div class="row" style="margin-bottom:10px">'
         +'<button class="btn ghost" id="miall">'+interfaceMarkup('ui.import-everything-verified.400d049ae1')+'</button></div>'
         +'<table><thead><tr><th>'+interfaceMarkup('ui.file.50009ce1da')+'</th><th>'+interfaceMarkup('ui.platform.c78ffe1957')+'</th><th>'+interfaceMarkup('ui.why.d3ae14a50b')+'</th>'
         +'<th lang="en" dir="ltr">DAT</th><th></th><th></th></tr></thead><tbody>'
         +c.slice(0,200).map(x=>'<tr data-path="'+esc(x.path||'')+'" '
           +'data-verdict="'+esc(x.verdict)+'">'
           +'<td><span lang="und" dir="auto">'+esc(x.filename)+'</span></td>'
           +'<td><select class="mi-pf">'+opts(x.platform)+'</select></td>'
           +'<td class="help" style="margin:0">'+appMessageMarkup(x.reason)+'</td>'
           +'<td>'+(x.hollow?'<span class="pill" lang="und" dir="auto" style="background:var(--bad);color:var(--bad-ink)" '+manualDiagnosticTitle(x.hollow)+'>'+interfaceMarkup('ui.empty-file.0045fa2e36')+'</span><br>':'')+verdict(x.verdict)+(x.header_says?'<br><span class="pill" lang="und" dir="auto" style="background:var(--warn);color:var(--warn-ink)" '+manualDiagnosticTitle(x.header_detail||'')+'>'+interfaceMarkup('ui.header-says.b5143b147b')+' <span lang="und" dir="auto">'+esc(x.header_says)+'</span></span>':'')+'</td>'
           +'<td><button class="btn mi-go">'+interfaceMarkup('ui.import.2cff9baabf')+'</button></td>'
           +'<td class="mi-st help" style="margin:0"></td></tr>').join('')
         +'</tbody></table>'
        :'<div class="empty-cat"><b>'+interfaceMarkup('ui.nothing-importable-there.b81b7140c5')+'</b>'
         +interfaceMarkup('ui.check-the-path-or-that-the-files-car.64b175ddee')+'</div>');

    out.querySelectorAll('tbody tr').forEach(row=>{
      const btn=row.querySelector('.mi-go');
      if(btn) btn.onclick=()=>adopt(row,false);
    });
    const all=out.querySelector('#miall');
    if(all) all.onclick=async()=>{
      all.disabled=true;
      // Verified only. A bulk button that also forced bad dumps would be a
      // way to override verification without ever deciding to.
      for(const row of out.querySelectorAll('tbody tr[data-verdict="verified"]')){
        if(row.querySelector('.mi-go')) await adopt(row,false);
      }
      all.disabled=false;
    };
  };
};


RENDER.tasks=async()=>{
  const d=await j('/api/v1/system/tasks').catch(()=>({items:[]}));
  const every=s=>!s?interfaceMarkup('ui.off.ca7981b46e')
    :s%3600===0?interfaceTemplateMarkup('ui.interval-count-h.c4dc89c3ad',{count:fmt(s/3600)})
    :s%60===0?interfaceTemplateMarkup('ui.interval-count-min.f79e014946',{count:fmt(s/60)})
    :interfaceTemplateMarkup('ui.interval-count-s.9f62c9a61f',{count:fmt(s)});
  const scheduled=(d.items||[]).map(t=>[t.name,t.label,t]);
  const manualOnly=[['RefreshLibrary','Re-read the library from RomM',null],
    ['Decompress','Batch decompress the library: extract via Compressatorium, '
     +'verify every output against the DATs. Originals are deleted only when '
     +'they verified AND the API call asked for deletion — this button never '
     +'deletes. Needs COMPRESSATORIUM_URL and decompress_path set in '
     +'settings.',null]];
  $('#page').innerHTML=`<div class="card"><h3 data-i18n="ui.tasks.b3a60e61a5">Tasks</h3>
    <p class="help" data-i18n="ui.the-service-runs-these-on-its-own-cl.4c7ec09277">The service runs these on its own clock &mdash; intervals live
      under Settings &rarr; General. Run starts one now regardless.</p>
    <table><thead><tr><th data-i18n="ui.task.4bc74b2135">Task</th><th data-i18n="ui.schedule.f4830a1dae">Schedule</th><th data-i18n="ui.last-ran.2e024dc014">Last ran</th>
      <th data-i18n="ui.result.6e7d50e84f">Result</th><th></th></tr></thead><tbody>
    ${scheduled.concat(manualOnly).map(([n,label,t])=>{
      const source=n==='RefreshLibrary'?'Refresh library':n==='Decompress'?'Decompress':null;
      const nameMarkup=source?interfaceMarkup(source):'<span lang="und" dir="auto">'+esc(n)+'</span>';
      const detailMarkup=label?(hasLabel(label)?interfaceMarkup(label):'<span lang="und" dir="auto">'+esc(label)+'</span>'):'';
      const result=t&&t.last_error?`<span lang="und" dir="auto" style="color:var(--warn)">${esc(t.last_error)}</span>`
        :t&&t.last_result?statusMarkup(t.last_result):'—';
      return `<tr><td><b>${nameMarkup}</b>
      <div style="color:var(--dim);font-size:12px">${detailMarkup}</div></td>
      <td>${t?every(t.interval_seconds):interfaceMarkup('ui.manual-only.be1016ce6d')}</td>
      <td style="color:var(--dim)">${t&&t.last_run?esc(regionalDateTime(t.last_run)):'—'}</td>
      <td style="color:var(--dim);font-size:12px">${result}</td>
      <td style="text-align:end"><button class="btn ghost" data-task="${esc(n)}" data-i18n="ui.run.00d60e31a4">Run</button></td>
      </tr>`;
    }).join('')}</tbody></table></div>`;
  document.querySelectorAll('[data-task]').forEach(b=>b.onclick=async()=>{
    b.disabled=true; b.innerHTML=interfaceMarkup('ui.running.46c541363b');
    // Decompress from the Tasks page is always a dry run: extraction is
    // minutes-to-hours of service work and a mis-click must not start it on
    // the whole library. The real run is an API call with an explicit
    // directory -- and only that call can authorise deletion.
    const body={name:b.dataset.task};
    if(b.dataset.task==='Decompress') body.dry_run=true;
    const r=await j('/api/v1/command',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify(body)});
    if(r.message)toastAppMessage(r.message);
    else if(r.scanned!==undefined)toastMessage('ui.scanned-count-dry-run.442c1ab947',{count:fmt(r.scanned)});
    else toastLabel('ui.done.11a6767d56');
    go('tasks'); refreshCounts();
  });
};

let LOG_TIMER=null;
RENDER.logs=async()=>{
  clearInterval(LOG_TIMER);
  $('#page').innerHTML=`<div class="card"><h3 data-i18n="ui.live-log.2cfbcb2b85">Live log</h3>
    <p class="help" data-i18n="ui.the-process-log-tailed-live-the-same.5513bb02d0">The process log, tailed live — the same lines journalctl
      or docker logs would show. Events (grabs, imports) stay under
      Activity &rarr; History.</p>
    <div class="row" style="margin-bottom:10px">
      <select id="lg-level">
        <option value="" data-i18n="ui.everything.75304cf77d">Everything</option>
        <option value="INFO" selected data-i18n="ui.info-and-up.c9f2eef041">Info and up</option>
        <option value="WARNING" data-i18n="ui.warnings-and-up.a96eb0f7ce">Warnings and up</option>
        <option value="ERROR" data-i18n="ui.errors-only.30767c1658">Errors only</option>
      </select>
      <label class="check" style="margin:0"><input type="checkbox" id="lg-follow"
        checked><span data-i18n="ui.follow.641d1ef657">Follow</span></label>
    </div>
    <pre id="lg-out" style="font:12px/1.6 ui-monospace,Menlo,monospace;
      color:var(--dim);white-space:pre-wrap;max-height:70vh;overflow:auto"></pre></div>`;
  let since=0;
  const paint=rows=>{
    if(!rows.length) return;
    const out=$('#lg-out'); if(!out) return;
    out.textContent+=rows.map(r=>
      `${regionalDateTime(r.at)}  ${r.level.padEnd(7)} ${r.name}  ${r.message}`)
      .join('\n')+'\n';
    if($('#lg-follow')?.checked) out.scrollTop=out.scrollHeight;
  };
  const pull=async()=>{
    if(!$('#lg-out')){clearInterval(LOG_TIMER);return;}
    const level=$('#lg-level').value;
    const d=await j(`/api/v1/log/tail?since=${since}&level=${level}`).catch(()=>null);
    if(!d) return;
    paint(d.items||[]); since=d.latest||since;
  };
  $('#lg-level').onchange=()=>{since=0;$('#lg-out').textContent='';pull();};
  await pull();
  LOG_TIMER=setInterval(pull,2000);
};

/* ---------------- theme control ---------------- */
/* The mode and the accent are already applied by the head script -- all that
   is left here is wiring the buttons and keeping them showing the truth. */
function paintTheme(){
  const mode=ROMTHEME.mode(), accent=ROMTHEME.accent().toLowerCase();
  document.querySelectorAll('[data-theme-set]').forEach(b=>{
    const selected=b.dataset.themeSet===mode;
    b.classList.toggle('on',selected);
    b.setAttribute('aria-pressed',String(selected));
  });
  document.querySelectorAll('[data-accent]').forEach(b=>{
    const selected=b.dataset.accent.toLowerCase()===accent;
    b.classList.toggle('on',selected);
    b.setAttribute('aria-pressed',String(selected));
  });
  const pick=$('#accent-pick'); if(pick) pick.value=accent;
}
function bindTheme(){
  document.documentElement.addEventListener('themechange',paintTheme);
  document.querySelectorAll('[data-theme-set]').forEach(b=>b.onclick=()=>
    ROMTHEME.set(b.dataset.themeSet,null));
  document.querySelectorAll('[data-accent]').forEach(b=>b.onclick=()=>
    ROMTHEME.set(null,b.dataset.accent));
  const pick=$('#accent-pick');
  // `input` rather than `change`: the OS colour picker is a live preview, and
  // waiting for it to be dismissed makes the whole control feel broken.
  if(pick) pick.oninput=()=>ROMTHEME.set(null,pick.value);
  paintTheme();
}

/* ---------------- boot ---------------- */
async function refreshCounts(){
  const s=await j('/api/v1/system/counts').catch(()=>({}));
  document.querySelectorAll('[data-ct]').forEach(b=>{
    const v=s[b.dataset.ct];
    // null means "not counted yet" -- a dash is honest where 0 would claim
    // the library is empty.
    b.textContent = v == null ? (b.dataset.ct === 'games' ? '—' : '') : (v ? fmt(v) : '');
    b.style.display = (v == null && b.dataset.ct !== 'games') ? 'none' : '';
    // The games badge is a sum of two unlike things on any library that
    // catalogues entries it does not hold. It stays a sum -- a badge that
    // renumbered itself would read as data loss -- but it no longer keeps
    // that to itself.
    if(b.dataset.ct === 'games' && s.games_catalogued){
      const source='On disk: {disk} · Catalogued elsewhere: {catalogued}';
      const values={disk:fmt(s.games_on_disk),catalogued:fmt(s.games_catalogued)};
      b.dataset.i18nTitleTemplate=source;
      b.dataset.i18nTitleValues=JSON.stringify(values);
      b.title=translateTemplate(source,values,readInterfaceLanguage());
    }
  });
}
(async()=>{
  document.querySelectorAll('.nav').forEach(n=>n.onclick=()=>{
    if(location.hash==='#'+n.dataset.page)go(n.dataset.page,true);
  });
  const navToggle=$('#nav-toggle'),navBackdrop=$('#nav-backdrop');
  navToggle.onclick=()=>setMobileNavOpen(true);
  navBackdrop.onclick=()=>setMobileNavOpen(false);
  window.addEventListener('resize',()=>{
    if(window.innerWidth>680)setMobileNavOpen(false,false);
  });
  const languageSelect=$('#interface-language');
  if(languageSelect){
    languageSelect.addEventListener('change',()=>{
      const preference=languageSelect.value;
      if(preference==='system'){
        try{localStorage.removeItem(INTERFACE_LANGUAGE_KEY);}catch(_){}
        activeInterfaceLanguage=null;
        applyInterfaceLanguage(browserInterfaceLanguage());
        return;
      }
      try{localStorage.setItem(INTERFACE_LANGUAGE_KEY,preference);activeInterfaceLanguage=null;}
      catch(_){activeInterfaceLanguage=preference;}
      applyInterfaceLanguage(preference);
    });
  }
  window.addEventListener('languagechange',()=>{
    if(readInterfacePreference()==='system')applyInterfaceLanguage(browserInterfaceLanguage());
  });
  window.addEventListener('storage',event=>{
    if(event.key!==INTERFACE_LANGUAGE_KEY&&event.key!==null)return;
    activeInterfaceLanguage=null;
    applyInterfaceLanguage();
  });
  applyInterfaceLanguage();
  bindTheme();
  let searchTimer=null;
  $('#search').oninput=()=>{const p=location.hash.slice(1)||'library';
    if(p!=='library') return;
    // Debounced: the search is server-side now, and a request per
    // keystroke over 166k rows is rude to everyone involved.
    LIB.offset=0; LIB.limit=120;
    clearTimeout(searchTimer);
    searchTimer=setTimeout(()=>RENDER.library(),250);};
  [PLATFORMS,SETTINGS]=await Promise.all([
    j('/api/platforms').catch(()=>[]), j('/api/v1/config').catch(()=>({}))]);
  const requestedPage=location.hash.slice(1), requestedBase=requestedPage.split('/')[0];
  const initialPage=(requestedBase==='game'||requestedBase==='search'||document.querySelector('.nav[data-page="'+CSS.escape(requestedBase)+'"]'))
    ?requestedPage:'library';
  if(location.hash!=='#'+initialPage)history.replaceState(null,'','#'+initialPage);
  go(initialPage);
  refreshCounts(); setInterval(refreshCounts,15000);
})();
""".replace("__UI_CATALOG__", UI_CATALOG_JSON) \
    .replace("__INTERFACE_LANGUAGES__", json.dumps(UI_AVAILABLE_LOCALES, ensure_ascii=False)) \
    .replace("__REGIONAL_FORMATS__", json.dumps([
        [tag, f'{item["nativeName"]} — {item["englishName"]}']
        for tag, item in UI_LOCALE_OPTIONS.items()
    ], ensure_ascii=False))


def page() -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>ROMarr</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style><script>{THEME_BOOT}</script></head><body>
<a class="skip-link" href="#main-content" data-i18n-key="ui.skip-to-content.ac576a66d4">Skip to content</a>
<aside id="rail" aria-label="ROMarr sidebar">
  <div id="brand">ROM<span>arr</span></div>
  <nav id="navwrap" aria-label="Main navigation">{_nav_html()}</nav>
  {_theme_control_html()}
</aside>
<button id="nav-backdrop" class="nav-backdrop" type="button" aria-label="Close navigation" data-i18n-aria-label="ui.close-navigation.99904db30d" hidden></button>
<div id="app-announcement" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>
<main id="main-content" tabindex="-1">
  <header id="top"><button id="nav-toggle" class="nav-toggle" type="button"
    aria-controls="navwrap" aria-expanded="false" aria-label="Open navigation" data-i18n-aria-label="ui.open-navigation.0ed77fd261" data-i18n-key="ui.menu.99af6606ff">Menu</button>
    <h1 id="page-title" tabindex="-1" data-i18n="ui.games.d9dae78103">Games</h1>
    <label class="sr-only" for="search" data-i18n-key="ui.filter-games.32633ce2ef">Filter games</label>
    <input id="search" data-i18n-placeholder="ui.filter.be331aa8d8" placeholder="Filter…"
      aria-label="Filter games" data-i18n-aria-label="ui.filter-games.32633ce2ef" autocomplete="off" lang="und" dir="auto"></header>
  <div class="page" id="page"></div>
</main>
<script>{I18N_RUNTIME}</script><script>{JS}</script></body></html>"""


# ------------------------------------------------------------ the door in --
#
# The API gate was built before the door. Every page of the UI loaded, and then
# every request it made came back 401, because a browser had no way to present
# a credential and no screen on which to offer one -- and the log line telling
# the operator to look under Settings pointed at a page that was itself 401ing.
# That is issue #8: an install that looks like it works and cannot be used.
#
# Two states, because a fresh install has nobody in it yet:
#
#   setup  -- nothing has claimed this install. The first visitor sets the
#             password. This is how Jellyfin, Gitea, Nextcloud and Authentik
#             all bootstrap, and it beats printing a secret into the log where
#             it stays forever and gets pasted into bug reports.
#   signin -- somebody has. Password, or an API key for anyone who kept one.
#
# An operator who does not want an unclaimed window at all sets ROMARR_PASSWORD
# or ROMARR_API_KEY in their template, and never sees the setup screen.

LOGIN_CSS = """
/* The stored mode and accent reach this screen too -- it is served before any
   of the app is, so a door in the wrong colours is the first thing an operator
   who chose light mode would see. */
body{display:flex;align-items:center;justify-content:center;min-height:100vh;
  padding:20px;
  background:radial-gradient(1100px 620px at 50% -10%,
    var(--accent-softer),transparent 70%),var(--bg)}
.box{width:100%;max-width:390px;background:var(--surface);
  border:1px solid var(--line);border-radius:var(--r-lg);padding:30px;
  box-shadow:var(--shadow-2),var(--edge)}
.box h1{display:flex;gap:0;font-size:26px;font-weight:700;letter-spacing:-.03em;
  justify-content:center;margin-bottom:6px}
.box h1 span{color:var(--accent-text)}
.box .sub{text-align:center;color:var(--dim);font-size:13px;margin-bottom:24px}
.box label{display:block;font-size:10.5px;font-weight:600;color:var(--dim);
  margin:15px 0 6px;text-transform:uppercase;letter-spacing:.08em}
.box input{width:100%;padding:10px 13px;background:var(--bg);color:var(--fg);
  border:1px solid var(--line);border-radius:var(--r-sm);outline:none;
  font-size:14px;transition:border-color var(--t),box-shadow var(--t)}
.box input:focus{border-color:var(--accent-line);box-shadow:var(--ring)}
.box button{width:100%;margin-top:22px;padding:11px;background:var(--accent);
  color:var(--accent-ink);border:0;border-radius:var(--r-sm);font-size:14px;
  font-weight:600;cursor:pointer;transition:filter var(--t),box-shadow var(--t)}
.box button:hover{filter:brightness(1.07);box-shadow:var(--shadow-1)}
.box button:disabled{opacity:.6;cursor:default;filter:none}
.note{margin-top:20px;padding:12px 14px;background:var(--bg);
  border:1px solid var(--line-soft);border-inline-start:3px solid var(--info);
  border-radius:var(--r-sm);color:var(--dim);font-size:12px;line-height:1.65}
.err{margin-top:16px;padding:11px 13px;border-radius:var(--r-sm);font-size:13px;
  background:color-mix(in srgb,var(--bad) 14%,transparent);
  border:1px solid color-mix(in srgb,var(--bad) 45%,transparent);
  color:var(--bad);display:none}
.err.on{display:block}
.alt{margin-top:16px;text-align:center;font-size:12px;color:var(--dim)}
.alt a{cursor:pointer}
.oidc-login{display:block;margin-top:16px;padding:10px 12px;text-align:center;
  border:1px solid var(--line);border-radius:var(--r-sm);color:var(--fg);
  text-decoration:none;font-size:13px;font-weight:600}
.oidc-login:hover{border-color:var(--accent-line);background:var(--bg)}
.oidc-login{display:flex;align-items:center;justify-content:center;gap:9px}
.oidc-provider-help{display:block;margin-top:8px;text-align:center;color:var(--dim);font-size:12px}
.public-language{position:fixed;top:14px;inset-inline-end:14px;z-index:5;
  display:flex;align-items:center;gap:8px;padding:8px 10px;
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r-sm);
  color:var(--dim);font-size:12px}
.public-language select{max-width:190px;padding:5px;background:var(--bg);
  color:var(--fg);border:1px solid var(--line);border-radius:4px}
@media(max-width:420px){.box{padding:24px 20px}}
"""

PUBLIC_I18N_JS = r"""
(()=>{
const catalog=__UI_CATALOG__,core=window.ROMarrI18n,key='romarrng.interface-language';
const languages=catalog.availableLocales.map(code=>[code,catalog.locales[code].nativeName]);
const detect=()=>core.resolveLocale(navigator.languages?.length?navigator.languages:[navigator.language],catalog,catalog.availableLocales);
const preference=()=>{try{const value=localStorage.getItem(key);return value&&catalog.availableLocales.includes(value)?value:'system'}catch(_){return'system'}};
let active=preference()==='system'?detect():preference();
const lookup=source=>core.lookup(catalog,source,active);
const translate=source=>core.translate(catalog,source,active);
const messageInfo=(source,values={})=>{const found=lookup(source);return{text:core.formatMessage(found.value,values,active,undefined,(nested,args)=>message(nested,args)),translated:found.translated,locale:found.locale}};
const message=(source,values={})=>messageInfo(source,values).text;
const has=source=>lookup(source).key!==null;
const localized=source=>lookup(source).translated;
const sources=new WeakMap();
const text=(node)=>{const parent=node.parentElement;if(!parent||parent.closest('script,style,textarea,input,select,code,[contenteditable="true"],[lang="und"],[data-i18n],[data-i18n-key]'))return;const source=sources.get(node)||node.data.replace(/\s+/g,' ').trim();if(!has(source))return;sources.set(node,source);const left=node.data.match(/^\s*/)?.[0]||'',right=node.data.match(/\s*$/)?.[0]||'',value=left+translate(source)+right;if(value!==node.data)node.data=value;parent.lang=localized(source)?active:'en';parent.dir=localized(source)&&core.isRTL(active,catalog)?'rtl':'ltr'};
const tree=root=>{if(root.nodeType===Node.TEXT_NODE){text(root);return}const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);while(walker.nextNode())text(walker.currentNode)};
const apply=()=>{document.documentElement.lang=active;document.documentElement.dir=core.isRTL(active,catalog)?'rtl':'ltr';document.querySelectorAll('[data-i18n],[data-i18n-key]').forEach(el=>{const source=el.dataset.i18nKey||el.dataset.i18n,done=localized(source);el.textContent=translate(source);el.lang=done?active:'en';el.dir=done&&core.isRTL(active,catalog)?'rtl':'ltr'});document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{const source=el.dataset.i18nPlaceholder,done=localized(source);el.placeholder=translate(source);el.lang=done?active:'en';el.dir=done&&core.isRTL(active,catalog)?'rtl':'ltr'});for(const [marker,attribute] of [['data-i18n-aria-label','aria-label'],['data-i18n-title','title']])document.querySelectorAll('['+marker+']').forEach(el=>{const source=el.getAttribute(marker),done=localized(source);el.setAttribute(attribute,translate(source));el.lang=done?active:'en';el.dir=done&&core.isRTL(active,catalog)?'rtl':'ltr'});tree(document.body);const selector=document.querySelector('#public-language-select');if(selector)selector.value=preference();document.title=translate(document.body.dataset.title||'ROMarr')+' · ROMarr'};
const picker=document.querySelector('#public-language-select');if(picker){picker.innerHTML='<option value="system" data-i18n-key="ui.use-browser-settings.02d22d3f39">Use browser settings</option>'+languages.map(([code,name])=>'<option value="'+code+'" lang="'+code+'" dir="'+(core.isRTL(code,catalog)?'rtl':'ltr')+'">'+name+'</option>').join('');picker.value=preference();picker.addEventListener('change',()=>{try{if(picker.value==='system')localStorage.removeItem(key);else localStorage.setItem(key,picker.value)}catch(_){}active=picker.value==='system'?detect():picker.value;apply()})}
const api=Object.assign({},core,{translate,message,messageInfo,has,apply,
  isRTLForLocale:locale=>core.isRTL(locale,catalog)});
Object.defineProperty(api,'language',{get:()=>active});
window.ROMarrI18n=api;
apply();
new MutationObserver(records=>{for(const record of records){if(record.type==='characterData')text(record.target);for(const node of record.addedNodes)tree(node)}}).observe(document.body,{subtree:true,childList:true,characterData:true});
window.addEventListener('languagechange',()=>{if(preference()==='system'){active=detect();apply()}});
window.addEventListener('storage',event=>{if(event.key!==key&&event.key!==null)return;active=preference()==='system'?detect():preference();apply()});
})()
""".replace("__UI_CATALOG__", UI_CATALOG_JSON)


def _public_language_picker() -> str:
    return ('<div class="public-language"><label for="public-language-select" '
            'data-i18n-key="ui.interface-language.8027f432a7">Interface language</label>'
            '<select id="public-language-select" aria-label="Interface language" '
            'data-i18n-aria-label="ui.interface-language.8027f432a7"></select></div>')


def login_page(*, claimed: bool, totp: bool = False,
               oidc_enabled: bool = False, oidc_failed: bool = False,
               oidc_provider: str = "generic") -> str:
    """The sign-in screen, or the first-run claim screen.

    Server-rendered and served unauthenticated, because the whole failure was
    a browser with no way to obtain a credential.
    """
    if claimed:
        title, action = "Sign in", "Sign in"
        if oidc_enabled:
            from .oidc import oidc_provider_presentation
            provider_label, provider_icon, provider_setup_url = (
                oidc_provider_presentation(oidc_provider)
            )
            oidc_entry = (
                '<a class="oidc-login" href="/auth/oidc/login">'
                '<svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18">'
                f'<use href="/oidc-provider-icons.svg#oidc-{provider_icon}"></use></svg>'
                f'Continue with {provider_label}</a>'
                f'<a class="oidc-provider-help" href="{provider_setup_url}" '
                f'aria-label="{provider_label} identity provider setup guide (opens in a new tab)" '
                'target="_blank" rel="noopener noreferrer">'
                f'Setup guide for {provider_label} <span aria-hidden="true">↗</span></a>'
            )
        else:
            oidc_entry = ""
        oidc_error = ("Single sign-on failed. Check the provider and account access, "
                      "then try again." if oidc_failed else "")
        fields = """
  <label for="password">Password</label>
  <input id="password" type="password" autocomplete="current-password" autofocus>
""" + ("""
  <label for="totp">Two-factor code</label>
  <input id="totp" inputmode="numeric" autocomplete="one-time-code"
         placeholder="000000">
""" if totp else "") + """
  <div class="alt"><a id="usekey">Use an API key instead</a></div>
  <div id="keyrow" style="display:none">
    <label for="apikey">API key</label>
    <input id="apikey" type="password" autocomplete="off">
  </div>
"""
        note = ("Lost the password? Set ROMARR_API_KEY in the container’s "
                "environment and restart, then sign in with it.")
    else:
        title, action = "Set your password", "Create password"
        oidc_entry = ""
        oidc_error = ""
        fields = """
  <label for="password">New password</label>
  <input id="password" type="password" autocomplete="new-password"
         minlength="8" autofocus>
  <label for="confirm">Confirm password</label>
  <input id="confirm" type="password" autocomplete="new-password" minlength="8">
"""
        note = ("Nobody has claimed this ROMarr yet, so this screen is open. "
                "Set the password now. To skip this step on future installs, "
                "put ROMARR_PASSWORD in your container environment.")

    title_key = _ui_key(title)
    note_key = _ui_key(note)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)} &middot; ROMarr</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}{LOGIN_CSS}</style><script>{THEME_BOOT}</script></head><body data-title="{html.escape(title_key, quote=True)}">
{_public_language_picker()}
<form class="box" id="f" autocomplete="on">
  <h1>ROM<span>arr</span></h1>
  <div class="sub" data-i18n-key="{html.escape(title_key, quote=True)}">{html.escape(title)}</div>
  {fields}
  <button type="submit" id="go">{action}</button>
  <div class="err{' on' if oidc_error else ''}" id="err" role="alert" aria-live="assertive">{oidc_error}</div>
  {oidc_entry}
  <div class="note" data-i18n-key="{html.escape(note_key, quote=True)}">{html.escape(note)}</div>
</form>
<script>{I18N_RUNTIME}</script><script>{PUBLIC_I18N_JS}</script>
<script>
var claimed = {str(bool(claimed)).lower()};
var f = document.getElementById('f'), err = document.getElementById('err'),
    go = document.getElementById('go');
var keylink = document.getElementById('usekey');
if (keylink) keylink.onclick = function() {{
  document.getElementById('keyrow').style.display = 'block';
  keylink.parentNode.style.display = 'none';
  document.getElementById('apikey').focus();
}};
function fail(m, raw) {{
  var localized = raw ? null :
    (m && typeof m === 'object' && typeof m.text === 'string'
      ? m : window.ROMarrI18n.messageInfo(m));
  err.textContent = raw ? String(m) : localized.text;
  err.lang = raw ? 'und' : (localized.translated ? localized.locale : 'en');
  err.dir = raw ? 'auto' : (localized.translated
    && window.ROMarrI18n.isRTLForLocale(localized.locale) ? 'rtl' : 'ltr');
  err.className = 'err on'; go.disabled = false;
  go.textContent = window.ROMarrI18n.translate(claimed ? 'Sign in' : 'Create password');
}}
f.onsubmit = async function(e) {{
  e.preventDefault();
  err.className = 'err';
  var pw = document.getElementById('password').value;
  var body, url;
  if (claimed) {{
    var keyEl = document.getElementById('apikey');
    var key = keyEl ? keyEl.value : '';
    var totpEl = document.getElementById('totp');
    url = '/api/v1/login';
    body = {{password: pw, apikey: key, totp: totpEl ? totpEl.value : ''}};
  }} else {{
    var confirmEl = document.getElementById('confirm');
    if (pw.length < 8) return fail('Use at least 8 characters.');
    if (pw !== confirmEl.value) return fail('The two passwords do not match.');
    url = '/api/v1/setup';
    body = {{password: pw}};
  }}
  go.disabled = true; go.textContent = 'Working…';
  try {{
    var r = await fetch(url, {{method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body)}});
    if (r.ok) {{ location.href = '/'; return; }}
    var d = {{}};
    try {{ d = await r.json(); }} catch (_) {{}}
    var detail = d.detail || d.error;
    if (d.error === 'weak password') {{
      var minimum = (String(detail || '').match(/\\d+/) || [])[0] || '8';
      fail(window.ROMarrI18n.messageInfo('Use at least {{count}} characters.',
        {{count:minimum}}));
    }} else if (detail) fail(detail, !window.ROMarrI18n.has(detail));
    else fail(window.ROMarrI18n.messageInfo('Refused (HTTP {{status}}).', {{status:r.status}}));
  }} catch (_) {{ fail('Could not reach ROMarr.'); }}
}};
</script></body></html>"""


# ------------------------------------------------------ the invitation link --
#
# Where a peering invitation lands, and the one page in ROMarr written for
# somebody who does not have an account here.
#
# Alice sends Bob a link. Bob clicks it and his browser goes to ALICE'S server,
# because Alice's address is the only address Alice knows. That is the whole
# difficulty with a Plex-style link in a system with no central anything:
# plex.tv/link works because plex.tv exists, and nothing here is allowed to. So
# this page's job is to hand Bob back to his own ROMarr, which it does by
# rewriting the same path and the same fragment onto the host he types once.
#
# The invariant that lets the page know which of the two servers it is running
# on: `u` appears in the fragment ONLY on a link that has been rehomed. No `u`
# means this is the inviter's server and there is nowhere to forward to. A `u`
# means the visitor is home, and the page hands the invitation to the app.
#
# Nothing here is a secret. The fragment carries an invitation id and a display
# name, and a browser never sends a fragment to any server -- so this page is
# reached, in the log, as a bare GET /link with no query and no referrer trail.
# The credential is the claim code, which travels by whatever channel the two
# of them chose and is typed in on the far side.

LINK_CSS = """
.box{max-width:460px}
.box .who{font-size:15px;font-weight:600;text-align:center;margin-bottom:4px}
.box .id{font:12px/1.5 ui-monospace,Menlo,monospace;color:var(--dim);
  text-align:center;word-break:break-all;margin-bottom:18px}
.box .step{display:flex;gap:10px;align-items:flex-start;margin:14px 0;
  font-size:13px;color:var(--dim);line-height:1.6}
.box .step b{display:flex;align-items:center;justify-content:center;
  flex:0 0 20px;height:20px;border-radius:50%;background:var(--surface-3);
  color:var(--fg);font-size:11px;margin-top:1px}
.box .copy{width:100%;margin-top:10px;padding:9px;background:transparent;
  color:var(--fg);border:1px solid var(--line);border-radius:4px;
  font-size:13px;cursor:pointer}
.box code{font:12px/1.6 ui-monospace,Menlo,monospace;word-break:break-all}
"""

#: Plain, uninterpolated: this script has regular expressions and apostrophes
#: in it, and every one of them is a chance for an f-string to eat a backslash
#: and produce a page that renders blank with one line in the console.
LINK_JS = r"""
/* The fragment, which never left this browser. */
function frag() {
  var out = {};
  location.hash.replace(/^#/, '').split('&').forEach(function (pair) {
    if (!pair) return;
    var i = pair.indexOf('=');
    var k = i < 0 ? pair : pair.slice(0, i);
    var v = i < 0 ? '' : pair.slice(i + 1);
    try { out[decodeURIComponent(k)] = decodeURIComponent(v); }
    catch (_) { out[k] = v; }
  });
  return out;
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}
var box = document.getElementById('box');
var f = frag(), here = location.origin;

function bad(msg) {
  box.innerHTML = '<h1>ROM<span>arr</span></h1>'
    + '<div class="sub">Not an invitation</div>'
    + '<div class="note">' + esc(window.ROMarrI18n.translate(msg)) + '</div>';
}

/* Home. The fragment was rehomed onto this host, so this IS the recipient's
   server. Hand the invitation to the app through sessionStorage rather than
   through the URL: the app's router owns the hash, and an invitation has no
   business surviving into the next tab. If nobody is signed in here, the app
   shell serves the sign-in screen and the invitation is waiting afterwards. */
function home() {
  try {
    sessionStorage.setItem('romarr-invite', JSON.stringify(
      {url: f.u, peer_id: f.i, name: f.n || ''}));
  } catch (_) {}
  location.replace('/#peers');
}

/* Away. This is the inviter's server. Ask for the recipient's own address and
   rewrite the same link onto it, carrying this origin in `u` so their ROMarr
   knows who invited them. Remembered locally, because the second invitation
   somebody receives should not ask twice. */
function away() {
  var mine = '';
  try { mine = localStorage.getItem('romarr-home') || ''; } catch (_) {}
  var link = here + '/link#i=' + encodeURIComponent(f.i)
    + (f.n ? '&n=' + encodeURIComponent(f.n) : '');
  box.innerHTML = '<h1>ROM<span>arr</span></h1>'
    + '<div class="sub">You have been invited to peer</div>'
    + '<div class="who" lang="und" dir="auto">' + esc(f.n || here) + '</div>'
    + '<div class="id" lang="und" dir="auto">' + esc(here) + '</div>'
    + '<div class="step"><b>1</b><span>Tell ROMarr where your own server '
    + 'lives. This page is on your friend&rsquo;s server, so it has to send '
    + 'you home.</span></div>'
    + '<label for="home">Your ROMarr address</label>'
    + '<input id="home" type="url" placeholder="http://192.168.1.20:7878" '
    + 'value="' + esc(mine) + '" autofocus>'
    + '<button id="go">Open this invitation on my ROMarr</button>'
    + '<div class="step"><b>2</b><span data-i18n="ui.your-romarr-asks-for-a-claim-code-ei.d959ceaac8">Your ROMarr asks for a claim code: eight characters your friend sends separately. It is not in this link and expires after 15 minutes.</span></div>'
    + '<div class="note"><span data-i18n="ui.no-romarr-on-this-device-copy-the-li.2d22717ea8">No ROMarr on this device? Copy the link and paste it into Friends &rarr; I have an invitation on your own server.</span>'
    + '<br><br><code>' + esc(link) + '</code>'
    + '<button class="copy" id="copy">Copy the link</button></div>';
  document.getElementById('copy').onclick = function () {
    var b = document.getElementById('copy');
    navigator.clipboard.writeText(link).then(
      function () { b.textContent = 'Copied'; },
      function () { b.textContent = 'Select the link above and copy it'; });
  };
  document.getElementById('go').onclick = function () {
    var raw = document.getElementById('home').value.trim();
    if (!raw) return;
    if (!/^https?:\/\//i.test(raw)) raw = 'http://' + raw;
    raw = raw.replace(/\/+$/, '');
    try { localStorage.setItem('romarr-home', raw); } catch (_) {}
    location.href = raw + '/link#i=' + encodeURIComponent(f.i)
      + (f.n ? '&n=' + encodeURIComponent(f.n) : '')
      + '&u=' + encodeURIComponent(here);
  };
}

if (!f.i) bad('This link carries no invitation. Copy the whole thing, '
  + 'including the part after the # — that is where the invitation is, '
  + 'and some chat clients cut it off.');
else if (f.u) home();
else away();
"""


def link_page() -> str:
    """The landing page for an invitation link.

    A constant. It takes no parameters, reads no invitation and returns the
    same bytes to everybody, which is what lets it sit on the open-path list
    without being a thing that can leak: there is nothing behind it to ask.

    `referrer: no-referrer` because this page navigates to the recipient's own
    server, and the inviter's hostname is not the recipient's server's business
    to learn from a header.
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Invitation &middot; ROMarr</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<style>{CSS}{LOGIN_CSS}{LINK_CSS}</style></head><body data-title="Invitation">
{_public_language_picker()}
<div class="box" id="box">
  <h1>ROM<span>arr</span></h1>
  <div class="sub" data-i18n="ui.checking-this-invitation.9246131855">Checking this invitation&hellip;</div>
</div>
<script>{I18N_RUNTIME}</script><script>{PUBLIC_I18N_JS}</script>
<script>{LINK_JS}</script></body></html>"""


def steam_result_page(kind: str, message: str = "") -> str:
    """Render the Steam return screen in the visitor's interface language."""
    copy = {
        "expired": ("That sign-in link has expired", "Start again from Lists.", "Back"),
        "unverified": ("Steam sign-in could not be verified", "Nothing was connected.", "Back to Lists"),
        "connected": ("Steam connected", "", "Back to Lists"),
    }.get(kind)
    if copy is None:
        raise ValueError("unknown Steam result page")
    heading, detail, back = copy
    heading_key = UI_SOURCE_TO_ID.get(heading, heading)
    detail_key = UI_SOURCE_TO_ID.get(detail, detail)
    back_key = UI_SOURCE_TO_ID.get(back, back)
    dynamic = (f'<p lang="und" dir="auto">{html.escape(str(message))}</p>'
               if message else "")
    detail_markup = (f'<p data-i18n-key="{html.escape(detail_key, quote=True)}">{html.escape(detail)}</p>'
                     if detail else "")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(heading)} · ROMarr</title><style>{CSS}{LOGIN_CSS}</style></head>
<body data-title="{html.escape(heading_key, quote=True)}"><main class="box">
  <h2 data-i18n-key="{html.escape(heading_key, quote=True)}">{html.escape(heading)}</h2>
  {detail_markup}{dynamic}
  <p><a href="/#lists" data-i18n-key="{html.escape(back_key, quote=True)}">{html.escape(back)}</a></p>
</main><script>{I18N_RUNTIME}</script><script>{PUBLIC_I18N_JS}</script></body></html>'''
