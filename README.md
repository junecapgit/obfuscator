# obfus (Python port)

Python implementation of the local-first code obfuscator. Same CLI, behavior and
mapping/encryption formats as the Go version in the repository root (`..`).

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Usage

```powershell
obfus input.js -o safe.js --map map.json
obfus restore safe.js -o restored.js --map map.json
obfus ai input.py -o ai_safe.py
obfus light plan.diff -o safe.diff --map map.json [--keys id,name]
obfus light restore safe.diff -o restored.diff --map map.json
# or without installing the script:
python -m obfus --help
```

### Light mode

For Terraform files, `terraform plan` output, and GitHub diffs. It works on any text file
(no extension restriction) and replaces only the quoted values of attributes named `id`/`name`
or ending in `_id`/`_name` (plus plurals such as `subnet_ids = [...]`), including `-`/`+`/`~`
diff lines and `"old" -> "new"` changes:

```text
+ subnet_id   = "subnet-0abc"      ->  + subnet_id   = "obf_id_1"
+ server_name = "server_name_dev"  ->  + server_name = "obf_name_1"
```

Everything else is untouched: other attributes, tags, `(known after apply)`, and values with
`${...}` interpolation. Identical values share a placeholder, and `light restore` reverses it using
the mapping (plain or encrypted, per `.obfusconfig.json`). `--keys arn,key` replaces the suffix list.

Supports `.js`, `.py`, `.tf`. Optional `.obfusconfig.json` (cwd) enables encrypted
mappings (AES-256-GCM); see the top-level README. Encrypted mappings are
interchangeable with the Go version.

## Tests

```powershell
pytest
```

## Layout

| Module | Go equivalent |
|---|---|
| `obfus/cli.py` | `cmd/obfus` |
| `obfus/tokenizer/` | `core/tokenizer` |
| `obfus/mapping.py` | `core/mapping` |
| `obfus/transform.py` | `core/transform` |
| `obfus/storage.py` | `core/storage` |
| `obfus/security.py` | `core/security` |
| `obfus/config.py` | `core/config` |

Files are read/written byte-faithfully (UTF-8 + `surrogateescape`, no newline translation).
