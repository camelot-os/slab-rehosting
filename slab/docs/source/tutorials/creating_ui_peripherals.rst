.. _creating_ui_peripherals:

==========================
Creating UI Peripherals
==========================

This tutorial shows how to create visual peripherals using MCUemu's GUI framework.
You'll learn to build LED displays, consoles, and logic analyzers.

Overview
========

MCUemu provides ``slab_gui`` for pygame-based visualization:

.. figure:: ../images/debug_dashboard.png
   :alt: Debug Dashboard
   :align: center
   :width: 90%

   Debug Dashboard: Control panel, LED status, logic analyzer, dual console

Available Widgets
=================

.. list-table:: GUI Widgets
   :widths: 25 75
   :header-rows: 1

   * - Widget
     - Description
   * - ``LEDStatusPro``
     - GPIO LED display with glow effects
   * - ``ConsoleWidget``
     - Interactive console with input field
   * - ``LogicAnalyzerPro``
     - Real-time waveform display with zoom/pan
   * - ``ControlPanel``
     - Start/Stop/Reset buttons with status
   * - ``DebugDashboardPro``
     - Complete dashboard combining all widgets

Creating an LED Display
=======================

.. code-block:: python
   :caption: led_display.py

   from slab_gui.debug_dashboard import (
       LEDStatusPro, Theme, PYGAME_AVAILABLE
   )
   import pygame

   # Initialize pygame
   pygame.init()
   screen = pygame.display.set_mode((300, 100))
   clock = pygame.time.Clock()

   # Create LED widget
   led_panel = LEDStatusPro(x=10, y=10, width=280, height=80)

   # Add LEDs with custom colors
   led_panel.add_led("PA5", Theme.ACCENT_GREEN)   # Green LED
   led_panel.add_led("PB0", Theme.ACCENT_BLUE)    # Blue LED
   led_panel.add_led("PC13", Theme.ACCENT_RED)    # Red LED

   # Main loop
   running = True
   while running:
       for event in pygame.event.get():
           if event.type == pygame.QUIT:
               running = False

       # Toggle LEDs (simulation)
       import time
       led_panel.set_led("PA5", int(time.time()) % 2 == 0)

       screen.fill(Theme.BG_PRIMARY)
       led_panel.draw(screen)
       pygame.display.flip()
       clock.tick(30)

   pygame.quit()

Connecting LEDs to GPIO
-----------------------

.. code-block:: python

   from slab_stm32.stm32_gpio import STM32GPIO

   # Create GPIO with LED callback
   gpioa = STM32GPIO(base=0x40020000, port_name='A')

   def on_gpio_change(pin, value, is_output):
       if is_output:
           led_name = f"A{pin}"
           led_panel.set_led(led_name, bool(value))

   gpioa.on_pin_change = on_gpio_change

Creating an Interactive Console
===============================

.. code-block:: python
   :caption: console_example.py

   from slab_gui.debug_dashboard import ConsoleWidget, Theme
   import pygame

   pygame.init()
   screen = pygame.display.set_mode((400, 300))

   # Create console
   console = ConsoleWidget(
       x=10, y=10, width=380, height=280,
       title="UART Console",
       color=Theme.ACCENT_GREEN
   )

   # Handle input submission
   def on_input(text):
       console.add_line(f"[TX] {text}")
       # Send to peripheral...

   console.on_input = on_input

   # Add initial messages
   console.add_line("Console ready")
   console.add_line("Type below and press Enter")

   running = True
   while running:
       for event in pygame.event.get():
           if event.type == pygame.QUIT:
               running = False
           else:
               console.handle_event(event)

       screen.fill(Theme.BG_PRIMARY)
       console.draw(screen)
       pygame.display.flip()

   pygame.quit()

Connecting Console to UART
--------------------------

.. code-block:: python

   from slab_stm32.stm32_usart import STM32USART

   usart = STM32USART(base=0x40004400, name='USART2')

   # Display TX output
   def on_uart_tx(byte):
       if byte == 0x0A:  # Newline
           line = tx_buffer.decode('utf-8', errors='replace')
           console.add_line(line.strip())
           tx_buffer.clear()
       else:
           tx_buffer.append(byte)

   tx_buffer = bytearray()
   usart.on_tx = on_uart_tx

   # Handle console input
   def on_input(text):
       usart.inject_rx((text + '\r\n').encode())

   console.on_input = on_input

Logic Analyzer with Zoom
========================

The ``LogicAnalyzerPro`` widget displays real-time waveforms:

