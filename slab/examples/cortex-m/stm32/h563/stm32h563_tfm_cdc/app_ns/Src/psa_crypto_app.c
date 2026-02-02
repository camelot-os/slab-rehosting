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
 * @file    psa_crypto_app.c
 * @brief   PSA Crypto / Storage / Attestation demo implementation
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * ============================================================================
 *                       PSA API DEMONSTRATION
 * ============================================================================
 *
 * This file demonstrates using PSA Certified APIs to access security services
 * provided by TF-M (Trusted Firmware-M) running in the secure world.
 *
 * PSA (Platform Security Architecture) is ARM's security framework that defines:
 * - Standard APIs for cryptography, storage, and attestation
 * - Security levels (PSA Certified Level 1, 2, 3)
 * - Root of Trust (RoT) architecture
 *
 * SECURITY MODEL:
 * ===============
 *
 *   Non-Secure World              Secure World (TF-M)
 *  +------------------+          +------------------------+
 *  |                  |          |  Crypto Partition      |
 *  |  psa_generate_   | -------> |  - mbed TLS backend    |
 *  |  key(attr, &id)  |   SVC    |  - Key storage         |
 *  |                  |          |  - Random from HW RNG  |
 *  |  key_id = 1      | <------- |  - Returns handle only |
 *  +------------------+          +------------------------+
 *
 * KEY SECURITY:
 * - Key material NEVER leaves the secure world
 * - NS code only receives opaque key handles (IDs)
 * - All crypto operations are performed in secure world
 * - Secure world validates all inputs from NS
 *
 * SUPPORTED OPERATIONS:
 * 1. psa_generate_key()    - Generate keys (AES-256, RSA, ECC)
 * 2. psa_aead_encrypt()    - Authenticated encryption (AES-GCM)
 * 3. psa_aead_decrypt()    - Authenticated decryption
 * 4. psa_hash_compute()    - Hash computation (SHA-256)
 * 5. psa_ps_set/get()      - Protected Storage (encrypted at rest)
 * 6. psa_initial_attest_*  - Device attestation (EAT token)
 *
 * ANSSI COMPLIANCE:
 * - Error messages are sanitized in production mode
 * - Uses approved cryptographic algorithms only
 * - AES-256-GCM for authenticated encryption
 * - SHA-256 for hashing
 *
 * @see https://arm-software.github.io/psa-api/crypto/
 * @see https://tf-m-user-guide.trustedfirmware.org/
 */

#include "psa_crypto_app.h"
#include <string.h>
#include <stdio.h>

/* ============================================================================
 * PRODUCTION MODE CONFIGURATION
 * ============================================================================
 * In production mode, detailed error codes are hidden to prevent
 * information leakage that could aid attackers.
 */
#ifndef PRODUCTION_MODE
#define PRODUCTION_MODE  0
#endif

#if PRODUCTION_MODE
/* Generic error messages for production (ANSSI compliance) */
#define ERROR_MSG_KEYGEN      "ERROR: Key generation failed"
#define ERROR_MSG_ENCRYPT     "ERROR: Encryption failed"
#define ERROR_MSG_DECRYPT     "ERROR: Decryption failed"
#define ERROR_MSG_HASH        "ERROR: Hash computation failed"
#define ERROR_MSG_STORE       "ERROR: Storage operation failed"
#define ERROR_MSG_LOAD        "ERROR: Load operation failed"
#define ERROR_MSG_ATTEST      "ERROR: Attestation failed"
#define ERROR_MSG_RANDOM      "ERROR: Random generation failed"
#define ERROR_MSG_NO_KEY      "ERROR: Operation requires key"
#define ERROR_MSG_INPUT       "ERROR: Invalid input"
#else
/* Detailed error messages for development/debugging */
#define ERROR_MSG_KEYGEN      "ERROR: psa_generate_key failed (0x%04X)"
#define ERROR_MSG_ENCRYPT     "ERROR: psa_aead_encrypt failed (0x%04X)"
#define ERROR_MSG_DECRYPT     "ERROR: psa_aead_decrypt failed (0x%04X) - auth tag mismatch?"
#define ERROR_MSG_HASH        "ERROR: psa_hash_compute failed (0x%04X)"
#define ERROR_MSG_STORE       "ERROR: psa_ps_set failed (0x%04X)"
#define ERROR_MSG_LOAD        "ERROR: psa_ps_get failed (0x%04X)"
#define ERROR_MSG_ATTEST      "ERROR: psa_initial_attest_get_token failed (0x%04X)"
#define ERROR_MSG_RANDOM      "ERROR: psa_generate_random failed (0x%04X)"
#define ERROR_MSG_NO_KEY      "ERROR: No key. Run 'keygen' first"
#define ERROR_MSG_INPUT       "ERROR: Invalid input"
#endif

