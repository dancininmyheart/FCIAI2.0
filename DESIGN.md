# PPT Agent Studio Design System

## Product Intent

PPT Agent Studio is an anonymized portfolio demo for a stateful PowerPoint
translation agent. The interface should feel quiet, reliable, and technically
credible. It is a focused workbench rather than a marketing site: upload
settings, task state, recovery actions, and output access must remain easy to
scan during a short interview demonstration.

The public UI exposes only the PPT translation workflow. Historical PDF,
analysis, dictionary-administration, and company-specific surfaces are outside
the demo navigation and design contract.

## Public Identity

- Product name: **PPT Agent Studio**.
- Descriptor: **AI-powered presentation translation** / **智能演示文稿翻译**.
- Identity is text-first. Do not use an inherited company logo, customer mark,
  favicon, legal entity name, or branded illustration.
- Use generic presentation/translation icons only when they clarify an action.
- Screenshots and fixtures must use synthetic or authorized names and content.
- Demo screens must not expose API keys, account identifiers, internal hosts,
  local user directories, or original filenames from confidential documents.

## Experience Principles

1. Make the upload-to-download path understandable without prior explanation.
2. Keep the current task state visible until the user acknowledges the result.
3. Preserve user context after recoverable failures and state what can be retried.
4. Separate model-generated semantics from deterministic validation in UI copy.
5. Use the same primary workflow with mouse, keyboard, and touch.
6. Prefer restrained borders and spacing over decorative cards or large shadows.
7. Never reduce interface text below a readable size to fit a viewport.
8. Do not present fixture measurements as production performance claims.

## Foundation

### Color

Public identity tokens live in `brand.css`; `experience.css` keeps compatibility
aliases for older workflow components. The palette is intentionally neutral and
is not derived from an employer or customer identity.

| Token | Value | Use |
| --- | --- | --- |
| `--studio-canvas` | `#f6f8fc` | Application background |
| `--studio-surface` | `#ffffff` | Primary surfaces |
| `--studio-ink-950` | `#080d19` | High-contrast text and dark shell |
| `--studio-slate-600` | `#475569` | Secondary text |
| `--studio-slate-200` | `#e2e8f0` | Secondary surfaces and dividers |
| `--studio-indigo` | `#635bff` | Primary actions and active state |
| `--studio-indigo-hover` | `#5148e5` | Primary hover state |
| `--studio-cyan` | `#22d3ee` | Product accent |
| `--studio-success` | `#16a36a` | Completed state |
| `--studio-warning` | `#d97706` | Waiting or warning state |
| `--studio-danger` | `#dc3545` | Failed or destructive state |

Primary actions use indigo where contrast is needed; cyan remains a supporting
accent and is not used as body text on light surfaces.

### Typography

- UI: `Inter`, `Segoe UI`, `Microsoft YaHei`, `PingFang SC`, system UI,
  sans-serif.
- Logs and identifiers: `Cascadia Mono`, `Consolas`, monospace.
- Base size: 14px desktop and 15px on compact touch layouts.
- Body line height: 1.5. Letter spacing remains `0`.
- Page titles: 24px/32px. Section titles: 18px/26px. Labels: 14px/20px.

### Spacing And Shape

- Spacing uses a 4px base: 4, 8, 12, 16, 24, and 32px.
- Controls are at least 40px high; compact icon actions are at least 36px square.
- Large surface radius: 22px. Standard panel radius: 16px. Compact control
  radius: 10px.
- Shadows are reserved for drawers, dialogs, and toasts. Content panels use
  borders.

## Layout

- Desktop: a compact product header and a fluid, centered translation workspace.
- Tablet: settings and work area stack; secondary controls may enter a drawer.
- Mobile: one content column, 16px page gutters, full-width primary actions.
- Tables retain their semantic layout and scroll horizontally in a labelled
  region.
- The browser remains zoomable at every viewport.

## Components

### App Shell

The shell provides a skip link, landmarks, the text product identity, and at
most the navigation needed for PPT translation and task history. Demo mode must
not render links to legacy product modules.

### Upload Zone

The upload zone exposes button semantics, keyboard activation, `.ppt` / `.pptx`
accepted types, file-size guidance, and a visible focus state. Upload progress
is announced through a live region and uses a determinate progressbar when a
percentage is available.

### Translation Settings

Source language, target language, translation mode, model provider, page range,
and optional OCR are grouped in task order. Advanced settings should not compete
with the primary **Start translation** action.

### Task Status

Queued, processing, validating, completed, and failed states use one persistent
status surface. Copy should distinguish Provider generation from deterministic
validation. A completed result remains available through the result area and
history table.

### History Table

History starts with a loading state, then shows data, an intentional empty
state, or a recoverable error with refresh. Icon-only actions have accessible
names and tooltips. Destructive actions require confirmation.

### Feedback

Non-blocking success and error feedback uses toasts. Dialogs are reserved for
completion and destructive confirmation. Toasts do not cover the product header
or the primary action.

## Content Guidelines

- Say **Provider response failed validation**, not **the AI made a mistake**,
  when the precise failure is structural.
- Do not claim perfect layout preservation, zero hallucinations, or a fixed cost
  reduction.
- Keep fixture context beside benchmark numbers, for example **deterministic
  duplicate-text fixture, 100 calls → 1**.
- Error messages may include a correlation ID but never raw source text, secrets,
  absolute local paths, or Provider credentials.
- Use `demo-deck.pptx`, `sample-presentation.pptx`, and similarly generic names
  in documentation and screenshots.

## Motion And Accessibility

- Motion is limited to opacity and transform transitions under 200ms.
- `prefers-reduced-motion: reduce` disables nonessential animation.
- Every interactive element has a visible `:focus-visible` state.
- Live task messages use `aria-live`; decorative icons use `aria-hidden`.
- Touch targets are at least 40px and no workflow depends on hover.

## Portfolio Boundary

Anonymous presentation branding is not a substitute for an open-source release
review. Before publishing the repository, separately review licenses, commit
history, sample files, generated artifacts, environment files, logs, and source
comments for confidential or company-specific material.
