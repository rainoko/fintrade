# Frontend Architecture

TypeScript (required — no plain JS), React, Vite, Material UI (MUI). See [Architecture.md](../Architecture.md) for how this fits the overall system, and [API.md](API.md) for the exact contract every feature below is built against.

## 1. Why React (not Astro), why TypeScript, why MUI

This is a stateful dashboard: live portfolio data, per-stock analysis and charts, frequent re-fetching/re-rendering, forms and confirmations. Astro's island architecture targets mostly-static, content-first sites — the opposite of this app's profile. React fits a data-dense interactive dashboard.

TypeScript is required project-wide: the API boundary (signals, confidence breakdowns, portfolio positions, risk warnings) is exactly the kind of shape-sensitive data where a silent `undefined`/typo bug is costly, and generating types from the backend's committed OpenAPI snapshot keeps both sides honest at compile time.

**Material UI (MUI)** is the component library — Material Design gives this app a coherent, accessible baseline (forms, tables, dialogs, navigation) without hand-building and re-testing basic widgets. Don't reach for a second component library or hand-rolled CSS framework alongside it; extend MUI's theme rather than fighting it.

## 2. State management: server state only, no client-state library

**TanStack Query (`@tanstack/react-query`) is the only data layer.** Every piece of server-derived data (positions, risk, stock analysis, price history) is fetched and cached through it — no data is ever duplicated into component state "just in case."

**Redux and MobX are not allowed, under any circumstance.** This is a hard rule, not a default that yields to a future need: this app has no cross-cutting *client* state complex enough to justify one (no undo stacks, no multi-step wizards spanning routes, no offline sync). If a genuine cross-page client-state need appears later, use React Context first and re-evaluate then — don't add a state library preemptively to solve a problem that doesn't exist yet.

