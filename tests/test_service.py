from pathlib import Path
import pytest

from obfus.service import ObfuscatorService, ai_safe_folder, obfuscate_folder, restore_folder
from obfus.config import Config, EncryptionConfig


def test_obfuscate_folder_full_mode_with_tf_and_tfvars(tmp_path):
    input_dir = tmp_path / "project"
    input_dir.mkdir()

    # Create directory structure
    (input_dir / "main.tf").write_text(
        'variable "cluster_name" {\n  type = string\n}\n\n'
        'resource "aws_eks_cluster" "prod" {\n  name = var.cluster_name\n  enabled = true\n}\n'
    )
    (input_dir / "terraform.tfvars").write_text(
        'cluster_name = "k8s-prod"\nnode_count = 5\nenabled = true\n'
    )
    sub = input_dir / "modules" / "vpc"
    sub.mkdir(parents=True)
    (sub / "network.tf").write_text(
        'resource "aws_vpc" "main" {\n  cidr_block = "10.0.0.0/16"\n}\n'
    )
    (sub / "terragrunt.hcl").write_text(
        'inputs = {\n  vpc_name = "custom-vpc"\n}\n'
    )
    (input_dir / "README.md").write_text("# Project Docs\nDo not change.")

    output_dir = tmp_path / "out"
    map_file = tmp_path / "mapping.json"

    res_out, m = obfuscate_folder(
        input_dir,
        output_dir=output_dir,
        map_path=map_file,
        mode="full",
    )

    assert res_out == output_dir
    assert map_file.is_file()

    # Verify duplicate directory structure
    assert (output_dir / "main.tf").is_file()
    assert (output_dir / "terraform.tfvars").is_file()
    assert (output_dir / "modules" / "vpc" / "network.tf").is_file()
    assert (output_dir / "modules" / "vpc" / "terragrunt.hcl").is_file()
    assert (output_dir / "README.md").is_file()

    # Verify non-code file copied as-is
    assert (output_dir / "README.md").read_text() == "# Project Docs\nDo not change."

    # Verify obfuscation in main.tf and terraform.tfvars
    out_main = (output_dir / "main.tf").read_text()
    out_vars = (output_dir / "terraform.tfvars").read_text()
    assert "k8s-prod" not in out_vars
    assert "prod" not in out_main
    # Keyword 'true' preserved and identifier 'enabled' mapped consistently
    enabled_var = m.forward["enabled"]
    assert f"{enabled_var} = true" in out_vars
    assert f"{enabled_var} = true" in out_main

    # Unified mapping: cluster_name should map to the same placeholder in both
    placeholder_cluster = m.forward["cluster_name"]
    assert placeholder_cluster in out_main
    assert placeholder_cluster in out_vars

    # Restore folder
    restored_dir = tmp_path / "restored"
    restore_folder(
        output_dir,
        output_dir=restored_dir,
        map_path=map_file,
        mode="full",
    )

    assert (restored_dir / "main.tf").read_text() == (input_dir / "main.tf").read_text()
    assert (restored_dir / "terraform.tfvars").read_text() == (input_dir / "terraform.tfvars").read_text()
    assert (restored_dir / "modules" / "vpc" / "network.tf").read_text() == (sub / "network.tf").read_text()
    assert (restored_dir / "modules" / "vpc" / "terragrunt.hcl").read_text() == (sub / "terragrunt.hcl").read_text()
    assert (restored_dir / "README.md").read_text() == (input_dir / "README.md").read_text()


def test_gitignore_ignores_files_and_folders(tmp_path):
    input_dir = tmp_path / "my_repo"
    input_dir.mkdir()

    # Add .gitignore
    (input_dir / ".gitignore").write_text(
        "secret.tfvars\n"
        "ignored_folder/\n"
        "*.log\n"
        "deep/ignored.txt\n"
    )

    # Valid files
    (input_dir / "main.tf").write_text('resource "aws_s3_bucket" "b" {}\n')
    (input_dir / "dev.tfvars").write_text('env = "dev"\n')

    # Ignored files and folders
    (input_dir / "secret.tfvars").write_text('secret_token = "SUPER_SECRET"\n')
    (input_dir / "debug.log").write_text("log info")
    ignored_dir = input_dir / "ignored_folder"
    ignored_dir.mkdir()
    (ignored_dir / "inner.tf").write_text('variable "secret" {}\n')

    deep = input_dir / "deep"
    deep.mkdir()
    (deep / "ignored.txt").write_text("skip me")
    (deep / "keep.tf").write_text('variable "allowed" {}\n')

    out_dir = tmp_path / "output_repo"
    obfuscate_folder(input_dir, output_dir=out_dir)

    # Valid files must exist in duplicate structure
    assert (out_dir / "main.tf").is_file()
    assert (out_dir / "dev.tfvars").is_file()
    assert (out_dir / "deep" / "keep.tf").is_file()

    # Ignored files and folders must NOT exist in output
    assert not (out_dir / "secret.tfvars").exists()
    assert not (out_dir / "debug.log").exists()
    assert not (out_dir / "ignored_folder").exists()
    assert not (out_dir / "deep" / "ignored.txt").exists()


