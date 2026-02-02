.. _api_slab_gui:

============
slab_gui API
============

GUI components for MCU visualization.

.. automodule:: slab_gui
   :members:
   :undoc-members:
   :show-inheritance:

Debug Dashboard
===============

.. automodule:: slab_gui.debug_dashboard
   :members:
   :undoc-members:

Classes
-------

DebugDashboardPro
^^^^^^^^^^^^^^^^^

Complete debug dashboard combining all widgets.

.. code-block:: python

   from slab_gui.debug_dashboard import DebugDashboardPro

   dashboard = DebugDashboardPro(width=900, height=700)
   dashboard.init_pygame()

   # Add LEDs
   dashboard.add_led("PA5", (0, 255, 0))
   dashboard.add_led("PB0", (0, 100, 255))

   # Add signal channels
   dashboard.add_signal("GPIO", SignalType.DIGITAL)
   dashboard.add_signal("UART_TX", SignalType.UART_TX)

   # Wire callbacks
   dashboard.on_start = lambda: print("Started")
   dashboard.on_stop = lambda: print("Stopped")

   # Run
   dashboard.run_loop()

LogicAnalyzerPro
^^^^^^^^^^^^^^^^

Real-time waveform display with zoom and pan.

.. code-block:: python

   from slab_gui.debug_dashboard import LogicAnalyzerPro, SignalCapture

   capture = SignalCapture()
   capture.add_channel("CLK", color=(0, 255, 255))
   capture.start()

   analyzer = LogicAnalyzerPro(x=0, y=0, width=800, height=200, capture=capture)

   # Record transitions
   capture.record("CLK", 1)
   capture.record("CLK", 0)

   # Zoom
   analyzer.zoom_in()
   analyzer.zoom_out()

ConsoleWidget
^^^^^^^^^^^^^

Interactive console with input field.

.. code-block:: python

   from slab_gui.debug_dashboard import ConsoleWidget

   console = ConsoleWidget(x=0, y=0, width=400, height=300,
                           title="UART", color=(100, 255, 100))

   console.on_input = lambda text: print(f"Input: {text}")
   console.add_line("Console ready")

LEDStatusPro
^^^^^^^^^^^^

LED status display with glow effects.

.. code-block:: python

   from slab_gui.debug_dashboard import LEDStatusPro

   leds = LEDStatusPro(x=0, y=0, width=200, height=100)
   leds.add_led("LED1", (0, 255, 0))
   leds.add_led("LED2", (255, 0, 0))

   leds.set_led("LED1", True)   # Turn on
   leds.set_led("LED2", False)  # Turn off

ControlPanel
^^^^^^^^^^^^

Emulator control with Start/Stop/Reset buttons.

.. code-block:: python

   from slab_gui.debug_dashboard import ControlPanel

   control = ControlPanel(x=0, y=0, width=300, height=80)

   control.on_start = lambda: print("Start clicked")
   control.on_stop = lambda: print("Stop clicked")
   control.on_reset = lambda: print("Reset clicked")

   control.set_running(True)
   control.update_stats(ops=1000, elapsed=1.5)

Signal Capture
--------------

.. autoclass:: slab_gui.debug_dashboard.SignalCapture
   :members:

Export Formats
^^^^^^^^^^^^^^

VCD (Value Change Dump):

.. code-block:: python

   capture.export_vcd("/tmp/capture.vcd")

Sigrok session (.sr):

.. code-block:: python

   capture.export_sigrok("/tmp/capture.sr")

Logic Analyzer (Legacy)
=======================

.. automodule:: slab_gui.logic_analyzer
   :members:
   :undoc-members:

LED Widgets
===========

.. automodule:: slab_gui.led
   :members:
   :undoc-members:
