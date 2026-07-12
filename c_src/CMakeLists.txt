cmake_minimum_required(VERSION 3.20)
project(crb_analyzer CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# nlohmann/json is header-only — included via third_party/
add_executable(static_analyzer
    static_analyzer.cpp
)

target_include_directories(static_analyzer PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)
