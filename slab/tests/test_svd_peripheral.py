"""
Tests for SVD Auto-Stub Peripheral Set and Board Integration

Tests SVDStubPeripheral, SVDStubPeripheralSet, SVD board mode,
binary patches, and quickstart integration.

Author: Twisted Wires Security Lab
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
import pytest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from slab_cortex_m.svd_parser import SVDParser, SVDDevice, SVDPeripheral, SVDRegister, SVDField, SVDInterrupt
from slab_cortex_m.svd_peripheral import SVDStubPeripheral, SVDStubPeripheralSet, _map_svd_cpu

# =============================================================================
# FIXTURES
# =============================================================================

MINIMAL_SVD = '''\
<?xml version="1.0" encoding="utf-8"?>
<device schemaVersion="1.1" xmlns:xs="http://www.w3.org/2001/XMLSchema-instance">
  <name>TEST_MCU</name>
  <version>1.0</version>
  <description>Test MCU for unit tests</description>
  <vendor>TestVendor</vendor>
  <cpu>
    <name>CM4</name>
    <revision>r0p1</revision>
    <endian>little</endian>
    <mpuPresent>1</mpuPresent>
    <fpuPresent>1</fpuPresent>
    <nvicPrioBits>4</nvicPrioBits>
  </cpu>
  <addressUnitBits>8</addressUnitBits>
  <width>32</width>
  <peripherals>
    <peripheral>
      <name>RCC</name>
      <description>Reset and Clock Control</description>
      <baseAddress>0x40023800</baseAddress>
      <addressBlock>
        <offset>0</offset>
        <size>0x400</size>
        <usage>registers</usage>
      </addressBlock>
      <registers>
        <register>
          <name>CR</name>
          <description>Clock control register</description>
          <addressOffset>0x00</addressOffset>
          <size>32</size>
          <resetValue>0x00000083</resetValue>
          <fields>
            <field>
              <name>HSION</name>
              <description>HSI clock enable</description>
              <bitOffset>0</bitOffset>
              <bitWidth>1</bitWidth>
            </field>
            <field>
              <name>HSIRDY</name>
              <description>HSI clock ready</description>
              <bitOffset>1</bitOffset>
              <bitWidth>1</bitWidth>
              <access>read-only</access>
            </field>
            <field>
              <name>PLLON</name>
              <description>PLL enable</description>
              <bitOffset>24</bitOffset>
              <bitWidth>1</bitWidth>
            </field>
            <field>
              <name>PLLRDY</name>
              <description>PLL ready</description>
              <bitOffset>25</bitOffset>
              <bitWidth>1</bitWidth>
              <access>read-only</access>
            </field>
          </fields>
        </register>
        <register>
          <name>CFGR</name>
          <description>Clock configuration register</description>
          <addressOffset>0x08</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
          <fields>
            <field>
              <name>SW</name>
              <description>System clock switch</description>
              <bitOffset>0</bitOffset>
              <bitWidth>2</bitWidth>
            </field>
            <field>
              <name>SWS</name>
              <description>System clock switch status</description>
              <bitOffset>2</bitOffset>
              <bitWidth>2</bitWidth>
              <access>read-only</access>
            </field>
          </fields>
        </register>
        <register>
          <name>AHB1ENR</name>
          <description>AHB1 peripheral clock enable</description>
          <addressOffset>0x30</addressOffset>
          <size>32</size>
          <resetValue>0x00100000</resetValue>
          <fields>
            <field>
              <name>GPIOAEN</name>
              <description>GPIOA clock enable</description>
              <bitOffset>0</bitOffset>
              <bitWidth>1</bitWidth>
            </field>
          </fields>
        </register>
      </registers>
      <interrupt>
        <name>RCC</name>
        <description>RCC global interrupt</description>
        <value>5</value>
      </interrupt>
    </peripheral>
    <peripheral>
      <name>GPIOA</name>
      <description>General-purpose I/Os</description>
      <baseAddress>0x40020000</baseAddress>
      <addressBlock>
        <offset>0</offset>
        <size>0x400</size>
        <usage>registers</usage>
      </addressBlock>
      <registers>
        <register>
          <name>MODER</name>
          <description>GPIO port mode register</description>
          <addressOffset>0x00</addressOffset>
          <size>32</size>
          <resetValue>0xA8000000</resetValue>
        </register>
        <register>
          <name>IDR</name>
          <description>GPIO port input data register</description>
          <addressOffset>0x10</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
          <access>read-only</access>
        </register>
        <register>
          <name>ODR</name>
          <description>GPIO port output data register</description>
          <addressOffset>0x14</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
        </register>
      </registers>
    </peripheral>
    <peripheral>
      <name>USART1</name>
      <description>Universal synchronous asynchronous receiver transmitter</description>
      <baseAddress>0x40011000</baseAddress>
      <addressBlock>
        <offset>0</offset>
        <size>0x400</size>
        <usage>registers</usage>
      </addressBlock>
      <registers>
        <register>
          <name>SR</name>
          <description>Status register</description>
          <addressOffset>0x00</addressOffset>
          <size>32</size>
          <resetValue>0x00C00000</resetValue>
        </register>
        <register>
          <name>DR</name>
          <description>Data register</description>
          <addressOffset>0x04</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
        </register>
        <register>
          <name>CR1</name>
          <description>Control register 1</description>
          <addressOffset>0x0C</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
          <fields>
            <field>
              <name>UE</name>
              <description>USART enable</description>
              <bitOffset>13</bitOffset>
              <bitWidth>1</bitWidth>
            </field>
          </fields>
        </register>
      </registers>
      <interrupt>
        <name>USART1</name>
        <description>USART1 global interrupt</description>
        <value>37</value>
      </interrupt>
    </peripheral>
  </peripherals>
</device>
'''

NRF_SVD = '''\
<?xml version="1.0" encoding="utf-8"?>
<device schemaVersion="1.1">
  <name>nRF52840</name>
  <version>1.0</version>
  <description>Nordic nRF52840</description>
  <vendor>Nordic Semiconductor</vendor>
  <cpu>
    <name>CM4</name>
    <revision>r0p1</revision>
    <endian>little</endian>
    <mpuPresent>1</mpuPresent>
    <fpuPresent>1</fpuPresent>
    <nvicPrioBits>3</nvicPrioBits>
  </cpu>
  <addressUnitBits>8</addressUnitBits>
  <width>32</width>
  <peripherals>
    <peripheral>
      <name>CLOCK</name>
      <description>Clock control</description>
      <baseAddress>0x40000000</baseAddress>
      <addressBlock>
        <offset>0</offset>
        <size>0x1000</size>
        <usage>registers</usage>
      </addressBlock>
      <registers>
        <register>
          <name>TASKS_HFCLKSTART</name>
          <addressOffset>0x000</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
        </register>
        <register>
          <name>EVENTS_HFCLKSTARTED</name>
          <addressOffset>0x100</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
        </register>
      </registers>
    </peripheral>
  </peripherals>
</device>
'''


@pytest.fixture
def svd_file(tmp_path):
    """Create a temporary SVD file."""
    path = tmp_path / "test_mcu.svd"
    path.write_text(MINIMAL_SVD)
    return str(path)


@pytest.fixture
def nrf_svd_file(tmp_path):
    path = tmp_path / "nrf52840.svd"
    path.write_text(NRF_SVD)
    return str(path)


@pytest.fixture
def svd_device():
    """Parse the minimal SVD and return device."""
    parser = SVDParser()
    return parser.parse_string(MINIMAL_SVD)


@pytest.fixture
def stub_pset(svd_file):
    return SVDStubPeripheralSet.from_svd(svd_file)


# =============================================================================
# SVDStubPeripheral TESTS
# =============================================================================

class TestSVDStubPeripheral:
    def test_create_from_svd(self, svd_device):
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc)
        assert stub.name == 'RCC'
        assert stub.base == 0x40023800
        assert stub.size == 0x400
        assert stub.irq == 5

    def test_reset_values(self, svd_device):
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc)
        # CR reset = 0x83
        val, status = stub.read(0x40023800, 4)
        assert val == 0x00000083
        assert status == 0

    def test_write_and_read_back(self, svd_device):
        gpio = svd_device.get_peripheral('GPIOA')
        stub = SVDStubPeripheral(gpio)
        # Write ODR
        stub.write(0x40020014, 4, 0x55AA)
        val, _ = stub.read(0x40020014, 4)
        assert val == 0x55AA

    def test_read_only_register_ignored(self, svd_device):
        gpio = svd_device.get_peripheral('GPIOA')
        stub = SVDStubPeripheral(gpio)
        # IDR is read-only, write should be ignored
        stub.write(0x40020010, 4, 0x1234)
        val, _ = stub.read(0x40020010, 4)
        assert val == 0  # Still reset value

    def test_contains(self, svd_device):
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc)
        assert stub.contains(0x40023800)
        assert stub.contains(0x40023BFF)
        assert not stub.contains(0x40023C00)
        assert not stub.contains(0x40020000)

    def test_ready_bit_auto_set(self, svd_device):
        """Test that HSION -> HSIRDY and PLLON -> PLLRDY auto-set works."""
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc, auto_ready=True)

        # Clear all bits first
        stub.regs[0x00] = 0

        # Set HSION (bit 0)
        stub.write(0x40023800, 4, 0x01)
        val, _ = stub.read(0x40023800, 4)
        # HSIRDY (bit 1) should be auto-set
        assert val & 0x02, f"HSIRDY not set: 0x{val:08X}"

        # Set PLLON (bit 24)
        stub.write(0x40023800, 4, val | (1 << 24))
        val, _ = stub.read(0x40023800, 4)
        # PLLRDY (bit 25) should be auto-set
        assert val & (1 << 25), f"PLLRDY not set: 0x{val:08X}"

    def test_ready_bit_auto_clear(self, svd_device):
        """Test that clearing enable also clears ready."""
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc, auto_ready=True)

        # Set HSION
        stub.regs[0x00] = 0
        stub.write(0x40023800, 4, 0x01)
        val, _ = stub.read(0x40023800, 4)
        assert val & 0x02  # HSIRDY set

        # Clear HSION
        stub.write(0x40023800, 4, 0x00)
        val, _ = stub.read(0x40023800, 4)
        assert not (val & 0x02)  # HSIRDY cleared

    def test_no_auto_ready(self, svd_device):
        """Test with auto_ready disabled."""
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc, auto_ready=False)
        stub.regs[0x00] = 0

        stub.write(0x40023800, 4, 0x01)
        val, _ = stub.read(0x40023800, 4)
        # No auto-ready, HSIRDY should NOT be set
        assert not (val & 0x02)

    def test_byte_write(self, svd_device):
        gpio = svd_device.get_peripheral('GPIOA')
        stub = SVDStubPeripheral(gpio)
        # Write byte to ODR
        stub.write(0x40020014, 4, 0xAABBCCDD)
        # Write byte to lower byte only
        stub.write(0x40020014, 1, 0x11)
        val, _ = stub.read(0x40020014, 4)
        assert val == 0xAABBCC11

    def test_halfword_write(self, svd_device):
        gpio = svd_device.get_peripheral('GPIOA')
        stub = SVDStubPeripheral(gpio)
        stub.write(0x40020014, 4, 0xAABBCCDD)
        stub.write(0x40020014, 2, 0x1122)
        val, _ = stub.read(0x40020014, 4)
        assert val == 0xAABB1122

    def test_byte_read(self, svd_device):
        gpio = svd_device.get_peripheral('GPIOA')
        stub = SVDStubPeripheral(gpio)
        stub.write(0x40020014, 4, 0xAABBCCDD)
        val, _ = stub.read(0x40020014, 1)
        assert val == 0xDD

    def test_reset(self, svd_device):
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc)
        stub.write(0x40023800, 4, 0xFFFFFFFF)
        stub.reset()
        val, _ = stub.read(0x40023800, 4)
        assert val == 0x00000083

    def test_trigger_irq(self, svd_device):
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc)
        irqs = []
        stub.irq_callback = lambda n, l: irqs.append((n, l))
        stub.trigger_irq(1)
        assert irqs == [(5, 1)]

    def test_trigger_irq_no_callback(self, svd_device):
        rcc = svd_device.get_peripheral('RCC')
        stub = SVDStubPeripheral(rcc)
        # Should not raise
        stub.trigger_irq(1)


# =============================================================================
# SVDStubPeripheralSet TESTS
# =============================================================================

class TestSVDStubPeripheralSet:
    def test_from_svd(self, svd_file):
        pset = SVDStubPeripheralSet.from_svd(svd_file)
        assert pset.name == 'TEST_MCU'
        assert len(pset.peripherals) == 3  # RCC, GPIOA, USART1

    def test_find_peripheral(self, stub_pset):
        p = stub_pset.find_peripheral(0x40023800)
        assert p is not None
        assert p.name == 'RCC'

    def test_find_peripheral_not_found(self, stub_pset):
        p = stub_pset.find_peripheral(0x50000000)
        assert p is None

    def test_get_peripheral(self, stub_pset):
        p = stub_pset.get_peripheral('GPIOA')
        assert p is not None
        assert p.base == 0x40020000

    def test_read_through(self, stub_pset):
        val, status = stub_pset.read(0x40023800, 4)
        assert val == 0x83
        assert status == 0

    def test_write_through(self, stub_pset):
        stub_pset.write(0x40020014, 4, 0xABCD)
        val, _ = stub_pset.read(0x40020014, 4)
        assert val == 0xABCD

    def test_read_unmapped(self, stub_pset):
        val, status = stub_pset.read(0x50000000, 4)
        assert val == 0
        assert status == 0

    def test_setup_irq_callback(self, stub_pset):
        irqs = []
        stub_pset.setup_irq_callback(lambda n, l: irqs.append((n, l)))
        rcc = stub_pset.get_peripheral('RCC')
        rcc.trigger_irq(1)
        assert irqs == [(5, 1)]

    def test_reset(self, stub_pset):
        stub_pset.write(0x40023800, 4, 0xFFFF)
        stub_pset.reset()
        val, _ = stub_pset.read(0x40023800, 4)
        assert val == 0x83

    def test_get_memory_info(self, stub_pset):
        info = stub_pset.get_memory_info()
        assert info['cpu_type'] == 'cortex-m4'
        assert info['flash_base'] == 0x08000000
        assert info['sram_base'] == 0x20000000
        assert info['periph_base'] == 0x40000000
        assert info['periph_size'] > 0

    def test_skips_arm_internal(self):
        """ARM internal peripherals (>= 0xE0000000) should be skipped."""
        svd = '''\
<?xml version="1.0" encoding="utf-8"?>
<device schemaVersion="1.1">
  <name>T</name><version>1</version><description>t</description>
  <cpu><name>CM4</name><revision>r0</revision><endian>little</endian>
    <mpuPresent>0</mpuPresent><fpuPresent>0</fpuPresent><nvicPrioBits>4</nvicPrioBits>
  </cpu>
  <addressUnitBits>8</addressUnitBits><width>32</width>
  <peripherals>
    <peripheral>
      <name>GPIOA</name><description>t</description><baseAddress>0x40020000</baseAddress>
      <registers><register><name>R</name><addressOffset>0</addressOffset>
        <size>32</size><resetValue>0</resetValue></register></registers>
    </peripheral>
    <peripheral>
      <name>NVIC</name><description>t</description><baseAddress>0xE000E100</baseAddress>
      <registers><register><name>ISER0</name><addressOffset>0</addressOffset>
        <size>32</size><resetValue>0</resetValue></register></registers>
    </peripheral>
  </peripherals>
</device>'''
        parser = SVDParser()
        dev = parser.parse_string(svd)
        pset = SVDStubPeripheralSet(dev)
        assert len(pset.peripherals) == 1
        assert pset.peripherals[0].name == 'GPIOA'


# =============================================================================
# MEMORY LAYOUT DETECTION TESTS
# =============================================================================

class TestMemoryLayout:
    def test_nrf_detection(self, nrf_svd_file):
        pset = SVDStubPeripheralSet.from_svd(nrf_svd_file)
        info = pset.get_memory_info()
        assert info['flash_base'] == 0x00000000
        assert info['cpu_type'] == 'cortex-m4'

    def test_cpu_mapping(self):
        assert _map_svd_cpu('CM0') == 'cortex-m0'
        assert _map_svd_cpu('CM0+') == 'cortex-m0'
        assert _map_svd_cpu('CM3') == 'cortex-m3'
        assert _map_svd_cpu('CM4') == 'cortex-m4'
        assert _map_svd_cpu('CM7') == 'cortex-m7'
        assert _map_svd_cpu('CM33') == 'cortex-m33'
        assert _map_svd_cpu('CM55') == 'cortex-m55'
        assert _map_svd_cpu('unknown') == 'cortex-m4'


# =============================================================================
# BOARD INTEGRATION TESTS
# =============================================================================

class TestBoardSVDMode:
    def test_load_svd_board_config(self, svd_file, tmp_path):
        """Test loading a board YAML with SVD: prefix."""
        from slab_cortex_m.board import load_board_config
        board_yaml = tmp_path / "test_board.yaml"
        board_yaml.write_text(f"""\
