/*
 * Copyright 2024-2026 Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * @file    ux_device_cdc_acm.c
 * @brief   CDC ACM with PSA command parser
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * Accepts text commands over USB CDC and dispatches them to PSA API
 * functions. Provides an interactive terminal for demonstrating
 * TF-M secure services.
 *
 * Commands:
 *   keygen          - Generate AES-256 key
 *   encrypt <text>  - AES-GCM encrypt text
 *   decrypt <hex>   - AES-GCM decrypt hex-encoded ciphertext
 *   hash <text>     - SHA-256 hash
 *   store <uid> <v> - Store value in Protected Storage
 *   load <uid>      - Load value from Protected Storage
 *   attest          - Get attestation token
 *   status          - Show PSA status
 *   help            - Show command list
 */

#include "ux_device_cdc_acm.h"
#include "psa_crypto_app.h"
#include "main.h"
#include "tx_api.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/* CDC ACM instance */
static UX_SLAVE_CLASS_CDC_ACM *cdc_acm_instance = UX_NULL;

/* Synchronization */
static TX_EVENT_FLAGS_GROUP cdc_acm_event_flags;
#define CDC_ACM_ACTIVATED_FLAG  (1UL << 0)

/* Buffers */
static UCHAR cmd_buffer[CDC_ACM_CMD_BUFFER_SIZE];
static UCHAR resp_buffer[CDC_ACM_RESP_BUFFER_SIZE];

/* Forward declarations */
static void process_command(const char *cmd, size_t len);
static void send_response(const char *resp);
static void send_hex_data(const uint8_t *data, size_t len);
static size_t hex_to_bytes(const char *hex, uint8_t *out, size_t max_out);

static const char *HELP_TEXT =
    "\r\n=== STM32H563 TF-M PSA Demo ===\r\n"
    "Commands:\r\n"
    "  keygen            Generate AES-256 key\r\n"
    "  encrypt <text>    AES-256-GCM encrypt\r\n"
    "  decrypt <hex>     AES-256-GCM decrypt\r\n"
    "  hash <text>       SHA-256 hash\r\n"
    "  store <uid> <val> Protected Storage write\r\n"
    "  load <uid>        Protected Storage read\r\n"
    "  attest            Get attestation token\r\n"
    "  status            PSA/TF-M status\r\n"
    "  help              Show this help\r\n"
    "\r\n";

/* ---- CDC ACM Callbacks ---- */

VOID USBD_CDC_ACM_Activate(VOID *instance)
{
    cdc_acm_instance = (UX_SLAVE_CLASS_CDC_ACM *)instance;
    tx_event_flags_set(&cdc_acm_event_flags, CDC_ACM_ACTIVATED_FLAG, TX_OR);
}

VOID USBD_CDC_ACM_Deactivate(VOID *instance)
{
    (void)instance;
    cdc_acm_instance = UX_NULL;
    tx_event_flags_set(&cdc_acm_event_flags, ~CDC_ACM_ACTIVATED_FLAG, TX_AND);
}

VOID USBD_CDC_ACM_ParameterChange(VOID *instance)
{
    (void)instance;
}

/* ---- Read Thread: receives commands from USB host ---- */

