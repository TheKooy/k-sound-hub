cmake_minimum_required(VERSION 3.20)
project(audio_hud_overlay LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick)
find_package(LayerShellQt REQUIRED)

qt_standard_project_setup()
qt_policy(SET QTP0001 NEW)

qt_add_executable(audio-hud-overlay
    main.cpp
)

qt_add_qml_module(audio-hud-overlay
    URI AudioHudOverlay
    VERSION 1.0
    QML_FILES
        Overlay.qml
)

target_link_libraries(audio-hud-overlay
    PRIVATE
        Qt6::Core
        Qt6::Gui
        Qt6::Qml
        Qt6::Quick
        LayerShellQt::Interface
)
