import io

import pytest

from obfus import light
from obfus.cli import run

PLAN = '''  # aws_instance.web will be created
  + resource "aws_instance" "web" {
      + ami           = "ami-123456"
      + id            = (known after apply)
      + subnet_id     = "subnet-0abc"
      + vpc_security_group_ids = ["sg-1", "sg-2"]
      + server_name   = "server_name_dev"
      ~ display_name  = "old-name" -> "new-name"
      + tags          = {
          + "Name" = "keep-me"
        }
      + description   = "uses ${var.env_name}"
    }
'''


def test_obfuscates_only_id_and_name_values():
    safe, m = light.obfuscate(PLAN)

    assert 'subnet_id     = "obf_id_1"' in safe
    assert 'server_name   = "obf_name_1"' in safe
    assert '"old-name" -> "new-name"' not in safe
    assert 'vpc_security_group_ids = ["obf_id_2", "obf_id_3"]' in safe
    assert "ami-123456" in safe and "keep-me" not in safe
    assert "(known after apply)" in safe
    assert "${var.env_name}" in safe
    assert "server_name_dev" not in safe and "subnet-0abc" not in safe
    assert len(m.forward) == len(m.reverse) == 7


def test_round_trip_is_exact():
    safe, m = light.obfuscate(PLAN)
    assert light.restore(safe, m) == PLAN


def test_same_value_gets_same_placeholder_across_diff_lines():
    text = '- vpc_id = "vpc-1"\n+ vpc_id = "vpc-1"\nother_vpc_id = "vpc-1"\n'
    safe, m = light.obfuscate(text)
    assert safe.count("obf_id_1") == 3 and len(m.forward) == 1


def test_custom_keys():
    safe, _ = light.obfuscate('a_arn = "arn:x"\nb_id = "i-1"\n', light.parse_keys("arn"))
    assert 'a_arn = "obf_arn_1"' in safe and 'b_id = "i-1"' in safe


def test_obfuscates_attributes_with_name_anywhere_in_key():
    text = 'display_name = "web-dev"\nname_prefix = "prod"\ntags = {"Name" = "public"}\n'
    safe, m = light.obfuscate(text)

    assert 'display_name = "obf_name_1"' in safe
    assert 'name_prefix = "obf_name_2"' in safe
    assert '"Name" = "obf_name_3"' in safe
    assert len(m.forward) == 3
    assert light.restore(safe, m) == text


def test_obfuscates_ipv4_ipv6_cidrs_and_subnet_masks():
    text = (
        'cidr_block = "10.20.0.0/16"\n'
        'public_ip = "203.0.113.7"\n'
        'subnet_mask = "255.255.255.0"\n'
        'ipv6_cidr_block = "2001:db8::/32"\n'
        'description = "Connect to 198.51.100.10"\n'
        'unchanged = "not an address"\n'
    )
    safe, m = light.obfuscate(text)

    assert '"obf_subnet_1"' in safe
    assert '"obf_ip_1"' in safe
    assert '"obf_subnet_2"' in safe
    assert '"obf_subnet_3"' in safe
    assert '"Connect to obf_ip_2"' in safe
    assert '"not an address"' in safe
    assert light.restore(safe, m) == text


def test_existing_placeholder_in_input_is_not_reused():
    text = 'note = "obf_id_1"\nx_id = "real"\n'
    safe, m = light.obfuscate(text)
    assert m.forward == {"real": "obf_id_2"}
    assert light.restore(safe, m) == text


def test_parse_keys_validation():
    assert light.parse_keys(None) == ("id", "name")
    with pytest.raises(ValueError):
        light.parse_keys("bad key!")


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OBFUS_PASSWORD", raising=False)
    return tmp_path


def invoke(*args):
    out, err = io.StringIO(), io.StringIO()
    return run(list(args), out, err), err.getvalue()


def test_cli_light_round_trip_on_diff_file(cwd):
    (cwd / "changes.diff").write_bytes(PLAN.replace("\n", "\r\n").encode())

    assert invoke("light", "changes.diff", "-o", "safe.diff", "--map", "m.json")[0] == 0
    assert b"server_name_dev" not in (cwd / "safe.diff").read_bytes()
    assert invoke("light", "restore", "safe.diff", "-o", "back.diff", "--map", "m.json")[0] == 0
    assert (cwd / "back.diff").read_bytes() == (cwd / "changes.diff").read_bytes()


def test_cli_light_keys_flag_and_encryption(cwd, monkeypatch):
    (cwd / "p.txt").write_text('a_arn = "arn:x"\n')
    (cwd / ".obfusconfig.json").write_text('{"encryption":{"enabled":true}}')
    monkeypatch.setenv("OBFUS_PASSWORD", "pw")

    assert invoke("light", "p.txt", "-o", "s.txt", "--keys=arn", "--map", "m.enc")[0] == 0
    assert "obf_arn_1" in (cwd / "s.txt").read_text()
    assert b"arn:x" not in (cwd / "m.enc").read_bytes()
    assert invoke("light", "restore", "s.txt", "-o", "r.txt", "--map", "m.enc")[0] == 0
    assert (cwd / "r.txt").read_text() == 'a_arn = "arn:x"\n'


def test_cli_light_errors(cwd):
    (cwd / "p.txt").write_text("x")
    code, err = invoke("light", "p.txt", "-o", "s.txt", "--map", "m.json", "--keys")
    assert code == 1 and "missing value for --keys" in err
    code, err = invoke("light", "p.txt", "-o", "s.txt")
    assert code == 1 and "missing required --map" in err
