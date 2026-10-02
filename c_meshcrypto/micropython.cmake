# Pass to make.py as USER_C_MODULE=/abs/path/c_meshcrypto/micropython.cmake
add_library(usermod_meshcrypto INTERFACE)
target_sources(usermod_meshcrypto INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modmeshcrypto.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/add_scalar.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/fe.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/ge.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/key_exchange.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/keypair.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/sc.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/sha512.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/sign.c
    ${CMAKE_CURRENT_LIST_DIR}/ed25519/verify.c
)
target_include_directories(usermod_meshcrypto INTERFACE ${CMAKE_CURRENT_LIST_DIR})
target_compile_definitions(usermod_meshcrypto INTERFACE ED25519_NO_SEED=1)
# Do NOT add target_compile_options(... INTERFACE -Ox): INTERFACE options leak into every
# usermod source (LVGL included) and the last -O on the command line wins.
target_link_libraries(usermod INTERFACE usermod_meshcrypto)
