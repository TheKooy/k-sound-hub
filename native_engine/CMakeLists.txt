cmake_minimum_required(VERSION 3.16)
project(ksound_native_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(PkgConfig REQUIRED)
pkg_check_modules(PIPEWIRE REQUIRED IMPORTED_TARGET libpipewire-0.3)

add_executable(ksound_native_engine
  src/main.cpp
  src/files.cpp
  src/realtime.cpp
  src/engine.cpp
)

target_include_directories(ksound_native_engine PRIVATE include)

target_compile_options(ksound_native_engine PRIVATE -O2 -pipe -Wall -Wextra -Wpedantic)


add_executable(ksound_native_micro_engine
  src/micro_engine.cpp
)

target_include_directories(ksound_native_micro_engine PRIVATE include)

target_compile_options(ksound_native_micro_engine PRIVATE -O2 -pipe -Wall -Wextra -Wpedantic)

add_executable(ksound_pipewire_probe
  src/pipewire_probe.cpp
)

target_include_directories(ksound_pipewire_probe PRIVATE include)

target_link_libraries(ksound_pipewire_probe PRIVATE PkgConfig::PIPEWIRE)

target_compile_options(ksound_pipewire_probe PRIVATE -O2 -pipe -Wall -Wextra -Wpedantic)

add_executable(ksound_pipewire_playback_probe
  src/pipewire_playback_probe.cpp
)

target_include_directories(ksound_pipewire_playback_probe PRIVATE include)

target_link_libraries(ksound_pipewire_playback_probe PRIVATE PkgConfig::PIPEWIRE)

target_compile_options(ksound_pipewire_playback_probe PRIVATE -O2 -pipe -Wall -Wextra -Wpedantic)

add_executable(ksound_pipewire_capture_probe src/pipewire_capture_probe.cpp)
target_link_libraries(ksound_pipewire_capture_probe PRIVATE PkgConfig::PIPEWIRE)
target_compile_options(ksound_pipewire_capture_probe PRIVATE -O2 -pipe -Wall -Wextra -Wpedantic)