.. code-block:: python
   :caption: logic_analyzer_example.py

   from slab_gui.debug_dashboard import (
       LogicAnalyzerPro, SignalCapture, SignalType, Theme
   )
   import pygame
   import time

   pygame.init()
   screen = pygame.display.set_mode((800, 200))

   # Create capture engine
   capture = SignalCapture()
   capture.add_channel("CLK", SignalType.DIGITAL, Theme.ACCENT_CYAN)
   capture.add_channel("DATA", SignalType.DIGITAL, Theme.ACCENT_GREEN)
   capture.add_channel("TX", SignalType.UART_TX, Theme.ACCENT_YELLOW)
   capture.start()

   # Create analyzer widget
   analyzer = LogicAnalyzerPro(
       x=10, y=10, width=780, height=180,
       capture=capture
   )

   # Simulate signals
   start = time.time()
   clock_state = 0

   running = True
   while running:
       for event in pygame.event.get():
           if event.type == pygame.QUIT:
               running = False
           else:
               analyzer.handle_event(event)  # Zoom/pan

       # Generate test signals
       if int((time.time() - start) * 100) % 2 == 0:
           clock_state = 1 - clock_state
           capture.record("CLK", clock_state)

       screen.fill(Theme.BG_PRIMARY)
       analyzer.draw(screen)
       pygame.display.flip()

   # Export capture
   capture.export_vcd("/tmp/capture.vcd")
   capture.export_sigrok("/tmp/capture.sr")

   pygame.quit()

**Zoom Controls:**

- Mouse wheel: Zoom in/out
- Click + drag: Pan waveforms
- +/- keys: Zoom in/out
- Left/Right arrows: Scroll

Complete Debug Dashboard
========================

The ``DebugDashboardPro`` combines all widgets:

.. code-block:: python
   :caption: full_dashboard.py

   from slab_gui.debug_dashboard import (
       DebugDashboardPro, SignalType, Theme
   )

   # Create dashboard
   dashboard = DebugDashboardPro(
       width=900, height=700,
       title="MCUemu Debug Dashboard"
   )

   if not dashboard.init_pygame():
       print("Failed to init pygame")
       exit(1)

   # Add LEDs
   for name, color in [
       ("LED1", Theme.ACCENT_GREEN),
       ("LED2", Theme.ACCENT_BLUE),
       ("LED3", Theme.ACCENT_RED),
   ]:
       dashboard.add_led(name, color)

   # Add signal channels
   dashboard.add_signal("GPIO", SignalType.DIGITAL)
   dashboard.add_signal("UART_TX", SignalType.UART_TX)
   dashboard.add_signal("SPI_CLK", SignalType.SPI)

   # Wire up callbacks
   dashboard.on_start = lambda: print("Started")
   dashboard.on_stop = lambda: print("Stopped")
   dashboard.on_reset = lambda: print("Reset")
   dashboard.on_uart_input = lambda t: print(f"UART: {t}")
   dashboard.on_cdc_input = lambda t: print(f"CDC: {t}")

   # Run main loop
   dashboard.run_loop()
   dashboard.close()

Integrating with Emulation
==========================

Connect the dashboard to a running QEMU emulation:

.. code-block:: python

   async def run_with_dashboard():
       dashboard = DebugDashboardPro(width=900, height=700)
       dashboard.init_pygame()

       # Create peripheral set with dashboard integration
       ps = STM32F4PeripheralSet()

       # Connect GPIO to LEDs
       for port, gpio in ps.gpio.items():
           gpio.on_pin_change = lambda pin, val, is_out, p=port: \
               dashboard.set_led(f"{p}{pin}", bool(val)) if is_out else None

       # Connect UART to console
       ps.usart2.on_tx = lambda b: dashboard.uart_console.add_byte(b)

       # Wire dashboard callbacks to emulator control
       async def start():
           await start_qemu()
       dashboard.on_start = lambda: asyncio.create_task(start())

       # Main loop
       while dashboard.running:
           dashboard.handle_events()
           dashboard.draw()
           await asyncio.sleep(0.001)

       dashboard.close()

   asyncio.run(run_with_dashboard())

Exporting Captures
==================

Export waveforms for analysis with external tools:

.. code-block:: python

   # VCD format (GTKWave compatible)
   capture.export_vcd("/tmp/capture.vcd")

   # Sigrok session format (PulseView compatible)
   capture.export_sigrok("/tmp/capture.sr")

   # Open in GTKWave
   # $ gtkwave /tmp/capture.vcd

   # Open in PulseView
   # $ pulseview /tmp/capture.sr

Next Steps
==========

* :ref:`debugging_bootloops` - Diagnose and fix boot issues
* :ref:`trustzone_emulation` - Emulate secure firmware
* :ref:`api/slab_gui` - Full GUI API reference
