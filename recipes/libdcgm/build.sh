#!/usr/bin/env bash
set -euo pipefail

# Apply here rather than through the recipe's source cache so repeated local recipe
# development cannot reuse an extraction patched by an earlier revision.
patch -p0 < "${RECIPE_DIR}/conda.patch"

# libdcgm dynamically loads NVML and does not compile or link CUDA code. Skip
# discovery of the three complete CUDA SDKs required by DCGM's diagnostic targets.
cmake ${CMAKE_ARGS} -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DBUILD_TESTING=OFF \
  -DCTEST_USE_LAUNCHERS=OFF \
  -DDCGM_LIBRARY_ONLY=ON

cmake --build build --target dcgm --parallel "${CPU_COUNT:-4}"

install -d "${PREFIX}/lib" "${PREFIX}/include/datacenter-gpu-manager-4" \
  "${PREFIX}/lib/cmake/DCGM"
install -m 755 "build/libdcgm.so.4.6.0" "${PREFIX}/lib/libdcgm.so.4.6.0"
ln -s libdcgm.so.4.6.0 "${PREFIX}/lib/libdcgm.so.4"
ln -s libdcgm.so.4 "${PREFIX}/lib/libdcgm.so"

for header in \
  dcgm_agent.h dcgm_api_export.h dcgm_errors.h dcgm_fields.h dcgm_helpers.h dcgm_structs.h; do
  install -m 644 "dcgmlib/${header}" "${PREFIX}/include/datacenter-gpu-manager-4/${header}"
done

cat > "${PREFIX}/lib/cmake/DCGM/DCGMConfig.cmake" <<'EOF'
if(NOT TARGET DCGM::dcgm)
  get_filename_component(_DCGM_PREFIX "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
  add_library(DCGM::dcgm SHARED IMPORTED)
  set_target_properties(DCGM::dcgm PROPERTIES
    IMPORTED_LOCATION "${_DCGM_PREFIX}/lib/libdcgm.so.4"
    INTERFACE_INCLUDE_DIRECTORIES "${_DCGM_PREFIX}/include/datacenter-gpu-manager-4"
  )
  unset(_DCGM_PREFIX)
endif()
EOF

cat > "${PREFIX}/lib/cmake/DCGM/DCGMConfigVersion.cmake" <<EOF
set(PACKAGE_VERSION "${PKG_VERSION}")
if(PACKAGE_FIND_VERSION_MAJOR EQUAL 4 AND
   NOT PACKAGE_FIND_VERSION VERSION_GREATER PACKAGE_VERSION)
  set(PACKAGE_VERSION_COMPATIBLE TRUE)
endif()
if(PACKAGE_FIND_VERSION VERSION_EQUAL PACKAGE_VERSION)
  set(PACKAGE_VERSION_EXACT TRUE)
endif()
EOF
