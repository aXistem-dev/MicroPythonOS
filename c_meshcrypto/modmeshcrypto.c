// meshcrypto: MicroPython bindings for orlp/ed25519 as vendored by MeshCore (lib/ed25519).
// Keys use MeshCore's layout: pub = 32 bytes, prv = 64 bytes (clamped scalar || prefix).
#include <string.h>
#include "py/runtime.h"
#include "py/objstr.h"
#include "ed25519/ed_25519.h"

static void check_len(mp_buffer_info_t *b, size_t n, const char *what) {
    if (b->len != n) {
        mp_raise_msg_varg(&mp_type_ValueError, MP_ERROR_TEXT("%s must be %d bytes"), what, (int)n);
    }
}

// create_keypair(seed32) -> (pub32, prv64)
static mp_obj_t mc_create_keypair(mp_obj_t seed_in) {
    mp_buffer_info_t seed;
    mp_get_buffer_raise(seed_in, &seed, MP_BUFFER_READ);
    check_len(&seed, 32, "seed");
    uint8_t pub[32], prv[64];
    ed25519_create_keypair(pub, prv, seed.buf);
    mp_obj_t t[2] = { mp_obj_new_bytes(pub, 32), mp_obj_new_bytes(prv, 64) };
    return mp_obj_new_tuple(2, t);
}
static MP_DEFINE_CONST_FUN_OBJ_1(mc_create_keypair_obj, mc_create_keypair);

// derive_pub(prv64) -> pub32
static mp_obj_t mc_derive_pub(mp_obj_t prv_in) {
    mp_buffer_info_t prv;
    mp_get_buffer_raise(prv_in, &prv, MP_BUFFER_READ);
    check_len(&prv, 64, "prv");
    uint8_t pub[32];
    ed25519_derive_pub(pub, prv.buf);
    return mp_obj_new_bytes(pub, 32);
}
static MP_DEFINE_CONST_FUN_OBJ_1(mc_derive_pub_obj, mc_derive_pub);

// sign(msg, pub32, prv64) -> sig64
static mp_obj_t mc_sign(mp_obj_t msg_in, mp_obj_t pub_in, mp_obj_t prv_in) {
    mp_buffer_info_t msg, pub, prv;
    mp_get_buffer_raise(msg_in, &msg, MP_BUFFER_READ);
    mp_get_buffer_raise(pub_in, &pub, MP_BUFFER_READ);
    mp_get_buffer_raise(prv_in, &prv, MP_BUFFER_READ);
    check_len(&pub, 32, "pub");
    check_len(&prv, 64, "prv");
    uint8_t sig[64];
    ed25519_sign(sig, msg.buf, msg.len, pub.buf, prv.buf);
    return mp_obj_new_bytes(sig, 64);
}
static MP_DEFINE_CONST_FUN_OBJ_3(mc_sign_obj, mc_sign);

// verify(sig64, msg, pub32) -> bool
static mp_obj_t mc_verify(mp_obj_t sig_in, mp_obj_t msg_in, mp_obj_t pub_in) {
    mp_buffer_info_t sig, msg, pub;
    mp_get_buffer_raise(sig_in, &sig, MP_BUFFER_READ);
    mp_get_buffer_raise(msg_in, &msg, MP_BUFFER_READ);
    mp_get_buffer_raise(pub_in, &pub, MP_BUFFER_READ);
    if (sig.len != 64 || pub.len != 32) {
        return mp_const_false;
    }
    return mp_obj_new_bool(ed25519_verify(sig.buf, msg.buf, msg.len, pub.buf));
}
static MP_DEFINE_CONST_FUN_OBJ_3(mc_verify_obj, mc_verify);

// key_exchange(other_pub32, prv64) -> shared32 (X25519 on the Montgomery form of an Ed25519 key)
static mp_obj_t mc_key_exchange(mp_obj_t pub_in, mp_obj_t prv_in) {
    mp_buffer_info_t pub, prv;
    mp_get_buffer_raise(pub_in, &pub, MP_BUFFER_READ);
    mp_get_buffer_raise(prv_in, &prv, MP_BUFFER_READ);
    check_len(&pub, 32, "pub");
    if (prv.len != 32 && prv.len != 64) {
        mp_raise_ValueError(MP_ERROR_TEXT("prv must be 32 or 64 bytes"));
    }
    uint8_t ss[32];
    ed25519_key_exchange(ss, pub.buf, prv.buf);
    return mp_obj_new_bytes(ss, 32);
}
static MP_DEFINE_CONST_FUN_OBJ_2(mc_key_exchange_obj, mc_key_exchange);

static const mp_rom_map_elem_t meshcrypto_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_meshcrypto) },
    { MP_ROM_QSTR(MP_QSTR_create_keypair), MP_ROM_PTR(&mc_create_keypair_obj) },
    { MP_ROM_QSTR(MP_QSTR_derive_pub), MP_ROM_PTR(&mc_derive_pub_obj) },
    { MP_ROM_QSTR(MP_QSTR_sign), MP_ROM_PTR(&mc_sign_obj) },
    { MP_ROM_QSTR(MP_QSTR_verify), MP_ROM_PTR(&mc_verify_obj) },
    { MP_ROM_QSTR(MP_QSTR_key_exchange), MP_ROM_PTR(&mc_key_exchange_obj) },
};
static MP_DEFINE_CONST_DICT(meshcrypto_globals, meshcrypto_globals_table);

const mp_obj_module_t meshcrypto_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&meshcrypto_globals,
};

MP_REGISTER_MODULE(MP_QSTR_meshcrypto, meshcrypto_user_cmodule);
