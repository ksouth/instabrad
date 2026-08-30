# Instabrad CLI UI Design System

Status: first-pass visual specification. Colours are intentionally not yet final.

## Purpose

Instabrad's CLI should feel deliberate, playful, readable, and clearly designed by a person. It should avoid generic emoji-heavy developer-tool styling while still having warmth, personality, and a little silliness.

The interface should remain useful first: hierarchy, spacing, alignment, progress visibility, and state clarity matter more than decoration.

## Core principles

- Use Unicode dingbats, ornaments, box-drawing characters, and texture instead of emoji.
- Keep spacing mathematically consistent.
- Keep labels and body text mostly neutral/default terminal colour.
- Use colour selectively on values, active progress, state changes, and attention cues.
- Do not rely on sound alone for any state change.
- Every sound cue MUST have a simultaneous visible colour cue.
- Prefer centred title treatment for now; ordinary content remains left-aligned.
- Header ornaments must be visually balanced on both sides.
- Symbols may be playful. Hearts are explicitly allowed and will receive semantic rules rather than being treated as rare decoration.
- Glyph appearance varies by font and terminal. Final choices must be validated in Terminal.app, not only in Markdown/ChatGPT/GitHub.

## Current favourite glyph palette

Primary favourites selected so far:

```text
✫  ✴  ◌  ▥  ◎  ✘  ❃  ♡  ❝  ❞
❬  ❭  ❮  ❯  ❰  ❱  ❲  ❳  ❴  ❵  ➜
```

Previously liked and still available for testing:

```text
❖  ❦  ✣  ✤  ✦  ✧  ✱  ✲  ✳  ✶  ✷  ✹  ✺  ❈  ❉  ❊
```

Texture / separator favourites:

```text
░░░░░░░░░░
╌╌╌╌╌╌╌╌
```

Note: `◎`, `░`, and `╌` have already shown noticeable rendering differences between interfaces. Terminal.app rendering is authoritative for implementation.

## Title / splash screen

Current preferred general shape:

```text
┌────────────────────────────────────────────────────┐
│                  ✦ INSTABRAD ✦                     │
└────────────────────────────────────────────────────┘
```

Requirements:

- The title line is centred programmatically, never padded by hand.
- If a symbol appears on the left of a header, the same visual weight must appear on the right.
- Border width is fixed by the UI component, not individual call sites.
- Exact title ornament is still open for refinement; `✦`, `✫`, `✴`, `❃`, and `♡` are candidates.
- Main content beneath the splash/title remains left-aligned.

## Layout

- Use a consistent panel width across the project. Initial candidate: 54–60 columns; final width TBD after Terminal.app preview.
- One consistent indentation level for content under labels.
- Numeric metrics align vertically by value.
- Padding spaces are never intentionally colourised.
- Avoid excessive vertical whitespace, but do not compress sections into a wall of text.
- Prefer a live/status-dashboard feel over endless scrolling logs where practical.

Example metric block:

```text
Comments        143
Replies          31
Buttons          47
Round             8
Elapsed       01:43
```

Only the digits/value text may receive the metric accent colour.

## Main progress bar

Primary loading/progress component:

```text
█████████░░░░░░░░░
```

Rules:

- Filled block: coloured accent.
- Remaining `░` area: muted/default colour.
- Used for the main process or a process with meaningful progress/completion.
- Completed bar may change to the success colour.
- Do not animate with needless colour changes.

## Subprocess / activity bar

Secondary activity texture:

```text
••••••••············
```

Rules:

- Used for subprocesses, background work, or activity where exact percentage is less meaningful.
- Filled `•` portion may use the active accent colour.
- Remaining `·` portion stays muted/default.
- Main process uses the block bar; subprocesses use the dot bar.

## Colour roles

Exact RGB/hex values are deliberately deferred to a dedicated palette pass.

Semantic roles:

- `accent`: active process, selected values, filled progress.
- `success`: completed work.
- `attention`: user action required / sound-trigger state.
- `error`: failed operation.
- `border`: optional subtle panel/border colour.
- `muted`: inactive progress / secondary metadata.
- `default`: normal terminal foreground.

Colour policy:

