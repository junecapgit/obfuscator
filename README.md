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
(no extension restriction) and replaces quoted values of `id` attributes and any attribute key
containing `name` (including object keys such as `"Name"`). It also obfuscates IPv4/IPv6 addresses,
CIDRs, and IPv4 subnet masks wherever they appear, including in string values and diff text.
Diff lines (`-`/`+`/`~`) and `"old" -> "new"` changes are supported:

```text
+ subnet_id   = "subnet-0abc"      ->  + subnet_id   = "obf_id_1"
+ server_name = "server_name_dev"  ->  + server_name = "obf_name_1"
  cidr_block  = "10.20.0.0/16"     ->    cidr_block  = "obf_subnet_1"
  public_ip   = "203.0.113.7"      ->    public_ip   = "obf_ip_1"
```

Other attributes and values with `${...}` interpolation remain untouched. Identical values share a
placeholder, and `light restore` reverses it using the mapping (plain or encrypted, per
`.obfusconfig.json`). `--keys arn,key` sets the attribute suffix list; name-key and IP matching
remain enabled.

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
