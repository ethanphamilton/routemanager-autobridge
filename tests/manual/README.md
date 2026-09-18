# Manual scripts

Hand-run diagnostics. **None of these are collected by pytest** — they are
named so they fall outside `python_files = ["test_*.py"]`, and `pytest tests/`
ignores them. Run them explicitly, from the repository root.

| Script | Touches live systems? | What it does |
| --- | --- | --- |
| `workwave_live_submit.py` | **Yes — writes to WorkWave** | Submits three real orders (standard / drain / fill) to the configured territory to confirm connectivity and payload shape. Delete them from the WorkWave dashboard afterwards. |
| `live_zoho_test.py` | Reads from Zoho | Pulls live CRM records through the generator and reports what would be produced. Never submits to WorkWave. |
| `regression_completed_handlers.py` | No | Asserts expected annual visit counts across every membership handler. The closest thing to a full-pipeline regression check. |
| `analyze_bimonthly.py` | No | Prints bi-monthly scheduling edge cases for inspection. |

Both live scripts read credentials from `functions/rm_autobridge/.env`, which is
gitignored and must be created locally — see `.env.example`.
