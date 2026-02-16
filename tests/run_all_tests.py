#!/usr/bin/env python3
"""
Comprehensive Test Runner for IndicAgent

Runs all test suites with proper infrastructure checks and reporting.
Replaces old integration test runners with a unified approach.

Usage:
    python tests/run_all_tests.py [--quick] [--unit-only] [--integration-only] [--coverage]
"""

import argparse
import asyncio
import subprocess
import time
from pathlib import Path

import asyncpg
import redis.asyncio as redis


# Colors for output
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{Colors.END}")


def print_success(message: str):
    """Print a success message."""
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")


def print_error(message: str):
    """Print an error message."""
    print(f"{Colors.RED}❌ {message}{Colors.END}")


def print_warning(message: str):
    """Print a warning message."""
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.END}")


def print_info(message: str):
    """Print an info message."""
    print(f"{Colors.BLUE}ℹ️  {message}{Colors.END}")


async def check_infrastructure() -> dict[str, bool]:
    """Check if required infrastructure is available."""
    print_section("INFRASTRUCTURE CHECKS")

    status = {"redis": False, "postgresql": False, "project_structure": False}

    # Check Redis
    try:
        redis_client = redis.Redis(host="localhost", port=6379, db=0)
        await redis_client.ping()
        await redis_client.aclose()
        status["redis"] = True
        print_success("Redis connection successful")
    except Exception as e:
        print_error(f"Redis connection failed: {e}")

    # Check PostgreSQL
    try:
        conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/indicagent")
        await conn.fetchval("SELECT 1")
        await conn.close()
        status["postgresql"] = True
        print_success("PostgreSQL connection successful")
    except Exception as e:
        print_error(f"PostgreSQL connection failed: {e}")

    # Check project structure
    project_root = Path(__file__).parent.parent
    required_dirs = ["src", "tests", "config", "services"]
    all_dirs_exist = all((project_root / dir_name).exists() for dir_name in required_dirs)

    if all_dirs_exist:
        status["project_structure"] = True
        print_success("Project structure validated")
    else:
        print_error("Project structure incomplete")

    return status


def run_command(command: list[str], description: str, timeout: int = 300) -> bool:
    """Run a command and return success status."""
    print_info(f"Running: {description}")

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path(__file__).parent.parent,
        )

        if result.returncode == 0:
            print_success(f"{description} - PASSED")
            return True
        else:
            print_error(f"{description} - FAILED")
            if result.stdout:
                print(f"STDOUT: {result.stdout[-500:]}")  # Last 500 chars
            if result.stderr:
                print(f"STDERR: {result.stderr[-500:]}")  # Last 500 chars
            return False

    except subprocess.TimeoutExpired:
        print_error(f"{description} - TIMEOUT")
        return False
    except Exception as e:
        print_error(f"{description} - ERROR: {e}")
        return False


def run_unit_tests(with_coverage: bool = False) -> bool:
    """Run all unit tests."""
    print_section("UNIT TESTS")

    if with_coverage:
        command = [
            "python",
            "-m",
            "pytest",
            "tests/unit/",
            "-v",
            "--cov=src",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov",
            "--cov-fail-under=70",
        ]
        description = "Unit Tests with Coverage"
    else:
        command = ["python", "-m", "pytest", "tests/unit/", "-v"]
        description = "Unit Tests"

    return run_command(command, description)


def run_integration_tests(quick: bool = False) -> bool:
    """Run integration tests."""
    print_section("INTEGRATION TESTS")

    # Define test categories
    test_categories = [
        {
            "name": "Core Pipeline Tests",
            "files": ["tests/integration/test_simple_pipeline.py"],
            "timeout": 60,
        },
        {
            "name": "Comprehensive Timeframe Aggregation",
            "files": ["tests/integration/test_comprehensive_timeframe_aggregation.py"],
            "timeout": 120,
        },
        {
            "name": "SSE Integration Tests",
            "files": ["tests/integration/test_sse_integration.py"],
            "timeout": 90,
        },
        {
            "name": "Enhanced Indicator Processing",
            "files": ["tests/integration/test_enhanced_indicator_processor.py"],
            "timeout": 180,
        },
        {
            "name": "API Health Tests",
            "files": ["tests/integration/test_api_health.py"],
            "timeout": 30,
        },
    ]

    if quick:
        # Only run core tests in quick mode
        test_categories = test_categories[:2]

    results = []

    for category in test_categories:
        print(f"\n{Colors.BOLD}Running {category['name']}...{Colors.END}")

        for test_file in category["files"]:
            command = ["python", "-m", "pytest", test_file, "-v", "-s"]
            success = run_command(
                command, f"{category['name']} - {Path(test_file).name}", timeout=category["timeout"]
            )
            results.append(success)

    return all(results)


