create .env file with
---------------------
OPENAI_API_KEY="sk-proj.....ka"
SECRET_KEY=your-super-secret-jwt-key-change-in-production
SIMPLE_MODEL=gpt-4o-mini
ADVANCED_MODEL=gpt-4o

CMD Commands
------------
pip install -r requirements.txt
cd backend
uvicorn app:app --reload --port 8000