def test_gitignore_negation_and_nested_gitignore(tmp_path):
    input_dir = tmp_path / "nested_repo"
    input_dir.mkdir()

    (input_dir / ".gitignore").write_text("*.log\n!keep.log\n")
    (input_dir / "test.log").write_text("drop")
    (input_dir / "keep.log").write_text("preserve")

    sub = input_dir / "sub"
    sub.mkdir()
    (sub / ".gitignore").write_text("local_secret.tf\n")
    (sub / "local_secret.tf").write_text('secret = "x"')
    (sub / "normal.tf").write_text('val = "ok"')

    out_dir = tmp_path / "out_nested"
    obfuscate_folder(input_dir, output_dir=out_dir)

    assert not (out_dir / "test.log").exists()
    assert (out_dir / "keep.log").is_file()
    assert not (out_dir / "sub" / "local_secret.tf").exists()
    assert (out_dir / "sub" / "normal.tf").is_file()


def test_default_output_folder_in_running_code_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    input_dir = tmp_path / "src_folder"
    input_dir.mkdir()
    (input_dir / "app.tf").write_text('variable "region" { default = "us-east-1" }\n')

    # Call with output_dir=None
    res_dir, m = obfuscate_folder(input_dir, output_dir=None)

    assert res_dir == tmp_path / "output"
    assert (tmp_path / "output" / "app.tf").is_file()
    assert (tmp_path / "output" / "map.json").is_file()


def test_light_mode_on_folder(tmp_path):
    input_dir = tmp_path / "infra"
    input_dir.mkdir()

    (input_dir / "main.tf").write_text(
        'resource "aws_vpc" "vpc" {\n  cidr_block = "10.0.0.0/16"\n  vpc_id = "vpc-1234"\n}\n'
    )
    (input_dir / "terraform.tfvars").write_text(
        'server_name = "my-cluster"\nvpc_id = "vpc-1234"\npublic_ip = "198.51.100.1"\n'
    )

    out_dir = tmp_path / "out_light"
    map_file = tmp_path / "light_map.json"

    obfuscate_folder(
        input_dir,
        output_dir=out_dir,
        map_path=map_file,
        mode="light",
    )

    out_main = (out_dir / "main.tf").read_text()
    out_vars = (out_dir / "terraform.tfvars").read_text()

    assert "10.0.0.0/16" not in out_main
    assert "my-cluster" not in out_vars
    assert "198.51.100.1" not in out_vars

    # Identical value in both files gets identical placeholder
    assert 'vpc_id = "obf_id_1"' in out_main
    assert 'vpc_id = "obf_id_1"' in out_vars

    # Restore light
    restored_dir = tmp_path / "restored_light"
    restore_folder(
        out_dir,
        output_dir=restored_dir,
        map_path=map_file,
        mode="light",
    )

    assert (restored_dir / "main.tf").read_text() == (input_dir / "main.tf").read_text()
    assert (restored_dir / "terraform.tfvars").read_text() == (input_dir / "terraform.tfvars").read_text()


def test_encrypted_folder_round_trip(tmp_path):
    input_dir = tmp_path / "enc_in"
    input_dir.mkdir()
    (input_dir / "app.py").write_text('secret_var = "sensitive_value"\n')

    out_dir = tmp_path / "enc_out"
    map_file = tmp_path / "mapping.enc"
    cfg = Config(encryption=EncryptionConfig(enabled=True, password_env="TEST_PASSWORD"))

    service = ObfuscatorService(cfg=cfg, password="vault-password")
    service.obfuscate_folder(input_dir, output_dir=out_dir, map_path=map_file)

    assert map_file.is_file()
    assert b"sensitive_value" not in map_file.read_bytes()

    restored = tmp_path / "enc_restored"
    service.restore_folder(out_dir, output_dir=restored, map_path=map_file)

    assert (restored / "app.py").read_text() == (input_dir / "app.py").read_text()


def test_ai_safe_folder(tmp_path):
    input_dir = tmp_path / "ai_in"
    input_dir.mkdir()
    (input_dir / "app.tf").write_text('variable "db_pwd" { default = "secret123" } // comment\n')

    out_dir = tmp_path / "ai_out"
    ai_safe_folder(input_dir, output_dir=out_dir)

    content = (out_dir / "app.tf").read_text()
    assert "secret123" not in content
    assert "comment" not in content
    assert "REDACTED_STR_1" in content


def test_obfuscate_folder_with_known_tokens_and_patterns_full_mode(tmp_path):
    input_dir = tmp_path / "proj_patterns"
    input_dir.mkdir()

    # Python code with comments, variables and string literals
    py_content = (
        "# Contributed by John Smith\n"
        'ABC12345 = "client_key"\n'
        'app_host = "app-dev-001"\n'
        'greeting = "Hello John Smith, deploying app-dev-001"\n'
    )
    (input_dir / "service.py").write_text(py_content)

    # Terraform code
    tf_content = (
        'resource "aws_instance" "app" {\n'
        '  server = "app-prod-999"\n'
        '  creator = "John Smith"\n'
        '}\n'
    )
    (input_dir / "main.tf").write_text(tf_content)

    # Unsupported non-code text file
    yaml_content = (
        "service:\n"
        "  owner: John Smith\n"
        "  token: ABC12345\n"
        "  cluster: app-qa-042\n"
    )
    (input_dir / "config.yaml").write_text(yaml_content)

    # Binary file
    (input_dir / "data.bin").write_bytes(b"\x00\xff\xfe\x01\x02")

    output_dir = tmp_path / "out_patterns"
    map_file = tmp_path / "map_patterns.json"

    patterns = ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]

    out_dir, m = obfuscate_folder(
        input_dir,
        output_dir=output_dir,
        map_path=map_file,
        mode="full",
        patterns=patterns,
    )

    # Verify sensitive tokens are obfuscated in Python
    safe_py = (output_dir / "service.py").read_text()
    assert "John Smith" not in safe_py
    assert "ABC12345" not in safe_py
    assert "app-dev-001" not in safe_py

    # Verify sensitive tokens are obfuscated in Terraform
    safe_tf = (output_dir / "main.tf").read_text()
    assert "John Smith" not in safe_tf
    assert "app-prod-999" not in safe_tf

    # Verify sensitive tokens are obfuscated in YAML
    safe_yaml = (output_dir / "config.yaml").read_text()
    assert "John Smith" not in safe_yaml
    assert "ABC12345" not in safe_yaml
    assert "app-qa-042" not in safe_yaml

    # Verify binary file copied unchanged
    assert (output_dir / "data.bin").read_bytes() == b"\x00\xff\xfe\x01\x02"

    # Restore folder
    restored_dir = tmp_path / "restored_patterns"
    restore_folder(
        output_dir,
        output_dir=restored_dir,
        map_path=map_file,
        mode="full",
    )

    assert (restored_dir / "service.py").read_text() == py_content
    assert (restored_dir / "main.tf").read_text() == tf_content
    assert (restored_dir / "config.yaml").read_text() == yaml_content
    assert (restored_dir / "data.bin").read_bytes() == b"\x00\xff\xfe\x01\x02"


def test_obfuscate_folder_with_patterns_light_mode(tmp_path):
    input_dir = tmp_path / "proj_light_pats"
    input_dir.mkdir()

    tf_content = (
        'server_name = "app-prod-100"\n'
        'owner = "John Smith"\n'
        'key = "ABC12345"\n'
    )
    (input_dir / "vars.tf").write_text(tf_content)

    output_dir = tmp_path / "out_light_pats"
    map_file = tmp_path / "lmap.json"

    patterns = ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]

    obfuscate_folder(
        input_dir,
        output_dir=output_dir,
        map_path=map_file,
        mode="light",
        patterns=patterns,
    )

    safe_tf = (output_dir / "vars.tf").read_text()
    assert "John Smith" not in safe_tf
    assert "ABC12345" not in safe_tf
    assert "app-prod-100" not in safe_tf

    restored_dir = tmp_path / "restored_light_pats"
    restore_folder(
        output_dir,
        output_dir=restored_dir,
        map_path=map_file,
        mode="light",
    )

    assert (restored_dir / "vars.tf").read_text() == tf_content

