# NavigIQ web app — design brief

How the product UI was derived from the original NavigIQ concept (the Lovable
prototype in `Desktop/UIUX`, used as a visual and UX reference only), and the
rules the implementation follows.

## What the concept got right, and was kept

- **Identity.** Warm sand background, one deep olive accent, Sora for display
  and DM Sans for text, soft 20–32 px radii, gentle elevation. It reads local
  and calm rather than "tech product".
- **An immersive hero with a question.** "What's your mood today?" with a
  large ask bar and quick intents.
- **Curated collections, trending rails, saved places and plans** as the
  building blocks of the home screen.

## What was raw, and what replaced it

| In the concept | In the product |
|---|---|
| Mock services, invented "trending" places, fake distances and plan data | Every card, reason, cost and time comes from the API. No mock ships (MSW is used in unit tests only). |
| AI-generated photos presented as named landmarks (a palace, Lalbagh's glasshouse) | Places show their own Wikimedia photo, credited, or category artwork. Generated images appear only as mood illustration, labelled "Illustration" (ADR-033). |
| A plan detail page listing stop names, "timings and routing arrive later" | The plan screen: day-by-day timeline, validated times, cost estimates, buffers, weather, numbered map pins, quick changes, what-if comparison, versions and undo. |
| "Directions" button implying NavigIQ routes you | "Open in OpenStreetMap" — labelled external. Maps draw pins, never a route line (ADR-022). |
| Sign-up asking for mobile number, gender and age | Email and password only (all the backend uses). Anonymous use is complete; an account adds saved places, preferences and cross-device plans. |
| Separate hero/collections/trending services computed in the browser | One backend: `/context` for the real IST time and forecast, `/pois/recommend` for ranked places with reasons, `/collections` for curated sets. |

## Information architecture

**Explore · Ask NavigIQ · Plans · Saved** — a header on desktop, a bottom tab
bar on phones. Search, collections, places and "I'm bored" live under
Explore; profile and sign-out under the avatar.

## Screens

| Screen | Route | Notes |
|---|---|---|
| Explore home | `/` | Hero art follows the real time of day and forecast; "Right now" rail (moods by time of day, indoor when rain is forecast); your plans; collection rails; mood tiles; plan CTA |
| Search | `/search` | Text, category, mood, area (gazetteer-resolved or reported unknown), budget, distance; list or map; filters in a bottom sheet on phones |
| Place | `/places/:id` | Only fields NavigIQ has; unverified hours flagged; sources and licences; similar places |
| Ask NavigIQ | `/ask` | One conversation for discover/understand/plan; each response type renders as real UI (cards, comparison table, cited answer, plan preview, what-if side by side); conversation restored after reload |
| I'm bored | `/bored` | One surprise at a time with "show me something different"; mood tiles |
| Collections | `/collections`, `/collections/:id` | Backend-defined sets |
| Plan builder | `/plans/new` | Structured, no model needed; 1–7 days; real preview before saving; infeasible requests show the planner's own relaxations |
| Plan | `/plans/:id` | Days collapse; per-day and whole-plan changes; stop menu (replace, replace with a category, remove, external map); "Updating day 2… keeping …"; change summary with undo; what-if compare; versions and restore |
| Plans, Saved, Profile, Sign in/up | | |

## Design system

`frontend/src/styles/index.css` is the only place colours, type, radii,
shadows and motion are defined. Components use semantic tokens
(`bg-background`, `text-muted-foreground`, `bg-primary`…), never raw values.
Each category group has a soft tone and an ink tone, used for badges and for
place artwork. Motion is short (260–420 ms, ease-out) and entirely disabled
under `prefers-reduced-motion`.

Primitives: `components/ui` (Button variants, Chip, Badge, Skeleton,
EmptyState, ErrorState, Field/Input, Segmented, Dialog, BottomSheet,
ResponsivePanel).

## Honesty rules the UI enforces

- No ratings, review counts, "popular times" or prices presented as fact.
  Costs are ranges labelled "est.", per person on places and for the party on
  plans, always "excluding transport".
- No travel times. The gap between stops is a buffer and says so.
- Loading text describes what the server is doing for that kind of request
  (e.g. "checking opening hours and your budget" for plans), never generic
  progress theatre.
- Weather appears only when the forecast service answered; otherwise the UI
  says it's unavailable.
- Reasons on cards are the ranking engine's reason codes, rendered as text.

## Accessibility

Axe (WCAG 2.1 A/AA) runs on every main screen in the Playwright suite with no
violations; skip link; visible focus; labelled controls; keyboard-operable
menus and sheets (Radix/vaul); 44 px+ touch targets on the tab bar; colour
contrast checked in the final (non-animated) state.

## Performance

Route-level code splitting; Leaflet loads only when a map is shown; photos
lazy-load; TanStack Query caches server state (context 5 min, collections
10 min); the production bundle's main chunk is ~126 kB gzipped.
