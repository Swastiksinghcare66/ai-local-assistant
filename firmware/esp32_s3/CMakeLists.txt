cmake_minimum_required(VERSION 3.22)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Compile only main + direct/transitive dependencies.
# Prevents unused components such as esp_lcd from entering SIA build.
idf_build_set_property(MINIMAL_BUILD ON)

project(sia_esp32s3_firmware)
