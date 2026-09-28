# MedIntel Frontend

Next.js 15 + React 19 + TypeScript + Tailwind CSS 4 frontend for the MedIntel
medical document intelligence platform.

## Run (dev)

```bash
npm install
npm run dev          # http://localhost:3000 (backend on :8000)
```

Set `NEXT_PUBLIC_API_URL` to point at a different backend (defaults to
`http://localhost:8000/api/v1`).

## Structure

- `src/lib/api.ts` — typed API client (all endpoints + response types)
- `src/lib/format.ts` — display helpers (bytes, dates, status styles)
- `src/components/` — auth context, shared UI shell (cards, empty states, spinners)
- `src/app/` — pages: landing, login, dashboard, upload, document viewer
  (overview/ask/summaries/extractions/sections/pages/timeline), compare

## Build

```bash
npm run build        # production build (standalone output)
npm run start
```
