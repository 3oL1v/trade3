# Overnight local research

The overnight runner uses two sequential roles on the local Ollama model:

- `proposer` returns bounded JSON parameters for the existing V2 strategy family;
- `critic` accepts or corrects those parameters;
- the Python replay engine, not the model, calculates every trade and metric.

Ruflo registers the two roles and the research task. The model has no shell tools,
exchange credentials, order API, or permission to edit strategy code.

The search does not stop after the first profitable trial. It runs until either
`max_trials` or `max_hours` is reached. Training and validation metrics are visible
to the agents. The later holdout window is only evaluated for the final leaders.

Start:

```powershell
.\scripts\start_overnight_research.ps1
```

Monitor or stop:

```powershell
.\scripts\status_overnight_research.ps1
.\scripts\stop_overnight_research.ps1
```

Results are stored under `research/overnight/runs/`. They are research artifacts,
not trading calls. A positive holdout still requires review on more symbols,
walk-forward periods, funding data, and forward observation before any real risk.