What state lives where:
- **Server state** (anything that came from the API): TanStack Query only — `useQuery`/`useMutation`, with `queryClient.invalidateQueries` on mutation success (e.g. adding/deleting a position invalidates the portfolio and risk queries).
- **Local UI state** (a dialog's open/closed flag, a form's in-progress field values, a table's sort column): plain `useState`/`useReducer` in the component that owns it. Don't lift it further than the component(s) that actually need it.
- **Cross-cutting UI state that isn't server data** (rare — e.g. a global snackbar/toast queue): a small React Context, colocated with what it serves. Only introduce one when a second, unrelated component genuinely needs the same state — not preemptively.

Function components and hooks only. No class components.

## 3. Module Layout

```
frontend/
  .storybook/
    main.ts
    preview.ts
  src/
    api/
      client.ts            # thin fetch wrapper: base URL, JSON parsing, typed error mapping (404/422/503 -> ApiError)
      types.ts              # generated from the committed backend/openapi.json — never hand-edited
      stocks.ts               # typed endpoint functions: getStockAnalysis(ticker), getStockHistory(ticker, params)
      portfolio.ts
    theme/
      theme.ts              # MUI theme: palette (incl. semantic BUY/SELL/HOLD + risk-breach colors), typography
    utils/
      format.ts             # domain-agnostic pure-function display helpers (humanizeSnakeCase, formatNullableNumber) shared across features
    components/
      common/                # generic, reusable, presentational, domain-agnostic — every one exposed via Storybook
        PageHeader/
          PageHeader.tsx
          PageHeader.stories.tsx
          PageHeader.test.tsx
        StatCard/
        SignalBadge/          # BUY/SELL/HOLD colored chip
        ConfidenceGauge/       # 0-100 with Low/Medium/High band coloring (Analyse.md §6)
        PercentChange/          # colored +/- percentage display
        DataTable/               # thin MUI Table wrapper: sortable columns, empty state built in
        LoadingState/
        ErrorState/               # renders an ApiError (404/422/503) with a human-readable message per case
        EmptyState/
        ConfirmDialog/
      layout/                 # app shell, not reusable outside this app — no stories
        AppShell.tsx           # MUI AppBar + persistent nav
        NavDrawer.tsx
    features/                # one folder per domain area; owns its hooks + feature-specific components
      portfolio/
        hooks/
          usePortfolio.ts        # useQuery wrapping api/portfolio.ts#getPortfolio
          usePortfolioRisk.ts
          useAddPosition.ts        # useMutation, invalidates portfolio + risk queries on success
          useDeletePosition.ts
        components/
          PositionsTable.tsx        # built on common/DataTable
          AddPositionDialog.tsx
          RiskPanel.tsx               # total_open_risk_pct, 6% breach banner, per-position exit_flags
      stocks/
        hooks/
          useStockAnalysis.ts
          useStockHistory.ts
          useIndicatorHistory.ts        # GET /.../indicators — shared by PriceChart's overlay and frontend-oscillator-chart
        components/
          SignalSummary.tsx            # SignalBadge + ConfidenceGauge + confidence_breakdown table
          ScreensPanel.tsx                # Tide/Impulse/Wave/Trigger structured display
          IndicatorsPanel.tsx               # latest ema_13/ema_26/macd_histogram/bull_power/bear_power, as data — not a chart overlay (see §5)
          PriceChart.tsx                     # Lightweight Charts candlestick wrapper over /history, with an EMA13/EMA26 + BUY/SELL signal overlay from /indicators (see §5)
    pages/                  # route-level composition ONLY — layout + hooks + components, no business logic, no direct fetch() calls
      DashboardPage.tsx
      PortfolioPage.tsx
      StockDetailPage.tsx
    App.tsx                # router setup
    main.tsx
  tests/
    mocks/
      handlers.ts           # MSW handlers mirroring API.md, including every error case in API.md's "Error Cases to Cover in Tests"
      server.ts
    e2e/                   # Playwright specs -- real browser, real backend+frontend, no mocking (see Testing.md#end-to-end-playwright)
      dashboard.spec.ts
      navigation.spec.ts
      portfolio.spec.ts
      stock-analysis.spec.ts
  vite.config.ts
  playwright.config.ts
  tsconfig.json
  package.json
```

### Structure rules

- **Pages are thin.** A page file composes hooks + components and handles routing concerns (URL params, navigation) — it does not contain fetch logic, business rules, or markup beyond layout. If a page file is doing real work, that work belongs in a `features/<domain>/` hook or component instead.
- **`components/common/` is domain-agnostic.** A component belongs there only if it doesn't know what a "position" or a "signal" is — `SignalBadge` takes a `signal: 'BUY' | 'SELL' | 'HOLD'` prop, it doesn't fetch or know about the Triple Screen. Anything that references portfolio/stock domain concepts belongs under `features/<domain>/components/`, not `common/`. This isn't just a build-time aspiration — `pr-reviewer` explicitly checks every new/changed component's placement at review time (see `.claude/agents/pr-reviewer.md`), flagging both a domain-agnostic component stuck under `features/` and a near-duplicate that should have been consolidated into one shared `common/` component instead of copy-pasted across features.
- **`utils/` is for domain-agnostic *non-component* helpers.** The placement test mirrors `components/common/`'s but for plain functions: domain-agnostic (doesn't reference a feature's domain concepts) and not a component (no props, no rendering, no Storybook story) → `utils/`; domain-agnostic and a component → `components/common/`; references a feature's domain concepts (a "position", a "signal", a Triple Screen field) → `features/<domain>/`, colocated with the components/hooks that use it. `utils/format.ts`'s `humanizeSnakeCase`/`formatNullableNumber` are the motivating example: pure display helpers consumed by both `features/stocks` and `features/portfolio`, with no props/rendering to give them a Storybook story, so neither `features/<domain>/` nor `components/common/` fit.
- **One component per file**, named the same as the file, default-exported. A component's test and (for `common/`) story file are colocated in the same folder, not in a parallel `__tests__/`/`stories/` tree.
- **Hooks wrap exactly one API concern each** and live under the feature they serve (`features/portfolio/hooks/usePortfolio.ts`), not in a single catch-all `hooks/` folder — this keeps a feature's data layer next to the components that use it, and keeps `git blame`/navigation scoped to one domain at a time.
- **No default barrel-exporting `index.ts` re-exports for the sake of it** — import components/hooks from their actual file. A barrel is fine only where it demonstrably reduces real import noise (e.g. `components/common/index.ts` re-exporting every common component, since those are meant to be reused broadly).

## 4. Storybook: the common component library

Every component under `components/common/` **must** have a `.stories.tsx` covering its meaningful variants and states (e.g. `SignalBadge` gets a story per signal value; `ErrorState` gets a story per error case it renders; `DataTable` gets an empty-state story). This is what "reused and exposed and tracked by Storybook" means in practice — Storybook is the living catalog of the app's reusable UI, not a demo built after the fact. A new `common/` component isn't done until its story exists.

Feature-specific components (`features/<domain>/components/`) and pages do **not** get stories — they're wired to real hooks/data and are covered by component tests (with MSW), not Storybook. Storybook is for the domain-agnostic, reusable layer only.

`yarn build-storybook` must succeed as part of CI-equivalent verification (see `test-90`-style closing pass) — a component whose story is broken is exactly the kind of regression this exists to catch before it reaches a page.

## 5. Chart & indicator display: what the backend actually supports

`GET /api/stocks/{ticker}/history` returns raw OHLCV bars only — no indicator values. `GET /api/stocks/{ticker}/analysis` returns indicator values for the *latest* bar only (`ema_13`, `ema_26`, `macd_histogram`, `bull_power`, `bear_power`) — not a historical series. **Decision: the frontend does not recompute Elder's indicators in TypeScript to backfill a historical overlay.** Doing so would duplicate the backend's indicator math in a second language with no test-cross-checking, directly against the project's "confidence scores and signals are computed entirely in the backend... one place, testable once" principle (`Architecture.md` §3) — and the same reasoning extends to indicator math generally, not just final scoring.

`GET /api/stocks/{ticker}/indicators` (see [API.md](API.md#get-apistocksstickerindicators)) closes this gap: for a given `range`, it returns `ema_13`, `ema_26`, `macd_histogram`, `bull_power`, `bear_power`, `stochastic_k`, `force_index_2ema`, `channel_upper`/`channel_lower` (the Autoenvelope/channel band, `backend-channel-envelope-exposure`), and the resulting `signal`/`confidence`/`confidence_band` (Analyse.md §4-5), one entry per daily bar, oldest first — reusing `app.signals.engine.analyse` per bar rather than a second indicator implementation.

`PriceChart.tsx` fetches this via the shared `useIndicatorHistory` hook (`features/stocks/hooks/useIndicatorHistory.ts`) and overlays it on the candlestick series using Lightweight Charts' own native primitives rather than a custom-drawn overlay: `ema_13`/`ema_26` as two `LineSeries`, plus a `createSeriesMarkers`-based BUY/SELL arrow at each bar where the signal actually *changed* (not one marker per bar carrying that signal — see the `frontend-chart-signal-overlay` task's `decisions` entry for the full rationale, including why the overlay is daily-interval-only). `IndicatorsPanel.tsx` remains the separate latest-bar-only snapshot from `/analysis`, shown alongside the chart rather than on it.

`PriceChart.tsx` also draws `channel_upper`/`channel_lower` as two dashed `LineSeries` (Elder's Autoenvelope/channel band, ch. 41 — see `channelHelp` in `metricHelpContent.ts`), plus a shaded "value zone" between `ema_13`/`ema_26` (`frontend-channel-overlay`). Lightweight Charts has no native primitive for filling the region *between* two arbitrary line series (only line-to-pane-bottom), so the value zone is built from two `AreaSeries`: one filling from the pointwise-higher EMA down to the pane bottom in a translucent tint, and a second — added after, so it renders on top — repainting everything below the pointwise-lower EMA in the chart's own opaque background color, leaving only the true zone between the two EMAs visibly tinted (see the task's own `decisions` entry, including the light-mode-only assumption this relies on). Both new overlays get a `common/MetricHelp` affordance in a small legend row next to the range/interval controls, per this app's established explanatory pattern (`features/stocks/components/metricHelpContent.ts`).

`PriceChart.tsx` also draws `GET /api/stocks/{ticker}/analysis`'s `support_resistance_zones` (via its own `useStockAnalysis(ticker)` call — deduped by TanStack Query against `StockDetailPage`'s own use of the same query key, since both mount for the same ticker; `useStockAnalysis` sets an explicit `staleTime: 60_000` so that dedup holds even though `PriceChart` mounts strictly *after* `StockDetailPage`'s own copy of the query has already resolved, not concurrently with it like `useIndicatorHistory`'s `PriceChart`/`OscillatorChart` sibling pair above) as horizontal shaded bands, one `BaselineSeries` per zone (`frontend-support-resistance-overlay`). Unlike the value-zone's two-`AreaSeries` fill/mask technique, a `BaselineSeries` fills only between its plotted line and a fixed `baseValue` price, so a single series renders a self-contained, precisely-bounded band with no opaque masking series at all. Fill opacity scales with `strength_score` (a weak zone barely tints the chart, a major one reads as clearly more prominent); a zone whose `broken` flag shows its role has flipped is drawn dashed rather than solid. Independent of the EMA/channel/marker overlay above — not gated on daily-only `overlayEnabled`, since a support/resistance price level is interval-agnostic. A zone's most recent `false_breakout` episode (Elder ch. 18, "a specific, high-value trade setup") gets its own marker plus a dashed `createPriceLine` at `extreme_price`, the book's explicit stop-placement reference. `supportResistanceZoneHelp`/`falseBreakoutHelp` (`metricHelpContent.ts`) extend the same legend-row `common/MetricHelp` pattern the channel/value-zone pair above established.

Two independent effects now add fill series onto the same pane (the value-zone `AreaSeries` pair, and these zone `BaselineSeries` bands) — `PriceChart.tsx` keeps its candlestick series pinned above all of them via `bringSeriesToFront` (`utils/chart.ts`), which moves the series to the end of `chart.panes()[0].getSeries()` dynamically rather than a hardcoded `setSeriesOrder` index (the original PR #151 fix's own approach), since a hardcoded index from one effect goes stale the moment the other effect changes how many series exist in the pane — see `bringSeriesToFront`'s own doc comment and the `frontend-support-resistance-overlay` task's `decisions` entry.

`OscillatorChart.tsx` (`frontend-oscillator-chart`) is the historical-trend counterpart, fed by the same `useIndicatorHistory` hook (deduplicated by TanStack Query when mounted alongside `PriceChart` for the same ticker/range — the request is only made once): `stochastic_k`, `force_index_2ema`, and `macd_histogram` (daily-cadence, the Impulse System's own slope input — not Screen 1's weekly MACD-H) each get their own Lightweight Charts pane (native multi-pane support, one `IChartApi` instance, `chart.addSeries(definition, options, paneIndex)`), stacked beneath one another and sharing the same time axis. Stochastic %K gets dashed reference lines at the documented 30/70 oversold/overbought thresholds (Analyse.md §4); Force Index and MACD Histogram get a dotted zero baseline instead, since Analyse.md doesn't document a numeric threshold for either. `StockCharts.tsx` composes `PriceChart` + `OscillatorChart`, mirroring `PriceChart`'s own range/interval selection into `OscillatorChart` via optional `onRangeChange`/`onIntervalChange` callback props on `PriceChart` (rather than converting it into a fully controlled component) so both panes always plot the same window, and `OscillatorChart` is gated on `interval === 'daily'` the same way `PriceChart`'s own overlay is.

## 6. Key Dependencies

| Package | Purpose |
|---|---|
| `react`, `react-dom` | UI |
| `vite` | Build/dev server |
| `typescript` | Required language |
| `@mui/material`, `@mui/icons-material`, `@emotion/react`, `@emotion/styled` | Material Design components + required peer deps |
| `react-router-dom` | Client-side routing (Dashboard / Portfolio / Stock Detail) |
| `@tanstack/react-query` | Server-state fetching/caching — the *only* data layer, see §2 |
| `lightweight-charts` (TradingView) | Candlestick chart (`PriceChart.tsx`) |
| `vitest` + `@testing-library/react` | Component/unit testing (see [Testing.md](Testing.md)) |
| `msw` (Mock Service Worker) | Mocks the backend API in tests, so no test ever hits a real network call |
| `storybook` (+ `@storybook/react-vite`, a11y/interactions addons) | Catalogs and tests `components/common/` in isolation |
| `openapi-typescript` (dev dependency, generator only) | Generates `api/types.ts` from `backend/openapi.json` |
| `@fontsource/inter` | Self-hosted Inter font files, loaded once in `main.tsx` (and again in `.storybook/preview.tsx`) so the theme's declared font family actually renders |
| `@playwright/test` | Real-browser end-to-end suite (`tests/e2e/`) — a separate, un-mocked category from `vitest`/`msw` above, see [Testing.md](Testing.md#end-to-end-playwright) |

Explicitly **not** used: Redux, Redux Toolkit, MobX, Zustand, Recoil, Jotai, or any other client-state library (see §2).

**No `resolutions` entry for `openapi-typescript`'s `typescript` peer.** `openapi-typescript@7.13.0`'s published `peerDependencies` still pin `typescript@^5.x`, which conflicts with this project's own `typescript@~6.0.2` — no released `openapi-typescript` version has widened that range yet (tracked upstream: [openapi-ts/openapi-typescript#2723](https://github.com/openapi-ts/openapi-typescript/issues/2723)). Under npm this genuinely required an `overrides` entry (`frontend-verify-npm-install`, PR #115) to force the resolver past an `ERESOLVE` failure. During the npm→Yarn migration (`migrate-yarn2`, PR #116) that entry was translated to Yarn's `resolutions` syntax (`"openapi-typescript/typescript": "$typescript"`) — but Yarn's `resolutions` only rewrites real dependency edges, and under Yarn `typescript` is only a `peerDependency` of `openapi-typescript`, not a real dependency edge, so the translated entry never actually did anything: `yarn install` emitted the same `YN0060` peer warning for `openapi-typescript`'s stale `^5.0.0` request with the entry present, and removing it (`migrate-yarn2-followups`) changed neither `yarn.lock` nor the resolved `node_modules/typescript` — confirmed by diffing both before and after the removal. It was therefore deleted rather than kept as inert config, closing the open question `migrate-yarn2`'s review had raised. The `YN0060` warning itself is expected and harmless under Yarn regardless — a peer-range notice, not a resolution failure — and the `typescript@6.0.3` actually resolved is verified working end to end: a fresh install is clean and `generate:api-types` regenerates `src/api/types.ts` byte-for-byte identical to the committed file (`frontend-verify-npm-install`'s `decisions`; reconfirmed after the `resolutions` removal in `migrate-yarn2-followups`'s `decisions`), and a synthetic-schema smoke test covering `oneOf`/`allOf`/`readOnly`/`webhooks` (constructs the current `backend/openapi.json` doesn't exercise) also generates correct, `tsc --strict`-clean output under `typescript@6.0.3` (`frontend-verify-npm-install-followups`'s `decisions`).

## 7. API Contract Alignment

`api/types.ts` types must match the backend's Pydantic response schemas exactly (see [API.md](API.md)). Generate these types from the **committed** `backend/openapi.json` snapshot (see [API.md §Contract Snapshot & Parallel Development](API.md#contract-snapshot--parallel-development)) — e.g. via `openapi-typescript backend/openapi.json -o src/api/types.ts` — rather than hand-maintaining a parallel definition or requiring the Python backend to be running. This is what lets frontend and backend implementation proceed at the same time: every route's request/response/error shape is already final in that file even before its handler logic exists.

`api/client.ts` maps every documented error case (see [API.md's "Error Cases to Cover in Tests"](API.md#error-cases-to-cover-in-tests)) to a typed `ApiError` with a `status` and `detail`, so `ErrorState` can render a distinct, human-readable message per case (unknown ticker vs. insufficient history vs. provider unavailable) rather than one generic "something went wrong."

## Testing Notes

- Every component that renders API data is tested with **MSW-mocked responses**, including every error/empty state in [API.md's error cases](API.md#error-cases-to-cover-in-tests) — not just the happy path.
- `SignalBadge`/`ConfidenceGauge` get explicit tests for boundary values (0%, 100%, the Low/Medium/High band edges from Analyse.md §6) since off-by-one band errors are easy to introduce.
- Every `components/common/` component has both a test and a story (§4); a component with one but not the other is incomplete.
- No test hits the real backend or a real market data provider — see [Testing.md](Testing.md) for the coverage gate and CI wiring.
