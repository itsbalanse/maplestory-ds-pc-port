cmake_minimum_required(VERSION 3.20)
project(MapleStoryDS_PC LANGUAGES C CXX ASM)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# DS hardware model: melonDS core (GPL-3.0), pinned to release 1.1.
# Fetch it with port/scripts/setup.sh (clones into thirdparty/melonDS-src).
set(MELONDS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../thirdparty/melonDS-src" CACHE PATH "melonDS source tree")
set(BUILD_QT_SDL OFF CACHE BOOL "" FORCE)
set(ENABLE_OGLRENDERER OFF CACHE BOOL "" FORCE)
set(ENABLE_GDBSTUB OFF CACHE BOOL "" FORCE)
set(ENABLE_LTO_RELEASE OFF CACHE BOOL "" FORCE)
add_subdirectory(${MELONDS_DIR} melonds EXCLUDE_FROM_ALL)

find_package(SDL2 REQUIRED)

add_executable(MapleStoryDS WIN32
    src/main.cpp
    src/emu.cpp
    src/input.cpp
    src/ui.cpp
    src/platform.cpp
)
target_include_directories(MapleStoryDS PRIVATE src ${MELONDS_DIR}/src)
target_link_libraries(MapleStoryDS PRIVATE core SDL2::SDL2 comdlg32 gdi32)
target_link_options(MapleStoryDS PRIVATE -static -Wl,--stack,67108864)
set_target_properties(MapleStoryDS PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

# Ship SDL2.dll next to the executable
find_file(SDL2_DLL SDL2.dll HINTS ${SDL2_PREFIX}/bin $ENV{MSYSTEM_PREFIX}/bin C:/msys64/ucrt64/bin)
if (SDL2_DLL)
    add_custom_command(TARGET MapleStoryDS POST_BUILD COMMAND ${CMAKE_COMMAND} -E copy_if_different ${SDL2_DLL} $<TARGET_FILE_DIR:MapleStoryDS>)
endif()
