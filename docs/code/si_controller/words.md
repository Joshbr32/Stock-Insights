# si_controller/words.py
**Purpose:** Plain-sentence wording of `/status`, shared by the CLI and the manager: the verdict, state words, durations, service lines.
**Used by:** `cli.py`, `si_manager/window.py`, `si_manager/pages.py`, tests.  **Depends on:** nothing.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `STATE_WORDS`, `SERVICE_WORDS` | dict | State to word (`backoff` is "Restarting soon"). |
| `duration(seconds)` | func | `42 s`, `5 min`, `3 h 12 min`, `2 days 1 h`; "" for None. |
| `state_tone(state, health_ok)` | func | `good`, `warn`, `bad` or `busy` for a server state. |
| `verdict(status)` | func | `(tone, sentence)`: "The server is running and healthy.", "The server is not running.", "The server is waiting to start: …", "The server stopped unexpectedly and restarts in 15 s.", and for None "Can't reach the controller, so the server's state is unknown." |
| `service_line(label, svc)` | func | `(tone, "SQL Server (MSSQL$X): running")`; `missing` and `unknown` are `idle`. |

## How to change it safely
Pure and tested (`test_words`). Sentence case, no all-caps, one fact per sentence (design system, "Words").

## Map
- 1-24 word tables
- 26-51 `duration`, `state_tone`
- 53-85 `verdict`
- 87-end `service_line`
