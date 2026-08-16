# routes — the HTTP surface. Each file is one resource and exports a FastAPI
# APIRouter; main.py just includes them. Keep these thin — logic lives in
# services/ and the domain modules (auth.py, store.py, llm.py, ...).