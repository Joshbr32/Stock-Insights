# si_controller/redaction.py
**Purpose:** `redact_line(line)` masks secret-looking values in captured server output before it is stored or shown.
**Used by:** `supervisor.ServerProcess._read`.  **Depends on:** `re`.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `redact_line(line)` | func | Replaces with `[redacted]`: the value of any key containing password, passwd, pwd, token, secret, api key, authorization or credential (`k=v`, `k: v`, `"k": "v"`, ODBC `PWD=`); `Bearer`/`Basic` credentials; `scheme://user:pass@`. Leaves `None`, `null`, `true`, `false` and empty values alone. |

## How to change it safely
Add a case to `test_redaction` for every new pattern. Over-redacting a trailing quote or bracket is acceptable; missing a secret is not.

## Map
- 1-26 patterns
- 28-end `redact_line`
