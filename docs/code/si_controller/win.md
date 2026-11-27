# si_controller/win.py
**Purpose:** ctypes wrappers (no psutil, no pywin32): a kill-on-close job object, a process's memory and CPU time, a Windows service's state.
**Used by:** `supervisor.py` (job, usage, service state, `machine_status`).  **Depends on:** `ctypes` (kernel32, advapi32).

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `IS_WINDOWS` | const | Every function returns a harmless value on other platforms. |
| `Job()` | class | `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: when the controller's handle closes (exit, crash, task ended) Windows ends the server too. `assign(handle)`, `terminate()`, `close()`. |
| `process_usage(handle)` | func | `{working_set_mb, private_mb, cpu_seconds}` or None. |
| `service_state(name)` | func | `running`, `stopped`, `starting`, `stopping`, `paused`, …, `missing` (error 1060) or `unknown`. Needs no special rights. |

## How to change it safely
Keep `argtypes`/`restype` declared for every call (handles are pointer-sized on 64-bit); struct sizes use `c_size_t`.

## Map
- 1-86 platform guard, structures, prototypes
- 88-122 `Job`
- 125-143 `process_usage`
- 146-end `service_state`
