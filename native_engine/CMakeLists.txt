cmake_minimum_required(VERSION 3.16)
project(ksound_native_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

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
