/**
  ******************************************************************************
  * @file      startup_stm32u5a5xx.s
  * @author    MCD Application Team
  * @brief     STM32U5A5xx devices vector table GCC toolchain.
  *            This module performs:
  *                - Set the initial SP
  *                - Set the initial PC == Reset_Handler,
  *                - Set the vector table entries with the exceptions ISR address
  *                - Branches to main in the C library (which eventually
  *                  calls main()).
  *            After Reset the Cortex-M33 processor is in Thread mode,
  *            priority is Privileged, and the Stack is set to Main.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2021-2023 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */

  .syntax unified
  .cpu cortex-m33
  .fpu softvfp
  .thumb

.global g_pfnVectors
.global Default_Handler

/* start address for the initialization values of the .data section.
defined in linker script */
.word _sidata
/* start address for the .data section. defined in linker script */
.word _sdata
/* end address for the .data section. defined in linker script */
.word _edata
/* start address for the .bss section. defined in linker script */
.word _sbss
/* end address for the .bss section. defined in linker script */
.word _ebss

  .section .text.Reset_Handler
  .weak Reset_Handler
  .type Reset_Handler, %function
Reset_Handler:
  ldr   r0, =_estack
  mov   sp, r0          /* set stack pointer */

/* Call the clock system initialization function.*/
  bl  SystemInit

/* Copy the data segment initializers from flash to SRAM */
  ldr r0, =_sdata
  ldr r1, =_edata
  ldr r2, =_sidata
  movs r3, #0
  b LoopCopyDataInit

CopyDataInit:
  ldr r4, [r2, r3]
  str r4, [r0, r3]
  adds r3, r3, #4

LoopCopyDataInit:
  adds r4, r0, r3
  cmp r4, r1
  bcc CopyDataInit

/* Zero fill the bss segment. */
  ldr r2, =_sbss
  ldr r4, =_ebss
  movs r3, #0
  b LoopFillZerobss

FillZerobss:
  str  r3, [r2]
  adds r2, r2, #4

LoopFillZerobss:
  cmp r2, r4
  bcc FillZerobss

/* Call static constructors */
  bl __libc_init_array
/* Call the application's entry point.*/
  bl main

LoopForever:
  b LoopForever

.size Reset_Handler, .-Reset_Handler

/**
 * @brief  This is the code that gets called when the processor receives an
 *         unexpected interrupt.  This simply enters an infinite loop, preserving
 *         the system state for examination by a debugger.
 *
 * @param  None
 * @retval None
 */
  .section .text.Default_Handler,"ax",%progbits
Default_Handler:
Infinite_Loop:
  b Infinite_Loop
  .size Default_Handler, .-Default_Handler

/******************************************************************************
*
* The STM32U5A5xx vector table.  Note that the proper constructs
* must be placed on this to ensure that it ends up at physical address
* 0x0000.0000.
*
* Cortex-M33 core: 16 exception vectors + up to 134 peripheral IRQs.
*
******************************************************************************/
  .section  .isr_vector,"a",%progbits
  .type  g_pfnVectors, %object

