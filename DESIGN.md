# Design System — Assay Ledger

## Direction

Local AI Lab behaves like a comparative assay result sheet: strategies are specimens,
evaluation dimensions are columns and every state is an evidence stamp with a recoverable
reference. The interface refuses the generic dashboard of detached KPI cards.

## Scene and mode

Operate mode for long sessions at a Windows workstation under normal office or daylight
illumination. The default surface is light, dense and calm. Dark mode is not inferred from
the technical category.

## Color roles

| Role | Token | Use |
| --- | --- | --- |
| Canvas | `#f2f4f2` | application background |
| Sheet | `#fcfdfb` | primary work surface |
| Ink | `#14231f` | primary text |
| Muted ink | `#52615c` | secondary copy |
| Rule | `#c8cfcb` | measurement lines and separation |
| Selected | `#2457d6` | navigation and focused selection |
| Tested | `#126b58` | evidence proved by an executed test |
| Pending | `#9a560d` | missing evidence or action required |
| Blocked | `#b52b24` | failed guard or closed gate |
| Detected | `#315e80` | observed but not workload-tested |

Color never communicates status alone; every status includes a label and concise symbol.

## Typography

- Headings and navigation: `Bahnschrift`, falling back to `Segoe UI Variable` and sans-serif.
- Body and controls: `Aptos`, falling back to `Segoe UI` and sans-serif.
- Identifiers, hashes and measured values only: `Cascadia Mono`, `Consolas`, monospace.
- Display tracking never tighter than `-0.03em`; body line height is at least `1.45`.

## Composition

- A 248px navigation rail establishes place and privacy mode.
- The work surface is a ruled sheet, not a collection of cards.
- Dense comparisons use semantic tables with sticky headers and keyboard focus.
- A contextual inspector on the right explains the active phase gate and exact missing evidence.
- At narrow widths the inspector moves below the sheet; the comparison remains horizontally
  scrollable instead of collapsing evidence into ambiguous tiles.

## Components and states

- Controls use 8–12px radii; pills are reserved for small status stamps.
- One separation method at a time: rules for tables, restrained offset shadow for floating
  menus, never border plus broad shadow.
- Every asynchronous surface implements loading, empty, error and retry states.
- Demonstration content is visibly marked `DEMOSTRACIÓN`; detected data is never called tested.
- Focus rings use a 3px cobalt outline with offset and remain visible on every interactive item.

## Motion

The authored motion is the evidence scan: when a dataset is refreshed, a single cobalt
measurement rule traverses the comparison sheet and settles into the selected row. Content
is visible without animation, and `prefers-reduced-motion` disables the scan.

## Prohibitions

- No gradient text, decorative glass, neon glow or fake charts.
- No giant metric hero or equal-size card grid as page structure.
- No unsupported claims, invented benchmarks or unlabeled sample values.
- No frontend filesystem, SQLite, vault, shell or secret access.
