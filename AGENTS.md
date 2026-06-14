# Trade3

Local AI-assisted intraday futures decision terminal.

## Product Boundary

- Scan up to 20 liquid USDT perpetual futures.
- Support long and short trade plans on 5m/15m with 1h/4h context.
- Use deterministic market-data and risk calculations before LLM analysis.
- Use local Ollama models for explanation and chart review.
- Use Ruflo for development and analysis-agent orchestration.
- The human user always decides whether to enter a trade.
- Do not add order placement, exchange trading permissions, or withdrawal access.
- A model-generated score is not a calibrated win probability.

## Quick Start

### Setup
```bash
npm install && npm run build
```

### Test
```bash
npm test
```

## Agent Behavior

### Token Budget
- Prefer `local_agents/reports/` over repeating repository exploration.
- Delegate bounded analysis, planning, and diff review to the local Ollama queue.
- Keep cloud-agent responses and progress updates concise.
- Use cloud models for implementation only when the local critic sets
  `escalate_to_codex=true` or when deterministic verification fails.
- Never start the generic Ruflo daemon; its headless workers invoke cloud AI.

### Code Standards
- Keep files under 500 lines
- No hardcoded secrets or credentials
- Validate input at system boundaries
- Use typed interfaces for public APIs
- Keep scoring and position sizing deterministic and unit tested
- Store timestamps in UTC
- Record the inputs and version of every generated trade plan

### File Organization
- `/src` - Source code files
- `/tests` - Test files
- `/docs` - Documentation
- `/config` - Configuration files

## Skills

| Skill | Purpose |
|-------|---------|
| `$swarm-orchestration` | Multi-agent coordination for complex tasks |
| `$memory-management` | Pattern storage and semantic search |

## Security Rules

- NEVER commit .env files or secrets
- Exchange integrations are market-data only unless the user explicitly changes the product boundary
- Never request API withdrawal permission
- Never expose Ollama or internal services to the public network by default
- Always validate user inputs
- Prevent directory traversal attacks
- Use parameterized queries for databases
- Sanitize output to prevent XSS

## Links

- Documentation: https://github.com/ruvnet/ruflo
