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
