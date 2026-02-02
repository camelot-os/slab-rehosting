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
 * @file    psa_crypto_app.h
 * @brief   PSA Crypto/Storage/Attestation demo functions
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * Provides high-level functions that use PSA APIs to demonstrate
 * TF-M secure services from the non-secure world.
 */

#ifndef PSA_CRYPTO_APP_H
#define PSA_CRYPTO_APP_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include <stddef.h>
#include "psa/crypto.h"
#include "psa/protected_storage.h"
#include "psa/initial_attestation.h"

/* Maximum sizes */
#define PSA_APP_MAX_PLAINTEXT_LEN   256
#define PSA_APP_MAX_CIPHERTEXT_LEN  (PSA_APP_MAX_PLAINTEXT_LEN + 32)  /* + tag + nonce */
#define PSA_APP_MAX_HASH_LEN        64   /* SHA-512 max */
#define PSA_APP_MAX_STORAGE_LEN     256
#define PSA_APP_MAX_ATTEST_LEN      512

/* Result structure for operations */
typedef struct {
    int32_t status;             /* 0 = success, negative = PSA error code */
    uint8_t data[PSA_APP_MAX_CIPHERTEXT_LEN];
    size_t  data_len;
    char    message[128];       /* Human-readable result/error */
} psa_app_result_t;

/**
 * @brief  Initialize PSA crypto subsystem
 * @retval 0 on success, PSA error code on failure
 */
int32_t app_psa_init(void);

/**
 * @brief  Generate an AES-256 key for AEAD operations
 * @param  result: output with key ID in message
 * @retval 0 on success
 */
int32_t app_psa_keygen(psa_app_result_t *result);

/**
 * @brief  Encrypt plaintext using AES-256-GCM
 * @param  plaintext: input data
 * @param  plaintext_len: input length
 * @param  result: output with ciphertext in data[]
 * @retval 0 on success
 */
int32_t app_psa_encrypt(const uint8_t *plaintext, size_t plaintext_len,
                         psa_app_result_t *result);

/**
 * @brief  Decrypt ciphertext using AES-256-GCM
 * @param  ciphertext: input data (nonce + ct + tag)
 * @param  ciphertext_len: input length
 * @param  result: output with plaintext in data[]
 * @retval 0 on success
 */
int32_t app_psa_decrypt(const uint8_t *ciphertext, size_t ciphertext_len,
                         psa_app_result_t *result);

/**
 * @brief  Compute SHA-256 hash
 * @param  input: data to hash
 * @param  input_len: data length
 * @param  result: output with hash in data[]
 * @retval 0 on success
 */
int32_t app_psa_hash(const uint8_t *input, size_t input_len,
                      psa_app_result_t *result);

/**
 * @brief  Store data in PSA Protected Storage
 * @param  uid: storage identifier (1-65535)
 * @param  data: data to store
 * @param  data_len: data length
 * @param  result: output with status message
 * @retval 0 on success
 */
int32_t app_psa_store(uint32_t uid, const uint8_t *data, size_t data_len,
                       psa_app_result_t *result);

/**
 * @brief  Load data from PSA Protected Storage
 * @param  uid: storage identifier
 * @param  result: output with retrieved data in data[]
 * @retval 0 on success
 */
int32_t app_psa_load(uint32_t uid, psa_app_result_t *result);

/**
 * @brief  Get PSA Initial Attestation Token (EAT)
 * @param  result: output with attestation token in data[]
 * @retval 0 on success
 */
int32_t app_psa_attest(psa_app_result_t *result);

/**
 * @brief  Get PSA status information
 * @param  result: output with status string in message
 * @retval 0 on success
 */
int32_t app_psa_status(psa_app_result_t *result);

#ifdef __cplusplus
}
#endif

#endif /* PSA_CRYPTO_APP_H */
