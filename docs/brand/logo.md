# TailorbirdCV logo

Brand assets for TailorbirdCV (tool that tailors a master CV to each job description, truthfully, without inventing experience).

## Files

| File | Use |
| --- | --- |
| `logo.svg` | Primary horizontal lockup (mark + wordmark) on light background `#F4F7F5`, 960x480 |
| `logo-dark.svg` | Same lockup on deep green `#0F3D2E` |
| `icon.svg` | Mark only, on rounded-square deep green tile (480x480, corner radius 108). App icon / favicon source |

## Concept

A tailorbird (Orthotomus) perched on a leaf. Tailorbirds sew leaves together with plant fibre to build their nests, so the leaf carries a dashed running stitch. Metaphor: stitching one master CV into a custom fit for each role.

Slogan candidate: "Stitched to fit."

## Mark description

Flat, geometric, solid colors only. No gradients, no shadows, no outlines.

- Bird in profile, facing right. Round body, small round head.
- Tail: narrow upright wedge pointing up-left.
- Crown: rust-orange cap on top of the head.
- Beak: small amber triangle pointing right.
- Eye: tiny dot in the off-white/background color.
- Wing: short light-green curve across the body.
- Legs: two short vertical strokes under the body.
- Leaf: lime-green crescent under the bird, with a dashed dark-green stitch line along its length.

Mark geometry lives in a 120x120 viewBox. Both SVGs reuse the same paths.

## Wordmark

- Text: `TailorbirdCV`, one word, camel case.
- Font: Outfit (Google Fonts), weight 600. Fallbacks: Sora, Helvetica Neue, Arial.
- Letter-spacing: -0.03em.
- "Tailorbird" in the main text color, "CV" in the accent color.
- Text in the SVGs is live `<text>`, not outlined. Load Outfit (or convert text to outlines) before using the logo in print or where the font is missing.

## Colors

| Role | Hex |
| --- | --- |
| Deep forest green (bird, dark background, main text) | `#0F3D2E` |
| Leaf green (leaf, wing) | `#8CCB7A` |
| Crown orange-red | `#E4572E` |
| Beak amber (also "CV" on dark) | `#F2A93B` |
| "CV" rust on light | `#C8431D` |
| Off-white (light background, bird on dark) | `#F4F7F5` |

## Variants

- Light: bird `#0F3D2E`, "Tailorbird" `#0F3D2E`, "CV" `#C8431D`, background `#F4F7F5`.
- Dark: background `#0F3D2E`, bird and "Tailorbird" `#F4F7F5`, "CV" `#F2A93B`.
- Icon: dark variant mark, no text, centered on rounded square.

## Usage rules

- Keep clear space around the lockup of at least the height of the bird's head.
- Minimum size: mark readable at 32px. Below that use the icon.
- Do not recolor, add gradients or shadows, rotate, or stretch.
- Do not use the light-variant bird on dark backgrounds. Use `logo-dark.svg`.
- Do not use a face, feather detail, or 3D rendering.

## Prompt for regenerating in an image model

Minimalist vector logo for "TailorbirdCV". Flat geometric tailorbird in profile facing right, perched on a lime-green crescent leaf with a dashed dark-green running stitch. Deep green body (#0F3D2E), rust-orange crown (#E4572E), amber beak (#F2A93B), light-green wing curve (#8CCB7A). Wordmark in Outfit semibold, "Tailorbird" green, "CV" rust. Flat solid colors, no gradients or shadows, works at 32px, off-white background (#F4F7F5).

## Name status (checked 2026-10-05)

`tailorbirdcv` was free on PyPI and GitHub at the time. The root name "Tailorbird" is used by Tailorbird, Inc. (real estate software) and joelstransky/Tailorbird (job-search tool). Check domains and trademarks before launch.
