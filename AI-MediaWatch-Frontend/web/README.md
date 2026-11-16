# AI Media Watch dashboard

React 18, TypeScript, Vite 5, Tailwind CSS, TanStack Query, React Router,
Recharts, Cytoscape, Lucide icons and react-markdown.

See the [root README](../../README.md) for complete Windows installation
and local AI setup. From this directory:

```powershell
npm ci
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
npm run build
```

The development server proxies `/api` to `http://127.0.0.1:8003`.
Run the AIMW API and Local Agent as described in the root README.
Generated `dist/` and `node_modules/` are not source and are ignored.

Optional `VITE_API_BASE` overrides the same-origin API prefix.
`VITE_API_KEY` supplies the client API-key header (default: `dev`).
All `VITE_*` values are exposed in the browser bundle; never put private
credentials in them. Keep local overrides in an ignored `.env.local`.

The dashboard includes analysis, queue, reports, entity graphs,
investigation, feedback and metrics views. Displayed model confidence is
not a calibrated probability; metrics views do not establish performance
without an independently labeled dataset. See the root README limitations.
