#!/usr/bin/env bash
set -euo pipefail

# Triton is a superbuild. CMAKE_ARGS supplies the conda toolchain, sysroot,
# compiler/linker flags, and relocatable install prefix. The recipe patch
# forwards the relevant values into Triton's nested core build.
#
# Use CMake's FindProtobuf module through a tiny config-mode adapter. This provides
# the protobuf::libprotobuf / protobuf::protoc targets expected by Triton while
# working with the protobuf layout in the current RoboStack-compatible stack.
mkdir -p "${SRC_DIR}/system-cmake/protobuf"
cat > "${SRC_DIR}/system-cmake/protobuf/protobuf-config.cmake" <<'EOF'
include("${CMAKE_ROOT}/Modules/FindProtobuf.cmake")
EOF

cmake ${CMAKE_ARGS} -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_STANDARD=17 \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCUDAToolkit_ROOT="${PREFIX}" \
  -DBUILD_TESTING=OFF \
  -DProtobuf_DIR="${SRC_DIR}/system-cmake/protobuf" \
  -DGTEST_ROOT="${PREFIX}" \
  -DgRPC_DIR="${PREFIX}/lib/cmake/grpc" \
  -Dc-ares_DIR="${PREFIX}/lib/cmake/c-ares" \
  -Dabsl_DIR="${PREFIX}/lib/cmake/absl" \
  -Dre2_DIR="${PREFIX}/lib/cmake/re2" \
  -Dnlohmann_json_DIR="${PREFIX}/share/cmake/nlohmann_json" \
  -DBoost_INCLUDE_DIR="${PREFIX}/include" \
  -DRapidJSON_DIR="${PREFIX}/lib/cmake/RapidJSON" \
  -DRAPIDJSON_INCLUDE_DIRS="${PREFIX}/include" \
  -DTRITON_VERSION=2.60.0 \
  -DTRITON_COMMON_REPO_TAG=r25.08 \
  -DTRITON_THIRD_PARTY_REPO_TAG=r25.08 \
  -DTRITON_CORE_HEADERS_ONLY=OFF \
  -DTRITON_BUILD_PYTHON_BINDINGS=OFF \
  -DTRITON_ENABLE_GPU=ON \
  -DTRITON_ENABLE_METRICS=OFF \
  -DTRITON_ENABLE_METRICS_GPU=OFF \
  -DTRITON_ENABLE_METRICS_CPU=OFF \
  -DTRITON_ENABLE_TRACING=OFF \
  -DTRITON_ENABLE_NVTX=OFF \
  -DTRITON_ENABLE_GCS=OFF \
  -DTRITON_ENABLE_S3=OFF \
  -DTRITON_ENABLE_AZURE_STORAGE=OFF \
  -DTRITON_ENABLE_ENSEMBLE=OFF

cmake --build build --parallel "${CPU_COUNT:-8}"
cmake --install build
