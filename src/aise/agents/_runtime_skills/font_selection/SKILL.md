---
name: font_selection
description: Pick fonts that cover every Unicode block your UI actually renders, via a centralized resolver — never hardcode a single font name like "arial" or pass `None` to pygame.font.Font, because both silently render `.notdef` (tofu boxes) for any character outside their glyph table
---

# Font Selection Skill

## When to Use

Use this skill whenever you write or modify code that calls
``pygame.font.SysFont(...)``, ``pygame.font.Font(...)``,
``QFont(...)``, ``ImageFont.truetype(...)``, ``createApp(...)`` with
a custom font, or any equivalent in your project's UI stack.

## Why this skill exists

A font's glyph table is finite. ``Arial`` (and any pure-Latin font)
covers the Latin / Greek / Cyrillic Unicode blocks but contains no
CJK glyphs at all. When code calls ``font.render("贪吃蛇", ...)``
against an Arial Font object, FreeType returns the ``.notdef`` glyph
— an empty box (tofu, 豆腐) — for every CJK character. The render
**succeeds**, the surface has many non-zero pixels (filled by the
box outline), every test that checks "is anything drawn" passes,
and the user sees a screen full of identical boxes where text
should be.

This skill exists because the failure mode is invisible to every
automated check that doesn't compare two distinct characters' pixel
patterns. Preventing it must happen at the **font selection** site
in source code, before the glyph table is even consulted.

## Core rule: zero hardcoded single-font names

In any UI source file, the following patterns are **forbidden**:

```python
pygame.font.SysFont("arial", N)         # FORBIDDEN: single name
pygame.font.SysFont("Arial", N)         # FORBIDDEN: same
pygame.font.SysFont(None, N)            # FORBIDDEN: implicit default
pygame.font.Font(None, N)               # FORBIDDEN: pygame's bundled freesansbold (Latin only)
pygame.font.Font("/some/path.ttf", N)   # DISCOURAGED: hard path, no fallback
```

Equivalents in other UI frameworks are equally forbidden:
- Qt: ``QFont("Arial", N)`` without ``setStyleStrategy(PreferDefault)`` and a fallback list.
- Tk: ``font="Arial 14"`` literal.
- HTML/CSS: ``font-family: Arial`` without a fallback chain.
- PIL: ``ImageFont.truetype("arial.ttf", N)`` without try/except + fallback.

Why: the call **assumes** the host has Arial installed AND that
Arial covers your literals' Unicode blocks. The first assumption
fails on minimal Linux containers; the second fails on every CJK
literal.

## Required pattern: centralized font resolver

Every project MUST contain exactly **one** font resolver module that
all UI code goes through. Place it at a stable location (depending
on stack convention):

| Stack | Path |
| ----- | ---- |
| Python (pygame) | ``src/<package>/shared/font_resolver.py`` |
| Python (Qt / Tk) | ``src/<package>/shared/font_resolver.py`` |
| TypeScript | ``src/shared/fontResolver.ts`` |
| Go | ``internal/shared/fontresolver/resolver.go`` |
| Rust | ``src/shared/font_resolver.rs`` |

Minimal Python+pygame template (adapt other stacks accordingly):

```python
"""Font resolver — selects a font that covers the UI's actual literals."""

from __future__ import annotations
import pygame

# Candidate fonts ordered by host-system prevalence. ``SysFont``
# accepts comma-separated names and returns the first match. Order
# CJK-capable fonts FIRST so any CJK literal renders correctly even
# if a Latin-only font is also installed.
_CJK_CAPABLE = (
    # Linux
    "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK JP",
    "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
    "Source Han Sans CN", "AR PL UMing CN",
    # macOS
    "PingFang SC", "PingFang TC", "Heiti SC", "Hiragino Sans GB",
    # Windows
    "Microsoft YaHei", "Microsoft JhengHei", "SimHei", "SimSun",
    # Latin fallback (covers ASCII; CJK still tofu — but the chain
    # above almost never falls all the way through).
    "DejaVu Sans", "Liberation Sans", "Arial",
)

_QUERY = ",".join(name.lower().replace(" ", "") for name in _CJK_CAPABLE)


def get_font(size: int, *, bold: bool = False) -> pygame.font.Font:
    """Return a font whose glyph table covers CJK + Latin.

    Raises:
        RuntimeError: if pygame.font is not initialised (caller must
            run pygame.font.init() / pygame.init() first).
    """
    if not pygame.font.get_init():
        raise RuntimeError("get_font() called before pygame.font.init()")
    return pygame.font.SysFont(_QUERY, size, bold=bold)
```

For pure-English UIs (no CJK literals anywhere in the project) the
candidate list MAY drop the CJK section, but the **multi-name
pattern** must remain — never a single hardcoded font name. The
list ordering is by host prevalence, not by aesthetic preference.

## Migration: every existing call site

Replace every direct font construction with a ``get_font`` call.
Use a project-wide grep before declaring done:

```bash
grep -rn 'SysFont\|pygame\.font\.Font(\|QFont(\|ImageFont\.truetype' src/
# Expected: only the resolver module appears in results.
```

If the grep returns hits outside the resolver, you have not
migrated the project. Migrate them all in one sweep — partial
migration leaves the bug latent in the un-migrated component.

## Coordination with architect

The ``stack_contract.json`` schema declares each component's
``display_language`` (a string like ``"zh-CN"``, ``"en-US"``,
``"ja-JP"``, or ``null`` for non-UI components — see
``lifecycle_init_contract`` skill). The font resolver's candidate
list MUST cover the union of all components'
``display_language`` values:

- Any component with ``display_language`` containing CJK locale
  (zh-*, ja-*, ko-*) → resolver must include CJK-capable fonts at
  the top of its candidate list.
- Pure ``en-*`` projects can use a Latin-only chain.

If the architect did not declare ``display_language``, default to
the multi-locale chain above — rendering CJK with a Latin-only
font is unrecoverable, but rendering Latin with a CJK-capable font
is universally fine (only mildly aesthetically different).

## Anti-patterns to avoid

- **Per-call-site fallback**: writing
  ``try: pygame.font.SysFont("arial",N) except: pygame.font.SysFont(None,N)``
  in every render method. The fallback target is the same broken
  Latin-only font — this has zero coverage benefit and just
  scatters dead code. Centralise to ``get_font``.
- **Asserting via surface size only**: ``assert surf.get_size()[0] > 0``
  passes for tofu boxes; do not let this convince you the font is
  correct. See ``tdd`` skill for the glyph-distinct test pattern.
- **Hardcoded TTF path**: ``Font("/usr/share/fonts/.../X.ttf", N)``
  works on the developer's machine and breaks everywhere else.
  Always go through the resolver.
- **Per-component import of pygame.font.SysFont directly** while
  also importing ``get_font`` — use one OR the other, never mixed
  in the same file (mixed imports invariably drift back to the
  hardcoded form).

## Self-verify before reporting done

Before closing a UI implementation task, run:

```bash
grep -rn 'SysFont\|pygame\.font\.Font(' src/<package>/ui src/<package>/system
```

If anything outside ``font_resolver.py`` matches, you are not done.
Migrate it.