g_pfnVectors:
  .word _estack                         /* Top of Stack */
  .word Reset_Handler                   /* Reset Handler */
  .word NMI_Handler                     /* NMI Handler */
  .word HardFault_Handler               /* Hard Fault Handler */
  .word MemManage_Handler               /* MPU Fault Handler */
  .word BusFault_Handler                /* Bus Fault Handler */
  .word UsageFault_Handler              /* Usage Fault Handler */
  .word SecureFault_Handler             /* Secure Fault Handler */
  .word 0                               /* Reserved */
  .word 0                               /* Reserved */
  .word 0                               /* Reserved */
  .word SVC_Handler                     /* SVCall Handler */
  .word DebugMon_Handler                /* Debug Monitor Handler */
  .word 0                               /* Reserved */
  .word PendSV_Handler                  /* PendSV Handler */
  .word SysTick_Handler                 /* SysTick Handler */

  /* External Interrupts */
  .word WWDG_IRQHandler                 /*  0: Window Watchdog */
  .word PVD_PVM_IRQHandler              /*  1: PVD/PVM through EXTI */
  .word RTC_IRQHandler                  /*  2: RTC non-secure */
  .word RTC_S_IRQHandler                /*  3: RTC secure */
  .word TAMP_IRQHandler                 /*  4: Tamper non-secure */
  .word RAMCFG_IRQHandler               /*  5: RAMCFG global */
  .word FLASH_IRQHandler                /*  6: Flash non-secure */
  .word FLASH_S_IRQHandler              /*  7: Flash secure */
  .word GTZC_IRQHandler                 /*  8: GTZC global (TrustZone) */
  .word RCC_IRQHandler                  /*  9: RCC non-secure */
  .word RCC_S_IRQHandler                /* 10: RCC secure */
  .word EXTI0_IRQHandler                /* 11: EXTI Line0 */
  .word EXTI1_IRQHandler                /* 12: EXTI Line1 */
  .word EXTI2_IRQHandler                /* 13: EXTI Line2 */
  .word EXTI3_IRQHandler                /* 14: EXTI Line3 */
  .word EXTI4_IRQHandler                /* 15: EXTI Line4 */
  .word EXTI5_IRQHandler                /* 16: EXTI Line5 */
  .word EXTI6_IRQHandler                /* 17: EXTI Line6 */
  .word EXTI7_IRQHandler                /* 18: EXTI Line7 */
  .word EXTI8_IRQHandler                /* 19: EXTI Line8 */
  .word EXTI9_IRQHandler                /* 20: EXTI Line9 */
  .word EXTI10_IRQHandler               /* 21: EXTI Line10 */
  .word EXTI11_IRQHandler               /* 22: EXTI Line11 */
  .word EXTI12_IRQHandler               /* 23: EXTI Line12 */
  .word EXTI13_IRQHandler               /* 24: EXTI Line13 */
  .word EXTI14_IRQHandler               /* 25: EXTI Line14 */
  .word EXTI15_IRQHandler               /* 26: EXTI Line15 */
  .word IWDG_IRQHandler                 /* 27: IWDG */
  .word SAES_IRQHandler                 /* 28: Secure AES */
  .word GPDMA1_Channel0_IRQHandler      /* 29: GPDMA1 Channel 0 */
  .word GPDMA1_Channel1_IRQHandler      /* 30: GPDMA1 Channel 1 */
  .word GPDMA1_Channel2_IRQHandler      /* 31: GPDMA1 Channel 2 */
  .word GPDMA1_Channel3_IRQHandler      /* 32: GPDMA1 Channel 3 */
  .word GPDMA1_Channel4_IRQHandler      /* 33: GPDMA1 Channel 4 */
  .word GPDMA1_Channel5_IRQHandler      /* 34: GPDMA1 Channel 5 */
  .word GPDMA1_Channel6_IRQHandler      /* 35: GPDMA1 Channel 6 */
  .word GPDMA1_Channel7_IRQHandler      /* 36: GPDMA1 Channel 7 */
  .word ADC1_2_IRQHandler               /* 37: ADC1 & ADC2 */
  .word DAC1_IRQHandler                 /* 38: DAC1 underrun */
  .word FDCAN1_IT0_IRQHandler           /* 39: FDCAN1 IT0 */
  .word FDCAN1_IT1_IRQHandler           /* 40: FDCAN1 IT1 */
  .word TIM1_BRK_IRQHandler             /* 41: TIM1 Break */
  .word TIM1_UP_IRQHandler              /* 42: TIM1 Update */
  .word TIM1_TRG_COM_IRQHandler         /* 43: TIM1 Trigger/Commutation */
  .word TIM1_CC_IRQHandler              /* 44: TIM1 Capture Compare */
  .word TIM2_IRQHandler                 /* 45: TIM2 global */
  .word TIM3_IRQHandler                 /* 46: TIM3 global */
  .word TIM4_IRQHandler                 /* 47: TIM4 global */
  .word TIM5_IRQHandler                 /* 48: TIM5 global */
  .word TIM6_IRQHandler                 /* 49: TIM6 global */
  .word TIM7_IRQHandler                 /* 50: TIM7 global */
  .word TIM8_BRK_IRQHandler             /* 51: TIM8 Break */
  .word TIM8_UP_IRQHandler              /* 52: TIM8 Update */
  .word TIM8_TRG_COM_IRQHandler         /* 53: TIM8 Trigger/Commutation */
  .word TIM8_CC_IRQHandler              /* 54: TIM8 Capture Compare */
  .word I2C1_EV_IRQHandler              /* 55: I2C1 Event */
  .word I2C1_ER_IRQHandler              /* 56: I2C1 Error */
  .word I2C2_EV_IRQHandler              /* 57: I2C2 Event */
  .word I2C2_ER_IRQHandler              /* 58: I2C2 Error */
  .word SPI1_IRQHandler                 /* 59: SPI1 global */
  .word SPI2_IRQHandler                 /* 60: SPI2 global */
  .word USART1_IRQHandler               /* 61: USART1 global */
  .word USART2_IRQHandler               /* 62: USART2 global */
  .word USART3_IRQHandler               /* 63: USART3 global */
  .word UART4_IRQHandler                /* 64: UART4 global */
  .word UART5_IRQHandler                /* 65: UART5 global */
  .word LPUART1_IRQHandler              /* 66: LPUART1 global */
  .word LPTIM1_IRQHandler               /* 67: LPTIM1 global */
  .word LPTIM2_IRQHandler               /* 68: LPTIM2 global */
  .word TIM15_IRQHandler                /* 69: TIM15 global */
  .word TIM16_IRQHandler                /* 70: TIM16 global */
  .word TIM17_IRQHandler                /* 71: TIM17 global */
  .word COMP_IRQHandler                 /* 72: COMP1/COMP2 */
  .word OTG_HS_IRQHandler               /* 73: USB OTG HS global */
  .word CRS_IRQHandler                  /* 74: CRS global */
  .word FMC_IRQHandler                  /* 75: FMC global */
  .word OCTOSPI1_IRQHandler             /* 76: OCTOSPI1 global */
  .word PWR_S3WU_IRQHandler             /* 77: PWR Stop3 wakeup */
  .word SDMMC1_IRQHandler               /* 78: SDMMC1 global */
  .word SDMMC2_IRQHandler               /* 79: SDMMC2 global */
  .word GPDMA1_Channel8_IRQHandler      /* 80: GPDMA1 Channel 8 */
  .word GPDMA1_Channel9_IRQHandler      /* 81: GPDMA1 Channel 9 */
  .word GPDMA1_Channel10_IRQHandler     /* 82: GPDMA1 Channel 10 */
  .word GPDMA1_Channel11_IRQHandler     /* 83: GPDMA1 Channel 11 */
  .word GPDMA1_Channel12_IRQHandler     /* 84: GPDMA1 Channel 12 */
  .word GPDMA1_Channel13_IRQHandler     /* 85: GPDMA1 Channel 13 */
  .word GPDMA1_Channel14_IRQHandler     /* 86: GPDMA1 Channel 14 */
  .word GPDMA1_Channel15_IRQHandler     /* 87: GPDMA1 Channel 15 */
  .word I2C3_EV_IRQHandler              /* 88: I2C3 Event */
  .word I2C3_ER_IRQHandler              /* 89: I2C3 Error */
  .word SAI1_IRQHandler                 /* 90: SAI1 global */
  .word SAI2_IRQHandler                 /* 91: SAI2 global */
  .word TSC_IRQHandler                  /* 92: TSC global */
  .word AES_IRQHandler                  /* 93: AES global */
  .word RNG_IRQHandler                  /* 94: RNG global */
  .word FPU_IRQHandler                  /* 95: FPU global */
  .word HASH_IRQHandler                 /* 96: HASH global */
  .word PKA_IRQHandler                  /* 97: PKA global */
  .word LPTIM3_IRQHandler               /* 98: LPTIM3 global */
  .word SPI3_IRQHandler                 /* 99: SPI3 global */
  .word I2C4_EV_IRQHandler              /* 100: I2C4 Event */
  .word I2C4_ER_IRQHandler              /* 101: I2C4 Error */
  .word MDF1_FLT0_IRQHandler            /* 102: MDF1 Filter 0 */
  .word MDF1_FLT1_IRQHandler            /* 103: MDF1 Filter 1 */
  .word MDF1_FLT2_IRQHandler            /* 104: MDF1 Filter 2 */
  .word MDF1_FLT3_IRQHandler            /* 105: MDF1 Filter 3 */
  .word UCPD1_IRQHandler                /* 106: UCPD1 global */
  .word ICACHE_IRQHandler               /* 107: ICACHE global */
  .word OTFDEC1_IRQHandler              /* 108: OTFDEC1 global */
  .word OTFDEC2_IRQHandler              /* 109: OTFDEC2 global */
  .word LPTIM4_IRQHandler               /* 110: LPTIM4 global */
  .word DCACHE1_IRQHandler              /* 111: DCACHE1 global */
  .word ADF1_IRQHandler                 /* 112: ADF1 global */
  .word ADC4_IRQHandler                 /* 113: ADC4 global */
  .word LPDMA1_Channel0_IRQHandler      /* 114: LPDMA1 Channel 0 */
  .word LPDMA1_Channel1_IRQHandler      /* 115: LPDMA1 Channel 1 */
  .word LPDMA1_Channel2_IRQHandler      /* 116: LPDMA1 Channel 2 */
  .word LPDMA1_Channel3_IRQHandler      /* 117: LPDMA1 Channel 3 */
  .word DMA2D_IRQHandler                /* 118: DMA2D global */
  .word DCMI_PSSI_IRQHandler            /* 119: DCMI/PSSI global */
  .word OCTOSPI2_IRQHandler             /* 120: OCTOSPI2 global */
  .word MDF1_FLT4_IRQHandler            /* 121: MDF1 Filter 4 */
  .word MDF1_FLT5_IRQHandler            /* 122: MDF1 Filter 5 */
  .word CORDIC_IRQHandler               /* 123: CORDIC global */
  .word FMAC_IRQHandler                 /* 124: FMAC global */
  .word LSECSSD_IRQHandler              /* 125: LSECSSD global */
  .word USART6_IRQHandler               /* 126: USART6 global */
  .word I2C5_EV_IRQHandler              /* 127: I2C5 Event */
  .word I2C5_ER_IRQHandler              /* 128: I2C5 Error */
  .word I2C6_EV_IRQHandler              /* 129: I2C6 Event */
  .word I2C6_ER_IRQHandler              /* 130: I2C6 Error */
  .word HSPI1_IRQHandler                /* 131: HSPI1 global */
  .word GPU2D_IRQHandler                /* 132: GPU2D global */
  .word GPU2D_ER_IRQHandler             /* 133: GPU2D error */
  .word GFXMMU_IRQHandler              /* 134: GFXMMU global */
  .word LTDC_IRQHandler                 /* 135: LTDC global */
  .word LTDC_ER_IRQHandler              /* 136: LTDC error */
  .word DSI_IRQHandler                  /* 137: DSI global */
  .word DCACHE2_IRQHandler              /* 138: DCACHE2 global */

  .size  g_pfnVectors, .-g_pfnVectors

