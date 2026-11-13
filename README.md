# Grimoire Wizard

Grimoire Wizard is split into independently deployable applications:

- [Backend](backend/README.md): PDF ingestion and the conversation API.
- [Frontend](frontend/README.md): Streamlit chat client for the implemented conversation API.
- [Architecture decisions](project_decisions/architecture.md) and
  [backend endpoint contract](project_decisions/backend_endpoints.md).

Run backend commands from `backend/`. Copy `backend/.env.example` to `.env` and
configure the Supabase credentials and Gemini API key there. Never expose the
Supabase service-role key in frontend code.