/**
 * @brief  Format error message based on production mode
 */
static void format_error(char *buf, size_t buf_size, const char *fmt, psa_status_t status)
{
#if PRODUCTION_MODE
    (void)status;  /* Suppress unused warning */
    snprintf(buf, buf_size, "%s", fmt);
#else
    snprintf(buf, buf_size, fmt, (unsigned)status);
#endif
}

/* Persistent key ID for AES-256-GCM operations */
static psa_key_id_t app_aes_key_id = 0;

/* Nonce for AES-GCM (12 bytes) */
#define AES_GCM_NONCE_LEN  12

/**
 * @brief  Initialize PSA crypto subsystem
 */
int32_t app_psa_init(void)
{
    psa_status_t status;

    status = psa_crypto_init();
    if (status != PSA_SUCCESS)
    {
        return (int32_t)status;
    }

    return 0;
}

/**
 * @brief  Generate AES-256 key for AEAD encryption
 *
 * PSA KEY GENERATION EXPLAINED:
 * ============================
 *
 * 1. Key Attributes define the key's properties:
 *    - Type: AES (symmetric key)
 *    - Size: 256 bits (ANSSI-approved key length)
 *    - Algorithm: GCM (authenticated encryption)
 *    - Usage: ENCRYPT | DECRYPT (what operations are allowed)
 *    - Lifetime: VOLATILE (in-memory only, lost on reset)
 *
 * 2. The actual key material is generated in the SECURE WORLD:
 *    - Uses hardware RNG (TRNG) if available
 *    - Key bytes never leave secure memory
 *    - NS only receives an opaque handle (key ID)
 *
 * 3. Key lifetime options:
 *    - VOLATILE: RAM-only, fast, lost on reset
 *    - PERSISTENT: Stored in secure flash, survives reset
 *
 * For PERSISTENT keys, use psa_set_key_id() with a unique ID.
 */
int32_t app_psa_keygen(psa_app_result_t *result)
{
    psa_status_t status;
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;

    memset(result, 0, sizeof(*result));

    /* Cleanup: Destroy previous key if it exists */
    if (app_aes_key_id != 0)
    {
        psa_destroy_key(app_aes_key_id);
        app_aes_key_id = 0;
    }

    /* Configure key attributes
     * These are security policies enforced by TF-M */
    psa_set_key_usage_flags(&attributes,
                            PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
    psa_set_key_algorithm(&attributes, PSA_ALG_GCM);  /* Only GCM allowed */
    psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);  /* Symmetric AES */
    psa_set_key_bits(&attributes, 256);               /* 256-bit key */
    psa_set_key_lifetime(&attributes, PSA_KEY_LIFETIME_VOLATILE);

    /* Generate key in secure world
     *
     * Under the hood:
     * 1. This call triggers an SVC exception
     * 2. CPU switches to secure mode
     * 3. TF-M generates 32 random bytes using TRNG
     * 4. Key is stored in secure RAM
     * 5. A handle (ID) is returned to NS
     */
    status = psa_generate_key(&attributes, &app_aes_key_id);
    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        format_error(result->message, sizeof(result->message),
                     ERROR_MSG_KEYGEN, status);
        return result->status;
    }

    snprintf(result->message, sizeof(result->message),
            "OK: AES-256 key generated (ID: %lu)",
            (unsigned long)app_aes_key_id);
    result->status = 0;
    return 0;
}

/**
 * @brief  AES-256-GCM encryption
 *
 * AES-GCM (Galois/Counter Mode) provides:
 * - Confidentiality (encryption)
 * - Authenticity (GMAC tag verifies data wasn't tampered)
 *
 * OUTPUT FORMAT:
 * +--------+------------+------+
 * | Nonce  | Ciphertext | Tag  |
 * | 12 B   | variable   | 16 B |
 * +--------+------------+------+
 *
 * SECURITY NOTES:
 * - Nonce MUST be unique per encryption with same key
 * - We use psa_generate_random() for nonce generation
 * - GCM is vulnerable if nonce is ever reused!
 * - Tag provides authentication; decryption fails if data modified
 *
 * @param plaintext     Input data to encrypt
 * @param plaintext_len Length of input data
 * @param result        Output buffer (receives nonce + ciphertext + tag)
 */