name: Test_SVD_Board
mcu: "SVD:{svd_file}"
clock: 168000000
""")
        config = load_board_config(str(board_yaml))
        assert config.svd_path == svd_file
        assert config.mcu.startswith('SVD:')

    def test_create_svd_peripheral_set(self, svd_file, tmp_path):
        """Test creating peripheral set from SVD board config."""
        from slab_cortex_m.board import load_board_config, create_peripheral_set
        board_yaml = tmp_path / "test_board.yaml"
        board_yaml.write_text(f"""\
name: Test_SVD_Board
mcu: "SVD:{svd_file}"
""")
        config = load_board_config(str(board_yaml))
        pset = create_peripheral_set(config)
        assert isinstance(pset, SVDStubPeripheralSet)
        assert len(pset.peripherals) == 3

    def test_get_qemu_cpu_svd(self, svd_file, tmp_path):
        from slab_cortex_m.board import load_board_config, get_qemu_cpu
        board_yaml = tmp_path / "test_board.yaml"
        board_yaml.write_text(f"""\
name: Test_SVD_Board
mcu: "SVD:{svd_file}"
""")
        config = load_board_config(str(board_yaml))
        cpu = get_qemu_cpu(config)
        assert cpu == 'cortex-m4'

    def test_qemu_cpu_override(self, svd_file, tmp_path):
        from slab_cortex_m.board import load_board_config, get_qemu_cpu
        board_yaml = tmp_path / "test_board.yaml"
        board_yaml.write_text(f"""\
