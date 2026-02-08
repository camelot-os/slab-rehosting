.. _ci_testing:

===========================
Automated CI Testing Guide
===========================

This tutorial teaches you how to use SLAB for automated continuous integration (CI)
testing of embedded firmware. You will learn to write test scenarios, configure
assertions, generate machine-readable reports, and integrate with GitHub Actions.

**Author:** Mathieu Renard <mathieu.renard@twistedwires.io>

**Copyright:** (C) 2026 Twisted Wires Security Lab

CI Testing Philosophy
=====================

Traditional embedded testing requires physical hardware, making automation difficult.
SLAB enables deterministic, reproducible firmware execution in CI pipelines:

**Key Principles:**

1. **Deterministic Execution**
   QEMU provides cycle-accurate CPU emulation with reproducible timing. The same
   firmware binary always produces the same behavior.

2. **Machine-Readable Output**
   Test results are exported in standard formats:
   - JSON for custom tooling
   - JUnit XML for CI dashboards (Jenkins, GitHub Actions, GitLab CI)
   - LaTeX reports for documentation and audits

3. **MMIO Trace Evidence**
   Every peripheral access is logged, providing detailed execution traces for:
   - Post-mortem debugging of test failures
   - Reverse engineering documentation
   - Security audit trails

4. **Pass/Fail Assertions**
   Automated checks verify firmware behavior:
   - No crashes (clean QEMU exit)
   - Minimum activity threshold (MMIO operations)
   - GPIO toggles (LED blink tests)
   - UART output matching (future)

Step 1: Writing a CI Scenario YAML
===================================

Create a test scenario file describing the firmware under test and expected behavior.

Example: ``slab/ci/test_hello_blink.yaml``

.. code-block:: yaml

   scenarios:
     - name: "STM32F405 LED blink"
       board: slab/boards/stm32f405_hello_blink.yaml
       firmware: slab/examples/cortex-m/stm32/f405/demos/hello_blink/build/HelloBlink.bin
       timeout: 10
       assertions:
         - type: no_crash
         - type: mmio_count
           params:
             min: 50

**Field Explanations:**

- ``name``: Human-readable test name (appears in reports)
- ``board``: Path to board configuration YAML (defines peripherals and memory map)
- ``firmware``: Path to compiled firmware binary (``.bin`` file)
- ``timeout``: Maximum execution time in seconds (QEMU is killed afterward)
- ``assertions``: List of checks to perform (see Step 2)

**Multiple Scenarios:**

Group related tests in one file:

.. code-block:: yaml

   scenarios:
     - name: "Test 1"
       board: ...
       firmware: ...
       assertions: [...]

     - name: "Test 2"
       board: ...
       firmware: ...
       assertions: [...]

Step 2: Available Assertion Types
==================================

Assertions define pass/fail criteria for each test.

no_crash
--------

