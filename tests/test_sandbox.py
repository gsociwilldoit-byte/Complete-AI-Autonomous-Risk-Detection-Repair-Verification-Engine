import pytest

from sandbox.workspace import new_sandbox


def test_sandbox_is_isolated_from_canonical_workspace(seeded_org):
    sb1 = new_sandbox(["checkout-service"])
    sb2 = new_sandbox(["checkout-service"])
    assert sb1.root != sb2.root

    sb1.write_file("checkout-service", "checkout_service/config.py", "GATEWAY_TIMEOUT_MS = 999999")
    content_sb2 = sb2.read_file("checkout-service", "checkout_service/config.py")
    assert "999999" not in content_sb2

    sb1.cleanup()
    sb2.cleanup()


def test_sandbox_refuses_path_escape(seeded_org):
    sb = new_sandbox(["checkout-service"])
    with pytest.raises(PermissionError):
        sb.resolve("checkout-service", "../../../etc/passwd")
    sb.cleanup()


def test_sandbox_commands_confined_to_repo_cwd(seeded_org):
    sb = new_sandbox(["checkout-service"])
    result = sb.run_command("checkout-service", ["pwd"])
    assert result["stdout"].strip() == sb.repo_path("checkout-service")
    sb.cleanup()


def test_edit_file_requires_exact_unique_match(seeded_org):
    from tools.engineering import edit_file

    sb = new_sandbox(["checkout-service"])
    result = edit_file(
        sb,
        "checkout-service",
        "checkout_service/config.py",
        old_str="this string does not exist anywhere",
        new_str="x",
    )
    assert result["success"] is False
    sb.cleanup()


def test_bytecode_cache_does_not_mask_rapid_edits(seeded_org):
    """Regression test for a real bug found during development: two edits
    with equal-length values applied within the same second could leave a
    stale .pyc cached, making test runs silently reflect the wrong value."""
    import re

    from tools.engineering import edit_file, run_tests
    from tools.git_tools import read_file

    sb = new_sandbox(["checkout-service"])
    content = read_file(sb, "checkout-service", "checkout_service/config.py")
    current = re.search(r"GATEWAY_TIMEOUT_MS\s*=\s*(\d+)", content).group(1)
    edit_file(
        sb,
        "checkout-service",
        "checkout_service/config.py",
        f"GATEWAY_TIMEOUT_MS = {current}",
        "GATEWAY_TIMEOUT_MS = 5000",
    )
    edit_file(
        sb,
        "checkout-service",
        "checkout_service/config.py",
        "GATEWAY_TIMEOUT_MS = 5000",
        "GATEWAY_TIMEOUT_MS = 1450",
    )
    # scoped to this repo's own test file — checkout-service also carries the
    # separate, deliberate cross-repo error-schema drift (see the multi-repo
    # demo), which is unrelated to the timeout value under test here.
    result = run_tests(sb, "checkout-service", target="tests/test_checkout.py")
    assert result["passed"], f"stale bytecode suspected: {result['stdout'][-400:]}"
    sb.cleanup()