name: Test_SVD_Board
mcu: "SVD:{svd_file}"
qemu_cpu: cortex-m7
""")
        config = load_board_config(str(board_yaml))
        assert get_qemu_cpu(config) == 'cortex-m7'

    def test_svd_relative_path(self, tmp_path):
        """Test that SVD relative paths resolve against board YAML dir."""
        from slab_cortex_m.board import load_board_config
        svd = tmp_path / "device.svd"
        svd.write_text(MINIMAL_SVD)
        board_yaml = tmp_path / "board.yaml"
        board_yaml.write_text("""\
name: Test
mcu: "SVD:device.svd"
""")
        config = load_board_config(str(board_yaml))
        assert config.svd_path == str(tmp_path / "device.svd")

    def test_build_board_svd(self, svd_file, tmp_path):
        """Test building a full board from SVD config."""
        from slab_cortex_m.board import load_board_config
        from slab_cortex_m.board_builder import build_board
        board_yaml = tmp_path / "test_board.yaml"
        board_yaml.write_text(f"""\
name: Test_SVD_Board
mcu: "SVD:{svd_file}"
clock: 168000000
""")
        config = load_board_config(str(board_yaml))
        board = build_board(config)
        assert board.name == 'Test_SVD_Board'
        # Should be able to read/write
        val, status = board.read(0x40023800, 4)
        assert val == 0x83
        board.write(0x40020014, 4, 0xDEAD)
        val, _ = board.read(0x40020014, 4)
        assert val == 0xDEAD


# =============================================================================
# BINARY PATCH TESTS
# =============================================================================

class TestBinaryPatches:
    def test_parse_patches_list(self, tmp_path):
        from slab_cortex_m.board import load_board_config
        board_yaml = tmp_path / "test.yaml"
        board_yaml.write_text("""\
