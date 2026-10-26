import pytest

from obfus.tokenizer import (
    TokenType,
    for_file,
    reconstruct,
    tokenize_javascript,
    tokenize_python,
    tokenize_terraform,
)


def test_js_reconstructs_original():
    source = 'const customerId = "ABC123"; // comment\n/* block */\nlet total = customerId;'
    assert reconstruct(tokenize_javascript(source)) == source


def test_js_identifies_core_token_types():
    types = {t.type for t in tokenize_javascript('const name = "x" // c')}
    assert {TokenType.KEYWORD, TokenType.IDENTIFIER, TokenType.STRING, TokenType.COMMENT} <= types


def test_js_unterminated_block_comment_still_lossless():
    source = "let a = 1; /* never closed"
    assert reconstruct(tokenize_javascript(source)) == source


def test_python_reconstructs_with_triple_quote_and_comment():
    source = "def f():\n    s = '''line1\\nline2'''\n    # trailing\n    return s\n"
    assert reconstruct(tokenize_python(source)) == source


def test_python_detects_triple_quoted_string():
    strings = [t for t in tokenize_python('doc = """hello"""') if t.type is TokenType.STRING]
    assert [t.raw for t in strings] == ['"""hello"""']


def test_python_raw_string_ignores_backslash_escape():
    strings = [t.raw for t in tokenize_python("p = r'a\\'") if t.type is TokenType.STRING]
    assert strings == ["r'a\\'"]


def test_terraform_reconstructs_original():
    source = 'resource "aws_instance" "web" {\n  ami = "ami-123456"\n  # comment\n}\n'
    assert reconstruct(tokenize_terraform(source)) == source


def test_terraform_handles_heredoc_and_comments():
    source = (
        'resource "aws_instance" "web" {\n  user_data = <<EOF\nhello ${var.name}\nEOF\n'
        "  // trailing\n}\n"
    )
    tokens = tokenize_terraform(source)

    assert any(t.type is TokenType.KEYWORD and t.raw == "resource" for t in tokens)
    assert any(t.type is TokenType.STRING and t.raw.startswith("<<") for t in tokens)
    assert any(t.type is TokenType.COMMENT for t in tokens)
    assert reconstruct(tokens) == source


def test_terraform_indented_heredoc():
    source = "x = <<-EOT\n  body\n  EOT\ny = 1\n"
    heredocs = [t.raw for t in tokenize_terraform(source) if t.raw.startswith("<<")]
    assert heredocs == ["<<-EOT\n  body\n  EOT\n"]


def test_for_file_terraform_supported():
    source = 'variable "region" { default = "westus" }'
    assert reconstruct(for_file("infra/main.tf")(source)) == source


def test_for_file_is_case_insensitive_and_rejects_unknown():
    assert for_file("A.JS") is tokenize_javascript
    with pytest.raises(ValueError, match="unsupported file extension"):
        for_file("file.rb")


def test_for_file_supports_tfvars_and_related_files():
    tfvars_source = 'environment = "staging"\ncount = 3\nenabled = true\n'
    assert reconstruct(for_file("terraform.tfvars")(tfvars_source)) == tfvars_source
    assert reconstruct(for_file("prod.auto.tfvars")(tfvars_source)) == tfvars_source

    hcl_source = 'terragrunt = { source = "git::..." }\n'
    assert reconstruct(for_file("terragrunt.hcl")(hcl_source)) == hcl_source
    assert reconstruct(for_file(".terraform.lock.hcl")(hcl_source)) == hcl_source

    backend_source = 'bucket = "tf-state-bucket"\nkey = "prod.tfstate"\n'
    assert reconstruct(for_file("backend.tfbackend")(backend_source)) == backend_source

    assert reconstruct(for_file("config.tf.json")('{"key": "val"}')) == '{"key": "val"}'
    assert reconstruct(for_file("prod.tfvars.json")('{"key": "val"}')) == '{"key": "val"}'
    assert reconstruct(for_file(".terraformrc")('credentials "app.terraform.io" {}')) == 'credentials "app.terraform.io" {}'
