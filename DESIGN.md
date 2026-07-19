# Translation Workbench Design System

## Product Intent

FCIAI is an operational translation workbench. The interface should feel quiet,
reliable, and efficient for repeated PPT and PDF translation tasks. It is a tool,
not a marketing site: settings, task state, output access, and recovery actions
must remain easy to scan.

## Experience Principles

1. Keep the current task state visible until the user acknowledges the result.
2. Make the primary workflow usable with mouse, keyboard, and touch.
3. Use the same interaction model for PPT and PDF wherever their behavior matches.
4. Preserve user context after recoverable failures; explain what can be retried.
5. Prefer restrained borders and spacing over decorative cards or large shadows.
6. Never reduce text below a readable size to fit a viewport.

## Foundation

### Color

All UI colors are exposed as custom properties in `experience.css`.

| Token | Value | Use |
| --- | --- | --- |
| `--ux-page` | `#f4f7f9` | Application background |
| `--ux-panel` | `#ffffff` | Primary surfaces |
| `--ux-subtle` | `#eef4f7` | Secondary surfaces |
| `--ux-border` | `#d8e2e8` | Dividers and controls |
| `--ux-text` | `#26343d` | Primary text |
| `--ux-muted` | `#5d6b74` | Secondary text |
| `--ux-primary` | `#007eaf` | Primary actions and active state |
| `--ux-primary-hover` | `#006b94` | Primary hover state |
| `--ux-brand` | `#0094d9` | FrieslandCampina brand accent |
| `--ux-success` | `#18794e` | Completed state |
| `--ux-warning` | `#9a6700` | Waiting or warning state |
| `--ux-danger` | `#b42318` | Failed or destructive state |
| `--ux-focus` | `#005fcc` | Keyboard focus ring |

Primary text and controls use the darker primary token where contrast is needed;
the brighter brand cyan remains an accent.

### Typography

- UI: `Segoe UI`, `Microsoft YaHei`, `PingFang SC`, system UI, sans-serif.
- Logs and identifiers: `Cascadia Mono`, `Consolas`, monospace.
- Base size: 14px desktop and 15px on compact touch layouts.
- Body line height: 1.5. Letter spacing remains `0`.
- Page titles: 24px/32px. Section titles: 18px/26px. Labels: 14px/20px.

### Spacing And Shape

- Spacing uses a 4px base: 4, 8, 12, 16, 24, and 32px.
- Controls are at least 40px high; compact icon actions are at least 36px square.
- Panel radius: 8px. Control radius: 6px. Status badge radius: 4px.
- Shadows are reserved for drawers, dialogs, and toasts. Content panels use borders.

## Layout

- Desktop: fixed 240px navigation rail with a fluid workspace.
- Tablet: navigation becomes an off-canvas drawer; settings and work area stack.
- Mobile: one content column, 16px page gutters, full-width primary actions.
- Tables retain their semantic layout and scroll horizontally in a labelled region.
- The browser remains zoomable at every viewport.

## Components

### App Shell

The shell provides a skip link, landmark navigation, current-page indication, and
an off-canvas mobile menu. Opening the drawer traps visual attention with an
overlay; Escape and selecting a destination both close it.

### Upload Zone

Upload zones expose button semantics, keyboard activation, accepted file types,
and a visible focus state. Upload progress is announced through a live region and
uses a determinate progressbar when a percentage is available.

### Task Status

Queued, processing, completed, and failed states use one persistent status surface.
Messages are announced politely, while failures use assertive notification. A
completed result remains available through the result area and history table.

### History Table

History starts with a loading state, then shows data, an intentional empty state,
or a recoverable error with refresh. Icon-only actions have accessible names and
tooltips. Destructive actions still require confirmation.

### Feedback

Non-blocking success and error feedback uses toasts. Dialogs are reserved for
completion and destructive confirmation. Toasts do not cover global navigation or
the mobile header.

## Motion And Accessibility

- Motion is limited to opacity and transform transitions under 200ms.
- `prefers-reduced-motion: reduce` disables nonessential animation.
- Every interactive element has a visible `:focus-visible` state.
- Live task messages use `aria-live`; decorative icons use `aria-hidden`.
- Touch targets are at least 40px and no workflow depends on hover.
