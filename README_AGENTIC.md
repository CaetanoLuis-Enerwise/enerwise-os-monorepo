```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "..."
$env:ENERWISE_AGENT_MODEL = "gpt-5-mini"
```

```powershell
.\venv\Scripts\python.exe -m agentic_loops.cli run --task "Analisa o benchmark e propoe o proximo piloto" --thread-id pilot-001
```

```powershell
.\venv\Scripts\python.exe -m agentic_loops.cli run --task "Cria um plano de integracao OT" --thread-id ot-001 --approval-mode always
```

```powershell
.\venv\Scripts\python.exe -m agentic_loops.cli resume --thread-id ot-001 --approve
.\venv\Scripts\python.exe -m agentic_loops.cli resume --thread-id ot-001 --reject
.\venv\Scripts\python.exe -m agentic_loops.cli resume --thread-id ot-001 --edit "Resposta revista"
```

```powershell
.\venv\Scripts\python.exe -m agentic_loops.cli status --thread-id ot-001
.\venv\Scripts\python.exe -m agentic_loops.cli memory --limit 20
```

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
curl.exe -X POST http://127.0.0.1:8000/agentic/run -H "Content-Type: application/json" -d "{\"task\":\"Analisa o estado operacional\",\"thread_id\":\"api-001\",\"approval_mode\":\"risk\"}"
curl.exe -X POST http://127.0.0.1:8000/agentic/resume -H "Content-Type: application/json" -d "{\"thread_id\":\"api-001\",\"decision\":\"approve\"}"
curl.exe http://127.0.0.1:8000/agentic/threads/api-001
curl.exe http://127.0.0.1:8000/agentic/memory
```
