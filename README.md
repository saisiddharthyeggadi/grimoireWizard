# Grimoire Wizard

Grimoire Wizard is split into independently deployable applications:

- [Backend](backend/README.md): PDF ingestion and the conversation API.
- [Frontend](frontend/README.md): Streamlit chat client for the implemented conversation API.
- [Angular frontend](frontend-angular/README.md): browser-based chat client in a
  separate folder; Streamlit remains the fallback.
- [Architecture decisions](project_decisions/architecture.md) and
  [backend endpoint contract](project_decisions/backend_endpoints.md).

## How to run either frontend

1. Run the backend from `backend/` with its values in an ignored `.env` file.
   For authenticated use, set `AUTH_MODE=on`; never expose the service-role
   key in frontend code or chat.
2. To use the fallback, follow [the Streamlit instructions](frontend/README.md).
3. To use Angular, set `apiBaseUrl`, `supabaseUrl`, and `supabaseAnonKey` in
   `frontend-angular/src/environments/environment.ts`, then run `npm ci` and
   `npm start` from `frontend-angular/` and open `http://localhost:5173`.

The Angular frontend is an MVP with Google sign-in, document-library selection,
PDF previews, and citation navigation. Do not make it the default until it
passes the performance gate in `project_decisions/DECISIONS.md`. Authentication
and per-user RLS code are implemented but not production-verified: apply the
auth migration and pass the two-user isolation test before using production
data.
