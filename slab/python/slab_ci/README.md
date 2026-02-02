# Slab CI

Enterprise-grade CI/CD security testing module for the Slab security analysis framework.

## Features

- **User Authentication**: Role-based access control for test resources
- **Test Configuration**: YAML-based target and vulnerability definitions
- **Test Orchestration**: Automated side-channel and fault injection campaigns
- **Report Generation**: HTML, PDF, and JSON security reports
- **Notification System**: Email, Slack, and webhook notifications

## Installation

```bash
# Standalone installation
pip install slab-ci

# With report generation
pip install slab-ci[reports]

# With notification support
pip install slab-ci[notifications]

# Full installation
pip install slab-ci[full]

# Development installation
pip install -e .[dev]
```

## Quick Start

### 1. Define Test Target

```yaml
# targets/stm32f4_crypto.yaml
name: STM32F4 Crypto Library
version: "1.0.0"
firmware: firmware/crypto_lib.elf

target:
  architecture: cortex-m4
  frequency: 168000000
  flash_base: 0x08000000
  ram_base: 0x20000000

entry_points:
  aes_encrypt:
    address: 0x08001234
    input_address: 0x20000100
    output_address: 0x20000200
    key_address: 0x20000300

  aes_decrypt:
    address: 0x08001456
    input_address: 0x20000100
    output_address: 0x20000200
    key_address: 0x20000300

vulnerable_regions:
  - name: AES S-Box Lookup
    start: 0x08001280
    end: 0x08001300
    attack_type: sidechannel

  - name: Key Schedule
    start: 0x08001100
    end: 0x08001200
    attack_type: fault
```

### 2. Configure Test Project

```yaml
# projects/crypto_security_audit.yaml
name: Crypto Library Security Audit
description: Full security assessment of AES implementation

targets:
  - targets/stm32f4_crypto.yaml

tests:
  sidechannel:
    enabled: true
    methods:
      - cpa
      - dpa
      - template
    traces_per_attack: 10000

  fault_injection:
    enabled: true
    methods:
      - instruction_skip
      - register_corruption
    iterations: 5000

  fuzzing:
    enabled: true
    duration_minutes: 60
    seed_corpus: corpus/crypto/

thresholds:
  sidechannel_correlation: 0.5   # Fail if correlation > 0.5
  fault_success_rate: 0.01       # Fail if success rate > 1%
  fuzzing_crashes: 0             # Fail if any crashes found

notifications:
  on_complete: true
  on_failure: true
  channels:
    - email
    - slack
```

### 3. Setup Users and Permissions

```python
from slab_ci import AuthManager, User, UserRole, Group

# Create auth manager
auth = AuthManager(database="security_tests.db")

# Create users
admin = auth.create_user(
    username="admin",
    email="admin@example.com",
    role=UserRole.ADMIN
)

analyst = auth.create_user(
    username="analyst",
    email="analyst@example.com",
    role=UserRole.ANALYST
)

viewer = auth.create_user(
    username="viewer",
    email="viewer@example.com",
    role=UserRole.VIEWER
)

# Create group
crypto_team = auth.create_group(
    name="crypto_team",
    members=[admin, analyst]
)

# Assign project permissions
auth.grant_project_access(
    project="crypto_security_audit",
    group=crypto_team,
    permissions=["run", "view", "configure"]
)

auth.grant_project_access(
    project="crypto_security_audit",
    user=viewer,
    permissions=["view"]
)
```

### 4. Run Security Tests

```python
from slab_ci import TestConfig, ProjectConfig
from slab_ci import SecurityTestRunner

# Load project configuration
project = ProjectConfig.load("projects/crypto_security_audit.yaml")

# Create test runner
runner = SecurityTestRunner(project)

# Authenticate
runner.authenticate(username="analyst", password="...")

# Run all tests
results = runner.run_all_tests()

# Or run specific test types
sca_results = runner.run_sidechannel_tests()
fi_results = runner.run_fault_injection_tests()
fuzz_results = runner.run_fuzzing_tests()

# Check results
print(f"Tests passed: {results.passed}")
print(f"Tests failed: {results.failed}")
print(f"Vulnerabilities found: {results.vulnerability_count}")

# Generate report
report = runner.generate_report(format="html")
report.save("security_report.html")
```

