import io

import pytest

from obfus.cli import run

JS_SOURCE = 'const customerId = "ABC123";\nconsole.log(customerId);\n'


def invoke(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(list(args), out, err)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OBFUS_PASSWORD", raising=False)


def test_help_flag_returns_success():
    code, out, err = invoke("--help")
    assert code == 0 and "usage:" in out and not err


def test_subcommand_help_returns_success():
    code, out, _ = invoke("restore", "--help")
    assert code == 0 and "usage:" in out


def test_no_args_prints_usage_to_stderr():
    code, out, err = invoke()
    assert code == 1 and not out and "usage:" in err


def test_round_trip_obfuscate_and_restore(tmp_path):
    (tmp_path / "input.js").write_bytes(JS_SOURCE.encode())

    assert invoke("input.js", "-o", "safe.js", "--map", "map.json")[0] == 0
    safe = (tmp_path / "safe.js").read_text()
    assert "customerId" not in safe and "ABC123" not in safe

    assert invoke("restore", "safe.js", "-o", "restored.js", "--map=map.json")[0] == 0
    assert (tmp_path / "restored.js").read_bytes() == JS_SOURCE.encode()


def test_round_trip_preserves_crlf_and_non_ascii_bytes(tmp_path):
    source = 'x = "héllo"  # ünï\r\nprint(x)\r\n'.encode() + b"\xff\xfe\r\n"
    (tmp_path / "in.py").write_bytes(source)

    assert invoke("in.py", "-o", "safe.py", "--map", "m.json")[0] == 0
    assert invoke("restore", "safe.py", "-o", "out.py", "--map", "m.json")[0] == 0
    assert (tmp_path / "out.py").read_bytes() == source


def test_restore_fails_when_mapping_missing(tmp_path):
    (tmp_path / "safe.js").write_text("const x = 1;")
    code, _, err = invoke("restore", "safe.js", "-o", "r.js", "--map", "missing.json")
    assert code != 0 and "restore failed" in err


def test_restore_fails_on_corrupt_mapping(tmp_path):
    (tmp_path / "safe.js").write_text('const obf_var_1 = "obf_str_1";')
    (tmp_path / "map.json").write_text("{invalid-json")
    assert invoke("restore", "safe.js", "-o", "r.js", "--map", "map.json")[0] != 0


def test_ai_mode_removes_sensitive_content(tmp_path):
    (tmp_path / "input.js").write_text('const customerId = "ABC123"; // internal note')

    assert invoke("ai", "input.js", "-o", "ai_safe.js")[0] == 0

    output = (tmp_path / "ai_safe.js").read_text()
    assert "customerId" not in output
    assert "ABC123" not in output
    assert "internal note" not in output
    assert "REDACTED_STR_1" in output


def test_encrypted_round_trip_and_wrong_password(tmp_path, monkeypatch):
    (tmp_path / "input.js").write_bytes(JS_SOURCE.encode())
    (tmp_path / ".obfusconfig.json").write_text(
        '{"encryption":{"enabled":true,"passwordEnv":"OBFUS_PASSWORD"}}'
    )

    monkeypatch.setenv("OBFUS_PASSWORD", "correct-password")
    assert invoke("input.js", "-o", "safe.js", "--map", "map.enc")[0] == 0
    assert invoke("restore", "safe.js", "-o", "restored.js", "--map", "map.enc")[0] == 0
    assert (tmp_path / "restored.js").read_bytes() == JS_SOURCE.encode()

    monkeypatch.setenv("OBFUS_PASSWORD", "wrong-password")
    assert invoke("restore", "safe.js", "-o", "restored.js", "--map", "map.enc")[0] != 0


def test_encryption_enabled_without_password_fails(tmp_path):
    (tmp_path / "input.js").write_text("let a;")
    (tmp_path / ".obfusconfig.json").write_text('{"encryption":{"enabled":true}}')
    code, _, err = invoke("input.js", "-o", "safe.js", "--map", "map.enc")
    assert code == 1 and "is empty" in err


def test_terraform_round_trip(tmp_path):
    source = (
        'resource "aws_instance" "web" {\n  ami = "ami-123456"\n  user_data = <<EOF\n'
        "hello ${var.name}\nEOF\n}\n"
    )
    (tmp_path / "main.tf").write_text(source, newline="")

    assert invoke("main.tf", "-o", "safe.tf", "--map", "map.json")[0] == 0
    safe = (tmp_path / "safe.tf").read_text()
    assert "ami-123456" not in safe and "hello" not in safe

    assert invoke("restore", "safe.tf", "-o", "restored.tf", "--map", "map.json")[0] == 0
    assert (tmp_path / "restored.tf").read_text() == source


@pytest.mark.parametrize(
    "args, message",
    [
        (["input.js", "--map", "m.json"], "missing required -o"),
        (["input.js", "-o", "safe.js"], "missing required --map"),
        (["input.js", "-o"], "missing value for -o"),
        (["input.js", "-x"], "unknown flag"),
        (["a.js", "b.js", "-o", "s.js", "--map", "m"], "exactly one input file"),
        (["input.rb", "-o", "s.rb", "--map", "m"], "unsupported file extension"),
    ],
)
def test_argument_errors(tmp_path, args, message):
    (tmp_path / "input.js").write_text("let a;")
    (tmp_path / "input.rb").write_text("a = 1")
    code, _, err = invoke(*args)
    assert code == 1 and message in err


def test_cli_folder_default_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "my_project"
    proj.mkdir()
    (proj / "main.tf").write_text('variable "token" { default = "secret_val" }\n')
    (proj / "terraform.tfvars").write_text('token = "secret_val"\n')

    # Invoke on folder without -o and without --map
    code, out, err = invoke("my_project")
    assert code == 0 and not err

    output_dir = tmp_path / "output"
    assert (output_dir / "main.tf").is_file()
    assert (output_dir / "terraform.tfvars").is_file()
    assert (output_dir / "map.json").is_file()

    assert "secret_val" not in (output_dir / "main.tf").read_text()
    assert "secret_val" not in (output_dir / "terraform.tfvars").read_text()


def test_cli_folder_specified_output_and_restore(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text('user_name = "alice"\n')
    (proj / "sub").mkdir()
    (proj / "sub" / "lib.py").write_text('user_name = "alice"\n')

    code, out, err = invoke(str(proj), "-o", str(tmp_path / "custom_out"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err

    custom_out = tmp_path / "custom_out"
    assert (custom_out / "app.py").is_file()
    assert (custom_out / "sub" / "lib.py").is_file()
    assert "alice" not in (custom_out / "app.py").read_text()

    # Restore folder
    code, out, err = invoke("restore", str(custom_out), "-o", str(tmp_path / "restored"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert (tmp_path / "restored" / "app.py").read_text() == 'user_name = "alice"\n'
    assert (tmp_path / "restored" / "sub" / "lib.py").read_text() == 'user_name = "alice"\n'


def test_cli_light_folder(tmp_path):
    proj = tmp_path / "light_proj"
    proj.mkdir()
    (proj / "infra.tf").write_text('subnet_id = "subnet-1234"\n')
    (proj / "vars.tfvars").write_text('server_name = "prod-app"\n')

    code, out, err = invoke("light", str(proj), "-o", str(tmp_path / "light_out"), "--map", str(tmp_path / "lmap.json"))
    assert code == 0 and not err

    light_out = tmp_path / "light_out"
    assert "subnet-1234" not in (light_out / "infra.tf").read_text()
    assert "prod-app" not in (light_out / "vars.tfvars").read_text()

    # Restore light folder
    code, out, err = invoke("light", "restore", str(light_out), "-o", str(tmp_path / "light_restored"), "--map", str(tmp_path / "lmap.json"))
    assert code == 0 and not err
    assert (tmp_path / "light_restored" / "infra.tf").read_text() == 'subnet_id = "subnet-1234"\n'
    assert (tmp_path / "light_restored" / "vars.tfvars").read_text() == 'server_name = "prod-app"\n'


def test_cli_folder_respects_gitignore(tmp_path):
    proj = tmp_path / "git_proj"
    proj.mkdir()
    (proj / ".gitignore").write_text("*.secret\nignore_me/\n")
    (proj / "main.tf").write_text('variable "x" {}\n')
    (proj / "dev.secret").write_text('secret = 1\n')
    (proj / "ignore_me").mkdir()
    (proj / "ignore_me" / "test.tf").write_text('variable "y" {}\n')

    out_dir = tmp_path / "git_out"
    code, out, err = invoke(str(proj), "-o", str(out_dir), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err

    assert (out_dir / "main.tf").is_file()
    assert not (out_dir / "dev.secret").exists()
    assert not (out_dir / "ignore_me").exists()


def test_cli_flags_target_dir_and_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "in_proj"
    proj.mkdir()
    (proj / "main.tf").write_text('variable "a" {}\n')

    # Test --target-dir flag
    code, out, err = invoke(str(proj), "--target-dir", str(tmp_path / "custom_tgt"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert (tmp_path / "custom_tgt" / "main.tf").is_file()

    # Test config targetDir fallback
    (tmp_path / ".obfusconfig.json").write_text('{"targetDir":"config_target"}')
    code, out, err = invoke(str(proj))
    assert code == 0 and not err
    assert (tmp_path / "config_target" / "main.tf").is_file()


def test_cli_single_file_with_patterns_config_file(tmp_path):
    tokens_file = tmp_path / "tokens.json"
    tokens_file.write_text('["John Smith", "ABC12345", "app-[dev|qa|prod]-\\d{3}"]')

    src = (
        '# Written by John Smith\n'
        'app_id = "app-dev-001"\n'
        'key = "ABC12345"\n'
    )
    (tmp_path / "app.py").write_text(src)

    code, out, err = invoke(
        "app.py",
        "-o", "safe.py",
        "--map", "m.json",
        "--patterns", str(tokens_file),
    )
    assert code == 0 and not err

    safe = (tmp_path / "safe.py").read_text()
    assert "John Smith" not in safe
    assert "app-dev-001" not in safe
    assert "ABC12345" not in safe

    # Restore
    code, out, err = invoke("restore", "safe.py", "-o", "restored.py", "--map", "m.json")
    assert code == 0 and not err
    assert (tmp_path / "restored.py").read_text() == src


def test_cli_folder_with_patterns_config_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Put patterns directly in .obfusconfig.json
    (tmp_path / ".obfusconfig.json").write_text(
        '{"patterns": ["John Smith", "ABC12345", "app-[dev|qa|prod]-\\d{3}"]}'
    )

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text('token = "ABC12345"\n')
    (proj / "cluster.tf").write_text('name = "app-prod-100"\n')
    (proj / "README.md").write_text('Lead: John Smith\n')

    code, out, err = invoke(str(proj), "-o", str(tmp_path / "out"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err

    out_dir = tmp_path / "out"
    assert "ABC12345" not in (out_dir / "app.py").read_text()
    assert "app-prod-100" not in (out_dir / "cluster.tf").read_text()
    assert "John Smith" not in (out_dir / "README.md").read_text()

    # Restore
    code, out, err = invoke("restore", str(out_dir), "-o", str(tmp_path / "restored"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert (tmp_path / "restored" / "app.py").read_text() == 'token = "ABC12345"\n'
    assert (tmp_path / "restored" / "cluster.tf").read_text() == 'name = "app-prod-100"\n'
    assert (tmp_path / "restored" / "README.md").read_text() == 'Lead: John Smith\n'


def test_cli_expands_tilde_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    target_dir = tmp_path / "my_dir"
    target_dir.mkdir()
    (target_dir / "infra.tf").write_text('server_name = "app-prod"\n')

    # Invoke with tilde in quotes "~/my_dir"
    code, out, err = invoke("light", "~/my_dir", "-o", "~/my_dir_safe")
    assert code == 0 and not err

    safe_dir = tmp_path / "my_dir_safe"
    assert safe_dir.is_dir()
    assert "app-prod" not in (safe_dir / "infra.tf").read_text()
    assert (safe_dir / "map.json").is_file()


def test_cli_missing_input_path_reports_clear_error():
    code, out, err = invoke("light", "nonexistent_directory_or_file", "-o", "out")
    assert code != 0
    assert "input path does not exist" in err


def test_verbose_displays_loaded_obfusconfig_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".obfusconfig.json").write_text('{"targetDir":"config_out","tokens":["SECRET_KEY"]}')
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text('SECRET_KEY = "xyz"\n')

    code, out, err = invoke("-v", str(proj), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert "Loaded .obfusconfig.json" in out
    assert '"tokens": ["SECRET_KEY"]' in out or "SECRET_KEY" in out
    assert "Status: converting folder" in out
    assert "Files converted:" in out
    assert "app.py" in out
    assert "Total files converted: 1" in out


def test_verbose_without_obfusconfig_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "test.js").write_text("const x = 1;\n")

    code, out, err = invoke(str(proj), "-o", str(tmp_path / "out"), "--map", str(tmp_path / "m.json"), "-v")
    assert code == 0 and not err
    assert "No .obfusconfig.json loaded" in out
    assert "Status: converting folder" in out
    assert "Files converted:" in out
    assert "test.js" in out


def test_verbose_folder_with_subfolders_and_unsupported_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.tf").write_text('variable "tok" {}\n')
    (proj / "sub").mkdir()
    (proj / "sub" / "script.py").write_text('val = "prod"\n')
    # Unsupported binary/unparsed file
    (proj / "data.bin").write_bytes(b"\x00\x01\x02\x03\xff")

    code, out, err = invoke("--verbose", str(proj), "-o", str(tmp_path / "out"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert "Files converted:" in out
    assert "main.tf" in out
    assert "sub/script.py" in out
    assert "Files copied (unsupported):" in out
    assert "data.bin" in out
    assert "2 file(s) converted" in out
    assert "1 file(s) copied" in out


def test_verbose_folder_restore(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.tf").write_text('variable "tok" {}\n')

    # Obfuscate first quietly
    invoke(str(proj), "-o", str(tmp_path / "safe"), "--map", str(tmp_path / "m.json"))

    # Restore with -v
    code, out, err = invoke("restore", "-v", str(tmp_path / "safe"), "-o", str(tmp_path / "restored"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert "Status: restoring folder" in out
    assert "Files converted:" in out
    assert "main.tf" in out
    assert "Total files converted: 1" in out


def test_verbose_folder_light_and_light_restore(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "infra.tf").write_text('subnet_id = "subnet-999"\n')

    # Light obfuscate with -v
    code, out, err = invoke("light", "-v", str(proj), "-o", str(tmp_path / "safe"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert "Status: converting folder" in out
    assert "Files converted:" in out
    assert "infra.tf" in out

    # Light restore with -v
    code, out, err = invoke("light", "restore", "-v", str(tmp_path / "safe"), "-o", str(tmp_path / "restored"), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert "Status: restoring folder" in out
    assert "Files converted:" in out
    assert "infra.tf" in out


def test_verbose_folder_ai(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text('token = "secret"\n')

    code, out, err = invoke("ai", str(proj), "-o", str(tmp_path / "ai_out"), "-v")
    assert code == 0 and not err
    assert "Status: redacting folder" in out
    assert "Files converted:" in out
    assert "app.py" in out


def test_verbose_single_file_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".obfusconfig.json").write_text('{"tokens":["ABC"]}')
    (tmp_path / "in.js").write_text('const x = "ABC";\n')

    code, out, err = invoke("-v", "in.js", "-o", "out.js", "--map", "m.json")
    assert code == 0 and not err
    assert "Loaded .obfusconfig.json" in out
    assert "Status: converting 'in.js' -> 'out.js'" in out
    assert "File converted: in.js" in out


def test_non_verbose_remains_silent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".obfusconfig.json").write_text('{"targetDir":"config_out"}')
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text("x = 1\n")

    code, out, err = invoke(str(proj), "--map", str(tmp_path / "m.json"))
    assert code == 0 and not err
    assert out == ""