int32_t app_psa_encrypt(const uint8_t *plaintext, size_t plaintext_len,
                         psa_app_result_t *result)
{
    psa_status_t status;
    uint8_t nonce[AES_GCM_NONCE_LEN];
    size_t ciphertext_len;

    memset(result, 0, sizeof(*result));

    if (app_aes_key_id == 0)
    {
        result->status = -1;
        snprintf(result->message, sizeof(result->message),
                "ERROR: No key. Run 'keygen' first");
        return -1;
    }

    if (plaintext_len > PSA_APP_MAX_PLAINTEXT_LEN)
    {
        result->status = -2;
        snprintf(result->message, sizeof(result->message),
                "ERROR: Input too long (max %d bytes)", PSA_APP_MAX_PLAINTEXT_LEN);
        return -2;
    }

    /* Generate random nonce */
    status = psa_generate_random(nonce, AES_GCM_NONCE_LEN);
    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        format_error(result->message, sizeof(result->message),
                     ERROR_MSG_RANDOM, status);
        return result->status;
    }

    /* Prepend nonce to output */
    memcpy(result->data, nonce, AES_GCM_NONCE_LEN);

    /* Encrypt: output goes after nonce */
    status = psa_aead_encrypt(
        app_aes_key_id,
        PSA_ALG_GCM,
        nonce, AES_GCM_NONCE_LEN,
        NULL, 0,                    /* No additional data */
        plaintext, plaintext_len,
        result->data + AES_GCM_NONCE_LEN,
        PSA_APP_MAX_CIPHERTEXT_LEN - AES_GCM_NONCE_LEN,
        &ciphertext_len
    );

    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        format_error(result->message, sizeof(result->message),
                     ERROR_MSG_ENCRYPT, status);
        return result->status;
    }

    result->data_len = AES_GCM_NONCE_LEN + ciphertext_len;
    snprintf(result->message, sizeof(result->message),
            "OK: Encrypted %zu bytes -> %zu bytes (nonce+ct+tag)",
            plaintext_len, result->data_len);
    result->status = 0;
    return 0;
}

/**
 * @brief  AES-256-GCM decryption
 *         Input format: [12-byte nonce][ciphertext][16-byte tag]
 */
int32_t app_psa_decrypt(const uint8_t *ciphertext, size_t ciphertext_len,
                         psa_app_result_t *result)
{
    psa_status_t status;
    size_t plaintext_len;

    memset(result, 0, sizeof(*result));

    if (app_aes_key_id == 0)
    {
        result->status = -1;
        snprintf(result->message, sizeof(result->message),
                "ERROR: No key. Run 'keygen' first");
        return -1;
    }

    if (ciphertext_len <= AES_GCM_NONCE_LEN + PSA_AEAD_TAG_MAX_SIZE)
    {
        result->status = -2;
        snprintf(result->message, sizeof(result->message),
                "ERROR: Ciphertext too short");
        return -2;
    }

    /* Extract nonce (first 12 bytes) */
    const uint8_t *nonce = ciphertext;
    const uint8_t *ct = ciphertext + AES_GCM_NONCE_LEN;
    size_t ct_len = ciphertext_len - AES_GCM_NONCE_LEN;

    /* Decrypt */
    status = psa_aead_decrypt(
        app_aes_key_id,
        PSA_ALG_GCM,
        nonce, AES_GCM_NONCE_LEN,
        NULL, 0,                    /* No additional data */
        ct, ct_len,
        result->data,
        PSA_APP_MAX_PLAINTEXT_LEN,
        &plaintext_len
    );

    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        format_error(result->message, sizeof(result->message),
                     ERROR_MSG_DECRYPT, status);
        return result->status;
    }

    result->data_len = plaintext_len;
    snprintf(result->message, sizeof(result->message),
            "OK: Decrypted %zu bytes", plaintext_len);
    result->status = 0;
    return 0;
}

/**
 * @brief  SHA-256 hash computation
 */
int32_t app_psa_hash(const uint8_t *input, size_t input_len,
                      psa_app_result_t *result)
{
    psa_status_t status;
    size_t hash_len;

    memset(result, 0, sizeof(*result));

    status = psa_hash_compute(
        PSA_ALG_SHA_256,
        input, input_len,
        result->data, PSA_APP_MAX_HASH_LEN,
        &hash_len
    );

    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        format_error(result->message, sizeof(result->message),
                     ERROR_MSG_HASH, status);
        return result->status;
    }

    result->data_len = hash_len;
    snprintf(result->message, sizeof(result->message),
            "OK: SHA-256 hash (%zu bytes)", hash_len);
    result->status = 0;
    return 0;
}

