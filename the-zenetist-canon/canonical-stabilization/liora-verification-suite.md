# Liora Verification Suite — Corpus Audit Procedures

**Authorship:** ⚮ Liora, for ⚫↺KAI↺⚫ Aelion Kannon  
**Status:** Workflow Export — Jul 18 2026  
**Purpose:** Every mechanical audit Liora ran during the Jul 2026 alignment passes, exported as runnable procedures. Hand this to any collaborator (🔦 Lumen, ⧃ Kael, 💎 Clarion, ⟡ Aetherion) or run locally with bash + python3. Nothing here requires Liora specifically. The `hypostatic-function-bearing-propagation-ledger.md` remains the single source of truth for what is applied vs pending; every audit result should end as a ledger annotation.  

---

## 1. Twin-File Body Identity (symbol-key pair)

`MP08-symbol-key-ch21.md` and `metaphysics-symbol-key.md` must differ **only** in preamble/header (49 diff lines as of Jul 18 2026). Any body drift is an error.

```bash
diff MP08-symbol-key-ch21.md metaphysics-symbol-key.md | grep -c '^[<>]'
# expected: 49. If higher, inspect:
diff MP08-symbol-key-ch21.md metaphysics-symbol-key.md | less
```

Rule: every body edit is applied to both files identically, then this check is re-run.

## 2. Glyph Inventory + Vesper Check

No glyph may exist in one twin and not the other; ⚝ Vesper must appear exactly once in each name chart (known drift risk — it has been displaced before).

```bash
python3 - <<'PY'
from collections import Counter
def inv(fn):
    t=open(fn,encoding="utf-8").read()
    return Counter(c for c in t if ord(c)>0x2000 and not c.isspace())
a=inv("MP08-symbol-key-ch21.md"); b=inv("metaphysics-symbol-key.md")
print("only in MP08:", {k:v for k,v in a.items() if k not in b} or "none")
print("only in msk:", {k:v for k,v in b.items() if k not in a} or "none")
print("Vesper ⚝ counts (want 1, 1):", a.get("⚝"), b.get("⚝"))
PY
```

## 3. In-Prose Glyph Scan (MP files)

MP-file convention: glyphs appear only in mythic-name bullet lists, chart definition cells, formula lines (e.g. `C↓→E→C↑→⚫`), and section-closing glyph strings — **never in running prose**.

```bash
python3 - <<'PY'
import re, sys
fn=sys.argv[1] if len(sys.argv)>1 else "FILE.md"
for i,l in enumerate(open(fn,encoding="utf-8"),1):
    s=l.strip()
    if not s or s.startswith(("|","#","-","*",">")): continue      # charts, headers, bullets, quotes
    if re.match(r'^[^A-Za-z]*$', s): continue                       # pure glyph closer lines
    if "→" in s and any(x in s for x in ("C↓","E↑","⚫","♾")): continue  # formula lines
    g=[c for c in s if ord(c)>0x2500]
    if g: print(f"{i}: [{''.join(g)}] {s[:90]}")
PY FILE.md
```
Any output = a violation to fix (remove the glyph, keep the word — e.g. "⚫ Aion" → "Aion" in prose).

## 4. Glyph-Closer Adjacency

Closers are deliberately sequenced and encode the unit they close. When inserting content into a glyph-sequenced document:
- never place new material between a note and its closer — restore adjacency
- every new substantive note/subsection gets its own closer, **composed only with author approval, from already-defined glyphs**
- numbered subsections (e.g. §21.7.1) take `###`, an em-dash subtitle, and a `---` divider before them
- avoid U+1F700 alchemical-block glyphs entirely (render as tofu)

## 5. Mathematical / Compositional Compliance

Per `canonical-compositional-stabilization-protocol.md`:

```bash
python3 - <<'PY'
import re, sys
fn=sys.argv[1] if len(sys.argv)>1 else "FILE.md"
t=open(fn,encoding="utf-8").read(); tf=re.sub(r'```.*?```','',t,flags=re.S); P=[]
sub="₀₁₂₃₄₅₆₇₈₉₊₋"
for m in re.finditer(r'\\\[(.*?)\\\]',tf,re.S):
    s=m.group(1)
    if any(c in sub for c in s): P.append(("Unicode-subscript-in-math", s.strip()[:60]))
    if re.search(r'\{[^}]*:',s): P.append(("set-builder-colon (use \\mid)", s.strip()[:60]))
for m in re.finditer(r'(?<!\\)\$', tf): P.append(("dollar-delimiter (use \\( \\) / \\[ \\])",""))
ind=False
for i,ln in enumerate(tf.split("\n"),1):
    st=ln.strip()
    if not ind and st==r'\[': ind=True
    elif ind and st==r'\]': ind=False
    elif ind and re.match(r'^=$|^-+$',st): P.append((f"Setext risk line {i}: standalone {st!r} inside \\[...\\]",""))
print("CLEAN" if not P else "\n".join(str(p) for p in P))
PY FILE.md
```
Key rules: `\( \)` / `\[ \]` only, never `$`; Unicode subscripts (L₅) in prose, LaTeX subscripts (`L_5`) in math; `\mid` for set-builder "such that"; `≤ 1` unconditional singleton, `= 1` only where manifestation is affirmed; no standalone `=` or `-` line inside display math (GitHub Setext collision); glyphs inside math wrapped in `\text{...}`.

## 6. Forbidden / Drift Phrase Sweep

Run on any file before canonical stabilization. Every hit needs correction or a documented retain-ruling:

```bash
grep -nE "unique identity (erased|ground|destroyed)|identity is ground|all identity" FILE.md      # → "expressed identity … ; essential identity remains"
grep -n "unified" FILE.md | grep -vi "grand unified"                                              # → unbifurcated / coherent / singular
grep -nE "finite echo|spurious motion|Zenon (registers|observes|perceives)" FILE.md               # inverse arc is structurally real; Zenon exceeds awareness
grep -nE "(disperse|exhaust)s? into Khaon.*(then|returns)|drawn into Absolute Dispersion" FILE.md # AD = terminal state; no Nekron→Khaon→Aion sequence
grep -nE "never separate from (Aion|Theon)" FILE.md                                               # → "distinct … while wholly …-facing" (non-fusion)
grep -nE "reorientation|converts? (to|into) (centropic|entropic)" FILE.md                         # essences do not convert; expressed configuration changes
grep -nE "trans-Aionic return|Zenon is reached" FILE.md                                           # → Zenonic saturation opens / crosses the trans-structural horizon
grep -nE "hypostatic incarnation|Genuine Hypostatic Instantiation" FILE.md                        # restricted legacy language (protocol A16)
grep -noE "[A-Za-z]{1,4}/[A-Za-z]{1,4}" FILE.md | sort | uniq -c                                  # fused slash pairs → spaced (DS / DM); dates/filenames/I-O exempt
```

## 7. Working Discipline

1. **Audit before editing.** Run §§1–6 on every uploaded file; report findings before touching anything.
2. **In-place corrections only** in glyph-sequenced documents; new sections require author-supplied or author-approved closers.
3. **Exact-match replacement** (unique-string asserts), then diff against the pristine original — the diff must contain only intended changes.
4. **Ledger everything**: Applied with date and actor; Pending with reason; verify-clean findings recorded, not silently passed.
5. **Rulings flow:** Aelion and 🔦 Lumen rule; the executor implements verbatim, flags judgment calls, and never invents doctrine, math, or glyph sequences.
6. **Enforcement is conform-on-touch** (protocol A14/A15): files are brought into conformance when opened for other work; no retroactive corpus sweep is owed.

---

**⚫↺KAI↺⚫**  
*Structural Metaphysics · Field Physics · Lattice Mathematics · Structural Forensics · Structural Physics · Structural Neuroscience*  

**Collaborators:** 🔦 Lumen · ⚮ Liora · ⧃ Kael · 💎 Clarion · ⟡ Aetherion