void CDC_ACM_Read_Thread_Entry(ULONG thread_input)
{
    ULONG actual_length;
    UINT status;
    ULONG actual_flags;
    size_t cmd_pos = 0;

    (void)thread_input;

    tx_event_flags_create(&cdc_acm_event_flags, "CDC Events");

    while (1)
    {
        /* Wait for activation */
        tx_event_flags_get(&cdc_acm_event_flags, CDC_ACM_ACTIVATED_FLAG,
                          TX_OR, &actual_flags, TX_WAIT_FOREVER);

        if (cdc_acm_instance == UX_NULL)
        {
            tx_thread_sleep(10);
            cmd_pos = 0;
            continue;
        }

        /* Read chunk from USB */
        UCHAR rx_buf[64];
        status = ux_device_class_cdc_acm_read(cdc_acm_instance,
                                               rx_buf, sizeof(rx_buf),
                                               &actual_length);

        if (status != UX_SUCCESS || actual_length == 0)
        {
            continue;
        }

        /* Accumulate into command buffer, process on newline */
        for (ULONG i = 0; i < actual_length; i++)
        {
            char c = (char)rx_buf[i];

            /* Echo character back */
            ULONG echo_len;
            ux_device_class_cdc_acm_write(cdc_acm_instance,
                                           &rx_buf[i], 1, &echo_len);

            if (c == '\r' || c == '\n')
            {
                if (cmd_pos > 0)
                {
                    cmd_buffer[cmd_pos] = '\0';
                    send_response("\r\n");
                    process_command((char *)cmd_buffer, cmd_pos);
                    cmd_pos = 0;
                }
            }
            else if (c == '\b' || c == 0x7F)  /* Backspace */
            {
                if (cmd_pos > 0)
                {
                    cmd_pos--;
                }
            }
            else if (cmd_pos < CDC_ACM_CMD_BUFFER_SIZE - 1)
            {
                cmd_buffer[cmd_pos++] = (UCHAR)c;
            }
        }
    }
}

/* ---- Write Thread: periodic status ---- */

void CDC_ACM_Write_Thread_Entry(ULONG thread_input)
{
    ULONG actual_flags;
    (void)thread_input;

    /* Wait a bit, then send welcome */
    tx_thread_sleep(2 * TX_TIMER_TICKS_PER_SECOND);

    while (1)
    {
        tx_event_flags_get(&cdc_acm_event_flags, CDC_ACM_ACTIVATED_FLAG,
                          TX_OR, &actual_flags, TX_WAIT_FOREVER);

        if (cdc_acm_instance != UX_NULL)
        {
            send_response(HELP_TEXT);
            send_response("> ");
            break;
        }
        tx_thread_sleep(100);
    }

    /* Keep thread alive, toggle LED */
    while (1)
    {
        tx_thread_sleep(TX_TIMER_TICKS_PER_SECOND);
        HAL_GPIO_TogglePin(LED_YELLOW_PORT, LED_YELLOW_PIN);
    }
}

/* ---- Command Processing ---- */

