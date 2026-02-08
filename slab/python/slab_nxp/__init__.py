"""
SLAB NXP - NXP Microcontroller/Processor Peripheral Emulation

Comprehensive peripheral emulation for NXP devices:
- LPC55S69 (Cortex-M33) - FlexComm, CASPER crypto, TrustZone
- i.MX RT1060 (Cortex-M7) - Crossover MCU, FlexCAN, USB
- i.MX 6 (Cortex-A9) - Application processor
- i.MX 8 (Cortex-A53/A72) - Application processor

References:
- LPC55S6x User Manual (UM11126)
- i.MX RT1060 Reference Manual
- i.MX 6 Reference Manual
- i.MX 8 Reference Manual
- QEMU hw/arm/fsl-imx*, hw/misc/imx*

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"

# Base classes
from .nxp_base import (
    NXPPeripheral,
    NXPPeripheralSet,
    STATUS_OK,
    STATUS_ERROR,
)

# LPC55xx peripherals
from .lpc_flexcomm import (
    LPCFlexComm,
    LPCFlexCommUSART,
    LPCFlexCommSPI,
    LPCFlexCommI2C,
)

from .lpc_gpio import (
    LPCGPIO,
    LPCPINT,
)

from .lpc_ctimer import (
    LPCCTimer,
)

from .lpc_adc import (
    LPCADC,
)

from .lpc_crypto import (
    LPCCASPER,      # Cryptographic accelerator
    LPCHASHCRYPT,   # AES/HASH
    LPCPUF,         # Physical Unclonable Function
)

# i.MX RT peripherals
from .imxrt_lpuart import (
    IMXRTLpuart,
)

from .imxrt_lpspi import (
    IMXRTLpspi,
)

from .imxrt_lpi2c import (
    IMXRTLpi2c,
)

from .imxrt_gpio import (
    IMXRTGPIO,
)

from .imxrt_gpt import (
    IMXRTGPT,
    IMXRTPIT,
)

from .imxrt_adc import (
    IMXRTADC,
)

# Peripheral sets
from .lpc55s69 import (
    LPC55S69PeripheralSet,
)

from .imxrt1060 import (
    IMXRT1060PeripheralSet,
)

# i.MX 6/8 (Cortex-A) - optional
try:
    from .imx_uart import IMXUART
    from .imx_ecspi import IMXECSPI
    from .imx_i2c import IMXI2C
    from .imx_gpio import IMXGPIO
    from .imx_gpt import IMXGPT, IMXEPIT
    from .imx_caam import IMXCAAM
    from .imx6 import IMX6QPeripheralSet, IMX6ULPeripheralSet
    from .imx8 import IMX8MQPeripheralSet, IMX8MMPeripheralSet
except ImportError:
    pass

__all__ = [
    # Version
    "__version__",
    "__author__",
    # Base
    "NXPPeripheral",
    "NXPPeripheralSet",
    "STATUS_OK",
    "STATUS_ERROR",
    # LPC55xx
    "LPCFlexComm",
    "LPCFlexCommUSART",
    "LPCFlexCommSPI",
    "LPCFlexCommI2C",
    "LPCGPIO",
    "LPCPINT",
    "LPCCTimer",
    "LPCADC",
    "LPCCASPER",
    "LPCHASHCRYPT",
    "LPCPUF",
    # i.MX RT
    "IMXRTLpuart",
    "IMXRTLpspi",
    "IMXRTLpi2c",
    "IMXRTGPIO",
    "IMXRTGPT",
    "IMXRTPIT",
    "IMXRTADC",
    # i.MX 6/8
    "IMXUART",
    "IMXECSPI",
    "IMXI2C",
    "IMXGPIO",
    "IMXGPT",
    "IMXEPIT",
    "IMXCAAM",
    # Peripheral sets
    "LPC55S69PeripheralSet",
    "IMXRT1060PeripheralSet",
    "IMX6QPeripheralSet",
    "IMX6ULPeripheralSet",
    "IMX8MQPeripheralSet",
    "IMX8MMPeripheralSet",
]
