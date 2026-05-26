# Meeting Agent Web UI

Next.js frontend for the Meeting AI Agent demo. It supports meeting upload,
result review, worker roster management, meeting history, feedback submission,
and Google Calendar sync through the backend proxy.

## Development

```bash
npm install
npm run dev
```

The app expects the FastAPI backend at `http://localhost:8000` by default. Set
`NEXT_PUBLIC_API_URL` or `BACKEND_API_URL` when using a different backend URL.

## Checks

```bash
npm run lint
npm run build
```