name: PatchTest
mcu: STM32F405
patches:
  - start: 0x08001000
    data: [0x70, 0x47]
    description: "NOP a delay"
  - start: "0x08002000"
    data: "00bf00bf"
    description: "NOP 2 instructions"
""")
        config = load_board_config(str(board_yaml))
        assert len(config.patches) == 2
        assert config.patches[0].address == 0x08001000
        assert config.patches[0].data == bytes([0x70, 0x47])
        assert config.patches[0].description == "NOP a delay"
        assert config.patches[1].address == 0x08002000
        assert config.patches[1].data == bytes([0x00, 0xBF, 0x00, 0xBF])

    def test_apply_patches(self, tmp_path):
        from slab_cortex_m.board import BoardConfig, PatchEntry, apply_patches
        firmware = bytearray(0x4000)
        firmware[0x1000:0x1002] = b'\xAA\xBB'

        config = BoardConfig(
            name="test", mcu="STM32F405",
            patches=[
                PatchEntry(address=0x08001000, data=b'\x70\x47'),
                PatchEntry(address=0x08002000, data=b'\x00\xBF'),
            ]
        )
        n = apply_patches(firmware, config, load_base=0x08000000)
        assert n == 2
        assert firmware[0x1000:0x1002] == b'\x70\x47'
        assert firmware[0x2000:0x2001] == b'\x00'

    def test_apply_patches_out_of_range(self, tmp_path):
        from slab_cortex_m.board import BoardConfig, PatchEntry, apply_patches
        firmware = bytearray(0x100)
        config = BoardConfig(
            name="test", mcu="STM32F405",
            patches=[PatchEntry(address=0x08010000, data=b'\x70\x47')]
        )
        n = apply_patches(firmware, config, load_base=0x08000000)
        assert n == 0  # Patch out of range

    def test_no_patches(self):
        from slab_cortex_m.board import BoardConfig, apply_patches
        firmware = bytearray(0x100)
        config = BoardConfig(name="test", mcu="STM32F405")
        n = apply_patches(firmware, config)
        assert n == 0


# =============================================================================
# PERIPHERAL ADAPTER INTEGRATION
# =============================================================================

class TestAdapterIntegration:
    def test_svd_pset_with_adapter(self, svd_file):
        """Test that SVD stub pset works through PeripheralSetAdapter."""
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        pset = SVDStubPeripheralSet.from_svd(svd_file)
        adapter = PeripheralSetAdapter(pset, family='stm32')

        # Read through adapter
        val, status = adapter.read(0x40023800, 4)
        assert val == 0x83

        # Write through adapter
        adapter.write(0x40020014, 4, 0xBEEF)
        val, _ = adapter.read(0x40020014, 4)
        assert val == 0xBEEF

    def test_svd_pset_contains(self, svd_file):
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        pset = SVDStubPeripheralSet.from_svd(svd_file)
        adapter = PeripheralSetAdapter(pset, family='stm32')
        assert adapter.contains(0x40023800)
        assert not adapter.contains(0x50000000)

    def test_svd_pset_irq(self, svd_file):
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        pset = SVDStubPeripheralSet.from_svd(svd_file)
        adapter = PeripheralSetAdapter(pset, family='stm32')
        irqs = []
        adapter.irq_callback = lambda n, l: irqs.append((n, l))
        rcc = pset.get_peripheral('RCC')
        rcc.trigger_irq(1)
        assert irqs == [(5, 1)]


# =============================================================================
# QUICKSTART TOOL TESTS
# =============================================================================

class TestQuickstart:
    def test_parse_patch(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
        from quickstart import parse_patch
        addr, data = parse_patch("0x08001000:7047")
        assert addr == 0x08001000
        assert data == bytes([0x70, 0x47])

    def test_parse_patch_invalid(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
        from quickstart import parse_patch
        with pytest.raises(ValueError):
            parse_patch("invalid")

    def test_build_qemu_args(self, svd_file):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
        from quickstart import build_qemu_args
        pset = SVDStubPeripheralSet.from_svd(svd_file)
        info = pset.get_memory_info()
        args = build_qemu_args(info, 'test.bin', 5555, 'qemu-system-arm')
        assert args[0] == 'qemu-system-arm'
        assert '-kernel' in args
        assert 'test.bin' in args
        assert 'cortex-m4' in args[2]
