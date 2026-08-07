#!/bin/bash

set -ex

# This compatibility recipe intentionally builds only the generic/OpenBLAS matrix.
export blas_impl=generic

echo "#########################################################################"
echo "Building PyTorch ${PKG_VERSION} (Python ${PY_VER}, CUDA ${cuda_compiler_version})"
echo "#########################################################################"

# This is used to detect if it's in the process of building pytorch
export IN_PYTORCH_BUILD=1

# https://github.com/conda-forge/pytorch-cpu-feedstock/issues/243
# https://github.com/pytorch/pytorch/blob/v2.3.1/setup.py#L341
export PACKAGE_TYPE=conda

# remove pyproject.toml to avoid installing deps from pip
rm -rf pyproject.toml

# remove runtime pin for setuptools, upstream added it to workaround
# breakage from transitive dependencies using pkg_resources. we can handle
# these dependencies directly in conda-forge.
sed -i -e '/setuptools<82/d' setup.py

# uncomment to debug cmake build
# export CMAKE_VERBOSE_MAKEFILE=1

export USE_CUFILE=0
export USE_NUMA=0
export USE_ITT=0

#################### ADJUST COMPILER AND LINKER FLAGS #####################
# Pytorch's build system doesn't like us setting the c++ standard through CMAKE_CXX_FLAGS
# and will issue a warning.  We need to use at least C++17 to match the abseil ABI, see
# https://github.com/conda-forge/abseil-cpp-feedstock/issues/45, which pytorch 2.5 uses already:
# https://github.com/pytorch/pytorch/blob/v2.5.1/CMakeLists.txt#L36-L48
export CXXFLAGS="$(echo $CXXFLAGS | sed 's/-std=c++[0-9][0-9]//g')"
# The below three lines expose symbols that would otherwise be hidden or
# optimised away. They were here before, so removing them would potentially
# break users' programs
export CFLAGS="$(echo $CFLAGS | sed 's/-fvisibility-inlines-hidden//g')"
export CXXFLAGS="$(echo $CXXFLAGS | sed 's/-fvisibility-inlines-hidden//g')"
# ignore warnings; blows up the logs for no benefit; they need to be fixed upstream
export CXXFLAGS="$CXXFLAGS -w"

export LDFLAGS="$(echo $LDFLAGS | sed 's/-Wl,--as-needed//g')"
# The default conda LDFLAGs include -Wl,-dead_strip_dylibs, which removes all the
# MKL sequential, core, etc. libraries, resulting in a "Symbol not found: _mkl_blas_caxpy"
# error on osx-64.
export LDFLAGS="$(echo $LDFLAGS | sed 's/-Wl,-dead_strip_dylibs//g')"
export LDFLAGS_LD="$(echo $LDFLAGS_LD | sed 's/-dead_strip_dylibs//g')"
if [[ "$c_compiler" == "clang" ]]; then
    export CXXFLAGS="$CXXFLAGS -Wno-deprecated-declarations -Wno-unknown-warning-option -Wno-error=unused-command-line-argument -Wno-error=vla-cxx-extension"
    export CFLAGS="$CFLAGS -Wno-deprecated-declarations -Wno-unknown-warning-option -Wno-error=unused-command-line-argument -Wno-error=vla-cxx-extension"
else
    export CXXFLAGS="$CXXFLAGS -Wno-deprecated-declarations -Wno-error=maybe-uninitialized"
    export CFLAGS="$CFLAGS -Wno-deprecated-declarations -Wno-error=maybe-uninitialized"
fi

# This is not correctly found for linux-aarch64 since pytorch 2.0.0 for some reason
export _GLIBCXX_USE_CXX11_ABI=1

if [[ "$target_platform" == "osx-64" ]]; then
  export CXXFLAGS="$CXXFLAGS -DTARGET_OS_OSX=1"
  export CFLAGS="$CFLAGS -DTARGET_OS_OSX=1"
elif [[ "$target_platform" == linux-* ]]; then
    # Explicitly force non-executable stack to fix compatibility with glibc 2.41, due to:
    # ittptmark64.S.o: missing .note.GNU-stack section implies executable stack
    LDFLAGS="${LDFLAGS} -Wl,-z,noexecstack"
fi

# Dynamic libraries need to be lazily loaded so that torch
# can be imported on system without a GPU
LDFLAGS="${LDFLAGS//-Wl,-z,now/-Wl,-z,lazy}"

################ CONFIGURE CMAKE FOR CONDA ENVIRONMENT ###################
export CMAKE_GENERATOR=Ninja
export CMAKE_LIBRARY_PATH=$PREFIX/lib:$PREFIX/include:$CMAKE_LIBRARY_PATH
export CMAKE_PREFIX_PATH=$PREFIX
export CMAKE_BUILD_TYPE=Release