/*******************************************************************************
*
* Provide weak aliases for each Exception handler to the Default_Handler.
* As they are weak aliases, any function with the same name will override
* this definition.
*
*******************************************************************************/
  .weak  NMI_Handler
  .thumb_set NMI_Handler,Default_Handler

  .weak  HardFault_Handler
  .thumb_set HardFault_Handler,Default_Handler

  .weak  MemManage_Handler
  .thumb_set MemManage_Handler,Default_Handler

  .weak  BusFault_Handler
  .thumb_set BusFault_Handler,Default_Handler

  .weak  UsageFault_Handler
  .thumb_set UsageFault_Handler,Default_Handler

  .weak  SecureFault_Handler
  .thumb_set SecureFault_Handler,Default_Handler

  .weak  SVC_Handler
  .thumb_set SVC_Handler,Default_Handler

  .weak  DebugMon_Handler
  .thumb_set DebugMon_Handler,Default_Handler

  .weak  PendSV_Handler
  .thumb_set PendSV_Handler,Default_Handler

  .weak  SysTick_Handler
  .thumb_set SysTick_Handler,Default_Handler

  .weak  WWDG_IRQHandler
  .thumb_set WWDG_IRQHandler,Default_Handler

  .weak  PVD_PVM_IRQHandler
  .thumb_set PVD_PVM_IRQHandler,Default_Handler

  .weak  RTC_IRQHandler
  .thumb_set RTC_IRQHandler,Default_Handler

  .weak  RTC_S_IRQHandler
  .thumb_set RTC_S_IRQHandler,Default_Handler

  .weak  TAMP_IRQHandler
  .thumb_set TAMP_IRQHandler,Default_Handler

  .weak  RAMCFG_IRQHandler
  .thumb_set RAMCFG_IRQHandler,Default_Handler

  .weak  FLASH_IRQHandler
  .thumb_set FLASH_IRQHandler,Default_Handler

  .weak  FLASH_S_IRQHandler
  .thumb_set FLASH_S_IRQHandler,Default_Handler

  .weak  GTZC_IRQHandler
  .thumb_set GTZC_IRQHandler,Default_Handler

  .weak  RCC_IRQHandler
  .thumb_set RCC_IRQHandler,Default_Handler

  .weak  RCC_S_IRQHandler
  .thumb_set RCC_S_IRQHandler,Default_Handler

  .weak  EXTI0_IRQHandler
  .thumb_set EXTI0_IRQHandler,Default_Handler

  .weak  EXTI1_IRQHandler
  .thumb_set EXTI1_IRQHandler,Default_Handler

  .weak  EXTI2_IRQHandler
  .thumb_set EXTI2_IRQHandler,Default_Handler

  .weak  EXTI3_IRQHandler
  .thumb_set EXTI3_IRQHandler,Default_Handler

  .weak  EXTI4_IRQHandler
  .thumb_set EXTI4_IRQHandler,Default_Handler

  .weak  EXTI5_IRQHandler
  .thumb_set EXTI5_IRQHandler,Default_Handler

  .weak  EXTI6_IRQHandler
  .thumb_set EXTI6_IRQHandler,Default_Handler

  .weak  EXTI7_IRQHandler
  .thumb_set EXTI7_IRQHandler,Default_Handler

  .weak  EXTI8_IRQHandler
  .thumb_set EXTI8_IRQHandler,Default_Handler

  .weak  EXTI9_IRQHandler
  .thumb_set EXTI9_IRQHandler,Default_Handler

  .weak  EXTI10_IRQHandler
  .thumb_set EXTI10_IRQHandler,Default_Handler

  .weak  EXTI11_IRQHandler
  .thumb_set EXTI11_IRQHandler,Default_Handler

  .weak  EXTI12_IRQHandler
  .thumb_set EXTI12_IRQHandler,Default_Handler

  .weak  EXTI13_IRQHandler
  .thumb_set EXTI13_IRQHandler,Default_Handler

  .weak  EXTI14_IRQHandler
  .thumb_set EXTI14_IRQHandler,Default_Handler

  .weak  EXTI15_IRQHandler
  .thumb_set EXTI15_IRQHandler,Default_Handler

  .weak  IWDG_IRQHandler
  .thumb_set IWDG_IRQHandler,Default_Handler

  .weak  SAES_IRQHandler
  .thumb_set SAES_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel0_IRQHandler
  .thumb_set GPDMA1_Channel0_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel1_IRQHandler
  .thumb_set GPDMA1_Channel1_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel2_IRQHandler
  .thumb_set GPDMA1_Channel2_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel3_IRQHandler
  .thumb_set GPDMA1_Channel3_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel4_IRQHandler
  .thumb_set GPDMA1_Channel4_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel5_IRQHandler
  .thumb_set GPDMA1_Channel5_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel6_IRQHandler
  .thumb_set GPDMA1_Channel6_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel7_IRQHandler
  .thumb_set GPDMA1_Channel7_IRQHandler,Default_Handler

  .weak  ADC1_2_IRQHandler
  .thumb_set ADC1_2_IRQHandler,Default_Handler

  .weak  DAC1_IRQHandler
  .thumb_set DAC1_IRQHandler,Default_Handler

  .weak  FDCAN1_IT0_IRQHandler
  .thumb_set FDCAN1_IT0_IRQHandler,Default_Handler

  .weak  FDCAN1_IT1_IRQHandler
  .thumb_set FDCAN1_IT1_IRQHandler,Default_Handler

  .weak  TIM1_BRK_IRQHandler
  .thumb_set TIM1_BRK_IRQHandler,Default_Handler

  .weak  TIM1_UP_IRQHandler
  .thumb_set TIM1_UP_IRQHandler,Default_Handler

  .weak  TIM1_TRG_COM_IRQHandler
  .thumb_set TIM1_TRG_COM_IRQHandler,Default_Handler

  .weak  TIM1_CC_IRQHandler
  .thumb_set TIM1_CC_IRQHandler,Default_Handler

  .weak  TIM2_IRQHandler
  .thumb_set TIM2_IRQHandler,Default_Handler

  .weak  TIM3_IRQHandler
  .thumb_set TIM3_IRQHandler,Default_Handler

  .weak  TIM4_IRQHandler
  .thumb_set TIM4_IRQHandler,Default_Handler

  .weak  TIM5_IRQHandler
  .thumb_set TIM5_IRQHandler,Default_Handler

  .weak  TIM6_IRQHandler
  .thumb_set TIM6_IRQHandler,Default_Handler

  .weak  TIM7_IRQHandler
  .thumb_set TIM7_IRQHandler,Default_Handler

  .weak  TIM8_BRK_IRQHandler
  .thumb_set TIM8_BRK_IRQHandler,Default_Handler

  .weak  TIM8_UP_IRQHandler
  .thumb_set TIM8_UP_IRQHandler,Default_Handler

  .weak  TIM8_TRG_COM_IRQHandler
  .thumb_set TIM8_TRG_COM_IRQHandler,Default_Handler

  .weak  TIM8_CC_IRQHandler
  .thumb_set TIM8_CC_IRQHandler,Default_Handler

  .weak  I2C1_EV_IRQHandler
  .thumb_set I2C1_EV_IRQHandler,Default_Handler

  .weak  I2C1_ER_IRQHandler
  .thumb_set I2C1_ER_IRQHandler,Default_Handler

  .weak  I2C2_EV_IRQHandler
  .thumb_set I2C2_EV_IRQHandler,Default_Handler

  .weak  I2C2_ER_IRQHandler
  .thumb_set I2C2_ER_IRQHandler,Default_Handler

  .weak  SPI1_IRQHandler
  .thumb_set SPI1_IRQHandler,Default_Handler

  .weak  SPI2_IRQHandler
  .thumb_set SPI2_IRQHandler,Default_Handler

  .weak  USART1_IRQHandler
  .thumb_set USART1_IRQHandler,Default_Handler

  .weak  USART2_IRQHandler
  .thumb_set USART2_IRQHandler,Default_Handler

  .weak  USART3_IRQHandler
  .thumb_set USART3_IRQHandler,Default_Handler

  .weak  UART4_IRQHandler
  .thumb_set UART4_IRQHandler,Default_Handler

  .weak  UART5_IRQHandler
  .thumb_set UART5_IRQHandler,Default_Handler

  .weak  LPUART1_IRQHandler
  .thumb_set LPUART1_IRQHandler,Default_Handler

  .weak  LPTIM1_IRQHandler
  .thumb_set LPTIM1_IRQHandler,Default_Handler

  .weak  LPTIM2_IRQHandler
  .thumb_set LPTIM2_IRQHandler,Default_Handler

  .weak  TIM15_IRQHandler
  .thumb_set TIM15_IRQHandler,Default_Handler

  .weak  TIM16_IRQHandler
  .thumb_set TIM16_IRQHandler,Default_Handler

  .weak  TIM17_IRQHandler
  .thumb_set TIM17_IRQHandler,Default_Handler

  .weak  COMP_IRQHandler
  .thumb_set COMP_IRQHandler,Default_Handler

  .weak  OTG_HS_IRQHandler
  .thumb_set OTG_HS_IRQHandler,Default_Handler

  .weak  CRS_IRQHandler
  .thumb_set CRS_IRQHandler,Default_Handler

  .weak  FMC_IRQHandler
  .thumb_set FMC_IRQHandler,Default_Handler

  .weak  OCTOSPI1_IRQHandler
  .thumb_set OCTOSPI1_IRQHandler,Default_Handler

  .weak  PWR_S3WU_IRQHandler
  .thumb_set PWR_S3WU_IRQHandler,Default_Handler

  .weak  SDMMC1_IRQHandler
  .thumb_set SDMMC1_IRQHandler,Default_Handler

  .weak  SDMMC2_IRQHandler
  .thumb_set SDMMC2_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel8_IRQHandler
  .thumb_set GPDMA1_Channel8_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel9_IRQHandler
  .thumb_set GPDMA1_Channel9_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel10_IRQHandler
  .thumb_set GPDMA1_Channel10_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel11_IRQHandler
  .thumb_set GPDMA1_Channel11_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel12_IRQHandler
  .thumb_set GPDMA1_Channel12_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel13_IRQHandler
  .thumb_set GPDMA1_Channel13_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel14_IRQHandler
  .thumb_set GPDMA1_Channel14_IRQHandler,Default_Handler

  .weak  GPDMA1_Channel15_IRQHandler
  .thumb_set GPDMA1_Channel15_IRQHandler,Default_Handler

  .weak  I2C3_EV_IRQHandler
  .thumb_set I2C3_EV_IRQHandler,Default_Handler

  .weak  I2C3_ER_IRQHandler
  .thumb_set I2C3_ER_IRQHandler,Default_Handler

  .weak  SAI1_IRQHandler
  .thumb_set SAI1_IRQHandler,Default_Handler

  .weak  SAI2_IRQHandler
  .thumb_set SAI2_IRQHandler,Default_Handler

  .weak  TSC_IRQHandler
  .thumb_set TSC_IRQHandler,Default_Handler

  .weak  AES_IRQHandler
  .thumb_set AES_IRQHandler,Default_Handler

  .weak  RNG_IRQHandler
  .thumb_set RNG_IRQHandler,Default_Handler

  .weak  FPU_IRQHandler
  .thumb_set FPU_IRQHandler,Default_Handler

  .weak  HASH_IRQHandler
  .thumb_set HASH_IRQHandler,Default_Handler

  .weak  PKA_IRQHandler
  .thumb_set PKA_IRQHandler,Default_Handler

  .weak  LPTIM3_IRQHandler
  .thumb_set LPTIM3_IRQHandler,Default_Handler

  .weak  SPI3_IRQHandler
  .thumb_set SPI3_IRQHandler,Default_Handler

  .weak  I2C4_EV_IRQHandler
  .thumb_set I2C4_EV_IRQHandler,Default_Handler

  .weak  I2C4_ER_IRQHandler
  .thumb_set I2C4_ER_IRQHandler,Default_Handler

  .weak  MDF1_FLT0_IRQHandler
  .thumb_set MDF1_FLT0_IRQHandler,Default_Handler

  .weak  MDF1_FLT1_IRQHandler
  .thumb_set MDF1_FLT1_IRQHandler,Default_Handler

  .weak  MDF1_FLT2_IRQHandler
  .thumb_set MDF1_FLT2_IRQHandler,Default_Handler

  .weak  MDF1_FLT3_IRQHandler
  .thumb_set MDF1_FLT3_IRQHandler,Default_Handler

  .weak  UCPD1_IRQHandler
  .thumb_set UCPD1_IRQHandler,Default_Handler

  .weak  ICACHE_IRQHandler
  .thumb_set ICACHE_IRQHandler,Default_Handler

  .weak  OTFDEC1_IRQHandler
  .thumb_set OTFDEC1_IRQHandler,Default_Handler

  .weak  OTFDEC2_IRQHandler
  .thumb_set OTFDEC2_IRQHandler,Default_Handler

  .weak  LPTIM4_IRQHandler
  .thumb_set LPTIM4_IRQHandler,Default_Handler

  .weak  DCACHE1_IRQHandler
  .thumb_set DCACHE1_IRQHandler,Default_Handler

  .weak  ADF1_IRQHandler
  .thumb_set ADF1_IRQHandler,Default_Handler

  .weak  ADC4_IRQHandler
  .thumb_set ADC4_IRQHandler,Default_Handler

  .weak  LPDMA1_Channel0_IRQHandler
  .thumb_set LPDMA1_Channel0_IRQHandler,Default_Handler

  .weak  LPDMA1_Channel1_IRQHandler
  .thumb_set LPDMA1_Channel1_IRQHandler,Default_Handler

  .weak  LPDMA1_Channel2_IRQHandler
  .thumb_set LPDMA1_Channel2_IRQHandler,Default_Handler

  .weak  LPDMA1_Channel3_IRQHandler
  .thumb_set LPDMA1_Channel3_IRQHandler,Default_Handler

  .weak  DMA2D_IRQHandler
  .thumb_set DMA2D_IRQHandler,Default_Handler

  .weak  DCMI_PSSI_IRQHandler
  .thumb_set DCMI_PSSI_IRQHandler,Default_Handler

  .weak  OCTOSPI2_IRQHandler
  .thumb_set OCTOSPI2_IRQHandler,Default_Handler

  .weak  MDF1_FLT4_IRQHandler
  .thumb_set MDF1_FLT4_IRQHandler,Default_Handler

  .weak  MDF1_FLT5_IRQHandler
  .thumb_set MDF1_FLT5_IRQHandler,Default_Handler

  .weak  CORDIC_IRQHandler
  .thumb_set CORDIC_IRQHandler,Default_Handler

  .weak  FMAC_IRQHandler
  .thumb_set FMAC_IRQHandler,Default_Handler

  .weak  LSECSSD_IRQHandler
  .thumb_set LSECSSD_IRQHandler,Default_Handler

  .weak  USART6_IRQHandler
  .thumb_set USART6_IRQHandler,Default_Handler

  .weak  I2C5_EV_IRQHandler
  .thumb_set I2C5_EV_IRQHandler,Default_Handler

  .weak  I2C5_ER_IRQHandler
  .thumb_set I2C5_ER_IRQHandler,Default_Handler

  .weak  I2C6_EV_IRQHandler
  .thumb_set I2C6_EV_IRQHandler,Default_Handler

  .weak  I2C6_ER_IRQHandler
  .thumb_set I2C6_ER_IRQHandler,Default_Handler

  .weak  HSPI1_IRQHandler
  .thumb_set HSPI1_IRQHandler,Default_Handler

  .weak  GPU2D_IRQHandler
  .thumb_set GPU2D_IRQHandler,Default_Handler

  .weak  GPU2D_ER_IRQHandler
  .thumb_set GPU2D_ER_IRQHandler,Default_Handler

  .weak  GFXMMU_IRQHandler
  .thumb_set GFXMMU_IRQHandler,Default_Handler

  .weak  LTDC_IRQHandler
  .thumb_set LTDC_IRQHandler,Default_Handler

  .weak  LTDC_ER_IRQHandler
  .thumb_set LTDC_ER_IRQHandler,Default_Handler

  .weak  DSI_IRQHandler
  .thumb_set DSI_IRQHandler,Default_Handler

  .weak  DCACHE2_IRQHandler
  .thumb_set DCACHE2_IRQHandler,Default_Handler