def run_code_quality_checks() -> bool:
    """Run code quality checks."""
    print_section("CODE QUALITY CHECKS")

    checks = [
        {
            "command": ["python", "-m", "black", "--check", "."],
            "description": "Black Code Formatting Check",
            "timeout": 60,
        },
        {
            "command": ["python", "-m", "ruff", "check", "."],
            "description": "Ruff Linting Check",
            "timeout": 60,
        },
        {
            "command": ["python", "-m", "mypy", "src/", "--ignore-missing-imports"],
            "description": "MyPy Type Checking",
            "timeout": 120,
        },
    ]

    results = []
    for check in checks:
        success = run_command(check["command"], check["description"], check["timeout"])
        results.append(success)

    return all(results)


async def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(description="IndicAgent Comprehensive Test Runner")
    parser.add_argument(
        "--quick", action="store_true", help="Run only core tests for quick validation"
    )
    parser.add_argument("--unit-only", action="store_true", help="Run only unit tests")
    parser.add_argument(
        "--integration-only", action="store_true", help="Run only integration tests"
    )
    parser.add_argument("--coverage", action="store_true", help="Include coverage reporting")
    parser.add_argument("--no-quality", action="store_true", help="Skip code quality checks")

    args = parser.parse_args()

    print_section("INDICAGENT COMPREHENSIVE TEST SUITE")
    print_info(f"Mode: {'Quick' if args.quick else 'Full'}")

    start_time = time.time()

    # Check infrastructure
    infrastructure_status = await check_infrastructure()

    # Determine what tests to run
    if not any([args.unit_only, args.integration_only]):
        # Run all tests if no specific category specified
        run_unit = True
        run_integration = True
        run_quality = not args.no_quality
    else:
        run_unit = args.unit_only
        run_integration = args.integration_only
        run_quality = not args.no_quality and not args.unit_only and not args.integration_only

    results = {}

    # Run unit tests
    if run_unit:
        results["unit_tests"] = run_unit_tests(with_coverage=args.coverage)

    # Run integration tests (only if infrastructure is available)
    if run_integration:
        if infrastructure_status["redis"] and infrastructure_status["postgresql"]:
            results["integration_tests"] = run_integration_tests(quick=args.quick)
        else:
            print_warning("Skipping integration tests - infrastructure not available")
            results["integration_tests"] = None

    # Run code quality checks
    if run_quality:
        results["code_quality"] = run_code_quality_checks()

    # Summary
    print_section("TEST SUMMARY")

    total_time = time.time() - start_time
    print_info(f"Total execution time: {total_time:.1f} seconds")

    all_passed = True
    for test_type, result in results.items():
        if result is True:
            print_success(f"{test_type.replace('_', ' ').title()}: PASSED")
        elif result is False:
            print_error(f"{test_type.replace('_', ' ').title()}: FAILED")
            all_passed = False
        elif result is None:
            print_warning(f"{test_type.replace('_', ' ').title()}: SKIPPED")

    if all_passed and any(results.values()):
        print(f"\n{Colors.BOLD}{Colors.GREEN}🎉 ALL TESTS PASSED!{Colors.END}")
        if args.coverage:
            print_info("Coverage report generated in htmlcov/index.html")
        return 0
    else:
        print(f"\n{Colors.BOLD}{Colors.RED}❌ SOME TESTS FAILED{Colors.END}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