# PyTorch's setup.py honors $CMAKE_ARGS (see patch
# 0002b-Honor-CMAKE_ARGS-in-setup.py-cmake-invocation), so conda's flags reach
# cmake on the command line *before* project() -- which is what cross
# compilation needs (CMAKE_SYSTEM_NAME, CMAKE_OSX_SYSROOT, the cross binutils,
# ...). Append $SRC_DIR to CMAKE_FIND_ROOT_PATH so cross find_* can locate things
# unpacked in the source tree -- but only when conda actually set a root path
# (i.e. when cross compiling); forcing one on a native build would over-restrict
# find_*. (CMAKE_INSTALL_PREFIX is filtered out in patch 0002b, since cmake.py
# sets its own.)
# NB: CUDA builds receive *two* -DCMAKE_FIND_ROOT_PATH flags (conda's nvcc
# activation appends a second one with the CUDA targets); cmake uses the last,
# so append $SRC_DIR to *every* occurrence (g flag). Without it the winning
# entry omits the source tree and pytorch can't find the bundled oneDNN source
# ("MKLDNN source files not found!" -> USE_MKLDNN off -> undefined dnnl_graph
# symbol at import; CPU builds have a single entry and were unaffected).
CMAKE_ARGS="$(echo "$CMAKE_ARGS" | sed -E "s#(-DCMAKE_FIND_ROOT_PATH=[^[:space:]]*)#\1;${SRC_DIR}#g")"
export CMAKE_ARGS

export PYTORCH_BUILD_VERSION=$PKG_VERSION
# Always pass 0 to avoid appending ".post" to version string.
# https://github.com/conda-forge/pytorch-cpu-feedstock/issues/315
export PYTORCH_BUILD_NUMBER=0

export INSTALL_TEST=0
export BUILD_TEST=0

export USE_SYSTEM_SLEEF=1
# use our protobuf
export BUILD_CUSTOM_PROTOBUF=OFF
rm -rf $PREFIX/bin/protoc
export USE_SYSTEM_PYBIND11=1
export USE_SYSTEM_EIGEN_INSTALL=1
export USE_SYSTEM_FMT=1
export Python_ROOT_DIR=$PREFIX

# force using cblas_dot when cross-compiling
# (this matches the behavior to our patches)
export PYTORCH_BLAS_USE_CBLAS_DOT=ON

# workaround to stop setup.py from trying to check whether we checked out
# all submodules (we don't use all of them)
rm -f .gitmodules

# prevent six from being downloaded
> third_party/NNPACK/cmake/DownloadSix.cmake

if [[ "${target_platform}" != "${build_platform}" ]]; then
    # It helps cross compiled builds without emulation support to complete
    # Use BUILD PREFIX protoc instead of the one that is from the host platform
    sed -i.bak \
        "s,IMPORTED_LOCATION_RELEASE .*/bin/protoc,IMPORTED_LOCATION_RELEASE \"${BUILD_PREFIX}/bin/protoc," \
        ${PREFIX}/lib/cmake/protobuf/protobuf-targets-release.cmake
fi

# I don't know where this folder comes from, but it's interfering with the build in osx-64
rm -rf $PREFIX/git

if [[ "${CI}" == "github_actions" ]]; then
    # jaimerg -- Apr 2026
    # reduce parallelism to avoid getting OOM-killed on
    # blacksmith-16vCPU has 64GB on x64 and 48GB on ARM (linux)
    # blacksmith-16vCPU has 58GB on x64 (windows)
    # blacksmith-12vCPU has 48GB on ARM (osx)
    export MAX_JOBS=8
elif [[ "${CI}" == "azure" ]]; then
    export MAX_JOBS=${CPU_COUNT}
else
    # Leave a spare core for other tasks, per common practice.
    # Reducing further can help with out-of-memory errors.
    export MAX_JOBS=$((CPU_COUNT > 1 ? CPU_COUNT - 1 : 1))
fi

case "$blas_impl" in
    "generic")
        # Fake openblas
        export BLAS=OpenBLAS
        export OpenBLAS_HOME=${PREFIX}
        ;;
    "mkl")
        export BLAS=MKL
        ;;
    *)
        echo "[ERROR] Unsupported BLAS implementation '${blas_impl}'" >&2
        exit 1
        ;;
esac

# MacOS build is simple, and will not be for CUDA
if [[ "$OSTYPE" == "darwin"* ]]; then
    export USE_CUDA=0

    # Produce macOS builds with torch.distributed support.
    # This is enabled by default on Linux, but disabled by default on macOS,
    # because it requires an non-bundled compile-time dependency (libuv
    # through gloo). This dependency is made available through meta.yaml, so
    # we can override the default and set USE_DISTRIBUTED=1.
    export USE_DISTRIBUTED=1

    if [[ "$target_platform" == "osx-arm64" ]]; then
        # MKLDNN did not support on Apple M1 at the time support Apple M1
        # was added. Revisit later
        export USE_MKLDNN=0
    fi
