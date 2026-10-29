# obfus (Python port)

Python implementation of the local-first code obfuscator. Same CLI, behavior and
mapping/encryption formats as the Go version in the repository root (`..`), with
enhanced support for directory-wide processing, `.gitignore` filtering, and expanded
Terraform file tokenization (`.tf`, `.tfvars`, `.hcl`, `.tfbackend`).

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Usage

### Single-File Mode

```powershell
obfus input.js -o safe.js --map map.json
obfus restore safe.js -o restored.js --map map.json
obfus ai input.py -o ai_safe.py
obfus light plan.diff -o safe.diff --map map.json [--keys id,name]
obfus light restore safe.diff -o restored.diff --map map.json
```

### Folder Mode

You can run `obfus` (either **full** or **light** mode) on an entire directory:

```powershell
# Full mode: produces duplicate folder in ./output (or specified location) with map.json
obfus ./my-infra -o ./safe-infra --map map.json
# Or default to output/ in the running directory:
obfus ./my-infra

# Light mode on a folder:
obfus light ./my-infra -o ./safe-infra --map map.json [--keys id,name]

# Restore a folder:
obfus restore ./safe-infra -o ./restored-infra --map map.json
obfus light restore ./safe-infra -o ./restored-infra --map map.json
```

- **.gitignore support**: If the folder has a `.gitignore` (including nested `.gitignore` files), files and folders matching `.gitignore` patterns are ignored and omitted from the duplicate structure.
- **Unified mapping**: When obfuscating a folder, a single shared mapping is maintained across all files so variable names and values remain consistent across files.
- **Duplicate structure**: Unsupported or non-code files (such as documentation) are copied as-is to preserve the exact directory tree.

### Verbose Mode

Pass `-v` or `--verbose` to display loaded configuration (`.obfusconfig.json`) and progress/status information. When running on a folder, it shows status and a list of converted files:

```powershell
obfus -v ./my-infra -o ./safe-infra --map map.json
```

Example output:
```text
Loaded .obfusconfig.json from C:\project\.obfusconfig.json:
{
  "tokens": ["SECRET_TOKEN"]
}
Status: converting folder './my-infra' -> './safe-infra'
Files converted:
  - main.tf
  - sub/app.py
Total files converted: 2
```

### Python Service API

You can also call the obfuscation service directly from Python code:

```python
from obfus import ObfuscatorService, obfuscate_folder, restore_folder

# Full obfuscation on a directory
out_dir, mapping = obfuscate_folder(
    input_dir="./my-infra",
    output_dir="./safe-infra",
    mode="full",
)

# Light mode on a directory
out_dir, mapping = obfuscate_folder(
    input_dir="./my-infra",
    output_dir="./safe-infra",
    mode="light",
    keys=["id", "name"],
)

# Restore a directory
restore_folder(
    input_dir="./safe-infra",
    output_dir="./restored-infra",
    map_path="./safe-infra/map.json",
    mode="full",
)
```

### Terraform Support

The Terraform tokenizer supports:
- `.tf` configuration files
- `.tfvars` and `*.auto.tfvars` variable definitions
- `.hcl` (e.g. `terragrunt.hcl`, `.terraform.lock.hcl`, Packer/Nomad configurations)
- `.tfbackend` backend configurations
- `.tf.json` and `.tfvars.json`
- `.terraformrc` and `.tofurc`

Terraform keywords and language literals (`resource`, `module`, `variable`, `output`, `locals`, `provider`, `data`, `terraform`, `check`, `import`, `moved`, `run`, `assert`, `var`, `local`, `count`, `each`, `self`, `path`, `true`, `false`, `null`) are preserved.

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

Supports `.js`, `.py`, `.tf`, `.tfvars`, `.hcl`, etc. Optional `.obfusconfig.json` (cwd) enables encrypted
mappings (AES-256-GCM); see the top-level README. Encrypted mappings are
interchangeable with the Go version.

## Configuration

Optional `.obfusconfig.json` in your current working directory allows configuring default directories, encryption settings, and known token strings and regex patterns:

```json
{
  "targetDir": "./safe-infra",
  "inputDir": "./my-infra",
  "encryption": {
    "enabled": false,
    "passwordEnv": "OBFUS_PASSWORD"
  },
  "tokens": [
    "John Smith",
    "ABC12345"
  ],
  "patterns": [
    "app-[dev|qa|prod]-\\d{3}"
  ],
  "patternsFile": "tokens.json"
}
```

- **`targetDir`** (or `outputDir`): Default target directory where duplicate obfuscated structures are placed when not passed on the CLI.
- **`inputDir`**: Default input directory to process if omitted from CLI arguments.
- **`encryption`**: Enables AES-256-GCM encrypted mappings (see root README for details).
- **`tokens`** / **`patterns`**: List of literal strings or regex patterns to obfuscate across files, strings, and comments. Supports bracket alternation syntax such as `app-[dev|qa|prod]-\d{3}`.
- **`patternsFile`** (or `tokensFile`): Path to a standalone configuration file (e.g. `tokens.json`) containing token strings and patterns.

### Known Token Strings & Patterns Config File

You can also use a dedicated config file (e.g. `tokens.json`) containing a list of strings and regex patterns:

```json
[
  "John Smith",
  "ABC12345",
  "app-[dev|qa|prod]-\\d{3}"
]
```

Pass it on the CLI with `--patterns` or `--config`:

```powershell
obfus ./my-infra -o ./safe-infra --map map.json --patterns tokens.json
```

Or reference it in `.obfusconfig.json`:

```json
{
  "patternsFile": "tokens.json"
}
```

## Tests

```powershell
pytest
```

## Layout

| Module | Purpose |
|---|---|
| `obfus/service.py` | High-level service API for file and folder obfuscation/restoration |
| `obfus/gitignore.py` | GitIgnore filtering supporting root and nested `.gitignore` files |
| `obfus/patterns.py` | Known token strings and regex pattern matching, obfuscation and restore |
| `obfus/cli.py` | CLI entry point |
| `obfus/tokenizer/` | Tokenizers for JS, Python, Terraform (`.tf`, `.tfvars`, `.hcl`, `.tfbackend`) |
| `obfus/light.py` | Light mode attribute/diff/IP-based obfuscation |
| `obfus/mapping.py` | Identifier and string mapping generation and inversion |
| `obfus/transform.py` | Token transformations |
| `obfus/storage.py` | Mapping serialization and deserialization (JSON and encrypted) |
| `obfus/security.py` | AES-256-GCM encryption |
| `obfus/config.py` | Configuration file handling |

Files are read/written byte-faithfully (UTF-8 + `surrogateescape`, no newline translation).