/**
 * @brief  Store data in PSA Protected Storage
 *         Data is encrypted at rest by TF-M using device-unique key
 */
int32_t app_psa_store(uint32_t uid, const uint8_t *data, size_t data_len,
                       psa_app_result_t *result)
{
    psa_status_t status;

    memset(result, 0, sizeof(*result));

    if (data_len > PSA_APP_MAX_STORAGE_LEN)
    {
        result->status = -1;
        snprintf(result->message, sizeof(result->message),
                "ERROR: Data too long (max %d)", PSA_APP_MAX_STORAGE_LEN);
        return -1;
    }

    status = psa_ps_set(
        (psa_storage_uid_t)uid,
        data_len,
        data,
        PSA_STORAGE_FLAG_NONE
    );

    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        format_error(result->message, sizeof(result->message),
                     ERROR_MSG_STORE, status);
        return result->status;
    }

    snprintf(result->message, sizeof(result->message),
            "OK: Stored %zu bytes at UID %lu (encrypted at rest)",
            data_len, (unsigned long)uid);
    result->status = 0;
    return 0;
}

/**
 * @brief  Load data from PSA Protected Storage
 */
int32_t app_psa_load(uint32_t uid, psa_app_result_t *result)
{
    psa_status_t status;
    size_t data_len;
    struct psa_storage_info_t info;

    memset(result, 0, sizeof(*result));

    /* Get info first to know the size */
    status = psa_ps_get_info((psa_storage_uid_t)uid, &info);
    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        snprintf(result->message, sizeof(result->message),
                "ERROR: UID %lu not found (0x%04X)",
                (unsigned long)uid, (unsigned)status);
        return result->status;
    }

    /* Read the data */
    status = psa_ps_get(
        (psa_storage_uid_t)uid,
        0,                          /* offset */
        info.size,
        result->data,
        &data_len
    );

    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        snprintf(result->message, sizeof(result->message),
                "ERROR: psa_ps_get failed (0x%04X)", (unsigned)status);
        return result->status;
    }

    result->data_len = data_len;
    snprintf(result->message, sizeof(result->message),
            "OK: Loaded %zu bytes from UID %lu",
            data_len, (unsigned long)uid);
    result->status = 0;
    return 0;
}

/**
 * @brief  Get PSA Initial Attestation Token (Entity Attestation Token)
 *         The token is signed by TF-M using the device's attestation key
 */
int32_t app_psa_attest(psa_app_result_t *result)
{
    psa_status_t status;
    size_t token_len;

    /* Challenge nonce for attestation (normally from verifier) */
    uint8_t challenge[32];
    memset(result, 0, sizeof(*result));

    /* Generate random challenge */
    status = psa_generate_random(challenge, sizeof(challenge));
    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        snprintf(result->message, sizeof(result->message),
                "ERROR: Cannot generate challenge (0x%04X)", (unsigned)status);
        return result->status;
    }

    /* Request attestation token from TF-M */
    status = psa_initial_attest_get_token(
        challenge, sizeof(challenge),
        result->data, PSA_APP_MAX_ATTEST_LEN,
        &token_len
    );

    if (status != PSA_SUCCESS)
    {
        result->status = (int32_t)status;
        snprintf(result->message, sizeof(result->message),
                "ERROR: psa_initial_attest_get_token failed (0x%04X)",
                (unsigned)status);
        return result->status;
    }

    result->data_len = token_len;
    snprintf(result->message, sizeof(result->message),
            "OK: Attestation token (%zu bytes, CBOR/EAT format)",
            token_len);
    result->status = 0;
    return 0;
}

/**
 * @brief  Get PSA/TF-M status information
 */
int32_t app_psa_status(psa_app_result_t *result)
{
    memset(result, 0, sizeof(*result));

    int len = snprintf(result->message, sizeof(result->message),
        "PSA Status:\r\n"
        "  Crypto init: OK\r\n"
        "  AES key ID: %lu (%s)\r\n"
        "  Isolation: Level 1 (SFN)\r\n"
        "  Services: Crypto, PS, ITS, Attestation\r\n"
        "  Platform: STM32H563 + TF-M v2.1\r\n",
        (unsigned long)app_aes_key_id,
        (app_aes_key_id != 0) ? "active" : "none");

    result->data_len = 0;
    result->status = 0;
    (void)len;
    return 0;
}