elif [[ ${cuda_compiler_version} != "None" ]]; then
    if [[ "$target_platform" == "linux-aarch64" ]]; then
        # https://github.com/pytorch/pytorch/pull/121975
        # https://github.com/conda-forge/pytorch-cpu-feedstock/issues/264
        export USE_PRIORITIZED_TEXT_FOR_LD=1
    fi
    # Even though cudnn is used for CUDA builds, it's good to enable
    # for MKLDNN for CUDA builds when CUDA builds are used on a machine
    # with no NVIDIA GPUs.
    export USE_MKLDNN=1
    export USE_CUDA=1
    export USE_CUFILE=1
    # PyTorch has multiple different bits of logic finding CUDA, override
    # all of them.
    export CUDAToolkit_BIN_DIR=${BUILD_PREFIX}/bin
    export CUDAToolkit_ROOT_DIR=${PREFIX}
    # for CUPTI
    export CUDA_TOOLKIT_ROOT_DIR=${PREFIX}
    export CUDAToolkit_ROOT=${PREFIX}
    case ${target_platform} in
        linux-64)
            CUDA_TARGET=x86_64-linux
            ;;
        linux-aarch64)
            # conda-forge's CUDA 13 toolkit is the SBSA-hosted ARM distribution.
            # Device code is selected independently below: SM87 for Orin, SM110
            # for Thor. This is the same generic-host/native-GPU distinction we
            # verified for the original TensorRT SBSA experiment.
            CUDA_TARGET=sbsa-linux
            ;;
        *)
            echo "unknown CUDA arch, edit build.sh"
            exit 1
    esac
    export CUDAToolkit_TARGET_DIR=${PREFIX}/targets/${CUDA_TARGET}
    sed -i -e "s,@CUDA_TARGET@,${CUDA_TARGET}," torch/_inductor/cpp_builder.py
    sed -i -e "s,@CUDA_TARGET@,${CUDA_TARGET}," torch/utils/cpp_extension.py

    export TORCH_NVCC_FLAGS="-Xfatbin -compress-all"

    # Compatibility matrix for update: https://en.wikipedia.org/wiki/CUDA#GPUs_supported
    # Warning from pytorch v1.12.1: In the future we will require one to
    # explicitly pass TORCH_CUDA_ARCH_LIST to cmake instead of implicitly
    # setting it as an env variable.
    # Doing this is nontrivial given that we're using setup.py as an entry point, but should
    # be addressed to pre-empt upstream changing it, as it probably won't result in a failed
    # configuration.
    #
    # See:
    # https://pytorch.org/docs/stable/cpp_extension.html (Compute capabilities)
    # https://github.com/pytorch/pytorch/blob/main/.ci/manywheel/build_cuda.sh
    if [[ "${target_platform}" == "linux-aarch64" && "${tensorrt_flavor}" == "orin" ]]; then
        export TORCH_CUDA_ARCH_LIST="8.7+PTX"
    elif [[ "${target_platform}" == "linux-aarch64" ]]; then
        export TORCH_CUDA_ARCH_LIST="11.0+PTX"
    else
        # CUDA 13 no longer supports Maxwell/Pascal. Keep native workstation,
        # Ada/Hopper/Blackwell/Thor code and PTX for the newest architecture.
        export TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9;9.0;10.0;11.0;12.0+PTX"
    fi
    export TORCH_NVCC_FLAGS="$TORCH_NVCC_FLAGS -compress-mode=size"

    export NCCL_ROOT_DIR=$PREFIX
    export NCCL_INCLUDE_DIR=$PREFIX/include
    export USE_SYSTEM_NCCL=1
    export USE_SYSTEM_NVTX=1
    export USE_STATIC_NCCL=0
    export USE_STATIC_CUDNN=0
    export MAGMA_HOME="${PREFIX}"
    export USE_MAGMA=1
    export CUDA_VERSION=$cuda_compiler_version
    # ptxas advisories do not get ignored correctly, see
    # https://github.com/conda-forge/cuda-nvcc-feedstock/issues/60
    export CMAKE_CUDA_FLAGS="-w -Xptxas -w"
else
    if [[ "$target_platform" != *-64 ]]; then
      # Breakpad seems to not work on aarch64 or ppc64le
      # https://github.com/pytorch/pytorch/issues/67083
      export USE_BREAKPAD=0
    fi
    # MKLDNN is an Apache-2.0 licensed library for DNNs and is used
    # for CPU builds. Not to be confused with MKL.
    export USE_MKLDNN=1
    export USE_CUDA=0
    export TORCH_CUDA_ARCH_LIST=""
fi

echo '${CXX}'=${CXX}
echo '${PREFIX}'=${PREFIX}

# Unlike conda-forge's split libtorch/pytorch outputs, build once and keep the
# Python module, C++ libraries, headers and CMake metadata together. Splitting
# would require either conda-build's shared output work directory or compiling
# this very large project twice; neither is useful for this compatibility build.
$PREFIX/bin/python -m pip install . --no-deps --no-build-isolation -v --no-clean \
    --config-settings=--global-option=-q \
    | sed "s,${CXX},\$\{CXX\},g" \
    | sed "s,${PREFIX},\$\{PREFIX\},g"
