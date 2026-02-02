PSA API Demo (TF-M Variant)
===========================

The TF-M variant demonstrates PSA Certified APIs for cryptographic
services, protected storage, and device attestation.

Overview
--------

PSA (Platform Security Architecture) provides standardized APIs for:

- **Crypto**: Symmetric/asymmetric encryption, hashing, MAC, key management
- **Protected Storage**: Encrypted data storage with integrity
- **Attestation**: Device identity and state verification

All operations execute in the secure world via TF-M.

Initialization
--------------

Initialize PSA crypto before use:

.. code-block:: c

   #include "psa/crypto.h"

   int32_t app_psa_init(void)
   {
       psa_status_t status = psa_crypto_init();

       if (status != PSA_SUCCESS)
       {
           return (int32_t)status;
       }

       return 0;
   }

Key Generation
--------------

Generate an AES-256 key for encryption:

.. code-block:: c

   int32_t app_psa_keygen(psa_key_id_t *key_id)
   {
       psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;

       /* Configure key attributes */
       psa_set_key_usage_flags(&attributes,
                               PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
       psa_set_key_algorithm(&attributes, PSA_ALG_GCM);
       psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);
       psa_set_key_bits(&attributes, 256);
       psa_set_key_lifetime(&attributes, PSA_KEY_LIFETIME_VOLATILE);

       /* Generate key in secure world */
       psa_status_t status = psa_generate_key(&attributes, key_id);

       return (status == PSA_SUCCESS) ? 0 : (int32_t)status;
   }

AES-256-GCM Encryption
----------------------

Encrypt data with authenticated encryption:

.. code-block:: c

   int32_t app_psa_encrypt(psa_key_id_t key_id,
                            const uint8_t *plaintext, size_t plaintext_len,
                            uint8_t *output, size_t output_size,
                            size_t *output_len)
   {
       uint8_t nonce[12];
       size_t ciphertext_len;

       /* Generate random nonce */
       psa_status_t status = psa_generate_random(nonce, sizeof(nonce));
       if (status != PSA_SUCCESS)
           return (int32_t)status;

       /* Prepend nonce to output */
       memcpy(output, nonce, sizeof(nonce));

       /* Encrypt */
       status = psa_aead_encrypt(
           key_id,
           PSA_ALG_GCM,
           nonce, sizeof(nonce),
           NULL, 0,                    /* No additional data */
           plaintext, plaintext_len,
           output + sizeof(nonce),
           output_size - sizeof(nonce),
           &ciphertext_len
       );

       if (status == PSA_SUCCESS)
           *output_len = sizeof(nonce) + ciphertext_len;

       return (status == PSA_SUCCESS) ? 0 : (int32_t)status;
   }

Output format: ``[12-byte nonce][ciphertext][16-byte GCM tag]``

AES-256-GCM Decryption
----------------------

Decrypt and verify authenticated data:

.. code-block:: c

   int32_t app_psa_decrypt(psa_key_id_t key_id,
                            const uint8_t *ciphertext, size_t ciphertext_len,
                            uint8_t *plaintext, size_t plaintext_size,
                            size_t *plaintext_len)
   {
       /* Extract nonce from input */
       const uint8_t *nonce = ciphertext;
       const uint8_t *ct = ciphertext + 12;
       size_t ct_len = ciphertext_len - 12;

       /* Decrypt and verify tag */
       psa_status_t status = psa_aead_decrypt(
           key_id,
           PSA_ALG_GCM,
           nonce, 12,
           NULL, 0,
           ct, ct_len,
           plaintext, plaintext_size,
           plaintext_len
       );

       return (status == PSA_SUCCESS) ? 0 : (int32_t)status;
   }

SHA-256 Hashing
---------------

Compute a cryptographic hash:

.. code-block:: c

   int32_t app_psa_hash(const uint8_t *input, size_t input_len,
                         uint8_t *hash, size_t hash_size,
                         size_t *hash_len)
   {
       psa_status_t status = psa_hash_compute(
           PSA_ALG_SHA_256,
           input, input_len,
           hash, hash_size,
           hash_len
       );

       return (status == PSA_SUCCESS) ? 0 : (int32_t)status;
   }

Protected Storage
-----------------

Store data encrypted at rest:

.. code-block:: c

   int32_t app_psa_store(uint32_t uid, const uint8_t *data, size_t data_len)
   {
       psa_status_t status = psa_ps_set(
           (psa_storage_uid_t)uid,
           data_len,
           data,
           PSA_STORAGE_FLAG_NONE
       );

       return (status == PSA_SUCCESS) ? 0 : (int32_t)status;
   }

Load data from protected storage:

.. code-block:: c

   int32_t app_psa_load(uint32_t uid, uint8_t *data, size_t data_size,
                         size_t *data_len)
   {
       struct psa_storage_info_t info;

       /* Get size */
       psa_status_t status = psa_ps_get_info((psa_storage_uid_t)uid, &info);
       if (status != PSA_SUCCESS)
           return (int32_t)status;

       /* Read data */
       status = psa_ps_get(
           (psa_storage_uid_t)uid,
           0, info.size,
           data, data_len
       );

       return (status == PSA_SUCCESS) ? 0 : (int32_t)status;
   }

Device Attestation
------------------

Get a signed attestation token:

.. code-block:: c

   int32_t app_psa_attest(uint8_t *token, size_t token_size, size_t *token_len)
   {
       uint8_t challenge[32];

       /* Generate challenge nonce */
       psa_status_t status = psa_generate_random(challenge, sizeof(challenge));
       if (status != PSA_SUCCESS)
           return (int32_t)status;

       /* Get attestation token */
       status = psa_initial_attest_get_token(
           challenge, sizeof(challenge),
           token, token_size,
           token_len
       );

       return (status == PSA_SUCCESS) ? 0 : (int32_t)status;
   }

The token is in CBOR/EAT (Entity Attestation Token) format and can be
verified by a remote attestation service.

Error Handling
--------------

PSA functions return ``psa_status_t``:

.. list-table:: Common PSA Status Codes
   :widths: 30 70
   :header-rows: 1

   * - Status
     - Meaning
   * - ``PSA_SUCCESS``
     - Operation completed successfully
   * - ``PSA_ERROR_INVALID_ARGUMENT``
     - Invalid parameter
   * - ``PSA_ERROR_NOT_PERMITTED``
     - Operation not allowed
   * - ``PSA_ERROR_BUFFER_TOO_SMALL``
     - Output buffer too small
   * - ``PSA_ERROR_INVALID_SIGNATURE``
     - Signature/tag verification failed
   * - ``PSA_ERROR_DOES_NOT_EXIST``
     - Key or storage item not found

USB CDC Command Interface
-------------------------

The demo application accepts commands via USB CDC:

.. list-table:: Available Commands
   :widths: 20 80
   :header-rows: 1

   * - Command
     - Description
   * - ``status``
     - Show PSA/TF-M status
   * - ``keygen``
     - Generate AES-256 key
   * - ``encrypt <data>``
     - Encrypt data with AES-GCM
   * - ``decrypt <hex>``
     - Decrypt hex-encoded ciphertext
   * - ``hash <data>``
     - Compute SHA-256 hash
   * - ``store <uid> <data>``
     - Store data in protected storage
   * - ``load <uid>``
     - Load data from protected storage
   * - ``attest``
     - Get attestation token
   * - ``help``
     - Show available commands
