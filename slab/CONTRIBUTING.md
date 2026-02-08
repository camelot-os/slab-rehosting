# Contributing to MCUemu

Thank you for your interest in contributing to SLab Emu!

## Code of Conduct

Please be respectful and constructive in all interactions.

## How to Contribute

### Reporting Issues

- Check existing issues before creating a new one
- Include MCU type, QEMU version, and Python version
- Provide minimal reproduction steps
- Include relevant logs and error messages

### Submitting Code

1. **Fork the repository** and create a feature branch
2. **Write clear commit messages** following conventional commits:
   - `feat:` New features
   - `fix:` Bug fixes
   - `docs:` Documentation changes
   - `refactor:` Code refactoring
   - `test:` Test additions/changes

3. **Include tests** for new functionality
4. **Update documentation** if applicable
5. **Submit a pull request** with a clear description

### Code Style

**Python Code:**
- Follow PEP 8
- Use type hints for function signatures
- Document public APIs with docstrings
- Maximum line length: 100 characters

**QEMU C Code:**
- Follow QEMU coding style (Linux kernel style)
- 4-space indentation
- Opening braces on same line for functions
- Use QEMU memory API (memory_region_*)

### Testing

```bash
# Run Python tests
PYTHONPATH=slab/python pytest slab/tests/ -v

# Run specific test suite
pytest tests/test_svd_parser.py -v

# Check code style
python -m flake8 slab/python/
```

### Adding New Peripherals

1. Create peripheral class in appropriate package (`slab_stm32`, `slab_nrf`, etc.)
2. Implement register read/write handlers
3. Add unit tests
4. Update documentation

Example peripheral structure:

```python
class MyPeripheral:
    """My custom peripheral implementation."""

    def __init__(self, base_addr: int):
        self.base = base_addr
        self.regs = {}

    def read(self, addr: int, size: int) -> int:
        """Handle register read."""
        offset = addr - self.base
        return self.regs.get(offset, 0)

    def write(self, addr: int, value: int, size: int):
        """Handle register write."""
        offset = addr - self.base
        self.regs[offset] = value
```

### Adding New MCU Support

1. Create SVD parser configuration
2. Implement MCU-specific peripheral set
3. Add example firmware
4. Update supported MCU table in README

## License

- QEMU machine code: GPL-2.0-or-later
- Python packages: Apache-2.0

By contributing, you agree to license your contributions under these terms.

## Questions?

Contact: mathieu.renard@twistedwires.io

---

Copyright (C) 2026 Twisted Wires Security Lab