Verifies QEMU exits cleanly (firmware didn't trigger a fault or hang).

.. code-block:: yaml

   assertions:
     - type: no_crash

**Pass Conditions:**

- Exit code 0 (clean shutdown)
- Exit code 124 (killed by timeout, but running)
- Exit code -15 or 143 (SIGTERM from timeout)

**Fail Conditions:**

- Exit code 134 (SIGABRT, assertion failure)
- Exit code 139 (SIGSEGV, invalid memory access)

mmio_count
----------

Verifies firmware performed at least N peripheral operations (ensures it didn't
get stuck in early boot).

.. code-block:: yaml

   assertions:
     - type: mmio_count
       params:
         min: 100

**Use Cases:**

- Detect boot loops (MMIO count stays low)
- Verify firmware reached main application code
- Ensure peripheral initialization completed

gpio_toggle
-----------

Verifies a GPIO pin toggled at least N times (LED blink tests).

.. code-block:: yaml

   assertions:
     - type: gpio_toggle
       params:
         gpio: GPIOA      # GPIO port (GPIOA, GPIOB, ...)
         pin: 13          # Pin number (0-15)
         min_toggles: 4   # Minimum high/low transitions

**Implementation:**

The CI runner polls GPIO ODR (Output Data Register) during execution and counts
state changes. A toggle is any 0→1 or 1→0 transition.

**Example:** A 1Hz LED blink with 5-second timeout:

.. code-block:: c

   // Firmware toggles LED every 500ms
   while (1) {
       GPIO_ToggleBits(GPIOA, GPIO_Pin_13);
       Delay_ms(500);  // 2 toggles/second
   }

With a 5-second timeout, expect ~10 toggles. Set ``min_toggles: 8`` for safety margin.

uart_output (Future)
--------------------

Planned assertion to match UART output against expected strings.

.. code-block:: yaml

   assertions:
     - type: uart_output
       params:
         contains: "Boot complete"
         regex: "Temperature: \\d+\\.\\d+°C"

Step 3: Running Tests Locally
==============================

Single Scenario
---------------

Test one scenario file:

.. code-block:: bash

   PYTHONPATH=slab/python python3 -m slab_cortex_m.ci_runner \
       --scenario slab/ci/test_hello_blink.yaml

Output::

   [INFO] Running 2 scenario(s)
   [INFO] Running: STM32F405 LED blink
   [INFO] [STM32F405 LED blink] Starting QEMU: .../qemu-system-arm...
   [INFO]   PASS (10.0s, 222 MMIO ops)
   [INFO]     [+] no_crash: QEMU exit code: 0
   [INFO]     [+] mmio_count(>=50): count=222
   [INFO] Running: STM32F405 HelloBlinkUart
   [INFO]   PASS (10.0s, 237 MMIO ops)
   [INFO] RESULTS: 2/2 passed

Batch Mode
----------

Run all scenarios in a directory:

.. code-block:: bash

   PYTHONPATH=slab/python python3 -m slab_cortex_m.ci_runner \
       --batch slab/ci/ \
       --junit results.xml

This executes every ``.yaml`` file in ``slab/ci/`` and generates a JUnit XML report.

JSON Output
-----------

Export detailed results to JSON:

.. code-block:: bash

   PYTHONPATH=slab/python python3 -m slab_cortex_m.ci_runner \
       --scenario test.yaml \
       --output results.json

Example ``results.json``:

.. code-block:: json

   {
     "scenario": "STM32F405 LED blink",
     "passed": true,
     "duration": 10.23,
     "qemu_exit_code": 124,
     "mmio_count": 142,
     "assertions": [
       {"name": "no_crash", "passed": true, "detail": "QEMU exit code: 124"},
       {"name": "gpio_toggle", "passed": true, "detail": "GPIOA.13: 12 toggles"},
       {"name": "mmio_count", "passed": true, "detail": "142 >= 50"}
     ]
   }

Step 4: Generating Reports
===========================

The report generator runs all tests and produces comprehensive documentation.

Full Report Suite
-----------------

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
       --output-dir reports/ \
       --ci \
       --junit results.xml

**Generated Files:**

- ``results.xml``: JUnit XML for CI dashboards
- ``reports/<firmware>/report.tex``: LaTeX test report
- ``reports/<firmware>/mmio_trace.txt``: Full MMIO log
- ``reports/<firmware>/report.pdf``: Compiled PDF (requires pdflatex)

Specific Firmware
-----------------

Generate report for one firmware:

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
       --firmware "STM32F405 HelloBlink" \
       --output-dir reports/

MMIO Traces Only
----------------

Export MMIO logs without LaTeX:

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
       --mmio-log \
       --output-dir traces/

Step 5: GitHub Actions Integration
===================================

Complete workflow for automated testing on every push.

Create ``.github/workflows/slab-e2e.yml``:

.. code-block:: yaml

   name: SLAB E2E Tests

   on:
     push:
       branches: [main, develop]
     pull_request:
       branches: [main]

   jobs:
     test:
       runs-on: ubuntu-latest

       steps:
         - name: Checkout repository
           uses: actions/checkout@v4
           with:
             submodules: recursive

         - name: Install dependencies
           run: |
             sudo apt-get update
             sudo apt-get install -y \
               ninja-build \
               libglib2.0-dev \
               libpixman-1-dev \
               gcc-arm-none-eabi \
               python3-pip
             pip3 install cryptography pygame pyyaml

         - name: Build QEMU with slab-cortex-m
           run: |
             mkdir -p build && cd build
             ../configure --target-list=arm-softmmu --disable-docs
             ninja
             cd ..

         - name: Build firmware examples
           run: |
             make -C slab/examples/cortex-m/stm32/f405/demos/hello_blink
             make -C slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart

         - name: Run E2E tests
           run: |
             export PATH=$PWD/build:$PATH
             PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
               --ci \
               --junit results.xml \
               --output-dir reports/

         - name: Upload test results
           uses: actions/upload-artifact@v4
           if: always()
           with:
             name: test-reports
             path: |
               results.xml
               reports/

         - name: Publish test results
           uses: EnricoMi/publish-unit-test-result-action@v2
           if: always()
           with:
             files: results.xml

**Workflow Triggers:**

- ``push``: Run tests on every commit to main/develop
- ``pull_request``: Run tests on every PR

**Artifacts:**

Test reports are uploaded and accessible from the GitHub Actions UI for 90 days.

Step 6: Reading JUnit XML Results
==================================

JUnit XML is the standard format for test results in CI systems.

Example ``results.xml``:

.. code-block:: xml

   <testsuites>
     <testsuite name="slab-e2e" tests="2" failures="0" time="20.45">
       <testcase name="STM32F405 LED blink" time="10.23">
         <!-- PASS: No <failure> element -->
       </testcase>
       <testcase name="STM32F405 HelloBlinkUart" time="10.22">
         <failure message="gpio_toggle failed">
           GPIOA.13: 2 toggles &lt; 4 (expected)
         </failure>
       </testcase>
     </testsuite>
   </testsuites>

**CI Dashboard Integration:**

- Jenkins: Publish JUnit Test Result Report plugin
- GitHub Actions: ``EnricoMi/publish-unit-test-result-action``
- GitLab CI: ``junit: results.xml`` in ``.gitlab-ci.yml``

**Visual Feedback:**

CI systems display:

- Green checkmark for passing tests
- Red X for failing tests
- Test count summary (e.g., "15/16 passed")
- Per-test failure messages

Step 7: Understanding LaTeX Test Reports
=========================================

The generated LaTeX reports provide detailed documentation for audits and debugging.

Report Sections
---------------

**1. Architecture Diagram**

TikZ diagram showing:

- MCU core and memory
- Active peripherals (GPIO, UART, SPI, etc.)
- External devices (SPI flash, sensors, etc.)

**2. Peripheral Inventory**

Table listing all peripherals with base addresses and IRQ numbers.

**3. Build and Run Commands**

Exact commands to reproduce the test:

.. code-block:: bash

   # Build
   make -C slab/examples/cortex-m/stm32/f405/demos/hello_blink

   # Run
   PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
       --firmware "STM32F405 HelloBlink"

**4. MMIO Trace Timeline**

Chronological log of peripheral accesses:

.. code-block:: text

   0.000000  WRITE RCC.CR        0x00010001  (enable HSE)
   0.000123  READ  RCC.CR        0x00010001
   0.000456  READ  RCC.CR        0x00020001  (HSERDY set)
   0.001234  WRITE GPIOA.MODER   0x24000000

**5. Register Access Summary**

Table showing most-accessed registers (useful for reverse engineering):

.. code-block:: text

   Register         Reads  Writes  Total
   RCC.CR              45       1     46
   GPIOA.ODR            0      12     12
   TIM2.CNT            10       0     10

**6. Initialization Sequence**

Boot flow analysis showing peripheral initialization order (valuable for RE).

**7. UART Output**

Complete UART transcript (if firmware uses serial output).

**8. Test Verdict**

Pass/fail result with assertion details.

Use Cases
---------

- **Audits**: Provide evidence of firmware testing
- **Documentation**: Auto-generated test reports for releases
- **Debugging**: MMIO traces pinpoint crash locations
- **Reverse Engineering**: Understand firmware behavior without source code

Step 8: Adding Custom Assertions
=================================

Extend the CI framework with custom checks.

Example: Check UART Output
---------------------------

Edit ``slab/python/slab_cortex_m/ci_runner.py``:

.. code-block:: python

   def check_uart_output(server: 'CIBoardServer', params: dict) -> AssertionResult:
       """Check UART output contains expected string."""
       expected = params.get('contains', '')
       uart_output = getattr(server, 'uart_buffer', '')

       passed = expected in uart_output
       detail = f"Expected '{expected}' in UART output"
       if not passed:
           detail += f" (got: {uart_output[:50]}...)"

       return AssertionResult(
           name="uart_output",
           passed=passed,
           detail=detail
       )

Register the checker in ``ASSERTION_CHECKERS``:

.. code-block:: python

   ASSERTION_CHECKERS = {
       'no_crash': check_no_crash,
       'mmio_count': check_mmio_count,
       'gpio_toggle': check_gpio_toggle,
       'uart_output': check_uart_output,  # New!
   }

Update the server to capture UART:

.. code-block:: python

   class CIBoardServer(BasePeripheralServer):
       def __init__(self, board, port: int):
           super().__init__(port)
           self.uart_buffer = ""

           # Register UART callback
           for p in board.adapter.peripherals:
               if hasattr(p, 'name') and 'UART' in getattr(p, 'name', ''):
                   p.tx_callback = self._on_uart_tx

       def _on_uart_tx(self, char: int):
           self.uart_buffer += chr(char)

Use in YAML:

.. code-block:: yaml

   assertions:
     - type: uart_output
       params:
         contains: "Boot complete"

Best Practices
==============

**1. Test Isolation**

Each scenario should be independent (no shared state between tests).

**2. Deterministic Timeouts**

Use consistent timeouts for reproducible results:

- Boot tests: 5 seconds
- LED blink: 10 seconds
- Complex demos: 30 seconds

**3. Meaningful Assertions**

Combine multiple assertions for robust validation:

.. code-block:: yaml

   assertions:
     - type: no_crash           # Firmware didn't fault
     - type: mmio_count         # Reached main loop
       params: {min: 100}

**4. MMIO Threshold Tuning**

Run tests locally first to determine realistic MMIO counts, then set ``min``
to ~70% of observed value (allows variance).

**5. Artifact Retention**

Always upload test reports in CI (even on failure) for post-mortem debugging.

Next Steps
==========

- :ref:`debugging_bootloops` - Fix tests that hang during boot
- :ref:`stubbing_peripherals` - Create custom peripheral stubs for complex devices
- ``slab/ci/`` - Browse existing test scenarios (``test_hello_blink.yaml``, ``test_h563_tz.yaml``)

**Further Reading:**

- JUnit XML format: https://www.ibm.com/docs/en/developer-for-zos/14.1?topic=formats-junit-xml-format
- GitHub Actions artifacts: https://docs.github.com/en/actions/using-workflows/storing-workflow-data-as-artifacts
