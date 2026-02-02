# HelloBlink

USB CDC demo for STM32F405 that sends "helloworld\n\r" on startup, then echoes received data while blinking an LED.

## Features

- Sends `helloworld\n\r` over USB CDC on connection
- USB CDC echo mode (echoes back any received data)
- LED blink on PA13 (500ms toggle)
- 168 MHz system clock using HSE

## Hardware

- **MCU**: STM32F405RGTx (or compatible STM32F405/407)
- **USB**: OTG FS (PA11/PA12)
- **LED**: PA13 (directly driven, accent with resistor as needed)
- **Crystal**: 8 MHz HSE (adjust `PLLM` in `Src/main.c` if different)

## Requirements

- `arm-none-eabi-gcc` toolchain
- `make`
- `st-flash` or `openocd` for flashing

## Clone

```bash
git clone --recursive https://github.com/YOUR_USERNAME/HelloBlink.git
cd HelloBlink

# Initialize required ST SDK submodules
cd STM32CubeF4
git submodule update --init \
    Drivers/STM32F4xx_HAL_Driver \
    Drivers/CMSIS/Device/ST/STM32F4xx \
    Middlewares/ST/STM32_USB_Device_Library
cd ..
```

## Build

```bash
make
```

Output files in `build/`:
- `HelloBlink.bin` - Raw binary
- `HelloBlink.hex` - Intel HEX
- `HelloBlink.elf` - ELF with debug symbols

## Flash

Using st-flash:
```bash
make flash
```

Using OpenOCD:
```bash
make flash-openocd
```

## Usage

1. Flash the firmware
2. Connect USB to your PC
3. Open a serial terminal (e.g., `screen /dev/ttyACM0 115200`)
4. You'll see `helloworld` message
5. Type anything - it echoes back
6. LED on PA13 blinks continuously

## Configuration

| Setting | File | Default |
|---------|------|---------|
| LED Pin | `Inc/main.h` | PA13 |
| HSE Crystal | `Inc/stm32f4xx_hal_conf.h` | 8 MHz |
| PLL Config | `Src/main.c` | PLLM=8 (for 8MHz HSE) |
| Blink Rate | `Src/main.c` | 500ms |

## Project Structure

```
HelloBlink/
├── Inc/                    # Header files
├── Src/                    # Source files
│   ├── main.c              # Main application
│   ├── usbd_cdc_if.c       # USB CDC interface (echo)
│   ├── usbd_conf.c         # USB low-level driver
│   ├── usbd_desc.c         # USB descriptors
│   ├── stm32f4xx_it.c      # Interrupt handlers
│   └── system_stm32f4xx.c  # System init
├── STM32CubeF4/            # ST SDK (git submodule)
├── startup_stm32f405xx.s   # Startup code
├── STM32F405RGTx_FLASH.ld  # Linker script
└── Makefile
```

## License

Project code is MIT. STM32CubeF4 SDK has its own license (see STM32CubeF4/LICENSE.md).