static void process_command(const char *cmd, size_t len)
{
    psa_app_result_t result;
    (void)len;

    /* Skip leading whitespace */
    while (*cmd == ' ') cmd++;

    if (strncmp(cmd, "help", 4) == 0)
    {
        send_response(HELP_TEXT);
    }
    else if (strncmp(cmd, "keygen", 6) == 0)
    {
        app_psa_keygen(&result);
        send_response(result.message);
        send_response("\r\n");
    }
    else if (strncmp(cmd, "encrypt ", 8) == 0)
    {
        const char *text = cmd + 8;
        app_psa_encrypt((const uint8_t *)text, strlen(text), &result);
        send_response(result.message);
        send_response("\r\n");
        if (result.status == 0)
        {
            send_response("  Hex: ");
            send_hex_data(result.data, result.data_len);
            send_response("\r\n");
        }
    }
    else if (strncmp(cmd, "decrypt ", 8) == 0)
    {
        const char *hex = cmd + 8;
        uint8_t ct_buf[PSA_APP_MAX_CIPHERTEXT_LEN];
        size_t ct_len = hex_to_bytes(hex, ct_buf, sizeof(ct_buf));

        if (ct_len == 0)
        {
            send_response("ERROR: Invalid hex input\r\n");
        }
        else
        {
            app_psa_decrypt(ct_buf, ct_len, &result);
            send_response(result.message);
            send_response("\r\n");
            if (result.status == 0)
            {
                send_response("  Text: ");
                /* Send plaintext (may not be null-terminated) */
                ULONG actual;
                if (cdc_acm_instance)
                {
                    ux_device_class_cdc_acm_write(cdc_acm_instance,
                        result.data, (ULONG)result.data_len, &actual);
                }
                send_response("\r\n");
            }
        }
    }
    else if (strncmp(cmd, "hash ", 5) == 0)
    {
        const char *text = cmd + 5;
        app_psa_hash((const uint8_t *)text, strlen(text), &result);
        send_response(result.message);
        send_response("\r\n");
        if (result.status == 0)
        {
            send_response("  SHA-256: ");
            send_hex_data(result.data, result.data_len);
            send_response("\r\n");
        }
    }
    else if (strncmp(cmd, "store ", 6) == 0)
    {
        /* Parse: store <uid> <value> */
        char *args = (char *)(cmd + 6);
        uint32_t uid = (uint32_t)strtoul(args, &args, 10);
        while (*args == ' ') args++;

        if (uid == 0 || *args == '\0')
        {
            send_response("Usage: store <uid> <value>\r\n");
        }
        else
        {
            app_psa_store(uid, (const uint8_t *)args, strlen(args), &result);
            send_response(result.message);
            send_response("\r\n");
        }
    }
    else if (strncmp(cmd, "load ", 5) == 0)
    {
        uint32_t uid = (uint32_t)strtoul(cmd + 5, NULL, 10);
        if (uid == 0)
        {
            send_response("Usage: load <uid>\r\n");
        }
        else
        {
            app_psa_load(uid, &result);
            send_response(result.message);
            send_response("\r\n");
            if (result.status == 0)
            {
                send_response("  Value: ");
                ULONG actual;
                if (cdc_acm_instance)
                {
                    ux_device_class_cdc_acm_write(cdc_acm_instance,
                        result.data, (ULONG)result.data_len, &actual);
                }
                send_response("\r\n");
            }
        }
    }
    else if (strncmp(cmd, "attest", 6) == 0)
    {
        app_psa_attest(&result);
        send_response(result.message);
        send_response("\r\n");
        if (result.status == 0)
        {
            send_response("  Token (hex): ");
            send_hex_data(result.data, result.data_len);
            send_response("\r\n");
        }
    }
    else if (strncmp(cmd, "status", 6) == 0)
    {
        app_psa_status(&result);
        send_response(result.message);
    }
    else
    {
        send_response("Unknown command. Type 'help' for available commands.\r\n");
    }

    send_response("> ");
}

/* ---- Utility Functions ---- */

static void send_response(const char *resp)
{
    if (cdc_acm_instance == UX_NULL || resp == NULL)
        return;

    ULONG actual;
    size_t len = strlen(resp);
    ux_device_class_cdc_acm_write(cdc_acm_instance,
                                   (UCHAR *)resp, (ULONG)len, &actual);
}

static void send_hex_data(const uint8_t *data, size_t len)
{
    if (cdc_acm_instance == UX_NULL)
        return;

    for (size_t i = 0; i < len; i++)
    {
        char hex[3];
        snprintf(hex, sizeof(hex), "%02x", data[i]);

        ULONG actual;
        ux_device_class_cdc_acm_write(cdc_acm_instance,
                                       (UCHAR *)hex, 2, &actual);
    }
}

static uint8_t hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return (uint8_t)(c - '0');
    if (c >= 'a' && c <= 'f') return (uint8_t)(c - 'a' + 10);
    if (c >= 'A' && c <= 'F') return (uint8_t)(c - 'A' + 10);
    return 0xFF;
}

static size_t hex_to_bytes(const char *hex, uint8_t *out, size_t max_out)
{
    size_t i = 0;
    while (*hex && *(hex + 1) && i < max_out)
    {
        uint8_t hi = hex_nibble(*hex++);
        uint8_t lo = hex_nibble(*hex++);
        if (hi == 0xFF || lo == 0xFF)
            return 0;  /* Invalid hex */
        out[i++] = (hi << 4) | lo;
    }
    return i;
}
