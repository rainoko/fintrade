# Frontend Architecture

TypeScript (required — no plain JS), React, Vite. See [Architecture.md](../Architecture.md) for how this fits the overall system.

## 1. Why React (not Astro), why TypeScript

This is a stateful dashboard: live portfolio data, per-stock charts, frequent re-fetching/re-rendering, filters and interactions. Astro's island architecture is built for mostly-static, content-first sites (blogs, marketing, docs) with light interactivity — the opposite of this app's profile. React fits a data-dense interactive dashboard.

TypeScript is required project-wide: the API boundary (signals, confidence breakdowns, portfolio positions, risk warnings) is exactly the kind of shape-sensitive data where a silent `undefined`/typo bug is costly, and generating types from the backend's Pydantic schemas keeps both sides honest at compile time.

## 2. Module Layout

```
frontend/
  src/
    api/
      client.ts         # thin fetch wrapper
      types.ts           # generated/mirrored from backend Pydantic schemas (see API.md)
      stocks.ts           # typed endpoint functions
      portfolio.ts
    components/
      charts/
        PriceChart.tsx        # Lightweight Charts wrapper: candlesticks + EMA overlay
        IndicatorPane.tsx      # MACD / Stochastic / Force Index sub-panes
      signals/
        SignalBadge.tsx         # BUY/SELL/HOLD + confidence %
        ConfidenceBreakdown.tsx  # per-component score display (Analyse.md §6)
      portfolio/
        PositionTable.tsx
        RiskWarningBanner.tsx    # 2%/6% rule breaches
    hooks/
      useStockAnalysis.ts    # React Query hook wrapping api/stocks.ts
      usePortfolio.ts
    pages/
      Dashboard.tsx
      StockDetail.tsx
      Portfolio.tsx
    App.tsx
    main.tsx
  tests/
    unit/            # component tests, hooks
    mocks/            # MSW handlers mirroring API.md contract
  vite.config.ts
  tsconfig.json
```

## 3. Key Dependencies

| Package | Purpose |
|---|---|
| `react`, `react-dom` | UI |
| `vite` | Build/dev server |
| `typescript` | Required language |
| `@tanstack/react-query` | Server-state fetching/caching — avoids hand-rolled loading/error state per view |
| `lightweight-charts` (TradingView) | Candlestick + indicator-pane charts |
| `vitest` + `@testing-library/react` | Component/unit testing (see [Testing.md](Testing.md)) |
| `msw` (Mock Service Worker) | Mocks the backend API in tests, so no test ever hits a real network call |

State management beyond server state (React Query) stays in local component state / React context — no Redux/Zustand unless a concrete cross-page client-state need shows up. Don't add it preemptively.

## 4. Chart Integration

`PriceChart.tsx` wraps `lightweight-charts`: candlestick series for OHLC, line series overlay for EMA(13)/EMA(26), and marker annotations for BUY/SELL trigger points. `IndicatorPane.tsx` renders MACD-Histogram, Stochastic, and Force Index as separate synced panes below the price chart — matching how Elder's own charting layout works (price on top, oscillators below).

## 5. API Contract Alignment

`api/types.ts` types must match the backend's Pydantic response schemas exactly (see [API.md](API.md)). Generate these types from the **committed** `backend/openapi.json` snapshot (see [API.md §Contract Snapshot & Parallel Development](API.md#contract-snapshot--parallel-development)) — e.g. via `openapi-typescript backend/openapi.json -o src/api/types.ts` — rather than hand-maintaining a parallel definition or requiring the Python backend to be running. This is what lets frontend and backend implementation proceed at the same time: every route's request/response/error shape is already final in that file even before its handler logic exists.

## Testing Notes

- Every component that renders API data is tested with **MSW-mocked responses**, including error/empty states (no positions yet, indicator data unavailable, low-confidence signal) — not just the happy path.
- `SignalBadge`/`ConfidenceBreakdown` get explicit tests for boundary values (0%, 100%, the Low/Medium/High band edges from Analyse.md §6) since off-by-one band errors are easy to introduce.
- No test hits the real backend or a real market data provider — see [Testing.md](Testing.md) for the coverage gate and CI wiring.