- Palette stays small and refined rather than primary/stock ANSI-looking.
- Custom 24-bit RGB colours are allowed and preferred.
- Important numeric values may use the accent colour.
- Labels generally remain default colour.
- Green should not drift yellow/olive unless intentionally specified during palette design.
- A sound trigger must always be paired with a visible colour state change.

## Sound cues

Allowed: terminal bell / terminal attention behaviour.

Not wanted: push notifications or desktop notification banners.

Sound is used when:

1. Human input is required.
2. A long-running task completes.
3. Optionally, a blocking error requires attention.

Hard rule:

> Any sound cue MUST occur at the same moment as a visible colour cue.

Examples:

- Waiting for user: attention colour + bell.
- Complete: success colour + bell.
- Blocking error: error colour + bell.

The screen must remain understandable with audio disabled.

## Waiting for user

Example structure:

```text
❉ Waiting for user

Log into Instagram if necessary.
Press ENTER when ready.
```

Future symbol may change from `❉` after Terminal preview.

Behaviour:

- Render the waiting state in the attention colour.
- Sound terminal bell once.
- Do not repeatedly beep while waiting.

## Success / completion

Current liked wording:

```text
❈ Archive complete.

♡ Thank you for using Instabrad.
```

The heart is intentional and may become a recurring project motif.

Behaviour:

- Completion state uses success colour.
- Sound terminal bell once.
- Show useful outcome metrics and output path directly beneath it.

Example:

```text
❈ Archive complete.

Comments        143
Replies          31
Elapsed       02:17

Saved to
brad_data/browser_debug/

♡ Thank you for using Instabrad.
```

## Errors

Preferred error symbol:

```text
✘
```

Example:

```text
✘ Could not find the comments panel.
```

Rules:

- Use error colour.
- If user action is required, bell may sound once.
- Normal mode should display concise actionable errors.
- Full tracebacks belong in debug/developer mode.

## Arrows / directional UI

Preferred arrow:

```text
➜
```

Use for:

- next step
- destination/output path
- transitions
- compact instructional prompts

Avoid mixing many arrow families in the same interface.

## Quote / archival ornament set

Approved for experimentation:

```text
❝ ❞
❬ ❭
❮ ❯
❰ ❱
❲ ❳
❴ ❵
```

Potential uses:

- quoted post/comment excerpts
- archival metadata cards
- prompts or contextual text

These should be tested carefully because some pairs are visually heavier than others.

## Hearts

Approved glyph:

```text
♡
```

Hearts are not restricted to one ceremonial appearance. They are part of the intended personality of the interface.

Rules are not final yet. Candidate uses include:

- completion footer
- friendly non-critical acknowledgements
- project/about screen
- optional decorative separators in low-stakes contexts
- playful success states

Hearts should still have a purpose or rhythm; final density will be established through actual Terminal previews rather than an arbitrary scarcity rule.

## Component model

Implementation should eventually live in a reusable UI module instead of scattered print statements.

Potential API:

```python
ui.banner("INSTABRAD")
ui.section("Benchmark")
ui.metric("Comments", 143)
ui.progress(current=143, total=177)
ui.activity("Expanding replies")
ui.wait("Press ENTER when ready")
ui.success("Archive complete")
ui.error("Could not find comments panel")
ui.bell(state="attention")
```

The UI module owns:

- width
- padding
- centring
- left alignment
- numeric alignment
- Unicode symbols
- colours
- progress textures
- sound cues
- state styling

No individual scraper/collector script should manually reproduce these rules.

## Reuse beyond Instabrad

The design system should be written so the visual components can later be extracted into a reusable personal CLI package for other projects.

Instabrad is the first implementation, not necessarily the final home of the components.

Potential future package concept:

```text
ksouth-cli
```

This document therefore separates semantic component rules from Instabrad-specific scraping behaviour.

## Next design pass

1. Build a Terminal.app specimen/theme-preview script.
2. Render all shortlisted dingbats in the actual terminal font.
3. Render title/panel variants at fixed widths.
4. Preview main block and subprocess dot loaders.
5. Specify the 24-bit RGB palette visually.
6. Refine semantic symbol assignments.
7. Establish heart rules after seeing them in real UI states.
8. Implement reusable `ui.py` / theme components only after the preview is approved.
