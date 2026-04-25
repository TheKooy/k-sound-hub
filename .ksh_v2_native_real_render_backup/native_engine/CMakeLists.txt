cmake_minimum_required(VERSION 3.20)
project(ksound_native_engine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(ksound_native_engine
  src/main.cpp
  src/engine.cpp
  src/realtime.cpp
  src/files.cpp
)

target_include_directories(ksound_native_engine PRIVATE include)

if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(ksound_native_engine PRIVATE -Wall -Wextra -Wpedantic)
endif()