### 5. Integrate with CI/CD Pipeline

```yaml
# .gitlab-ci.yml
security_test:
  stage: security
  image: slab/security-testing:latest
  script:
    - pip install slab-ci[full]
    - python -m slab_ci run projects/crypto_security_audit.yaml
  artifacts:
    reports:
      junit: security_results.xml
    paths:
      - security_report.html
      - security_report.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
```

```yaml
# GitHub Actions
name: Security Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  security-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install Slab CI
        run: pip install slab-ci[full]

      - name: Run Security Tests
        run: python -m slab_ci run projects/crypto_security_audit.yaml

      - name: Upload Report
        uses: actions/upload-artifact@v3
        with:
          name: security-report
          path: security_report.html
```

### 6. CLI Usage

```bash
# Run all tests in project
slab-ci run projects/crypto_security_audit.yaml

# Run specific test type
slab-ci run projects/crypto_security_audit.yaml --test sidechannel
slab-ci run projects/crypto_security_audit.yaml --test fault_injection
slab-ci run projects/crypto_security_audit.yaml --test fuzzing

# Generate report only
slab-ci report projects/crypto_security_audit.yaml --format html --output report.html

# List available targets
slab-ci list-targets

# Validate configuration
slab-ci validate projects/crypto_security_audit.yaml

# Show test status
slab-ci status projects/crypto_security_audit.yaml
```

### 7. Custom Notification Handlers

```python
from slab_ci import NotificationHandler, TestResult

class SlackNotificationHandler(NotificationHandler):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def on_test_complete(self, result: TestResult):
        color = "good" if result.passed else "danger"
        message = {
            "attachments": [{
                "color": color,
                "title": f"Security Test: {result.project_name}",
                "fields": [
                    {"title": "Status", "value": result.status, "short": True},
                    {"title": "Duration", "value": f"{result.duration}s", "short": True},
                    {"title": "Vulnerabilities", "value": str(result.vulnerability_count), "short": True},
                ]
            }]
        }
        requests.post(self.webhook_url, json=message)

    def on_vulnerability_found(self, vuln):
        message = {
            "text": f":warning: Vulnerability found: {vuln.name}",
            "attachments": [{
                "color": "warning",
                "fields": [
                    {"title": "Type", "value": vuln.type, "short": True},
                    {"title": "Severity", "value": vuln.severity, "short": True},
                    {"title": "Location", "value": f"0x{vuln.address:08X}", "short": True},
                ]
            }]
        }
        requests.post(self.webhook_url, json=message)

# Register handler
from slab_ci import SecurityTestRunner

runner = SecurityTestRunner(project)
runner.add_notification_handler(
    SlackNotificationHandler("https://hooks.slack.com/...")
)
```

### 8. Report Templates

```python
from slab_ci import ReportGenerator

# Generate various report formats
generator = ReportGenerator(results)

# HTML report with charts
html_report = generator.generate(
    format="html",
    template="detailed",
    include_charts=True
)
html_report.save("detailed_report.html")

# Executive summary PDF
pdf_report = generator.generate(
    format="pdf",
    template="executive",
    include_recommendations=True
)
pdf_report.save("executive_summary.pdf")

# Machine-readable JSON
json_report = generator.generate(format="json")
json_report.save("results.json")

# JUnit XML for CI integration
junit_report = generator.generate(format="junit")
junit_report.save("security_results.xml")
```

## Configuration Reference

### User Roles

| Role | Permissions |
|------|-------------|
| ADMIN | Full access, user management, configuration |
| ANALYST | Run tests, view results, modify test configs |
| VIEWER | View results only |

### Test Types

| Type | Description |
|------|-------------|
| sidechannel | CPA, DPA, template attacks |
| fault_injection | Instruction skip, register corruption, clock glitch |
| fuzzing | Coverage-guided firmware fuzzing |
| timing | Timing attack analysis |

### Severity Levels

| Level | Description |
|-------|-------------|
| CRITICAL | Immediate key recovery possible |
| HIGH | Practical attack with moderate effort |
| MEDIUM | Theoretical vulnerability |
| LOW | Minor information leakage |
| INFO | Security observation |

## Author

Mathieu Renard <mathieu.renard@twistedwires.io>

## License

GPL-2.0-or-later
