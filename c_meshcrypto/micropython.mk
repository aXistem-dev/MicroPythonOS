MESHCRYPTO_DIR := $(USERMOD_DIR)
SRC_USERMOD_C += $(MESHCRYPTO_DIR)/modmeshcrypto.c
SRC_USERMOD_LIB_C += $(addprefix $(MESHCRYPTO_DIR)/ed25519/, add_scalar.c fe.c ge.c key_exchange.c keypair.c sc.c sha512.c sign.c verify.c)
CFLAGS_USERMOD += -I$(MESHCRYPTO_DIR) -DED25519_NO_SEED=1
